#!/usr/bin/env python3
"""Offline supervised training pipeline for KYA agent-risk scoring."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, classification_report, precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.load_known_bad_agents import KnownBadAgentsDB  # noqa: E402
from scoring.layer3 import ESCALATION_THRESHOLD, FEATURE_NAMES, Layer3MLEnsemble, _make_synthetic_data  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("train_kya")


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train KYA agent-risk Layer 3 ensemble")
    parser.add_argument("--score-file", type=Path, help="JSONL of exported agent_scores with feature vectors")
    parser.add_argument("--label-file", type=Path, default=Path("data/known_bad_agents.jsonl"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/kya"))
    parser.add_argument("--val-split", type=float, default=0.20)
    parser.add_argument("--base-rate", type=float, default=0.001)
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data for smoke-testing")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_agent_scores(path: Path) -> list[dict[str, Any]]:
    rows = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s:%d: %s", path, lineno, exc)
    log.info("Loaded %d agent score rows from %s", len(rows), path)
    return rows


def extract_features(rows: list[dict[str, Any]], known_bad: KnownBadAgentsDB) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    feature_rows = []
    labels = []
    normal_rows = []

    for row in rows:
        features = _feature_source(row)
        if not features:
            log.debug("Skipping row without feature vector: %s", row.get("id") or row.get("agent_id"))
            continue
        try:
            vector = [float(features.get(name, 0.0)) for name in FEATURE_NAMES]
        except (TypeError, ValueError) as exc:
            log.debug("Skipping malformed feature row for %s: %s", row.get("agent_id"), exc)
            continue

        label = int(
            bool(row.get("is_bad_agent") or row.get("label"))
            or known_bad.is_bad(row.get("agent_id"), row.get("principal_ref"), row.get("wallet"), row.get("address"))
        )
        feature_rows.append(vector)
        labels.append(label)
        if label == 0:
            normal_rows.append(vector)

    X_labelled = np.array(feature_rows, dtype=np.float32)
    y_labelled = np.array(labels, dtype=np.int32)
    X_normal = np.array(normal_rows, dtype=np.float32)
    log.info(
        "Features extracted: %d total | %d normal | %d bad-agent",
        len(y_labelled),
        len(y_labelled) - int(y_labelled.sum()),
        int(y_labelled.sum()),
    )
    return X_normal, X_labelled, y_labelled


def _feature_source(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("features", "feature_vector", "layer3_features"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    layer3 = row.get("layer3")
    if isinstance(layer3, dict):
        for key in ("features", "feature_vector", "layer3_features"):
            value = layer3.get(key)
            if isinstance(value, dict):
                return value
    return None


def validate_training_data(X_normal: np.ndarray, X_labelled: np.ndarray, y_labelled: np.ndarray) -> None:
    if len(X_labelled) == 0:
        raise SystemExit("No KYA features extracted. Export agent_scores with a features object or use --synthetic.")
    if len(X_normal) == 0:
        raise SystemExit("No normal agent scores found. Isolation Forest needs normal samples.")
    if len(set(y_labelled.tolist())) < 2:
        raise SystemExit("Need both normal and bad-agent labels. Add known_bad_agents rows or use --synthetic.")


def evaluate(layer3: Layer3MLEnsemble, X_val: np.ndarray, y_val: np.ndarray) -> None:
    probs = []
    preds = []
    for x in X_val:
        result = layer3.score("__kya_eval__", dict(zip(FEATURE_NAMES, x, strict=True)))
        probs.append(result.ensemble_score)
        preds.append(int(result.escalate_to_llm))

    probs_arr = np.array(probs)
    preds_arr = np.array(preds)
    print("\n" + "=" * 60)
    print("KYA VALIDATION METRICS")
    print("=" * 60)
    print(classification_report(y_val, preds_arr, target_names=["normal", "bad_agent"], digits=3, zero_division=0))

    if y_val.sum() > 0:
        print(f"  AUC-ROC : {roc_auc_score(y_val, probs_arr):.4f}")
        print(f"  AUC-PR  : {average_precision_score(y_val, probs_arr):.4f}")
        precision, recall, thresholds = precision_recall_curve(y_val, probs_arr)
        if len(thresholds) > 0:
            f1_scores = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-9)
            best_idx = int(f1_scores.argmax())
            print(
                f"  Best F1 threshold: {thresholds[best_idx]:.3f} "
                f"(P={precision[best_idx]:.3f} R={recall[best_idx]:.3f} F1={f1_scores[best_idx]:.3f})"
            )
        print(f"  Current threshold : {ESCALATION_THRESHOLD:.3f}\n")


def main() -> None:
    args = build_args()
    started = time.time()

    if args.synthetic:
        log.info("Generating synthetic KYA training data")
        X_normal, X_labelled, y_labelled = _make_synthetic_data(seed=args.seed)
    else:
        if not args.score_file or not args.score_file.exists():
            raise SystemExit("--score-file is required unless --synthetic is used")
        known_bad = KnownBadAgentsDB(args.label_file)
        X_normal, X_labelled, y_labelled = extract_features(load_agent_scores(args.score_file), known_bad)
        validate_training_data(X_normal, X_labelled, y_labelled)

    class_count = len(set(y_labelled.tolist()))
    val_size = max(math.ceil(len(y_labelled) * args.val_split), class_count)
    val_size = min(val_size, len(y_labelled) - class_count)
    stratify = y_labelled if int(y_labelled.sum()) >= 2 and int((y_labelled == 0).sum()) >= 2 else None
    X_train, X_val, y_train, y_val = train_test_split(
        X_labelled,
        y_labelled,
        test_size=val_size,
        stratify=stratify,
        random_state=args.seed,
    )

    layer3 = Layer3MLEnsemble(base_rate=args.base_rate, model_dir=args.model_dir, bootstrap_if_missing=False)
    layer3.fit(X_normal, X_train, y_train, X_val, y_val)
    evaluate(layer3, X_val, y_val)
    layer3.save_models()

    log.info("KYA training complete in %.1fs", time.time() - started)
    for path in sorted(args.model_dir.glob("*.pkl")):
        print(f"  {path} ({path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
