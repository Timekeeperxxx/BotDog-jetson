#!/usr/bin/env python3
"""Evaluate a local weather checkpoint on the locked DAWN external test set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.weather_detection import (  # noqa: E402
    HuggingFaceWeatherClassifier,
    TensorRTWeatherClassifier,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.model.suffix.lower() == ".engine":
        classifier = TensorRTWeatherClassifier(
            model_path=str(args.model),
            frame_width=640,
            frame_height=480,
            device="auto",
        )
        model_file = args.model
    else:
        classifier = HuggingFaceWeatherClassifier(
            model_path=str(args.model),
            frame_width=640,
            frame_height=480,
            device="auto",
            use_fp16=True,
        )
        model_file = args.model / "model.safetensors"
    mapping = {"Rain": "rain", "Snow": "snow", "Sand": "sandstorm"}
    rows: list[dict[str, object]] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    started = time.perf_counter()
    for folder, expected in mapping.items():
        for image_path in sorted((args.dataset / folder).glob("*.jpg")):
            image = cv2.imread(str(image_path))
            if image is None:
                raise RuntimeError(f"cannot decode {image_path}")
            resized = cv2.resize(image, (640, 480), interpolation=cv2.INTER_AREA)
            probabilities = classifier.predict(np.ascontiguousarray(resized).tobytes())
            ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
            predicted = ranked[0][0]
            confusion[expected][predicted] += 1
            rows.append(
                {
                    "file": str(image_path),
                    "expected": expected,
                    "predicted": predicted,
                    "correct": predicted == expected,
                    "top1_score": ranked[0][1],
                    "top2": f"{ranked[1][0]}:{ranked[1][1]:.6f}",
                    "top3": f"{ranked[2][0]}:{ranked[2][1]:.6f}",
                }
            )
    per_class: dict[str, object] = {}
    for expected in mapping.values():
        selected = [row for row in rows if row["expected"] == expected]
        correct = sum(bool(row["correct"]) for row in selected)
        per_class[expected] = {
            "samples": len(selected),
            "correct": correct,
            "accuracy": correct / len(selected),
        }
    correct = sum(bool(row["correct"]) for row in rows)
    summary = {
        "dataset": "DAWN v3 locked external test",
        "dataset_root": str(args.dataset.resolve()),
        "model": str(args.model.resolve()),
        "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "runtime": classifier.runtime,
        "device": classifier.device,
        "evaluation_rule": "strict directory label, Top-1 exact match",
        "labels_evaluated": list(mapping.values()),
        "samples": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows),
        "per_class": per_class,
        "confusion": {label: dict(counts) for label, counts in confusion.items()},
        "elapsed_seconds": time.perf_counter() - started,
        "training_separation": "DAWN images were not used by train_weather_4class.py",
        "wind": "excluded: not reliably observable from a single image",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "predictions.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
