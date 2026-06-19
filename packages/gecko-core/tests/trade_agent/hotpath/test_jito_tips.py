"""Tests for the Jito tip-floor baseline (recorded live shape + tier/outlier logic)."""

from __future__ import annotations

import httpx
from gecko_core.trade_agent.hotpath.jito_tips import (
    JitoTipsClient,
    TipFloor,
    parse_tip_floor,
)

# Recorded 2026-06-19 from bundles.jito.wtf/api/v1/bundles/tip_floor (SOL).
_LIVE = [
    {
        "time": "2026-06-19T05:22:09+00:00",
        "landed_tips_25th_percentile": 1.00025e-06,
        "landed_tips_50th_percentile": 2.014e-06,
        "landed_tips_75th_percentile": 6e-06,
        "landed_tips_95th_percentile": 0.0001,
        "landed_tips_99th_percentile": 0.0001,
        "ema_landed_tips_50th_percentile": 1.67e-06,
    }
]


def test_parse_live_shape():
    tf = parse_tip_floor(_LIVE)
    assert tf is not None
    assert tf.p50 == 2.014e-06
    assert tf.p95 == 0.0001
    assert tf.ema_p50 == 1.67e-06
    assert tf.time.startswith("2026-06-19")


def test_parse_bad_shapes_return_none():
    assert parse_tip_floor([]) is None
    assert parse_tip_floor("nope") is None
    assert parse_tip_floor([{"landed_tips_50th_percentile": 1.0}]) is None  # missing fields


def test_tier_buckets():
    tf = parse_tip_floor(_LIVE)
    assert tf is not None
    assert tf.tier(0.0002) == "p99+"  # above p99
    assert tf.tier(0.0001) == "p99+"  # == p99 (p95==p99 in this sample) -> top bucket
    assert tf.tier(7e-06) == "p75"
    assert tf.tier(2.014e-06) == "p50"
    assert tf.tier(1e-09) == "below"


def test_is_outlier():
    tf = parse_tip_floor(_LIVE)
    assert tf is not None
    assert tf.is_outlier(0.0001) is True  # at p95
    assert tf.is_outlier(1e-06) is False  # below p95
    assert tf.is_outlier(6e-06, at="p75") is True  # at p75


async def test_client_fetch_parses():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LIVE)

    c = JitoTipsClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    tf = await c.fetch_tip_floor()
    assert isinstance(tf, TipFloor)
    assert tf.p95 == 0.0001


async def test_client_fail_open_on_error():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    c = JitoTipsClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await c.fetch_tip_floor() is None
