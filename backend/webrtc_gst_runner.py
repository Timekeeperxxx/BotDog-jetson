"""
WSL2 运行器：使用 GStreamer webrtcbin 处理 WebRTC，信令走后端 /ws/webrtc-gst。

用法：
python3 webrtc_gst_runner.py --ws ws://<windows-host>:8000/ws/webrtc-gst --rtsp rtsp://...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import threading
from typing import Optional

import websockets

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
from gi.repository import Gst, GstWebRTC, GstSdp, GLib

Gst.init(None)


class WebRTCClient:
    def __init__(self, ws_url: str, rtsp_url: str, use_qsv: bool = False) -> None:
        self.ws_url = ws_url
        self.rtsp_url = rtsp_url
        self.use_qsv = use_qsv
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._pipeline: Optional[Gst.Pipeline] = None
        self._webrtcbin: Optional[Gst.Element] = None
        self._loop: Optional[GLib.MainLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None

    def _build_pipeline_h264(self) -> str:
        decoder = "qsvh265dec" if self.use_qsv else "avdec_h265"
        encoder = "qsvh264enc bitrate=3000 gop-size=1 rate-control=cbr usage-compliant=true" if self.use_qsv else (
            "x264enc tune=zerolatency speed-preset=ultrafast bitrate=3000 key-int-max=1 bframes=0"
        )

        return (
            "webrtcbin name=sendrecv bundle-policy=max-bundle "
            f"rtspsrc location={self.rtsp_url} latency=0 protocols=tcp drop-on-latency=true ! "
            "rtph265depay ! h265parse ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            f"{decoder} ! videoconvert ! "
            "video/x-raw,format=I420 ! "
            f"{encoder} ! h264parse config-interval=1 ! "
            "rtph264pay config-interval=1 pt=96 ! "
            "application/x-rtp,media=video,encoding-name=H264,payload=96 ! "
            "sendrecv.sink_0"
        )

    def start_pipeline(self) -> None:
        # 1. 极简管线：只保留核心转码部分
        # 暂时去掉所有可能导致崩溃的复杂属性（如 bundle-policy）
        decoder = "qsvh265dec" if self.use_qsv else "avdec_h265"
        encoder = (
            "qsvh264enc bitrate=8000 rate-control=cbr gop-size=30 b-frames=0"
            if self.use_qsv
            else "x264enc tune=zerolatency speed-preset=ultrafast bitrate=8000 key-int-max=30 bframes=0"
        )
        raw_format = "NV12" if self.use_qsv else "I420"
        payload_type = 103

        pipeline_str = (
            "webrtcbin name=sendrecv "
            f"rtspsrc location={self.rtsp_url} latency=0 protocols=tcp ! "
            "rtph265depay ! "
            "h265parse ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            f"{decoder} ! "
            f"video/x-raw,format={raw_format} ! "
            f"{encoder} ! "
            "h264parse config-interval=1 ! "
            f"rtph264pay aggregate-mode=zero-latency pt={payload_type} config-interval=1 ! "
            f"capsfilter name=filter caps=\"application/x-rtp,media=video,encoding-name=H264,payload={payload_type},packetization-mode=1\""
        )

        print("[GST] 正在以‘安全模式’初始化管线...")
        try:
            self._pipeline = Gst.parse_launch(pipeline_str)

            # 获取元素并做非空检查，防止访问空指针（Segfault 的主因）
            filter_element = self._pipeline.get_by_name("filter")
            webrtcbin = self._pipeline.get_by_name("sendrecv")

            if not filter_element or not webrtcbin:
                print("[ERROR] 管线元素获取失败！")
                return

            # 先把管线设为 READY 状态，让插件完成内存初始化
            self._pipeline.set_state(Gst.State.READY)

            # 请求衬垫
            print("[GST] 正在请求 WebRTC 接收口...")
            sink_pad = webrtcbin.request_pad_simple("sink_0")
            if not sink_pad:
                print("[ERROR] 无法请求 sink_0")
                return

            # 链接
            src_pad = filter_element.get_static_pad("src")
            res = src_pad.link(sink_pad)

            if res != Gst.PadLinkReturn.OK:
                print(f"[ERROR] 链接失败: {res}")
            else:
                print("[SUCCESS] 链路对接成功！")

            # 正式启动数据流
            self._pipeline.set_state(Gst.State.PLAYING)
            self._webrtcbin = webrtcbin

        except Exception as e:
            print(f"[CRITICAL] 初始化过程中发生致命错误: {e}")

    def stop_pipeline(self) -> None:
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
        if self._loop:
            self._loop.quit()
        self._pipeline = None
        self._webrtcbin = None
        self._loop = None
        self._loop_thread = None

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        msg_type = message.type
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[GST] ERROR: {err}, {debug}")
        elif msg_type == Gst.MessageType.EOS:
            print("[GST] EOS")

    def _on_ice_candidate(self, _element: Gst.Element, mlineindex: int, candidate: str) -> None:
        if not self._ws:
            return
        payload = {
            "msg_type": "ice_candidate",
            "payload": {
                "candidate": candidate,
                "sdpMLineIndex": mlineindex,
                "sdpMid": "video",
            },
        }
        if self._async_loop:
            self._async_loop.call_soon_threadsafe(
                asyncio.create_task, self._ws.send(json.dumps(payload))
            )

    async def _send_answer(self, answer: GstWebRTC.WebRTCSessionDescription) -> None:
        sdp_text = answer.sdp.as_text()
        await self._ws.send(
            json.dumps({"msg_type": "answer", "payload": {"sdp": sdp_text, "type": "answer"}})
        )

    def _on_answer_created(self, promise: Gst.Promise, _user_data, *_args) -> None:
        if not self._webrtcbin or not self._ws:
            return

        reply = promise.get_reply()
        answer = reply.get_value("answer")
        self._webrtcbin.emit("set-local-description", answer, Gst.Promise.new())
        if self._async_loop:
            self._async_loop.call_soon_threadsafe(
                asyncio.create_task, self._send_answer(answer)
            )

    def _set_remote_offer(self, sdp: str) -> None:
        if not self._webrtcbin:
            return

        _, sdp_msg = GstSdp.SDPMessage.new()
        GstSdp.sdp_message_parse_buffer(bytes(sdp.encode("utf-8")), sdp_msg)
        offer = GstWebRTC.WebRTCSessionDescription.new(
            GstWebRTC.WebRTCSDPType.OFFER, sdp_msg
        )
        self._webrtcbin.emit("set-remote-description", offer, Gst.Promise.new())

        promise = Gst.Promise.new_with_change_func(self._on_answer_created, None, None)
        self._webrtcbin.emit("create-answer", None, promise)

    def _add_ice_candidate(self, candidate: str, sdp_mline_index: int) -> None:
        if not self._webrtcbin:
            return
        self._webrtcbin.emit("add-ice-candidate", sdp_mline_index, candidate)

    async def run(self) -> None:
        self._async_loop = asyncio.get_running_loop()
        async with websockets.connect(self.ws_url) as websocket:
            self._ws = websocket
            print(f"[WS] connected: {self.ws_url}")

            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("msg_type")
                payload = data.get("payload", {})

                if msg_type == "offer":
                    sdp = payload.get("sdp")
                    if sdp:
                        self._set_remote_offer(sdp)
                elif msg_type == "ice_candidate":
                    candidate = payload.get("candidate")
                    if candidate:
                        self._add_ice_candidate(candidate, payload.get("sdpMLineIndex", 0))
                else:
                    print(f"[WS] unknown msg_type: {msg_type}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ws", required=True, help="WebSocket URL, e.g. ws://<host>:8000/ws/webrtc-gst")
    parser.add_argument("--rtsp", required=True, help="RTSP URL")
    parser.add_argument("--qsv", action="store_true", help="use QSV decode/encode")
    args = parser.parse_args()

    client = WebRTCClient(args.ws, args.rtsp, use_qsv=args.qsv)
    client.start_pipeline()
    try:
        await client.run()
    finally:
        client.stop_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
