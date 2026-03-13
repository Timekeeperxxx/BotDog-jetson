"""
WebRTC 信令处理器。

职责边界：
- 管理 WebRTC 对等连接
- 处理 SDP offer/answer 交换
- 处理 ICE 候选交换
- 管理连接生命周期
"""

import asyncio
import logging
import re
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .logging_config import logger
from .config import settings
from .udp_relay import UDPRelayManager
from .gst_rtsp_bridge import GstRtspBridge
from .video_track import GStreamerVideoSourceFactory


class WebRTCPeerConnection:
    """aiortc 对等连接管理器（UDP RTP 输入）。"""

    def __init__(self, client_id: str, websocket: WebSocket, bridge: GstRtspBridge):
        self.client_id = client_id
        self.websocket = websocket
        self.bridge = bridge
        self.pc: Optional[Any] = None
        self.video_track: Optional[Any] = None
        self._ice_candidates: list[dict] = []
        self._connected = False
        self._created_at = asyncio.get_event_loop().time()
        self._ice_gathering_complete = False

    async def initialize(self) -> None:
        try:
            from aiortc import RTCPeerConnection, RTCConfiguration

            configuration = RTCConfiguration(iceServers=[])
            self.pc = RTCPeerConnection(configuration)

            @self.pc.on("icegatheringstatechange")
            def on_ice_gathering_state_change():
                if self.pc:
                    logger.info(
                        f"ICE 收集状态变化: {self.client_id} -> {self.pc.iceGatheringState}"
                    )

            @self.pc.on("connectionstatechange")
            async def on_connectionstatechange():
                if self.pc is None:
                    return
                logger.info(
                    f"WebRTC 连接状态变化: {self.client_id} -> {self.pc.connectionState}"
                )

                if self.pc.connectionState == "connected":
                    self._connected = True
                    logger.info(f"WebRTC 连接已建立: {self.client_id}")
                elif self.pc.connectionState in ("failed", "disconnected", "closed"):
                    self._connected = False
                    logger.warning(
                        f"WebRTC 连接断开: {self.client_id} -> {self.pc.connectionState}"
                    )

            @self.pc.on("icecandidate")
            def on_ice_candidate(candidate):
                if candidate:
                    self._ice_candidates.append({
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    })
                else:
                    self._ice_gathering_complete = True

            # 启动 RTSP -> UDP 桥接
            self.bridge.start()

            # 创建并添加 UDP RTP 视频轨道
            width, height = map(int, settings.VIDEO_RESOLUTION.split('x'))
            self.video_track = GStreamerVideoSourceFactory.create_track(
                udp_port=settings.VIDEO_UDP_PORT,
                width=width,
                height=height,
                framerate=settings.VIDEO_FRAMERATE,
            )
            await self.video_track.start()
            self.pc.addTrack(self.video_track)

            logger.info(f"WebRTC 对等连接已初始化: {self.client_id}")

        except ImportError as e:
            logger.error(f"导入 aiortc 失败: {e}")
            raise
        except Exception as e:
            logger.error(f"初始化 WebRTC 对等连接失败: {e}")
            raise

    async def set_remote_description(self, sdp_type: str, sdp: str) -> None:
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        from aiortc import RTCSessionDescription

        description = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await self.pc.setRemoteDescription(description)
        logger.info(f"已设置远程描述: {self.client_id} ({sdp_type})")

    async def create_answer(self) -> str:
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        logger.info(f"已创建 SDP answer: {self.client_id}, 等待 ICE 收集...")

        for _ in range(20):
            if self._ice_gathering_complete:
                break
            await asyncio.sleep(0.5)

        return self.pc.localDescription.sdp

    async def get_ice_candidates(self) -> list[dict]:
        candidates = self._ice_candidates.copy()
        self._ice_candidates.clear()
        return candidates

    async def add_ice_candidate(self, candidate_dict: dict) -> None:
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        from aiortc import RTCIceCandidate

        candidate_str = candidate_dict.get("candidate", "")
        parts = candidate_str.split()
        if len(parts) < 8:
            return

        foundation = parts[0].split(':')[1] if ':' in parts[0] else parts[0]
        component = int(parts[1])
        protocol = parts[2]
        priority = int(parts[3])
        ip = parts[4]
        port = int(parts[5])

        candidate_type = "host"
        for i, part in enumerate(parts):
            if part == "typ" and i + 1 < len(parts):
                candidate_type = parts[i + 1]
                break

        candidate = RTCIceCandidate(
            component=component,
            foundation=foundation,
            ip=ip,
            port=port,
            priority=priority,
            protocol=protocol,
            type=candidate_type,
            sdpMid=candidate_dict.get("sdpMid"),
            sdpMLineIndex=candidate_dict.get("sdpMLineIndex"),
        )

        await self.pc.addIceCandidate(candidate)

    async def close(self) -> None:
        if self.video_track:
            await self.video_track.stop()
            self.video_track = None
        if self.pc:
            await self.pc.close()
            self.pc = None
        self._connected = False
        self.bridge.stop()
        logger.info(f"WebRTC 对等连接已关闭: {self.client_id}")

    @property
    def is_connected(self) -> bool:
        return self._connected and self.pc is not None

    @property
    def age_seconds(self) -> float:
        return asyncio.get_event_loop().time() - self._created_at


class WebRTCSignalingHandler:
    """
    WebRTC 信令处理器。

    管理 WebSocket 连接和 WebRTC 信令流程。
    """

    def __init__(self):
        """初始化信令处理器。"""
        self._connections: Dict[str, WebRTCPeerConnection] = {}
        self._lock = asyncio.Lock()
        self._udp_relay_manager = UDPRelayManager()
        self._udp_relay_started = False
        self._gst_bridge = GstRtspBridge()
        self._gst_websocket: Optional[WebSocket] = None
        self._browser_websocket: Optional[WebSocket] = None
        self._browser_client_id: Optional[str] = None

    async def start_udp_relay(self) -> None:
        """启动 UDP 视频流转发器。"""
        if self._udp_relay_started:
            return

        # 检查是否启用 UDP 转发器
        if not settings.UDP_RELAY_ENABLED:
            logger.info(
                f"UDP 转发器已禁用（video_track_native 直接监听端口 {settings.UDP_RELAY_LISTEN_PORT}）"
            )
            self._udp_relay_started = True
            return

        try:
            await self._udp_relay_manager.add_relay(
                name="video_stream",
                listen_port=settings.UDP_RELAY_LISTEN_PORT,
                bind_address=settings.UDP_RELAY_BIND_ADDRESS,
                target_port=settings.VIDEO_UDP_PORT,
                target_address=settings.UDP_RELAY_TARGET_ADDRESS,
                buffer_size=settings.UDP_RELAY_BUFFER_SIZE,
                enable_stats=settings.UDP_RELAY_ENABLE_STATS,
                stats_interval=settings.UDP_RELAY_STATS_INTERVAL,
            )
            self._udp_relay_started = True
            logger.info(
                f"UDP 视频流转发器已启动: "
                f"{settings.UDP_RELAY_BIND_ADDRESS}:{settings.UDP_RELAY_LISTEN_PORT} -> "
                f"{settings.UDP_RELAY_TARGET_ADDRESS}:{settings.VIDEO_UDP_PORT}"
            )
        except OSError as e:
            # 端口暂时不可用是正常的（相机可能还没推流）
            if "10049" in str(e) or "10048" in str(e):
                logger.warning(
                    f"UDP 端口 {settings.UDP_RELAY_LISTEN_PORT} 暂时不可用，等待视频流... "
                    f"这通常是因为相机还未开始推流"
                )
                # 不抛出错误，允许继续启动
                self._udp_relay_started = True
            else:
                logger.error(f"启动 UDP 视频流转发器失败: {e}")
                raise
        except Exception as e:
            logger.error(f"启动 UDP 视频流转发器失败: {e}")
            raise

    async def stop_udp_relay(self) -> None:
        """停止 UDP 视频流转发器。"""
        if not self._udp_relay_started:
            return

        await self._udp_relay_manager.stop_all()
        self._udp_relay_started = False
        logger.info("UDP 视频流转发器已停止")

    async def handle_connection(self, websocket: WebSocket) -> None:
        """
        处理 WebSocket 连接（浏览器端）。

        Args:
            websocket: WebSocket 连接
        """
        client_id = str(uuid.uuid4())
        logger.info(f"WebRTC 客户端连接: {client_id}")

        if settings.VIDEO_BACKEND_MODE == "webrtcbin":
            await self._handle_browser_relay(websocket, client_id)
            return

        try:
            await websocket.accept()

            # 创建对等连接
            peer_connection = WebRTCPeerConnection(client_id, websocket, self._gst_bridge)
            await peer_connection.initialize()

            async with self._lock:
                self._connections[client_id] = peer_connection

            # 发送欢迎消息
            await websocket.send_json({
                "msg_type": "welcome",
                "client_id": client_id,
            })

            # 消息循环
            while True:
                try:
                    data = await websocket.receive_json()
                    await self._handle_message(peer_connection, data)
                except WebSocketDisconnect:
                    logger.info(f"WebSocket 客户端断开: {client_id}")
                    break
                except Exception as e:
                    logger.error(f"处理消息失败 ({client_id}): {e}")
                    await websocket.send_json({
                        "msg_type": "error",
                        "error": str(e),
                    })

        except Exception as e:
            logger.error(f"WebRTC 连接处理失败 ({client_id}): {e}")
        finally:
            # 清理连接
            await peer_connection.close()
            async with self._lock:
                self._connections.pop(client_id, None)
            logger.info(f"WebRTC 客户端已清理: {client_id}")

    async def _handle_message(
        self,
        peer_connection: WebRTCPeerConnection,
        data: dict,
    ) -> None:
        """
        处理信令消息。

        Args:
            peer_connection: 对等连接实例
            data: 消息数据
        """
        msg_type = data.get("msg_type")
        payload = data.get("payload", {})

        if msg_type == "offer":
            sdp = payload.get("sdp")
            if not sdp:
                raise ValueError("缺少 SDP offer")

            await peer_connection.set_remote_description("offer", sdp)
            answer_sdp = await peer_connection.create_answer()

            await peer_connection.websocket.send_json({
                "msg_type": "answer",
                "payload": {
                    "sdp": answer_sdp,
                    "type": "answer",
                },
            })

            await asyncio.sleep(0.5)
            candidates = await peer_connection.get_ice_candidates()
            if candidates:
                await peer_connection.websocket.send_json({
                    "msg_type": "ice_candidates",
                    "payload": {"candidates": candidates},
                })

        elif msg_type == "ice_candidate":
            await peer_connection.add_ice_candidate(payload)

        else:
            logger.warning(f"未知消息类型: {msg_type}")


    async def handle_gst_connection(self, websocket: WebSocket) -> None:
        """
        处理 webrtcbin runner 的 WebSocket 连接。

        Args:
            websocket: WebSocket 连接
        """
        await websocket.accept()
        self._gst_websocket = websocket
        logger.info("webrtcbin runner 已连接")

        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    await self._handle_gst_message(data)
                except WebSocketDisconnect:
                    logger.info("webrtcbin runner 断开")
                    break
                except Exception as e:
                    logger.error(f"webrtcbin 消息处理失败: {e}")
                    await websocket.send_json({
                        "msg_type": "error",
                        "error": str(e),
                    })
        finally:
            if self._gst_websocket is websocket:
                self._gst_websocket = None
            logger.info("webrtcbin runner 已清理")

    async def _handle_browser_relay(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._browser_websocket = websocket
        self._browser_client_id = client_id
        logger.info(f"浏览器信令连接 (webrtcbin 模式): {client_id}")

        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    await self._handle_browser_message(data)
                except WebSocketDisconnect:
                    logger.info(f"浏览器信令断开: {client_id}")
                    break
                except Exception as e:
                    logger.error(f"浏览器信令处理失败 ({client_id}): {e}")
                    await websocket.send_json({
                        "msg_type": "error",
                        "error": str(e),
                    })
        finally:
            if self._browser_websocket is websocket:
                self._browser_websocket = None
                self._browser_client_id = None
            logger.info(f"浏览器信令已清理: {client_id}")

    async def _handle_browser_message(self, data: dict) -> None:
        msg_type = data.get("msg_type")
        payload = data.get("payload", {})

        if not self._gst_websocket or self._gst_websocket.client_state != WebSocketState.CONNECTED:
            raise RuntimeError("webrtcbin runner 未连接")

        if msg_type == "offer":
            sdp = payload.get("sdp")
            if not sdp:
                raise ValueError("缺少 SDP offer")

            await self._gst_websocket.send_json({
                "msg_type": "offer",
                "payload": {
                    "sdp": sdp,
                    "type": "offer",
                },
            })
        elif msg_type == "ice_candidate":
            await self._gst_websocket.send_json({
                "msg_type": "ice_candidate",
                "payload": payload,
            })
        else:
            logger.warning(f"未知浏览器消息类型: {msg_type}")

    async def _handle_gst_message(self, data: dict) -> None:
        msg_type = data.get("msg_type")
        payload = data.get("payload", {})

        if not self._browser_websocket or self._browser_websocket.client_state != WebSocketState.CONNECTED:
            logger.warning("浏览器未连接，忽略 webrtcbin 消息")
            return

        if msg_type == "answer":
            sdp = payload.get("sdp")
            if not sdp:
                raise ValueError("缺少 SDP answer")

            await self._browser_websocket.send_json({
                "msg_type": "answer",
                "payload": {
                    "sdp": sdp,
                    "type": "answer",
                },
            })
        elif msg_type == "ice_candidate":
            await self._browser_websocket.send_json({
                "msg_type": "ice_candidate",
                "payload": payload,
            })
        else:
            logger.warning(f"未知 webrtcbin 消息类型: {msg_type}")

    async def broadcast_status(self) -> None:
        """广播视频流状态。"""
        # TODO: 实现状态广播
        pass

    async def cleanup_stale_connections(self, timeout: float = 300) -> None:
        """
        清理过期连接。

        Args:
            timeout: 超时时间（秒）
        """
        async with self._lock:
            stale_clients = [
                client_id
                for client_id, pc in self._connections.items()
                if pc.age_seconds > timeout and not pc.is_connected
            ]

            for client_id in stale_clients:
                logger.info(f"清理过期连接: {client_id}")
                await self._connections[client_id].close()
                del self._connections[client_id]

    def get_udp_relay_stats(self) -> Dict[str, Any]:
        """
        获取 UDP 转发器统计信息。

        Returns:
            统计信息字典
        """
        if not self._udp_relay_started:
            return {"status": "not_started"}

        return self._udp_relay_manager.get_all_stats()
