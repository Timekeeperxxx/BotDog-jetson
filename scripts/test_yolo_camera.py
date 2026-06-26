#!/usr/bin/env python3
"""
Test YOLO camera inference with real-time bounding boxes.

Defaults are read from backend/.env:
- AI_RTSP_URL
- AI_MODEL_PATH
- AI_TARGET_CLASSES
- AI_CONFIDENCE_THRESHOLD
"""

from __future__ import annotations

import argparse
import threading
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_defaults():
    from backend.config import settings

    return {
        "source": settings.AI_RTSP_URL,
        "model": settings.AI_MODEL_PATH,
        "conf": settings.AI_CONFIDENCE_THRESHOLD,
        "classes": ",".join(settings.AI_TARGET_CLASSES),
    }


def _parse_source(value: str) -> str | int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return value


def _parse_classes(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _resolve_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str(PROJECT_ROOT / candidate)


def _has_display() -> bool:
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _open_capture(source: str | int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"cannot open video source: {source}")
    return cap


def _format_boxes(boxes: list[dict]) -> str:
    if not boxes:
        return "none"
    parts = []
    for box in boxes:
        x1, y1, x2, y2 = box["xyxy"]
        parts.append(
            f"{box['label']}:{box['conf']:.2f}"
            f"@({x1},{y1},{x2},{y2})"
        )
    return " | ".join(parts)


class _FrameStreamer:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None

    def update(self, frame) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return
        with self._condition:
            self._jpeg = encoded.tobytes()
            self._condition.notify_all()

    def wait_for_frame(self) -> bytes:
        with self._condition:
            while self._jpeg is None:
                self._condition.wait(timeout=1.0)
            return self._jpeg


def _start_web_server(streamer: _FrameStreamer, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                body = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>YOLO camera test</title>"
                    "<style>body{margin:0;background:#111;color:#eee;font-family:sans-serif;}"
                    "header{padding:10px 14px;background:#202020;}"
                    "img{display:block;width:100vw;height:calc(100vh - 42px);object-fit:contain;}</style>"
                    "</head><body><header>YOLO camera test</header>"
                    "<img src='/stream' alt='YOLO stream'></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path != "/stream":
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            try:
                while True:
                    jpeg = streamer.wait_for_frame()
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> int:
    defaults = _load_defaults()

    parser = argparse.ArgumentParser(description="Run YOLO on camera/RTSP and show boxes.")
    parser.add_argument("--source", default=defaults["source"], help="RTSP URL or camera index")
    parser.add_argument("--model", default=defaults["model"], help="YOLO .pt/.engine path")
    parser.add_argument("--conf", type=float, default=defaults["conf"], help="confidence threshold")
    parser.add_argument("--classes", default=defaults["classes"], help="comma-separated class names to keep")
    parser.add_argument("--imgsz", type=int, default=640, help="inference image size")
    parser.add_argument("--device", default=None, help="optional YOLO device, e.g. 0/cpu/cuda:0")
    parser.add_argument("--no-window", action="store_true", help="do not show OpenCV preview window")
    parser.add_argument("--web", action="store_true", help="serve annotated preview over HTTP")
    parser.add_argument("--web-host", default="0.0.0.0", help="HTTP preview bind host")
    parser.add_argument("--web-port", type=int, default=8090, help="HTTP preview port")
    parser.add_argument("--print-empty", action="store_true", help="print frames with no detections")
    parser.add_argument("--reconnect-delay", type=float, default=2.0, help="seconds before reconnect")
    args = parser.parse_args()

    source = _parse_source(args.source)
    model_path = _resolve_path(args.model)
    keep_classes = _parse_classes(args.classes)
    use_web = args.web
    if not args.no_window and not args.web and not _has_display():
        use_web = True
        print("DISPLAY is not available; falling back to --web preview.")
    show_window = not args.no_window and not use_web

    print(f"source={source}")
    print(f"model={model_path}")
    print(f"classes={sorted(keep_classes) if keep_classes else 'all'} conf={args.conf} imgsz={args.imgsz}")

    streamer = _FrameStreamer() if use_web else None
    web_server = None
    if streamer is not None:
        web_server = _start_web_server(streamer, args.web_host, args.web_port)
        print(f"web_preview_local=http://127.0.0.1:{args.web_port}")
        print(f"web_preview_lan=http://{_local_ip()}:{args.web_port}")

    model = YOLO(model_path, task="detect")
    names = model.names
    print(f"model_names={names}")

    cap = _open_capture(source)
    frame_index = 0
    last_empty_print = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print(f"frame read failed, reconnecting in {args.reconnect_delay:.1f}s")
                cap.release()
                time.sleep(args.reconnect_delay)
                cap = _open_capture(source)
                continue

            frame_index += 1
            predict_kwargs = {
                "source": frame,
                "conf": args.conf,
                "imgsz": args.imgsz,
                "verbose": False,
            }
            if args.device is not None:
                predict_kwargs["device"] = args.device

            results = model.predict(**predict_kwargs)
            boxes = []

            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                label = names.get(cls_id, str(cls_id))
                if keep_classes and label not in keep_classes:
                    continue

                conf = float(box.conf[0])
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                boxes.append({"label": label, "conf": conf, "xyxy": (x1, y1, x2, y2)})

                color = (0, 220, 80)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                text = f"{label} {conf:.2f}"
                cv2.putText(
                    frame,
                    text,
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                    cv2.LINE_AA,
                )

            now = time.time()
            if boxes or args.print_empty or now - last_empty_print >= 2.0:
                print(f"frame={frame_index} detections={len(boxes)} boxes={_format_boxes(boxes)}", flush=True)
                if not boxes:
                    last_empty_print = now

            if streamer is not None:
                streamer.update(frame)

            if show_window:
                cv2.imshow("YOLO camera test", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        if show_window:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
