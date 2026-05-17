from scoring.cost_tracker import CostTracker, estimate_cost_usd


def test_estimate_cost_usd_uses_gpt_4o_mini_rates():
    assert estimate_cost_usd(1000, 1000) == 0.00075


def test_cost_tracker_reports_calls_and_savings(tmp_path):
    tracker = CostTracker(tmp_path / "gpt_usage.log")
    tracker.log_gpt_call(protocol="0xabc", input_tokens=1000, output_tokens=500, score_delta=12)
    tracker.log_saved_call(protocol="0xabc", estimated_tokens=1000)

    report = tracker.report(protocol="0xabc").to_dict()

    assert report["today_usd"] == 0.00045
    assert report["month_usd"] == 0.00045
    assert report["calls_saved_by_ml"] == 1
    assert report["estimated_savings_usd"] == 0.00015
