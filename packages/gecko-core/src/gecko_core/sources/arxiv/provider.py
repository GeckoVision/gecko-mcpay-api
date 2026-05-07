"""ArxivSource — free, structured paper-abstract provider.

Backed by the public Arxiv export API:
    http://export.arxiv.org/api/query?search_query=<q>&max_results=<n>

Why a dedicated provider (and not "just a Tavily query"):
    - Tavily returns raw HTML pages we then have to fetch + parse, often
      losing the Atom abstract entirely. Arxiv's Atom feed is parseable
      first-class — title, abstract, authors, arxiv_id, pdf_url all come
      back in a single <entry/>.
    - No key, no rate-limit pain at our session volumes.
    - The abstract is the citation. Each entry is a self-contained chunk
      already, so there is nothing to chunk client-side.

Gating policy:
    - Always fires when classify_idea() returns any of {crypto, defi,
      devtools, hackathon-team} — Arxiv has strong CS / cryptography /
      protocol-paper coverage there.
    - Also fires when the idea text matches one of the technical-paper
      signal patterns ("agent", "agentic", "protocol", "x402", "rag",
      "embedding", "verifiable", "zk", "consensus", "research", ...) —
      this catches ideas like the founder's "Gecko: makes judgment
      tradeable" run where the classifier returns ∅ but the topic is
      research-adjacent.

The provider returns a ``SourceResult`` whose ``payload["chunks"]`` is a
list of dicts shaped like a ``BazaarChunk`` so the downstream rendering
+ economics ledger code paths don't fork on provider type. Cost is
always 0.0 (free).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

import httpx

from gecko_core.sources import SourceResult

logger = logging.getLogger(__name__)


ARXIV_API_BASE: str = "http://export.arxiv.org/api/query"

# Atom namespaces in the Arxiv response.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# Default per-call abstract cap. Tunable via env in the workflows
# rebalance step (GECKO_PROVIDER_QUOTA_ARXIV).
DEFAULT_MAX_RESULTS: int = 5

# HTTP timeout: Arxiv's mirror is generally fast (<1s) but can lag during
# their nightly index rebuild. 8s is plenty without holding up dispatch.
DEFAULT_TIMEOUT_SECONDS: float = 8.0

# Categories where Arxiv is reliably useful. Other classifications still
# run via the keyword-signal fallback below.
_CATEGORY_FIRES_FOR: frozenset[str] = frozenset({"crypto", "defi", "devtools", "hackathon-team"})

# Idea-text signals that flag a research-adjacent topic when the
# classifier returned ∅. Lowercased substring match; conservative so we
# don't fire on every SaaS idea that mentions "AI".
_TECHNICAL_SIGNALS: tuple[str, ...] = (
    "agent",
    "agentic",
    "protocol",
    "x402",
    "rag",
    "retrieval-augmented",
    "embedding",
    "verifiable",
    "zk",
    "zero-knowledge",
    "consensus",
    "research",
    "paper",
    "benchmark",
    "transformer",
    "diffusion",
    "llm",
    "mcp",
    "judgment",
    "judge",
    "marketplace",
    "tradeable",
    "tradable",
)


def _idea_has_technical_signal(idea: str) -> bool:
    text = (idea or "").lower()
    return any(sig in text for sig in _TECHNICAL_SIGNALS)


# Same stopword list shape as twit_sh — keep the keyword extraction
# behaviour predictable across providers so debugging tools aren't
# guessing which stop-list ran.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "at",
        "from",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "into",
        "than",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "i",
        "me",
        "my",
        "use",
        "uses",
        "using",
        "make",
        "makes",
        "making",
        "build",
        "builds",
    }
)


# S21-FIX-09 query-construction caps. The production failure was an
# Arxiv URL with 5 ANDed hyphenated terms; the mirror returned an empty
# 200 (not a valid empty <feed/>) because the query was overconstrained
# to the point of falling outside the index. Defaults below are tuned to
# stay inside the well-trodden recall envelope of the mirror:
#   - cap at 3 terms (going wider drops to zero hits in practice),
#   - OR-join (Arxiv's relevance ranking surfaces the matched paper;
#     AND-joining low-frequency tokens is the failure mode here),
#   - explode hyphens into their constituents so "research-market"
#     becomes ("research", "market") rather than a literal that the
#     Arxiv tokenizer never indexes.
DEFAULT_MAX_KEYWORDS: int = 4
# Loosened fallback used when the first attempt returns an empty body —
# we drop to the single most-discriminative term so we at least get the
# sort-by-relevance head of the index back.
FALLBACK_MAX_KEYWORDS: int = 1
# When keyword extraction yields fewer than this many salient tokens,
# the builder degrades to the raw idea text (truncated) rather than
# emitting a 0- or 1-term query that the Arxiv mirror routinely answers
# with a zero-byte body.
MIN_KEYWORDS_FOR_OR_QUERY: int = 2
# Hard cap for the raw-idea-fallback path so a 600-char Pro-tier idea
# doesn't blow past Arxiv's URL-length tolerance.
RAW_IDEA_FALLBACK_CHAR_BUDGET: int = 80


def _split_hyphens(token: str) -> list[str]:
    """Split a hyphenated token into its constituents.

    Arxiv's search_query tokenizer indexes on word boundaries; literals
    like ``strategy-architecture`` never match because no abstract carries
    that exact compound. We split into ``["strategy", "architecture"]``
    and let the OR-join recover recall.
    """
    parts = [p for p in token.split("-") if p and len(p) > 2]
    return parts or ([token] if token and "-" not in token else [])


def _extract_keywords(idea: str, *, limit: int) -> list[str]:
    """Return up to ``limit`` salient keywords from ``idea``.

    Hyphenated tokens are exploded; stopwords dropped; longer tokens
    preferred (they discriminate better than 3-letter words). Order is
    deterministic for a given input so retries with a shrunk ``limit``
    return a strict prefix of the wider keyword set.
    """
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", (idea or "").lower())
    exploded: list[str] = []
    for t in raw:
        exploded.extend(_split_hyphens(t))
    # Deterministic ranking: length desc, then first-seen order.
    indexed = list(enumerate(exploded))
    indexed.sort(key=lambda pair: (-len(pair[1]), pair[0]))
    seen: set[str] = set()
    kept: list[str] = []
    for _, t in indexed:
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        kept.append(t)
        if len(kept) >= limit:
            break
    return kept


def _build_query(
    idea: str,
    *,
    max_keywords: int = DEFAULT_MAX_KEYWORDS,
    operator: str = "OR",
) -> str:
    """Extract a small keyword set from the idea for arxiv search_query.

    Arxiv's search_query is a Lucene-style expression; we use ``all:term``
    OR'd together by default — Arxiv's relevance ranking lifts the
    best-matching abstract to the top, while AND-joining 3+ specialised
    tokens routinely returns zero hits (S21-FIX-09 production case).

    Hyphenated tokens are exploded into their constituents because the
    Arxiv index does not tokenise on hyphens, so ``research-market``
    matches nothing as a literal but ``research OR market`` is fine.
    """
    op = operator.upper().strip() or "OR"
    if op not in {"OR", "AND"}:
        op = "OR"
    kept = _extract_keywords(idea, limit=max_keywords)
    # FIX-09 fallback: if extraction couldn't surface even 2 salient terms,
    # an OR-of-1 (or empty) query is no better than "send the raw text",
    # and Arxiv's mirror handles raw text fine *as long as it's bounded*.
    # We only trigger this when the caller requested >=2 terms; an
    # explicit ``max_keywords=1`` call (the loosened retry path) is
    # honored as-is because the caller is intentionally narrowing.
    if max_keywords >= MIN_KEYWORDS_FOR_OR_QUERY and len(kept) < MIN_KEYWORDS_FOR_OR_QUERY:
        raw = (idea or "").strip()[:RAW_IDEA_FALLBACK_CHAR_BUDGET]
        return quote_plus(raw or "research")
    if not kept:
        # Caller asked for 1 term but extraction returned 0 — degrade the
        # same way rather than emit a malformed empty query.
        raw = (idea or "").strip()[:RAW_IDEA_FALLBACK_CHAR_BUDGET]
        return quote_plus(raw or "research")
    joiner = f"+{op}+"
    return joiner.join(f"all:{quote_plus(t)}" for t in kept)


def _parse_atom(xml_text: str, *, source_url: str | None = None) -> list[dict[str, Any]]:
    """Parse an Arxiv Atom feed into a list of normalized entry dicts.

    Returns an empty list on parse error — Arxiv occasionally serves a
    truncated body during their index rebuild and we'd rather degrade
    silently than fail the dispatch.

    On parse failure, emits a structured WARN (`arxiv.parse.empty`) with
    the requesting URL, the body length, and a 200-char excerpt so the
    operator can correlate the failure with what Arxiv actually returned.
    On success, the caller emits an INFO (`arxiv.parse.success`) so the
    failure rate is monitorable as a ratio of those two log keys.
    """
    if not xml_text or not xml_text.strip():
        # Arxiv occasionally returns a 200 with an empty body during
        # index rebuilds. Treat as parse-empty rather than passing an
        # empty string into ET.fromstring (which raises with a less
        # informative "no element found" message).
        logger.warning(
            "arxiv.parse.empty url=%s body_len=0 excerpt=''",
            source_url or "<unknown>",
        )
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        excerpt = xml_text[:200].replace("\n", " ")
        logger.warning(
            "arxiv.parse.empty url=%s body_len=%d excerpt=%r error=%s",
            source_url or "<unknown>",
            len(xml_text),
            excerpt,
            exc,
        )
        return []

    out: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        title_el = entry.find(f"{_ATOM_NS}title")
        summary_el = entry.find(f"{_ATOM_NS}summary")
        id_el = entry.find(f"{_ATOM_NS}id")
        published_el = entry.find(f"{_ATOM_NS}published")

        title = (title_el.text or "").strip() if title_el is not None else ""
        summary = (summary_el.text or "").strip() if summary_el is not None else ""
        full_id = (id_el.text or "").strip() if id_el is not None else ""
        published = (published_el.text or "").strip() if published_el is not None else ""

        # ``id`` is the abs-page URL; the arxiv_id is its trailing segment.
        arxiv_id = full_id.rsplit("/", 1)[-1] if full_id else ""

        authors: list[str] = []
        for author in entry.findall(f"{_ATOM_NS}author"):
            name_el = author.find(f"{_ATOM_NS}name")
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        pdf_url = ""
        for link in entry.findall(f"{_ATOM_NS}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                href = link.get("href") or ""
                if href:
                    pdf_url = href
                    break

        primary_category_el = entry.find(f"{_ARXIV_NS}primary_category")
        primary_category = (
            primary_category_el.get("term") if primary_category_el is not None else ""
        )

        if not (title or summary):
            continue

        out.append(
            {
                "title": title,
                "abstract": summary,
                "authors": authors,
                "arxiv_id": arxiv_id,
                "abs_url": full_id,
                "pdf_url": pdf_url,
                "published_date": published,
                "primary_category": primary_category,
            }
        )
    return out


def _entry_to_chunk(entry: dict[str, Any]) -> dict[str, Any]:
    """Render an Arxiv entry as a chunk-shaped dict for the dispatcher.

    ``provider_kind="free:arxiv"`` mirrors the Bazaar adapter convention
    (``bazaar:<adapter>``). Citation reads as ``arxiv:<id>``; the full
    abs_url stays in metadata so the renderer can surface it as a link.
    """
    arxiv_id = entry.get("arxiv_id", "")
    title = entry.get("title", "")
    abstract = entry.get("abstract", "")
    citation_id = f"arxiv:{arxiv_id}" if arxiv_id else "arxiv:unknown"

    text = f"{title}\n\n{abstract}".strip() if title or abstract else ""

    return {
        "text": text,
        "provider_kind": "free:arxiv",
        "cost_usd": "0",
        "metadata": {
            "citation_id": citation_id,
            "title": title,
            "authors": entry.get("authors", []),
            "arxiv_id": arxiv_id,
            "abs_url": entry.get("abs_url", ""),
            "pdf_url": entry.get("pdf_url", ""),
            "published_date": entry.get("published_date", ""),
            "primary_category": entry.get("primary_category", ""),
        },
        "creator_handle": None,
    }


class ArxivSource:
    """Free Arxiv provider conforming to the ``Source`` Protocol."""

    name: str = "arxiv"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        api_base: str = ARXIV_API_BASE,
    ) -> None:
        self._http = http_client
        self._owns_http = http_client is None
        self._max_results = int(max_results)
        self._timeout = float(timeout_seconds)
        self._api_base = api_base

    async def applies_to(self, *, categories: set[str], idea: str = "") -> bool:
        """True for technical/research-adjacent ideas.

        The ``Source`` Protocol's ``applies_to`` is keyword-only and
        canonical signature is ``(*, categories)``. ``idea`` is an
        optional extension we accept for the keyword-signal fallback;
        the dispatcher passes ``categories`` only, so when called via
        ``dispatch_sources`` the keyword fallback is *not* exercised.
        Callers wiring Arxiv in want to pass ``idea`` directly via
        ``fetch`` or via this method on a typed reference.
        """
        if categories & _CATEGORY_FIRES_FOR:
            return True
        return _idea_has_technical_signal(idea)

    def _build_url(self, query: str) -> str:
        return (
            f"{self._api_base}?search_query={query}"
            f"&start=0&max_results={self._max_results}"
            "&sortBy=relevance&sortOrder=descending"
        )

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        # Categorical OR keyword-signal — re-check so a direct caller that
        # bypassed ``applies_to`` still gets the right gating + a clean
        # ``fired=False`` instead of a wasted HTTP round-trip.
        if not (categories & _CATEGORY_FIRES_FOR or _idea_has_technical_signal(idea)):
            return SourceResult(
                source_name=self.name,
                payload={"chunks": []},
                fired=False,
            )

        owns_local = False
        client = self._http
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            owns_local = True

        # Two-attempt strategy: primary query (top-3 OR'd) → on empty body,
        # one retry with a single most-discriminative term. If both come
        # back zero-bytes, give up cleanly with a structured WARN that
        # carries both URLs so the operator can replay them.
        attempts: list[tuple[str, str]] = []  # (query, url)
        primary_query = _build_query(idea)
        attempts.append((primary_query, self._build_url(primary_query)))

        entries: list[dict[str, Any]] = []
        last_query = primary_query
        last_url = attempts[0][1]
        empty_body_urls: list[str] = []

        try:
            for attempt_idx, (query, url) in enumerate([*attempts, ("", "")]):
                # Sentinel allows us to drive the retry inside the loop on
                # empty_body without duplicating the request code; we break
                # out as soon as we either get entries or exhaust attempts.
                if not query:
                    if not empty_body_urls:
                        break
                    # Build fallback only if we hit empty_body at least once.
                    fallback_query = _build_query(
                        idea,
                        max_keywords=FALLBACK_MAX_KEYWORDS,
                        operator="OR",
                    )
                    if fallback_query == primary_query:
                        # Nothing to loosen — bail.
                        break
                    query = fallback_query
                    url = self._build_url(query)

                last_query, last_url = query, url

                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    return SourceResult(
                        source_name=self.name,
                        payload={"chunks": []},
                        fired=False,
                        error=f"arxiv: http error: {type(exc).__name__}: {exc}",
                    )

                if resp.status_code >= 400:
                    return SourceResult(
                        source_name=self.name,
                        payload={"chunks": []},
                        fired=False,
                        error=f"arxiv: HTTP {resp.status_code}",
                    )

                body = resp.text or ""
                if not body.strip():
                    # Production failure mode — Arxiv responded 200 with
                    # zero bytes. Distinct from a valid empty <feed/>.
                    logger.warning(
                        "arxiv.query.empty_body url=%s attempt=%d",
                        url,
                        attempt_idx + 1,
                    )
                    empty_body_urls.append(url)
                    continue  # try the fallback (or exit if exhausted)

                parsed = _parse_atom(body, source_url=url)
                if not parsed:
                    # Valid feed with zero results (or parse error already
                    # WARN'd by `_parse_atom`). Treat zero-results as a
                    # normal "no match" INFO so the dashboards can ratio
                    # against `empty_body`.
                    if "<feed" in body:
                        logger.info(
                            "arxiv.query.zero_results url=%s body_len=%d",
                            url,
                            len(body),
                        )
                    break  # don't retry on legitimate zero-results
                entries = parsed
                break
        finally:
            if owns_local:
                await client.aclose()

        if not entries:
            if len(empty_body_urls) >= 2:
                # Both attempts came back zero-bytes — emit the give-up
                # signal so the operator sees this as an Arxiv-side issue
                # rather than a code bug.
                logger.warning(
                    "arxiv.query.give_up urls=%s",
                    "|".join(empty_body_urls),
                )
                err = "arxiv: empty body on retry"
            elif empty_body_urls:
                err = "arxiv: empty body"
            else:
                err = "arxiv: empty result set"
            return SourceResult(
                source_name=self.name,
                payload={"chunks": []},
                fired=False,
                error=err,
            )

        chunks = [_entry_to_chunk(e) for e in entries[: self._max_results]]
        # Happy-path counterpart to `arxiv.parse.empty` so the operator can
        # compute a parse-success ratio over a CloudWatch window.
        logger.info(
            "arxiv.parse.success url=%s entry_count=%d chunk_count=%d",
            last_url,
            len(entries),
            len(chunks),
        )
        return SourceResult(
            source_name=self.name,
            payload={
                "chunks": chunks,
                "query": last_query,
                "abstract_count": len(chunks),
            },
            cost_usd=0.0,
            fired=True,
        )

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None


def make_arxiv_source(
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    http_client: httpx.AsyncClient | None = None,
) -> ArxivSource:
    """Factory consistent with ``make_bazaar_provider`` + ``TwitshSource``."""
    return ArxivSource(http_client=http_client, max_results=max_results)


__all__ = [
    "ARXIV_API_BASE",
    "DEFAULT_MAX_KEYWORDS",
    "DEFAULT_MAX_RESULTS",
    "FALLBACK_MAX_KEYWORDS",
    "ArxivSource",
    "_build_query",
    "_extract_keywords",
    "_idea_has_technical_signal",
    "_parse_atom",
    "_split_hyphens",
    "make_arxiv_source",
]
