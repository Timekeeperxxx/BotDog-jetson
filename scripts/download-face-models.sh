#!/usr/bin/env bash
set -euo pipefail

model_dir="${1:-/home/jetson/Projects/Models}"
mkdir -p "$model_dir"

curl -L --fail --retry 3 \
  -o "$model_dir/face_detection_yunet_2023mar.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
curl -L --fail --retry 3 \
  -o "$model_dir/face_recognition_sface_2021dec.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

printf '%s  %s\n' \
  "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4" \
  "$model_dir/face_detection_yunet_2023mar.onnx" \
  "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79" \
  "$model_dir/face_recognition_sface_2021dec.onnx" | sha256sum --check
