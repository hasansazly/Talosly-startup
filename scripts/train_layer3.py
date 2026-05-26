#!/usr/bin/env python3
"""Offline training pipeline for the Talosly Layer 3 XGBoost ensemble."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, classification_report, precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.load_known_hacks import KnownHacksDB  # noqa: E402
from scoring.features import Layer2FeatureEngineering  # noqa: E402
from scoring.layer3 import ESCALATION_THRESHOLD, FEATURE_NAMES, Layer3MLEnsemble, _make_synthetic_data  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("train_layer3")


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Layer 3 XGBoost ML ensemble")
    parser.add_argument("--tx-file", type=Path, help="JSONL of historical transactions")
    parser.add_argument("--hack-file", type=Path, default=Path("data/known_hacks.jsonl"))
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--val-split", type=float, default=0.20)
    parser.add_argument("--base-rate", type=float, default=0.001)
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data for smoke-testing")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_transactions(path: Path) -> list[dict]:
    txs = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            txs.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s:%d: %s", path, lineno, exc)
    log.info("Loaded %d transactions from %s", len(txs), path)
    return txs


def extract_features(txs: list[dict], known_hacks: KnownHacksDB) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    layer2 = Layer2FeatureEngineering()
    rows = []
    labels = []
    normal_rows = []

    for tx in txs:
        tx.setdefault("timestamp", time.time())
        try:
            features = layer2.process(tx)
        except Exception as exc:
            log.debug("Feature extraction failed for %s: %s", tx.get("hash") or tx.get("tx_hash"), exc)
            continue

        feature_dict = features.to_dict()
        row = [float(feature_dict[name]) for name in FEATURE_NAMES]
        tx_hash = str(tx.get("hash") or tx.get("tx_hash") or "").lower()
        label = int(bool(tx.get("is_exploit")) or known_hacks.is_exploit(tx_hash))
        rows.append(row)
        labels.append(label)
        if label == 0:
            normal_rows.append(row)

    X_labelled = np.array(rows, dtype=np.float32)
    y_labelled = np.array(labels, dtype=np.int32)
    X_normal = np.array(normal_rows, dtype=np.float32)
    log.info(
        "Features extracted: %d total | %d normal | %d exploit",
        len(y_labelled),
        len(y_labelled) - int(y_labelled.sum()),
        int(y_labelled.sum()),
    )
    return X_normal, X_labelled, y_labelled


def validate_training_data(X_normal: np.ndarray, X_labelled: np.ndarray, y_labelled: np.ndarray) -> None:
    if len(X_labelled) == 0:
        raise SystemExit("No features extracted. Check --tx-file format.")
    if len(X_normal) == 0:
        raise SystemExit("No normal transactions found. Isolation Forest needs normal samples.")
    if len(set(y_labelled.tolist())) < 2:
        raise SystemExit("Need both normal and exploit labels. Add known hashes or use --synthetic.")


def evaluate(layer3: Layer3MLEnsemble, X_val: np.ndarray, y_val: np.ndarray) -> None:
    probs = []
    preds = []
    for x in X_val:
        result = layer3.score("__eval__", dict(zip(FEATURE_NAMES, x, strict=True)))
        probs.append(result.ensemble_score)
        preds.append(int(result.escalate_to_llm))

    probs_arr = np.array(probs)
    preds_arr = np.array(preds)
    print("\n" + "=" * 60)
    print("VALIDATION METRICS")
    print("=" * 60)
    print(classification_report(y_val, preds_arr, target_names=["normal", "exploit"], digits=3, zero_division=0))

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
        log.info("Generating synthetic training data")
        X_normal, X_labelled, y_labelled = _make_synthetic_data(seed=args.seed)
    else:
        if not args.tx_file or not args.tx_file.exists():
            raise SystemExit("--tx-file is required unless --synthetic is used")
        known_hacks = KnownHacksDB(args.hack_file)
        X_normal, X_labelled, y_labelled = extract_features(load_transactions(args.tx_file), known_hacks)
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

    log.info("Training complete in %.1fs", time.time() - started)
    for path in sorted(args.model_dir.glob("*.pkl")):
        print(f"  {path} ({path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
