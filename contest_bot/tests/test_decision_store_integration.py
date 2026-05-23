def test_build_decision_doc_maps_panel_to_record():
    from jto_breakout_gecko_gated_contest_bot import build_decision_doc

    doc = build_decision_doc(
        run_id="r1",
        symbol="PYTH",
        snap={
            "adx": 27.6,
            "rsi": 67.0,
            "chop": 43.3,
            "adx_slope": 2.0,
            "adx_distance": 2.6,
            "chop_distance": 18.5,
        },
        signal={"fired": True, "type": "breakout"},
        panel_voices=[{"name": "chart_analyst", "verdict": "abstain", "confidence": 0.0}],
        oracle={"verdict": "pass", "citations": 9, "grounded": True},
        coordinator={"action": "decline", "rule": "chart_below_threshold"},
    )
    d = doc.to_dict()
    assert d["symbol"] == "PYTH" and d["indicators"]["adx_distance"] == 2.6
    assert d["coordinator"]["action"] == "decline" and d["market_context"] is None
