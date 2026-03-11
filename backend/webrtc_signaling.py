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

from .logging_config import logger
from .config import settings
# 使用 subprocess 版本的 GStreamer 视频源（零 Python 依赖）
from .video_track_native import GStreamerVideoSourceFactory
from .udp_relay import UDPRelayManager


class WebRTCPeerConnection:
    """
    WebRTC 对等连接管理器。

    每个客户端连接对应一个对等连接实例。
    """

    def __init__(self, client_id: str, websocket: WebSocket):
        """
        初始化对等连接。

        Args:
            client_id: 客户端唯一标识
            websocket: WebSocket 连接
        """
        self.client_id = client_id
        self.websocket = websocket
        self.pc: Optional[Any] = None  # RTCPeerConnection (延迟导入)
        self.video_track: Optional[Any] = None  # MediaStreamTrack
        self._ice_candidates: list[dict] = []
        self._remote_sdp: Optional[str] = None
        self._connected = False
        self._created_at = asyncio.get_event_loop().time()
        self._ice_gathering_complete = False  # ICE 收集完成标志

    async def initialize(self) -> None:
        """初始化 WebRTC 对等连接。"""
        try:
            from aiortc import RTCPeerConnection, MediaStreamTrack, RTCConfiguration, RTCIceServer
            from av import VideoFrame

            # ICE 服务器配置（本地测试，不使用 STUN）
            # 空配置将使用本地 host 候选
            configuration = RTCConfiguration(iceServers=[])
            self.pc = RTCPeerConnection(configuration)

            # 添加 ICE 收集状态监控
            @self.pc.on("icegatheringstatechange")
            def on_ice_gathering_state_change():
                """ICE 收集状态变化回调。"""
                if self.pc:
                    logger.info(
                        f"ICE 收集状态变化: {self.client_id} -> "
                        f"{self.pc.iceGatheringState}"
                    )

            @self.pc.on("connectionstatechange")
            async def on_connectionstatechange():
                """连接状态变化回调。"""
                if self.pc is None:
                    return
                logger.info(
                    f"WebRTC 连接状态变化: {self.client_id} -> "
                    f"{self.pc.connectionState}"
                )

                if self.pc.connectionState == "connected":
                    self._connected = True
                    logger.info(f"WebRTC 连接已建立: {self.client_id}")
                elif self.pc.connectionState in ("failed", "disconnected", "closed"):
                    self._connected = False
                    logger.warning(
                        f"WebRTC 连接断开: {self.client_id} -> "
                        f"{self.pc.connectionState}"
                    )

            @self.pc.on("icecandidate")
            def on_ice_candidate(candidate):
                """ICE 候选回调。"""
                if candidate:
                    self._ice_candidates.append({
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    })
                    logger.debug(f"收集到 ICE 候选: {self.client_id}")
                else:
                    # null candidate 表示收集完成
                    self._ice_gathering_complete = True
                    logger.info(f"ICE 收集完成: {self.client_id}, 共 {len(self._ice_candidates)} 个候选")

            # 创建并添加视频轨道（使用 GStreamer RTSP 直连真实相机架构）
            # RTSP 直连：rtsp://192.168.144.25:8554/main.264
            # 从配置读取参数并解析分辨率
            width, height = map(int, settings.VIDEO_RESOLUTION.split('x'))
            video_track = GStreamerVideoSourceFactory.create_track(
                rtsp_url=settings.CAMERA_RTSP_URL,  # RTSP 直连真实相机
                tcp_port=6000,  # TCP 环回端口
                width=width,
                height=height,
                framerate=settings.VIDEO_FRAMERATE,
            )
            self.video_track = video_track
            video_track.start()  # 同步调用（不再使用 await）
            self.pc.addTrack(video_track)

            logger.info(f"WebRTC 对等连接已初始化: {self.client_id}")

        except ImportError as e:
            logger.error(f"导入 aiortc 失败: {e}")
            raise
        except Exception as e:
            logger.error(f"初始化 WebRTC 对等连接失败: {e}")
            raise

    async def set_remote_description(self, sdp_type: str, sdp: str) -> None:
        """
        设置远程描述。

        Args:
            sdp_type: SDP 类型（offer/answer）
            sdp: SDP 内容
        """
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        from aiortc import RTCSessionDescription

        description = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await self.pc.setRemoteDescription(description)
        self._remote_sdp = sdp
        logger.info(f"已设置远程描述: {self.client_id} ({sdp_type})")

    async def create_answer(self) -> str:
        """
        创建 SDP answer。

        Returns:
            SDP 内容
        """
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        logger.info(f"已创建 SDP answer: {self.client_id}, 等待 ICE 收集...")

        # 等待 ICE 收集完成（最多 10 秒）
        for attempt in range(20):
            if self._ice_gathering_complete:
                logger.info(f"ICE 收集已完成: {self.client_id}")
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning(f"ICE 收集超时: {self.client_id}, 当前 {len(self._ice_candidates)} 个候选")

        # 修改 SDP：强制使用 H.264 baseline profile + 仅保留 H.264 + 提升码率
        sdp = self.pc.localDescription.sdp
        sdp = self._force_h264_baseline(sdp)
        sdp = self._force_h264_only(sdp)
        sdp = self._boost_video_bitrate(sdp)
        logger.info("✅ 已强制 SDP 仅使用 H.264 baseline profile")
        logger.info(f"✅ 已提升视频码率至高质量（{settings.VIDEO_BITRATE//1000000}Mbps）")

        return sdp

    def _force_h264_baseline(self, sdp: str) -> str:
        """
        修改 SDP，强制使用 H.264 baseline profile（浏览器兼容性最好）

        Args:
            sdp: 原始 SDP

        Returns:
            修改后的 SDP
        """
        lines = sdp.split('\n')
        modified_lines = []

        for line in lines:
            # 修改 H.264 profile-level-id 为 42e01f (baseline profile)
            if 'profile-level-id' in line and 'H264' in sdp:
                # 使用正则替换所有 profile-level-id=xxxxxx 格式
                line = re.sub(r'profile-level-id=[0-9a-f]{6}', 'profile-level-id=42e01f', line)

            modified_lines.append(line)

        return '\n'.join(modified_lines)

    def _force_h264_only(self, sdp: str) -> str:
        """
        修改 SDP，仅保留 H.264，禁用 VP8/VP9 等软解码器。

        Args:
            sdp: 原始 SDP

        Returns:
            修改后的 SDP（仅 H.264）
        """
        lines = sdp.split('\n')
        modified_lines = []
        allowed_payloads: set[int] = set()

        # 收集 H.264 payload type（数字形式）
        for line in lines:
            if line.startswith('a=rtpmap:') and 'H264' in line:
                # 格式: a=rtpmap:96 H264/90000
                try:
                    payload = int(line.split(':', 1)[1].split(' ', 1)[0])
                    allowed_payloads.add(payload)
                    logger.info(f"✅ 找到 H.264 payload: {payload}")
                except (ValueError, IndexError):
                    pass

        logger.info(f"📋 允许的 H.264 payload: {allowed_payloads}")

        # 如果没有找到 H.264，返回原 SDP（避免破坏）
        if not allowed_payloads:
            logger.warning("⚠️ SDP 中没有 H.264，返回原始 SDP")
            return sdp

        for line in lines:
            # 过滤视频 m= 行，只保留 H.264 payload
            if line.startswith('m=video'):
                parts = line.split(' ')
                # m=video <port> <proto> <payloads...>
                base = parts[:3]
                payloads = []
                for p in parts[3:]:
                    try:
                        if int(p) in allowed_payloads:
                            payloads.append(p)
                    except ValueError:
                        payloads.append(p)  # 保留非数字部分

                if payloads:
                    line = ' '.join(base + payloads)
                    logger.info(f"✅ 视频 m 行已更新: {line}")
                else:
                    logger.warning("⚠️ 过滤后没有有效 payload，保留原行")
                    # 保留原行，避免破坏
                    modified_lines.append(line)
                    continue

            # 过滤非 H.264 的 rtpmap/fmtp/rtcp-fb
            if line.startswith('a=rtpmap:') or line.startswith('a=fmtp:') or line.startswith('a=rtcp-fb:'):
                try:
                    # 格式: a=rtpmap:96 H264/90000 或 a=fmtp:96 profile-level-id=...
                    payload_str = line.split(':', 1)[1].split(' ')[0]
                    payload = int(payload_str)
                    if payload not in allowed_payloads:
                        continue  # 跳过非 H.264 的行
                except (ValueError, IndexError):
                    pass  # 保留无法解析的行

            modified_lines.append(line)

        result = '\n'.join(modified_lines)
        logger.info("✅ SDP 已强制为 H.264 only")
        return result

    def _boost_video_bitrate(self, sdp: str) -> str:
        """
        提升 SDP 中的视频码率设置，改善快速转动时的画质

        Args:
            sdp: 原始 SDP

        Returns:
            修改后的 SDP（高码率配置）
        """
        lines = sdp.split('\n')
        modified_lines = []

        # 目标码率：从配置读取（默认 8Mbps）
        target_bitrate = settings.VIDEO_BITRATE  # 8,000,000 bps

        for line in lines:
            # 提升视频码率（b=AS:带宽）
            if 'm=video' in line:
                modified_lines.append(line)
                # 在 m=video 后添加带宽行
                modified_lines.append(f'b=AS:{target_bitrate // 1000}')  # AS 单位是 kbps
                continue

            # 修改现有带宽设置
            if line.startswith('b=AS:') and 'video' in sdp[max(0, sdp.index(line)-500):sdp.index(line)]:
                # 提升视频带宽
                line = f'b=AS:{target_bitrate // 1000}'

            # 修改传输码率（TIAS）
            if 'TIAS' in line:
                # TIAS 是实际应用层码率
                line = line.replace(r'TIAS:[0-9]+', f'TIAS:{target_bitrate}')

            modified_lines.append(line)

        return '\n'.join(modified_lines)

    async def get_ice_candidates(self) -> list[dict]:
        """
        获取待发送的 ICE 候选。

        Returns:
            ICE 候选列表
        """
        candidates = self._ice_candidates.copy()
        self._ice_candidates.clear()
        return candidates

    async def add_ice_candidate(self, candidate_dict: dict) -> None:
        """
        添加 ICE 候选。

        Args:
            candidate_dict: ICE 候选字典
        """
        if not self.pc:
            raise RuntimeError("对等连接未初始化")

        from aiortc import RTCIceCandidate
        import re

        # 解析 candidate 字符串
        # 格式: "candidate:..." 字符串，包含所有信息
        candidate_str = candidate_dict.get("candidate", "")

        # 简单解析 candidate 字符串
        # 示例: "candidate:1 1 UDP 2122260223 192.168.1.100 54321 typ host"
        parts = candidate_str.split()
        if len(parts) < 8:
            logger.warning(f"无法解析 ICE 候选: {candidate_str}")
            return

        try:
            # 解析关键字段
            foundation = parts[0].split(':')[1] if ':' in parts[0] else parts[0]
            component = int(parts[1])
            protocol = parts[2]
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])

            # 查找 type
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
            logger.debug(f"已添加 ICE 候选: {self.client_id}")

        except Exception as e:
            logger.error(f"解析或添加 ICE 候选失败: {e}, candidate: {candidate_str}")
            # 不抛出异常，允许连接继续

    async def close(self) -> None:
        """关闭对等连接。"""
        if self.video_track:
            # stop() 现在是同步方法，直接调用即可
            self.video_track.stop()
            self.video_track = None
        if self.pc:
            await self.pc.close()
            self.pc = None
        self._connected = False
        logger.info(f"WebRTC 对等连接已关闭: {self.client_id}")

    @property
    def is_connected(self) -> bool:
        """是否已连接。"""
        return self._connected and self.pc is not None

    @property
    def age_seconds(self) -> float:
        """连接年龄（秒）。"""
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
        处理 WebSocket 连接。

        Args:
            websocket: WebSocket 连接
        """
        client_id = str(uuid.uuid4())
        logger.info(f"WebRTC 客户端连接: {client_id}")

        try:
            await websocket.accept()

            # 创建对等连接
            peer_connection = WebRTCPeerConnection(client_id, websocket)
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
            # 处理 SDP offer
            sdp = payload.get("sdp")
            if not sdp:
                raise ValueError("缺少 SDP offer")

            # 打印 SDP 用于调试
            print("\n" + "="*80)
            print("📥 收到前端 SDP Offer:")
            print("="*80)
            print(sdp)
            print("="*80 + "\n")

            try:
                await peer_connection.set_remote_description("offer", sdp)
                answer_sdp = await peer_connection.create_answer()

                # 打印 Answer SDP
                print("\n" + "="*80)
                print("📤 发送前端 SDP Answer:")
                print("="*80)
                print(answer_sdp)
                print("="*80 + "\n")

                await peer_connection.websocket.send_json({
                    "msg_type": "answer",
                    "payload": {
                        "sdp": answer_sdp,
                        "type": "answer",
                    },
                })

                # 等待一小段时间确保 ICE 候选已发送
                await asyncio.sleep(1.0)

                # 获取并发送所有 ICE 候选
                candidates = await peer_connection.get_ice_candidates()
                if candidates:
                    logger.info(f"发送 {len(candidates)} 个 ICE 候选")
                    await peer_connection.websocket.send_json({
                        "msg_type": "ice_candidates",
                        "payload": {
                            "candidates": candidates,
                        },
                    })
                else:
                    logger.info(f"没有 ICE 候选需要发送 ({peer_connection.client_id})")
            except Exception as e:
                print("\n" + "="*80)
                print(f"❌ 处理 Offer 时发生异常: {type(e).__name__}")
                print(f"异常详情: {e}")
                print("="*80 + "\n")
                raise

        elif msg_type == "ice_candidate":
            # 处理 ICE 候选
            await peer_connection.add_ice_candidate(payload)

        else:
            logger.warning(f"未知消息类型: {msg_type}")

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
