#!/usr/bin/env python3
"""Download the pinned baseline weather checkpoint into the Models directory."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download


REPOSITORY = "dima806/weather_types_image_detection"
CHECKPOINT = "checkpoint-3000"
TARGET_ROOT = Path("/home/jetson/Projects/Models/weather_types_image_detection")
FILES = (
    f"{CHECKPOINT}/config.json",
    f"{CHECKPOINT}/preprocessor_config.json",
    f"{CHECKPOINT}/model.safetensors",
)


def main() -> None:
    for filename in FILES:
        path = hf_hub_download(
            repo_id=REPOSITORY,
            filename=filename,
            local_dir=TARGET_ROOT,
        )
        print(path)


if __name__ == "__main__":
    main()
