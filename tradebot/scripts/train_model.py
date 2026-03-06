"""
Train ML model for trading strategy.

Loads dataset from CSV, trains RandomForest, saves model + feature names.
Run from project root: python scripts/train_model.py --dataset data/training.csv --output models/ml_strategy_v1.pkl
"""

import argparse
import csv
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.features import FEATURE_NAMES


def main():
    parser = argparse.ArgumentParser(description="Train ML trading model")
    parser.add_argument("--dataset", type=Path, required=True, help="Input CSV from build_dataset.py")
    parser.add_argument("--output", type=Path, default=Path("models/ml_strategy_v1.pkl"), help="Output model path")
    parser.add_argument("--test-frac", type=float, default=0.2, help="Fraction of data for test (time-based, last %%)")
    parser.add_argument("--n-estimators", type=int, default=100, help="RandomForest n_estimators")
    parser.add_argument("--max-depth", type=int, default=12, help="RandomForest max_depth")
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"[ERROR] Dataset not found: {args.dataset}")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Load CSV
    rows = []
    with open(args.dataset) as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)

    X = np.array([[float(row[fn]) for fn in FEATURE_NAMES] for row in rows])
    y = np.array([int(row["label"]) for row in rows])

    if len(X) < 100:
        print(f"[ERROR] Too few samples: {len(X)}")
        sys.exit(1)

    # Time-based split: last test_frac for test
    n = len(X)
    n_test = int(n * args.test_frac)
    n_train = n - n_test
    X_train, X_test = X[:n_train], X[n_train:]
    y_train, y_test = y[:n_train], y[n_train:]

    clf = RandomForestClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        random_state=42,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)

    print(f"[TRAIN] samples={n_train} test={n_test}")
    print(f"[METRICS] accuracy={acc:.4f} precision={prec:.4f} recall={rec:.4f}")

    print("[FEATURE_IMPORTANCE]")
    for fn, imp in sorted(zip(FEATURE_NAMES, clf.feature_importances_), key=lambda x: -x[1]):
        print(f"  {fn}: {imp:.4f}")

    payload = {"model": clf, "feature_names": FEATURE_NAMES}
    joblib.dump(payload, args.output)
    print(f"[OK] Saved to {args.output}")


if __name__ == "__main__":
    main()
