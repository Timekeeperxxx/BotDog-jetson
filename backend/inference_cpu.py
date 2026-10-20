"""Bound CPU work in this backend before loading GPU inference models."""
from __future__ import annotations


def configure_inference_cpu(torch_threads: int, opencv_threads: int) -> dict:
    import cv2
    import torch

    if not 1 <= int(torch_threads) <= 32 or not 1 <= int(opencv_threads) <= 32:
        raise ValueError("推理CPU线程数必须在1至32之间")
    before = {"torch_threads": torch.get_num_threads(), "opencv_threads": cv2.getNumThreads()}
    # The package benchmark uses two threads. The live process previously
    # inherited eight threads in both libraries while sharing CPUs with ROS.
    # Configure once at startup, never inside frame inference or a model switch.
    torch.set_num_threads(int(torch_threads))
    cv2.setNumThreads(int(opencv_threads))
    return {"before": before, "torch_threads": torch.get_num_threads(),
            "opencv_threads": cv2.getNumThreads(), "interop_threads_changed": False}
