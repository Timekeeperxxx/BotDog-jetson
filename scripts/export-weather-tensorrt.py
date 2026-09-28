#!/usr/bin/env python3
"""Export the deployed ViT weather checkpoint to a fixed-shape FP16 TensorRT engine."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import torch
from transformers import AutoModelForImageClassification


DEFAULT_MODEL_DIR = Path(
    "/home/jetson/Projects/Models/weather_types_image_detection/checkpoint-3000"
)
DEFAULT_ENGINE_PATH = Path(
    "/home/jetson/Projects/Models/weather_types_image_detection/weather_types_vit_fp16.engine"
)
DEFAULT_TRTEXEC = Path("/usr/src/tensorrt/bin/trtexec")


class _LogitsOnly(torch.nn.Module):
    def __init__(self, model: torch.nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.model(pixel_values=pixel_values).logits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE_PATH)
    parser.add_argument("--trtexec", type=Path, default=DEFAULT_TRTEXEC)
    parser.add_argument("--workspace-mib", type=int, default=2048)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-onnx", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir.expanduser().resolve()
    engine_path = args.engine.expanduser().resolve()
    onnx_path = engine_path.with_suffix(".onnx")
    metadata_path = engine_path.with_suffix(".json")

    if engine_path.exists() and not args.force:
        raise SystemExit(f"engine already exists: {engine_path}; pass --force to rebuild")
    if not args.trtexec.is_file():
        raise SystemExit(f"trtexec not found: {args.trtexec}")

    engine_path.parent.mkdir(parents=True, exist_ok=True)
    model = AutoModelForImageClassification.from_pretrained(
        model_dir,
        local_files_only=True,
    ).eval()
    wrapper = _LogitsOnly(model).eval()
    dummy = torch.zeros((1, 3, 224, 224), dtype=torch.float32)
    torch.onnx.export(
        wrapper,
        (dummy,),
        onnx_path,
        input_names=["pixel_values"],
        output_names=["logits"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )

    command = [
        str(args.trtexec),
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
        "--fp16",
        f"--memPoolSize=workspace:{max(256, args.workspace_mib)}",
        "--builderOptimizationLevel=4",
        "--skipInference",
    ]
    subprocess.run(command, check=True)

    labels = [
        str(model.config.id2label[index]).strip().lower()
        for index in range(len(model.config.id2label))
    ]
    metadata = {
        "format": "tensorrt",
        "precision": "fp16",
        "input_name": "pixel_values",
        "output_name": "logits",
        "input_shape": [1, 3, 224, 224],
        "labels": labels,
        "resize": [224, 224],
        "image_mean": [0.5, 0.5, 0.5],
        "image_std": [0.5, 0.5, 0.5],
        "resample": "bilinear",
        "source_model": str(model_dir),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not args.keep_onnx:
        onnx_path.unlink(missing_ok=True)
    print(f"engine={engine_path}")
    print(f"metadata={metadata_path}")


if __name__ == "__main__":
    main()
