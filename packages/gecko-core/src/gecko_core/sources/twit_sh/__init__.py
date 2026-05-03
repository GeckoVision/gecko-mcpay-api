"""twit.sh Source — live X/Twitter signal via x402 micropayments on Base.

twit.sh is itself x402-native — the same protocol Gecko speaks. We don't need
a wrapper SDK. We register an EVM signer with `x402Client`, pin it to Base
mainnet (`eip155:8453`), and let `x402AsyncTransport` handle the 402 → sign →
retry handshake transparently while we just call `httpx.AsyncClient.get()`.

Gating:
- `applies_to` returns True only for ideas in {crypto, defi, hackathon-team}.
  X signal is strongest there. Saas/regulated ideas don't fire (margin saver).
- If `is_twitsh_configured()` is False we silently skip.

Cost discipline:
- Hard per-session spend cap: $0.05. Once we've debited that much we stop
  hitting the API even if the caller would still want more results.
- 6h MongoDB cache, key = sha256("twit_sh:" + idea + "|" + categories_csv).
  Cache hit short-circuits all HTTP — and all spend.

API shape note (deviation tracking):
- The build plan documents two endpoints (`searchTweets`, `userTweets`) under
  `https://x402.twit.sh`. The exact path-layout is not yet pinned in the
  upstream docs we could fetch (see WebFetch attempts in S2X-08 report). We
  hardcode a minimal default path table here and surface it via the module-
  level `DEFAULT_CATALOG`. Sprint-2-final ships with the catalog baked at
  build time per build-plan §3.2; until that lands, this module reads from
  `TWITSH_CATALOG_JSON` env (overrideable for tests) before falling back.
- Per-tweet response normalization is best-effort: we look for common keys
  (`text` / `full_text`, `user.screen_name` / `author_handle`, `favorite_count`
  / `likes`, etc.) so the citation shape we publish is stable regardless of
  upstream wording.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from gecko_core.cache import cache_key, get_cached, is_mongo_configured, set_cached
from gecko_core.sources import SourceResult

logger = logging.getLogger(__name__)

# Categories where X signal is strongest. We'd rather skip than burn $0.05
# on a regulated/healthcare idea where Twitter is mostly noise.
_FIRES_FOR: frozenset[str] = frozenset({"crypto", "defi", "hackathon-team"})

# Default endpoint catalog. Build-time `npx twitsh endpoints --json` will
# eventually overwrite this via TWITSH_CATALOG_JSON. Keep paths under a
# `searchTweets`/`userTweets` namespace so the override has a stable schema.
#
# S14-TWITSH-02: the Sprint 13 probe (`5c73936`) confirmed the live surface
# is `/tweets/search?words=...`, not the previously-assumed
# `/search/tweets?q=...`. Catalog updated to match production. Tests that
# mock the legacy path are migrated alongside.
#
# 2026-05-04: live landing confirmed userTweets path is `/tweets/user`
# (not `/users/tweets`). Response shape: {data: [...], meta: {next_token}}.
# ~20 tweets/page, $0.01 USDC/request.
DEFAULT_CATALOG: dict[str, dict[str, str]] = {
    "searchTweets": {"path": "/tweets/search", "method": "GET", "query_param": "words"},
    "userTweets": {"path": "/tweets/user", "method": "GET", "query_param": "username"},
}

# Per-session hard cap. The build plan budgets $0.05 worst case; we enforce
# it client-side rather than rely on the wallet running dry.
SPEND_CAP_USD: float = 0.05

# Per-call price for budget arithmetic. The actual debit comes from the
# 402 challenge — this is the planner's pre-charge estimate.
#
# S14-TWITSH-02: the Sprint 13 probe captured the 402 challenge directly
# and confirmed the per-call price is **$0.01 USDC**, not the prior
# `0.005` constant. Cap math (`SPEND_CAP_USD / ASSUMED_PER_CALL_USD`) was
# 2x off — the planner thought it could afford ~10 reads at $0.05 when
# the actual ceiling is ~5. Constant corrected here so the spend-cap
# loop in `TwitshSource.fetch` halts at the right call count.
ASSUMED_PER_CALL_USD: float = 0.01

# Network identity for x402 EVM scheme registration.
_BASE_MAINNET_CAIP2: str = "eip155:8453"

# Cache TTL — build plan §3.7 specifies 12h for the deploy-time catalog cache;
# the per-idea results live a bit shorter (6h) to keep the signal fresh while
# still hitting >40% reuse rate against the next-iteration session of the same
# idea.
CACHE_TTL_SECONDS: int = 6 * 60 * 60

# Result cap: 10 tweets per session is the build plan's worst-case ceiling.
MAX_RESULTS: int = 10


def _load_catalog() -> dict[str, dict[str, str]]:
    """Resolve the endpoint catalog. Env > built-in default."""
    raw = os.environ.get("TWITSH_CATALOG_JSON")
    if not raw:
        return DEFAULT_CATALOG
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        logger.warning("twitsh: TWITSH_CATALOG_JSON malformed; using default catalog")
    return DEFAULT_CATALOG


def _is_twitsh_configured() -> bool:
    """Mirrors `Settings.is_twitsh_configured()` without importing gecko-api.

    `gecko-core` must not import `gecko-api` (gecko-api depends on gecko-core,
    not vice versa). We re-read the env directly.
    """
    enabled = os.environ.get("TWITSH_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not enabled:
        return False
    sentinels = {"", "__unset__", "__dev_change_me__"}
    pk = os.environ.get("TWITSH_WALLET_PRIVATE_KEY", "")
    if pk in sentinels:
        return False
    addr = os.environ.get("TWITSH_WALLET_ADDRESS", "")
    return addr not in sentinels


def _keyword_set(idea: str, categories: set[str]) -> list[str]:
    """Build a small (≤6) keyword query from idea + categories.

    Strip stopwords, dedupe lowercased, prefer longer tokens. Categories ride
    along verbatim so a 'crypto'/'defi' classification surfaces in the query
    and twit.sh's relevance signal can lean on it.
    """
    stop = {
        "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on",
        "with", "is", "are", "was", "were", "be", "been", "by", "at", "from",
        "this", "that", "these", "those", "it", "its", "as", "into", "than",
    }  # fmt: skip
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", idea.lower())
    seen: set[str] = set()
    keep: list[str] = []
    for t in sorted(tokens, key=len, reverse=True):
        if t in stop or t in seen:
            continue
        seen.add(t)
        keep.append(t)
        if len(keep) >= 4:
            break
    for c in sorted(categories):
        if c not in seen:
            keep.append(c)
            seen.add(c)
        if len(keep) >= 6:
            break
    return keep


def _normalize_tweet(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a twit.sh tweet dict into Gecko's citation shape.

    Keys we accept (best-effort, upstream-agnostic):
        text       <- note_tweet.text | text | full_text | content
        author     <- user.screen_name | author_handle | author.username
        url        <- url | tweet_url | permalink
        likes      <- public_metrics.like_count | likes | favorite_count
        replies    <- public_metrics.reply_count | replies
        reposts    <- public_metrics.retweet_count | retweets | reposts
        created_at <- created_at | timestamp

    S14-TWITSH-03: when X carries a long-form post, ``text`` is truncated
    at ~280 chars and the full body lands in ``note_tweet.text``. The
    probe found that twit.sh forwards ``note_tweet`` verbatim, so we
    prefer it when present — otherwise the citation surfaces the
    truncated stub and the validation report cites half a sentence.

    Returns None if neither text nor an id-shaped url can be recovered (a
    malformed entry shouldn't poison the whole result list).
    """
    note_tweet = raw.get("note_tweet")
    note_text: str | None = None
    if isinstance(note_tweet, dict):
        candidate = note_tweet.get("text")
        if isinstance(candidate, str) and candidate.strip():
            note_text = candidate
    text = note_text or raw.get("text") or raw.get("full_text") or raw.get("content")
    if not text:
        return None

    user = raw.get("user") or raw.get("author") or {}
    handle = (
        raw.get("author_handle")
        or (user.get("screen_name") if isinstance(user, dict) else None)
        or (user.get("username") if isinstance(user, dict) else None)
        or raw.get("username")
    )
    if isinstance(handle, str) and not handle.startswith("@"):
        handle = "@" + handle

    metrics = raw.get("public_metrics") or {}
    likes = (
        raw.get("likes")
        or raw.get("favorite_count")
        or (metrics.get("like_count") if isinstance(metrics, dict) else None)
        or 0
    )
    replies = (
        raw.get("replies")
        or (metrics.get("reply_count") if isinstance(metrics, dict) else None)
        or 0
    )
    reposts = (
        raw.get("reposts")
        or raw.get("retweets")
        or raw.get("retweet_count")
        or (metrics.get("retweet_count") if isinstance(metrics, dict) else None)
        or 0
    )
    url = raw.get("url") or raw.get("tweet_url") or raw.get("permalink") or ""

    return {
        "text": str(text),
        "author_handle": handle or "",
        "url": str(url),
        "engagement": {
            "likes": int(likes) if isinstance(likes, int | float) else 0,
            "replies": int(replies) if isinstance(replies, int | float) else 0,
            "reposts": int(reposts) if isinstance(reposts, int | float) else 0,
        },
        "created_at": raw.get("created_at") or raw.get("timestamp") or "",
    }


def _stub_tweets(idea: str, categories: set[str]) -> list[dict[str, Any]]:
    """Deterministic synthetic tweets for stub-mode `bb research`.

    Mirrors the contract of a real twit.sh search response: keys match
    the live shape so renderers / tests can't tell them apart.

    S19-STUB-FIXTURES-01: keyword-templated against the idea string so
    the demo screenshot reads as topical signal rather than canned
    "[stub] Builders are talking about <idea>" boilerplate. Bucket
    selection lives in ``gecko_core.sources._idea_keywords``; we just
    fill the templates here. The "[stub]" prefix is dropped so the
    surface text matches the live shape — the ``stub`` flag on the
    payload is the canonical "this came from a fixture" signal.
    """
    from gecko_core.sources._idea_keywords import (
        bucket_payload,
        pick_bucket,
        top_keywords,
    )

    bucket = pick_bucket(idea, categories)
    payload = bucket_payload(bucket)
    kws = top_keywords(idea, n=3)
    primary_kw = kws[0]
    secondary_kw = kws[1] if len(kws) > 1 else primary_kw

    hooks = payload["tweet_hooks"]
    # Two hooks → two tweets. Each templates {kw} against a different
    # top keyword so they don't both repeat the same word.
    text_a = hooks[0].format(kw=primary_kw)
    text_b = hooks[1 % len(hooks)].format(kw=secondary_kw)

    # Cap each text at ~280 chars to mirror live twit.sh truncation.
    def _cap(s: str) -> str:
        return s if len(s) <= 280 else s[:277] + "..."

    return [
        {
            "text": _cap(text_a),
            "author_handle": f"@builder_{primary_kw}"[:15],
            "url": "https://x402.twit.sh/stub/1",
            "engagement": {"likes": 42, "replies": 7, "reposts": 12},
            "created_at": "2026-05-01T00:00:00Z",
        },
        {
            "text": _cap(text_b),
            "author_handle": f"@signal_{secondary_kw}"[:15],
            "url": "https://x402.twit.sh/stub/2",
            "engagement": {"likes": 18, "replies": 3, "reposts": 5},
            "created_at": "2026-05-01T00:00:00Z",
        },
    ]


def _build_x402_client() -> httpx.AsyncClient | None:
    """Construct an `httpx.AsyncClient` whose transport handles x402 on Base.

    Returns None if any of the underlying x402 / eth_account libraries can't
    be imported — the caller should treat that as "unconfigured" and skip.
    """
    pk = os.environ.get("TWITSH_WALLET_PRIVATE_KEY")
    if not pk:
        return None

    try:
        from eth_account import Account
        from x402 import x402Client
        from x402.http.clients.httpx import x402AsyncTransport
        from x402.mechanisms.evm.exact import ExactEvmScheme
        from x402.mechanisms.evm.signers import EthAccountSigner
    except ImportError:  # pragma: no cover — deps shipped, guard for stripped envs
        logger.warning("twitsh: x402/eth_account not importable; skipping")
        return None

    try:
        account = Account.from_key(pk)
    except Exception as exc:
        logger.warning("twitsh: invalid private key (%s); skipping", type(exc).__name__)
        return None

    signer = EthAccountSigner(account)
    client = x402Client()
    # Register Base mainnet by CAIP-2 + the wildcard so different-style
    # network ids in 402 challenges still match.
    client.register(_BASE_MAINNET_CAIP2, ExactEvmScheme(signer=signer))
    client.register("eip155:*", ExactEvmScheme(signer=signer))
    transport = x402AsyncTransport(client)

    base = os.environ.get("TWITSH_BASE_URL", "https://x402.twit.sh")
    return httpx.AsyncClient(
        base_url=base,
        transport=transport,
        timeout=httpx.Timeout(20.0, connect=5.0),
    )


class TwitshSource:
    """`Source` impl. Ungated outside `applies_to`; cap-aware on `fetch`."""

    name: str = "twit_sh"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        catalog: dict[str, dict[str, str]] | None = None,
        spend_cap_usd: float = SPEND_CAP_USD,
        bypass_cache: bool | None = None,
    ) -> None:
        # `http_client` is injected in tests (respx-mounted MockTransport);
        # in production we lazily build one with the EVM signer.
        self._http: httpx.AsyncClient | None = http_client
        self._owns_http = http_client is None
        self._catalog = catalog or _load_catalog()
        self._spend_cap = float(spend_cap_usd)
        # S11-F18-01: opt-in bypass of the 6h Mongo result cache so
        # `--live-rag` eval gate runs measure *true cold-signal* spend
        # rather than getting served free cached payloads from a prior
        # warm run. Resolution order:
        #   1. explicit constructor arg (tests)
        #   2. `TWITSH_BYPASS_CACHE` env (script-driven gate runs)
        #   3. default False (production CLI / API stays cache-on)
        if bypass_cache is None:
            env = os.environ.get("TWITSH_BYPASS_CACHE", "").strip().lower()
            bypass_cache = env in ("1", "true", "yes", "on")
        self._bypass_cache = bool(bypass_cache)

    async def applies_to(self, *, categories: set[str]) -> bool:
        # S16-INTEGRATE-01: stub-mode bypass. When the platform is running
        # in stub payment mode the live x402 wallet config is irrelevant —
        # we synthesize a deterministic payload from a recorded fixture so
        # `bb research` always produces a twit.sh attribution line during
        # smoke. Live mode keeps the wallet+category gate.
        if os.environ.get("X402_MODE", "stub").strip().lower() == "stub":
            return True
        if not _is_twitsh_configured():
            return False
        return bool(_FIRES_FOR & categories)

    async def fetch(
        self,
        *,
        idea: str,
        categories: set[str],
        author_allowlist: frozenset[str] | None = None,
    ) -> SourceResult:
        """Single x402-paid search call. Optional post-filter by author handle.

        S14-TWITSH-01: ``author_allowlist`` (e.g. Colosseum judges) is
        hashed into the cache key so filtered and unfiltered runs do not
        collide. Tweets whose normalized ``@handle`` is not in the
        allowlist are dropped after the live fetch — the spend has
        already been paid, so we keep the network response for cache
        reuse but only emit allowed rows to the caller.
        """
        # S16-INTEGRATE-01 — stub-mode synthetic payload. Mirrors the
        # Bazaar stub-discovery pattern: no network, deterministic
        # fixture, non-zero attributed spend so the economics rollup
        # carries a `twitsh` line. Bypasses cache + x402 client entirely.
        if os.environ.get("X402_MODE", "stub").strip().lower() == "stub":
            synthetic = _stub_tweets(idea, categories)
            return SourceResult(
                source_name=self.name,
                payload={
                    "tweets": synthetic,
                    "from_cache": False,
                    "spend_usd": ASSUMED_PER_CALL_USD,
                    "stub": True,
                },
                cost_usd=ASSUMED_PER_CALL_USD,
                fired=True,
            )

        # Cache check first — never spend when a hit is plausible.
        categories_csv = ",".join(sorted(categories))
        # Allowlist hash: include in cache key so filtered/unfiltered
        # runs don't poison each other. Empty / None → "none" sentinel
        # keeps legacy keys stable (pre-S14 callers continue to hit
        # their cache).
        if author_allowlist:
            import hashlib

            allowlist_hash = hashlib.sha256(
                ",".join(sorted(author_allowlist)).encode("utf-8")
            ).hexdigest()[:12]
        else:
            allowlist_hash = "none"
        ckey = cache_key("twit_sh:", idea, "|", categories_csv, "|", allowlist_hash)

        if is_mongo_configured() and not self._bypass_cache:
            try:
                cached = await get_cached("twitsh_cache", ckey)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("twitsh: cache read failed (%s)", exc)
                cached = None
            if cached is not None:
                cached_tweets = cached.get("tweets", [])
                return SourceResult(
                    source_name=self.name,
                    payload={"tweets": cached_tweets, "from_cache": True, "spend_usd": 0.0},
                    cost_usd=0.0,
                    fired=True,
                )

        # Live path. Build (or reuse) the x402-equipped client.
        if self._http is None:
            self._http = _build_x402_client()
        if self._http is None:
            return SourceResult(
                source_name=self.name,
                payload={},
                fired=False,
                error="twitsh: client unavailable (config or import)",
            )

        keywords = _keyword_set(idea, categories)
        if not keywords:
            return SourceResult(
                source_name=self.name,
                payload={"tweets": [], "spend_usd": 0.0},
                fired=True,
            )

        spec = self._catalog.get("searchTweets") or DEFAULT_CATALOG["searchTweets"]
        path = spec.get("path", "/tweets/search")
        param = spec.get("query_param", "words")
        query = " ".join(keywords)

        spent: float = 0.0
        tweets: list[dict[str, Any]] = []

        # Single search call covers the top-N case. The build plan permits
        # up to ~10 reads across multiple endpoints; we ship the search
        # backbone here and leave per-judge `userTweets` for S2X-11 to compose
        # against this Source. The cap loop below is structured so adding
        # those calls later keeps the cap honest.
        for _ in range(1):
            if spent + ASSUMED_PER_CALL_USD > self._spend_cap:
                logger.info("twitsh: spend cap hit at $%.4f, halting", spent)
                break
            try:
                resp = await self._http.get(path, params={param: query})
            except httpx.HTTPError as exc:
                return SourceResult(
                    source_name=self.name,
                    payload={"tweets": tweets, "spend_usd": spent},
                    fired=False,
                    error=f"twitsh: http error: {type(exc).__name__}: {exc}",
                )
            if resp.status_code >= 400:
                return SourceResult(
                    source_name=self.name,
                    payload={"tweets": tweets, "spend_usd": spent},
                    fired=False,
                    error=f"twitsh: {resp.status_code} {resp.text[:200]}",
                )

            try:
                body = resp.json()
            except json.JSONDecodeError as exc:
                return SourceResult(
                    source_name=self.name,
                    payload={"tweets": tweets, "spend_usd": spent},
                    fired=False,
                    error=f"twitsh: non-JSON response: {exc}",
                )

            spent += ASSUMED_PER_CALL_USD
            raw_tweets = body.get("tweets") or body.get("data") or body.get("results") or []
            if not isinstance(raw_tweets, list):
                raw_tweets = []
            # Normalize the allowlist once: lowercase, strip leading "@"
            # so comparison is robust to capitalization / "@" presence on
            # either side. Empty allowlist → no post-filter.
            normalized_allow: frozenset[str] | None = None
            if author_allowlist:
                normalized_allow = frozenset(h.lstrip("@").lower() for h in author_allowlist if h)
            for raw in raw_tweets[:MAX_RESULTS]:
                if not isinstance(raw, dict):
                    continue
                norm = _normalize_tweet(raw)
                if norm is None:
                    continue
                if normalized_allow is not None:
                    handle = str(norm.get("author_handle") or "").lstrip("@").lower()
                    if handle not in normalized_allow:
                        continue
                tweets.append(norm)
                if len(tweets) >= MAX_RESULTS:
                    break

        # Persist to cache so the *next* same-idea session is free.
        if is_mongo_configured():
            try:
                await set_cached(
                    "twitsh_cache",
                    ckey,
                    {"tweets": tweets, "query": query},
                    ttl_seconds=CACHE_TTL_SECONDS,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("twitsh: cache write failed (%s)", exc)

        return SourceResult(
            source_name=self.name,
            payload={"tweets": tweets, "from_cache": False, "spend_usd": spent},
            cost_usd=spent,
            fired=True,
        )

    async def fetch_user_tweets(
        self,
        username: str,
        *,
        max_calls: int = 5,
    ) -> tuple[list[dict[str, Any]], float]:
        """Operator-driven ingestion: fetch recent tweets for a single handle.

        Hits the catalog ``userTweets`` endpoint
        (``/users/tweets?username=<h>``) up to ``max_calls`` times. The
        twit.sh ``userTweets`` surface returns up to ~10 tweets per call
        and (per the Sprint 13 probe + S21-JUDGE-CORPUS-01 follow-up
        probe) does NOT expose a documented pagination cursor — repeating
        the same call can return the same window. We still allow
        ``max_calls > 1`` because the live API occasionally rotates the
        window when called minutes apart, and dedup happens at the
        persistence layer (``tweet_id`` PK on the judge_corpus collection).

        Bypasses ``SPEND_CAP_USD``: this is an explicit operator command,
        not a session, so the per-session $0.05 cap does not apply.
        ``max_calls`` is the hard ceiling. Spend math is local: each
        successful call debits ``ASSUMED_PER_CALL_USD`` ($0.01).

        Returns ``(tweets, spent_usd)``. On error returns whatever was
        accumulated up to that point — partial success is intentional.
        Stub mode: returns synthetic tweets with the handle baked in so
        the smoke run completes without a wallet.
        """
        # Stub mode — synthesise tweets with the handle so callers can
        # validate end-to-end without a wallet. Same mechanism as
        # ``fetch``: deterministic shape, non-zero attributed spend.
        if os.environ.get("X402_MODE", "stub").strip().lower() == "stub":
            handle = username.lstrip("@").lower()
            now = "2026-05-02T00:00:00Z"
            synth = [
                {
                    "text": "Builders shipping on Solana right now should focus on UX, not L1 narratives. Saw too many decks last hackathon hide behind 'we use ZK'.",
                    "author_handle": f"@{handle}",
                    "url": f"https://x.com/{handle}/status/100000{i}",
                    "engagement": {"likes": 50 - i * 4, "replies": 3, "reposts": 7},
                    "created_at": now,
                    "id_str": f"100000{i}",
                }
                for i in range(6)
            ]
            return synth, ASSUMED_PER_CALL_USD * min(max_calls, 1)

        if self._http is None:
            self._http = _build_x402_client()
        if self._http is None:
            return [], 0.0

        spec = self._catalog.get("userTweets") or DEFAULT_CATALOG["userTweets"]
        path = spec.get("path", "/tweets/user")
        param = spec.get("query_param", "username")
        clean_handle = username.lstrip("@")
        # /tweets/user doesn't embed the author object — fill handle from arg.
        fallback_handle = f"@{clean_handle}"

        spent = 0.0
        tweets: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        next_token: str | None = None

        for _ in range(max(1, max_calls)):
            params: dict[str, str] = {param: clean_handle}
            if next_token:
                params["next_token"] = next_token
            try:
                resp = await self._http.get(path, params=params)
            except httpx.HTTPError as exc:
                logger.warning("twitsh.user_tweets.http_error: %s", exc)
                break
            if resp.status_code >= 400:
                logger.warning(
                    "twitsh.user_tweets.bad_status: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
                break
            try:
                body = resp.json()
            except json.JSONDecodeError:
                logger.warning("twitsh.user_tweets.non_json")
                break
            spent += ASSUMED_PER_CALL_USD
            raw_tweets = body.get("tweets") or body.get("data") or body.get("results") or []
            if not isinstance(raw_tweets, list):
                raw_tweets = []
            # Advance the pagination cursor for the next loop iteration.
            meta = body.get("meta") or {}
            next_token = meta.get("next_token") if isinstance(meta, dict) else None
            new_in_call = 0
            for raw in raw_tweets:
                if not isinstance(raw, dict):
                    continue
                norm = _normalize_tweet(raw)
                if norm is None:
                    continue
                # /tweets/user returns author_id not an author object — backfill.
                if not norm.get("author_handle"):
                    norm["author_handle"] = fallback_handle
                # Carry tweet_id through for dedup at persistence time.
                tid = raw.get("id_str") or raw.get("id") or raw.get("tweet_id") or norm.get("url")
                tid_s = str(tid) if tid is not None else ""
                if not tid_s or tid_s in seen_ids:
                    continue
                seen_ids.add(tid_s)
                norm["id_str"] = tid_s
                tweets.append(norm)
                new_in_call += 1
            # Stop if no new tweets or no further pages.
            if new_in_call == 0 or not next_token:
                break

        return tweets, spent

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None


__all__ = [
    "ASSUMED_PER_CALL_USD",
    "CACHE_TTL_SECONDS",
    "DEFAULT_CATALOG",
    "MAX_RESULTS",
    "SPEND_CAP_USD",
    "TwitshSource",
]
