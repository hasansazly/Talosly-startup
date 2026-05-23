from scoring.layer3 import Layer3MLEnsemble


def test_layer3_bootstrap_routes_exploit_and_normal_transactions(tmp_path):
    layer3 = Layer3MLEnsemble(model_dir=tmp_path)

    exploit_result = layer3.score(
        "0xdeadbeef",
        {
            "graph_centrality": 0.92,
            "velocity": 18.0,
            "pool_drain_ratio": 0.85,
            "flash_loan_fingerprint": 1.0,
            "wallet_age_days": 2.0,
            "tornado_tagged": True,
            "calldata_entropy": 6.81,
            "gas_anomaly_zscore": 42.0,
        },
    )
    normal_result = layer3.score(
        "0xcafebabe",
        {
            "graph_centrality": 0.04,
            "velocity": 0.2,
            "pool_drain_ratio": 0.00012,
            "flash_loan_fingerprint": 0.0,
            "wallet_age_days": 400.0,
            "tornado_tagged": False,
            "calldata_entropy": 3.11,
            "gas_anomaly_zscore": -0.33,
        },
    )

    assert exploit_result.escalate_to_llm is True
    assert normal_result.escalate_to_llm is False
    assert exploit_result.ensemble_score > normal_result.ensemble_score
    assert 0 <= exploit_result.gbm_prob <= 1
    assert len(exploit_result.shap_top) == 3


def test_layer3_pickle_round_trip(tmp_path):
    layer3 = Layer3MLEnsemble(model_dir=tmp_path)
    before = layer3.score(
        "0xabc",
        {
            "graph_centrality": 0.75,
            "velocity": 11.0,
            "pool_drain_ratio": 0.4,
            "flash_loan_fingerprint": 0.7,
            "wallet_age_days": 12.0,
            "tornado_tagged": False,
            "calldata_entropy": 6.1,
            "gas_anomaly_zscore": 7.0,
        },
    )

    layer3.save_models()
    reloaded = Layer3MLEnsemble(model_dir=tmp_path, bootstrap_if_missing=False)
    reloaded.load_models()
    after = reloaded.score(
        "0xabc",
        {
            "graph_centrality": 0.75,
            "velocity": 11.0,
            "pool_drain_ratio": 0.4,
            "flash_loan_fingerprint": 0.7,
            "wallet_age_days": 12.0,
            "tornado_tagged": False,
            "calldata_entropy": 6.1,
            "gas_anomaly_zscore": 7.0,
        },
    )

    assert after.ensemble_score == before.ensemble_score
    assert after.escalate_to_llm == before.escalate_to_llm
