"""
视频源 & 网口管理服务。

职责边界：
- 视频源（摄像头）的 CRUD 操作
- 网口配置的 CRUD 操作
- 启动时初始化默认数据（从 .env 读取种子值）
- 确保 is_primary / is_ai_source 的唯一约束
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .logging_config import logger
from .models import VideoSource, NetworkInterface, utc_now_iso


class VideoSourceService:
    """视频源管理服务。"""

    async def initialize_defaults(self, session: AsyncSession) -> None:
        """
        初始化默认视频源。

        如果数据库中没有任何视频源记录，则根据 .env 配置和硬编码默认值
        创建 cam1（主摄像头）和 cam2（画中画）两个默认视频源。
        """
        result = await session.execute(select(VideoSource))
        existing = result.scalars().all()
        if existing:
            logger.info(f"视频源已存在 {len(existing)} 条，跳过默认初始化")
            return

        # 从 .env 推算 WHEP 基础地址
        # AI_RTSP_URL 格式: rtsp://127.0.0.1:8554/cam
        rtsp_url = settings.AI_RTSP_URL
        # WHEP URL 与 RTSP 在同一主机，默认端口 8889
        # 尝试从 RTSP URL 提取主机名
        whep_host = "127.0.0.1"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(rtsp_url)
            if parsed.hostname:
                whep_host = parsed.hostname
        except Exception:
            pass

        ts = utc_now_iso()

        cam1 = VideoSource(
            name="cam1",
            label="主摄像头",
            source_type="whep",
            whep_url=f"http://{whep_host}:8889/cam/whep",
            rtsp_url=rtsp_url,
            enabled=1,
            is_primary=1,
            is_ai_source=1,
            sort_order=0,
            created_at=ts,
            updated_at=ts,
        )

        cam2 = VideoSource(
            name="cam2",
            label="图传摄像头",
            source_type="whep",
            whep_url=f"http://{whep_host}:8889/cam2/whep",
            rtsp_url=None,
            enabled=1,
            is_primary=0,
            is_ai_source=0,
            sort_order=1,
            created_at=ts,
            updated_at=ts,
        )

        session.add(cam1)
        session.add(cam2)
        await session.commit()
        logger.info(f"已初始化默认视频源: cam1 (主画面+AI), cam2 (画中画)")

    async def list_all(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """获取所有视频源。"""
        result = await session.execute(
            select(VideoSource).order_by(VideoSource.sort_order, VideoSource.source_id)
        )
        sources = result.scalars().all()
        return [self._to_dict(s) for s in sources]

    async def list_active(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """获取所有已启用的视频源（供前端消费）。"""
        result = await session.execute(
            select(VideoSource)
            .where(VideoSource.enabled == 1)
            .order_by(VideoSource.sort_order, VideoSource.source_id)
        )
        sources = result.scalars().all()
        return [self._to_dict(s) for s in sources]

    async def get_by_id(self, session: AsyncSession, source_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取视频源。"""
        result = await session.execute(
            select(VideoSource).where(VideoSource.source_id == source_id)
        )
        source = result.scalar_one_or_none()
        return self._to_dict(source) if source else None

    async def create(self, session: AsyncSession, data: Dict[str, Any]) -> Dict[str, Any]:
        """新增视频源。"""
        ts = utc_now_iso()

        # 如果设置为主画面，先取消其他主画面
        if data.get("is_primary"):
            await self._clear_flag(session, "is_primary")
        # 如果设置为 AI 源，先取消其他 AI 源
        if data.get("is_ai_source"):
            await self._clear_flag(session, "is_ai_source")

        source = VideoSource(
            name=data["name"],
            label=data["label"],
            source_type=data.get("source_type", "whep"),
            whep_url=data.get("whep_url"),
            rtsp_url=data.get("rtsp_url"),
            enabled=1 if data.get("enabled", True) else 0,
            is_primary=1 if data.get("is_primary", False) else 0,
            is_ai_source=1 if data.get("is_ai_source", False) else 0,
            sort_order=data.get("sort_order", 0),
            created_at=ts,
            updated_at=ts,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        logger.info(f"新增视频源: {source.name} ({source.label})")
        return self._to_dict(source)

    async def update(self, session: AsyncSession, source_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新视频源。"""
        result = await session.execute(
            select(VideoSource).where(VideoSource.source_id == source_id)
        )
        source = result.scalar_one_or_none()
        if not source:
            return None

        # 处理独占标志
        if data.get("is_primary") and not source.is_primary:
            await self._clear_flag(session, "is_primary")
        if data.get("is_ai_source") and not source.is_ai_source:
            await self._clear_flag(session, "is_ai_source")

        # 更新字段
        for field in ("name", "label", "source_type", "whep_url", "rtsp_url", "sort_order"):
            if field in data:
                setattr(source, field, data[field])

        if "enabled" in data:
            source.enabled = 1 if data["enabled"] else 0
        if "is_primary" in data:
            source.is_primary = 1 if data["is_primary"] else 0
        if "is_ai_source" in data:
            source.is_ai_source = 1 if data["is_ai_source"] else 0

        source.updated_at = utc_now_iso()
        await session.commit()
        await session.refresh(source)
        logger.info(f"更新视频源: {source.name} (id={source_id})")
        return self._to_dict(source)

    async def delete(self, session: AsyncSession, source_id: int) -> bool:
        """删除视频源。"""
        result = await session.execute(
            select(VideoSource).where(VideoSource.source_id == source_id)
        )
        source = result.scalar_one_or_none()
        if not source:
            return False

        name = source.name
        await session.delete(source)
        await session.commit()
        logger.info(f"删除视频源: {name} (id={source_id})")
        return True

    async def _clear_flag(self, session: AsyncSession, flag: str) -> None:
        """清除所有记录的指定标志（确保唯一性）。"""
        await session.execute(
            update(VideoSource).values(**{flag: 0})
        )

    @staticmethod
    def _to_dict(source: VideoSource) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "source_id": source.source_id,
            "name": source.name,
            "label": source.label,
            "source_type": source.source_type,
            "whep_url": source.whep_url,
            "rtsp_url": source.rtsp_url,
            "enabled": bool(source.enabled),
            "is_primary": bool(source.is_primary),
            "is_ai_source": bool(source.is_ai_source),
            "sort_order": source.sort_order,
            "created_at": source.created_at,
            "updated_at": source.updated_at,
        }


class NetworkInterfaceService:
    """网口管理服务。"""

    async def initialize_defaults(self, session: AsyncSession) -> None:
        """
        初始化默认网口配置。

        如果数据库中没有任何网口记录，则根据 .env 配置创建默认网口。
        """
        result = await session.execute(select(NetworkInterface))
        existing = result.scalars().all()
        if existing:
            logger.info(f"网口配置已存在 {len(existing)} 条，跳过默认初始化")
            return

        ts = utc_now_iso()

        robot_iface = NetworkInterface(
            name="robot_link",
            label="机器人连接网口",
            iface_name=settings.UNITREE_NETWORK_IFACE,
            ip_address=None,
            purpose="robot",
            enabled=1,
            created_at=ts,
            updated_at=ts,
        )
        session.add(robot_iface)
        await session.commit()
        logger.info(f"已初始化默认网口配置: robot_link ({settings.UNITREE_NETWORK_IFACE})")

    async def list_all(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """获取所有网口配置。"""
        result = await session.execute(
            select(NetworkInterface).order_by(NetworkInterface.iface_id)
        )
        ifaces = result.scalars().all()
        return [self._to_dict(i) for i in ifaces]

    async def get_by_id(self, session: AsyncSession, iface_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取网口配置。"""
        result = await session.execute(
            select(NetworkInterface).where(NetworkInterface.iface_id == iface_id)
        )
        iface = result.scalar_one_or_none()
        return self._to_dict(iface) if iface else None

    async def create(self, session: AsyncSession, data: Dict[str, Any]) -> Dict[str, Any]:
        """新增网口配置。"""
        ts = utc_now_iso()
        iface = NetworkInterface(
            name=data["name"],
            label=data["label"],
            iface_name=data["iface_name"],
            ip_address=data.get("ip_address"),
            purpose=data.get("purpose", "other"),
            enabled=1 if data.get("enabled", True) else 0,
            created_at=ts,
            updated_at=ts,
        )
        session.add(iface)
        await session.commit()
        await session.refresh(iface)
        logger.info(f"新增网口配置: {iface.name} ({iface.iface_name})")
        return self._to_dict(iface)

    async def update(self, session: AsyncSession, iface_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新网口配置。"""
        result = await session.execute(
            select(NetworkInterface).where(NetworkInterface.iface_id == iface_id)
        )
        iface = result.scalar_one_or_none()
        if not iface:
            return None

        for field in ("name", "label", "iface_name", "ip_address", "purpose"):
            if field in data:
                setattr(iface, field, data[field])

        if "enabled" in data:
            iface.enabled = 1 if data["enabled"] else 0

        iface.updated_at = utc_now_iso()
        await session.commit()
        await session.refresh(iface)
        logger.info(f"更新网口配置: {iface.name} (id={iface_id})")
        return self._to_dict(iface)

    async def delete(self, session: AsyncSession, iface_id: int) -> bool:
        """删除网口配置。"""
        result = await session.execute(
            select(NetworkInterface).where(NetworkInterface.iface_id == iface_id)
        )
        iface = result.scalar_one_or_none()
        if not iface:
            return False

        name = iface.name
        await session.delete(iface)
        await session.commit()
        logger.info(f"删除网口配置: {name} (id={iface_id})")
        return True

    @staticmethod
    def _to_dict(iface: NetworkInterface) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "iface_id": iface.iface_id,
            "name": iface.name,
            "label": iface.label,
            "iface_name": iface.iface_name,
            "ip_address": iface.ip_address,
            "purpose": iface.purpose,
            "enabled": bool(iface.enabled),
            "created_at": iface.created_at,
            "updated_at": iface.updated_at,
        }


# 全局服务实例
_video_source_service: Optional[VideoSourceService] = None
_network_interface_service: Optional[NetworkInterfaceService] = None


def get_video_source_service() -> VideoSourceService:
    """获取视频源服务单例。"""
    global _video_source_service
    if _video_source_service is None:
        _video_source_service = VideoSourceService()
    return _video_source_service


def get_network_interface_service() -> NetworkInterfaceService:
    """获取网口服务单例。"""
    global _network_interface_service
    if _network_interface_service is None:
        _network_interface_service = NetworkInterfaceService()
    return _network_interface_service
