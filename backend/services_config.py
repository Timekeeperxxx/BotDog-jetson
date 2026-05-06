"""
配置管理服务。

职责边界：
- 读取系统配置
- 更新系统配置
- 配置验证
- 配置变更历史记录
"""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .models_config import SystemConfig, ConfigChangeHistory
from .config import settings
from .logging_config import logger


class ConfigService:
    """
    配置管理服务。

    功能：
    - 从数据库读取配置
    - 更新配置到数据库
    - 验证配置值
    - 记录配置变更历史
    """

    # 定义默认配置项
    DEFAULT_CONFIGS = {
        # 后端核心配置
        "thermal_threshold": {
            "value": "60.0",
            "value_type": "float",
            "category": "backend",
            "description": "触发高温告警的温度阈值 (°C)",
            "is_hot_reloadable": True,
        },
        "heartbeat_timeout": {
            "value": "3.0",
            "value_type": "float",
            "category": "backend",
            "description": "心跳超时时间 (秒)",
            "is_hot_reloadable": False,
        },
        "control_rate_limit_hz": {
            "value": "20",
            "value_type": "int",
            "category": "backend",
            "description": "控制指令频率限制 (Hz)",
            "is_hot_reloadable": True,
        },
        "ws_max_clients_per_ip": {
            "value": "5",
            "value_type": "int",
            "category": "backend",
            "description": "单 IP 最大 WebSocket 连接数",
            "is_hot_reloadable": False,
        },
        "video_watchdog_timeout_s": {
            "value": "2.0",
            "value_type": "float",
            "category": "backend",
            "description": "视频看门狗超时时间 (秒)",
            "is_hot_reloadable": True,
        },
        "safety_block_motion_when_disconnected": {
            "value": "true" if settings.SAFETY_BLOCK_MOTION_WHEN_DISCONNECTED else "false",
            "value_type": "bool",
            "category": "backend",
            "description": "底层断链时是否阻止运动命令（开发调试可关闭，真机部署建议开启）",
            "is_hot_reloadable": True,
        },

        # 硬件网口配置
        "unitree_network_iface": {
            "value": settings.UNITREE_NETWORK_IFACE,
            "value_type": "string",
            "category": "hardware",
            "description": "宇树适配器使用的网卡名称（保存后通常需重启后端或重新初始化硬件适配器）",
            "is_hot_reloadable": False,
        },
        "mavlink_endpoint": {
            "value": settings.MAVLINK_ENDPOINT,
            "value_type": "string",
            "category": "hardware",
            "description": "MAVLink 连接端点（第一版仅保存，不支持运行时热更新）",
            "is_hot_reloadable": False,
        },

        # Canvas 区域绘制配置
        "zone_draw_saved_fill_rgba": {
            "value": settings.ZONE_DRAW_SAVED_FILL_RGBA,
            "value_type": "string",
            "category": "frontend_draw",
            "description": "已保存区域的填充颜色",
            "is_hot_reloadable": True,
        },
        "zone_draw_saved_stroke_rgba": {
            "value": settings.ZONE_DRAW_SAVED_STROKE_RGBA,
            "value_type": "string",
            "category": "frontend_draw",
            "description": "已保存区域的描边颜色",
            "is_hot_reloadable": True,
        },
        "zone_draw_saved_line_width": {
            "value": str(settings.ZONE_DRAW_SAVED_LINE_WIDTH),
            "value_type": "float",
            "category": "frontend_draw",
            "description": "已保存区域的描边线宽",
            "is_hot_reloadable": True,
        },
        "zone_draw_active_stroke_rgba": {
            "value": settings.ZONE_DRAW_ACTIVE_STROKE_RGBA,
            "value_type": "string",
            "category": "frontend_draw",
            "description": "当前绘制线条颜色",
            "is_hot_reloadable": True,
        },
        "zone_draw_active_line_width": {
            "value": str(settings.ZONE_DRAW_ACTIVE_LINE_WIDTH),
            "value_type": "float",
            "category": "frontend_draw",
            "description": "当前绘制线宽",
            "is_hot_reloadable": True,
        },
        "zone_draw_point_radius": {
            "value": str(settings.ZONE_DRAW_POINT_RADIUS),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "顶点圆点半径",
            "is_hot_reloadable": True,
        },
        "zone_draw_dash_on": {
            "value": str(settings.ZONE_DRAW_DASH_ON),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "虚线绘制段长度",
            "is_hot_reloadable": True,
        },
        "zone_draw_dash_off": {
            "value": str(settings.ZONE_DRAW_DASH_OFF),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "虚线间隔长度",
            "is_hot_reloadable": True,
        },
        "zone_draw_toolbar_bottom_px": {
            "value": str(settings.ZONE_DRAW_TOOLBAR_BOTTOM_PX),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "绘制工具栏底部偏移像素",
            "is_hot_reloadable": True,
        },
        "zone_draw_canvas_z_index": {
            "value": str(settings.ZONE_DRAW_CANVAS_Z_INDEX),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "绘制 canvas 的层级值",
            "is_hot_reloadable": True,
        },
        "zone_draw_toolbar_z_index": {
            "value": str(settings.ZONE_DRAW_TOOLBAR_Z_INDEX),
            "value_type": "int",
            "category": "frontend_draw",
            "description": "绘制工具栏的层级值",
            "is_hot_reloadable": True,
        },

        # HSV / 黄区识别配置
        "zone_yellow_h_low": {
            "value": str(settings.ZONE_YELLOW_H_LOW),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 色相下限",
            "is_hot_reloadable": True,
        },
        "zone_yellow_h_high": {
            "value": str(settings.ZONE_YELLOW_H_HIGH),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 色相上限",
            "is_hot_reloadable": True,
        },
        "zone_yellow_s_low": {
            "value": str(settings.ZONE_YELLOW_S_LOW),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 饱和度下限",
            "is_hot_reloadable": True,
        },
        "zone_yellow_s_high": {
            "value": str(settings.ZONE_YELLOW_S_HIGH),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 饱和度上限",
            "is_hot_reloadable": True,
        },
        "zone_yellow_v_low": {
            "value": str(settings.ZONE_YELLOW_V_LOW),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 亮度下限",
            "is_hot_reloadable": True,
        },
        "zone_yellow_v_high": {
            "value": str(settings.ZONE_YELLOW_V_HIGH),
            "value_type": "int",
            "category": "zone",
            "description": "黄色区域 HSV 亮度上限",
            "is_hot_reloadable": True,
        },
        "zone_border_v_threshold": {
            "value": str(settings.ZONE_BORDER_V_THRESHOLD),
            "value_type": "int",
            "category": "zone",
            "description": "黑边验证的亮度阈值",
            "is_hot_reloadable": True,
        },
        "zone_border_expand_px": {
            "value": str(settings.ZONE_BORDER_EXPAND_PX),
            "value_type": "int",
            "category": "zone",
            "description": "黑边验证外扩采样像素宽度",
            "is_hot_reloadable": True,
        },
        "zone_min_area_px": {
            "value": str(settings.ZONE_MIN_AREA_PX),
            "value_type": "int",
            "category": "zone",
            "description": "区域最小像素面积",
            "is_hot_reloadable": True,
        },
        "zone_max_area_ratio": {
            "value": str(settings.ZONE_MAX_AREA_RATIO),
            "value_type": "float",
            "category": "zone",
            "description": "区域最大画面占比",
            "is_hot_reloadable": True,
        },
        "zone_min_aspect": {
            "value": str(settings.ZONE_MIN_ASPECT),
            "value_type": "float",
            "category": "zone",
            "description": "区域最小长宽比",
            "is_hot_reloadable": True,
        },
        "zone_max_aspect": {
            "value": str(settings.ZONE_MAX_ASPECT),
            "value_type": "float",
            "category": "zone",
            "description": "区域最大长宽比",
            "is_hot_reloadable": True,
        },
        "zone_min_solidity": {
            "value": str(settings.ZONE_MIN_SOLIDITY),
            "value_type": "float",
            "category": "zone",
            "description": "区域最小饱满度",
            "is_hot_reloadable": True,
        },
        "zone_roi_top_ratio": {
            "value": str(settings.ZONE_ROI_TOP_RATIO),
            "value_type": "float",
            "category": "zone",
            "description": "检测 ROI 顶部裁剪比例",
            "is_hot_reloadable": True,
        },
        "zone_morph_kernel_size": {
            "value": str(settings.ZONE_MORPH_KERNEL_SIZE),
            "value_type": "int",
            "category": "zone",
            "description": "形态学核尺寸",
            "is_hot_reloadable": True,
        },
        "zone_w_area": {
            "value": str(settings.ZONE_W_AREA),
            "value_type": "float",
            "category": "zone",
            "description": "面积评分权重",
            "is_hot_reloadable": True,
        },
        "zone_w_solid": {
            "value": str(settings.ZONE_W_SOLID),
            "value_type": "float",
            "category": "zone",
            "description": "饱满度评分权重",
            "is_hot_reloadable": True,
        },
        "zone_w_border": {
            "value": str(settings.ZONE_W_BORDER),
            "value_type": "float",
            "category": "zone",
            "description": "黑边评分权重",
            "is_hot_reloadable": True,
        },
        "zone_center_crop_ratio": {
            "value": str(settings.ZONE_CENTER_CROP_RATIO),
            "value_type": "float",
            "category": "zone",
            "description": "中心文字检测裁剪比例",
            "is_hot_reloadable": True,
        },
        "zone_center_black_v_threshold": {
            "value": str(settings.ZONE_CENTER_BLACK_V_THRESHOLD),
            "value_type": "int",
            "category": "zone",
            "description": "中心黑字亮度阈值",
            "is_hot_reloadable": True,
        },
        "zone_center_black_min_ratio": {
            "value": str(settings.ZONE_CENTER_BLACK_MIN_RATIO),
            "value_type": "float",
            "category": "zone",
            "description": "中心黑字最小占比",
            "is_hot_reloadable": True,
        },
        "zone_center_text_bonus": {
            "value": str(settings.ZONE_CENTER_TEXT_BONUS),
            "value_type": "float",
            "category": "zone",
            "description": "检测到黑字时的质量奖励分",
            "is_hot_reloadable": True,
        },

        # 前端配置
        "ui_alert_ack_timeout_s": {
            "value": "60",
            "value_type": "int",
            "category": "frontend",
            "description": "告警确认超时时间 (秒)",
            "is_hot_reloadable": True,
        },
        "telemetry_display_hz": {
            "value": "15",
            "value_type": "int",
            "category": "frontend",
            "description": "遥测数据显示刷新率 (Hz)",
            "is_hot_reloadable": True,
        },
        "ui_lang": {
            "value": "zh-CN",
            "value_type": "string",
            "category": "frontend",
            "description": "界面语言",
            "is_hot_reloadable": True,
        },
        "ui_theme": {
            "value": "dark",
            "value_type": "string",
            "category": "frontend",
            "description": "UI 主题",
            "is_hot_reloadable": True,
        },

        # 存储配置
        "snapshot_retention_days": {
            "value": "30",
            "value_type": "int",
            "category": "storage",
            "description": "抓拍图片保留天数",
            "is_hot_reloadable": False,
        },
        "max_snapshot_disk_usage_gb": {
            "value": "50",
            "value_type": "int",
            "category": "storage",
            "description": "抓拍目录最大磁盘占用 (GB)",
            "is_hot_reloadable": False,
        },
        "telemetry_retention_days": {
            "value": "90",
            "value_type": "int",
            "category": "storage",
            "description": "遥测数据保留天数",
            "is_hot_reloadable": False,
        },

        # 自动跟踪配置 (AutoTrack)
        "auto_track_stable_hits": {
            "value": "3",
            "value_type": "int",
            "category": "auto_track",
            "description": "确定目标的防抖识别帧数",
            "is_hot_reloadable": True,
        },
        "auto_track_lost_timeout_frames": {
            "value": "30",
            "value_type": "int",
            "category": "auto_track",
            "description": "目标丢失后等待的超时帧数",
            "is_hot_reloadable": True,
        },
        "auto_track_yaw_deadband_px": {
            "value": "80",
            "value_type": "int",
            "category": "auto_track",
            "description": "目标居中平移转向死区 (像素)",
            "is_hot_reloadable": True,
        },
        "auto_track_forward_area_ratio": {
            "value": "0.15",
            "value_type": "float",
            "category": "auto_track",
            "description": "开始前进的目标面积比例上限",
            "is_hot_reloadable": True,
        },
        "auto_track_anchor_y_stop_ratio": {
            "value": "0.80",
            "value_type": "float",
            "category": "auto_track",
            "description": "防止过近的底部警戒线比例",
            "is_hot_reloadable": True,
        },
    }

    # 配置验证规则
    VALIDATION_RULES = {
        "thermal_threshold": {"min": 30.0, "max": 120.0},
        "heartbeat_timeout": {"min": 1.0, "max": 10.0},
        "control_rate_limit_hz": {"min": 5, "max": 50},
        "ws_max_clients_per_ip": {"min": 1, "max": 20},
        "video_watchdog_timeout_s": {"min": 1.0, "max": 10.0},
        "zone_draw_saved_line_width": {"min": 0.1, "max": 20.0},
        "zone_draw_active_line_width": {"min": 0.1, "max": 20.0},
        "zone_draw_point_radius": {"min": 1, "max": 20},
        "zone_draw_dash_on": {"min": 1, "max": 50},
        "zone_draw_dash_off": {"min": 0, "max": 50},
        "zone_draw_toolbar_bottom_px": {"min": 0, "max": 500},
        "zone_draw_canvas_z_index": {"min": -1000, "max": 1000},
        "zone_draw_toolbar_z_index": {"min": -1000, "max": 1000},
        "zone_yellow_h_low": {"min": 0, "max": 180},
        "zone_yellow_h_high": {"min": 0, "max": 180},
        "zone_yellow_s_low": {"min": 0, "max": 255},
        "zone_yellow_s_high": {"min": 0, "max": 255},
        "zone_yellow_v_low": {"min": 0, "max": 255},
        "zone_yellow_v_high": {"min": 0, "max": 255},
        "zone_border_v_threshold": {"min": 0, "max": 255},
        "zone_border_expand_px": {"min": 1, "max": 30},
        "zone_min_area_px": {"min": 1, "max": 1000000},
        "zone_max_area_ratio": {"min": 0.01, "max": 1.0},
        "zone_min_aspect": {"min": 1.0, "max": 50.0},
        "zone_max_aspect": {"min": 1.0, "max": 50.0},
        "zone_min_solidity": {"min": 0.0, "max": 1.0},
        "zone_roi_top_ratio": {"min": 0.0, "max": 1.0},
        "zone_morph_kernel_size": {"min": 1, "max": 51},
        "zone_w_area": {"min": 0.0, "max": 1.0},
        "zone_w_solid": {"min": 0.0, "max": 1.0},
        "zone_w_border": {"min": 0.0, "max": 1.0},
        "zone_center_crop_ratio": {"min": 0.1, "max": 1.0},
        "zone_center_black_v_threshold": {"min": 0, "max": 255},
        "zone_center_black_min_ratio": {"min": 0.0, "max": 1.0},
        "zone_center_text_bonus": {"min": 0.0, "max": 5.0},
        "ui_alert_ack_timeout_s": {"min": 10, "max": 600},
        "telemetry_display_hz": {"min": 5, "max": 30},
        "snapshot_retention_days": {"min": 7, "max": 365},
        "max_snapshot_disk_usage_gb": {"min": 10, "max": 500},
        "telemetry_retention_days": {"min": 30, "max": 365},
        "auto_track_stable_hits": {"min": 1, "max": 30},
        "auto_track_lost_timeout_frames": {"min": 5, "max": 300},
        "auto_track_yaw_deadband_px": {"min": 10, "max": 640},
        "auto_track_forward_area_ratio": {"min": 0.01, "max": 1.0},
        "auto_track_anchor_y_stop_ratio": {"min": 0.1, "max": 1.0},
    }

    def __init__(self):
        """初始化配置服务。"""
        self._config_cache: Dict[str, Any] = {}

    async def initialize_defaults(self, session: AsyncSession) -> None:
        """
        初始化默认配置。

        将默认配置写入数据库（如果不存在）。
        """
        for key, config_data in self.DEFAULT_CONFIGS.items():
            # 检查是否已存在
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                config = SystemConfig(
                    key=key,
                    value=config_data["value"],
                    value_type=config_data["value_type"],
                    category=config_data["category"],
                    description=config_data["description"],
                    is_hot_reloadable=config_data["is_hot_reloadable"],
                )
                session.add(config)
                logger.info(f"初始化默认配置: {key} = {config_data['value']}")

        await session.commit()

    async def get_all_configs(self, session: AsyncSession) -> Dict[str, Any]:
        """
        获取所有配置。

        Args:
            session: 数据库会话

        Returns:
            配置字典
        """
        result = await session.execute(select(SystemConfig))
        configs = result.scalars().all()

        return {config.key: config.to_dict() for config in configs}

    async def get_config(self, session: AsyncSession, key: str) -> Optional[Any]:
        """
        获取单个配置值。

        Args:
            session: 数据库会话
            key: 配置键

        Returns:
            配置值，如果不存在返回 None
        """
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            return config.to_dict()
        return None

    async def update_config(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        changed_by: str = "system",
        reason: str = "",
    ) -> SystemConfig:
        """
        更新配置。

        Args:
            session: 数据库会话
            key: 配置键
            value: 新值
            changed_by: 修改者
            reason: 修改原因

        Returns:
            更新后的配置对象

        Raises:
            ValueError: 配置值无效
        """
        # 验证配置值
        self._validate_config(key, value)

        # 获取现有配置
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if not config:
            raise ValueError(f"配置项不存在: {key}")

        # 记录旧值
        old_value = config.value

        # 更新配置
        config.value = str(value)

        # 记录变更历史
        history = ConfigChangeHistory(
            config_key=key,
            old_value=old_value,
            new_value=config.value,
            changed_by=changed_by,
            reason=reason,
        )
        session.add(history)

        await session.commit()
        await session.refresh(config)

        logger.info(
            f"配置已更新: {key} = {value} "
            f"(by {changed_by}, reason: {reason or 'N/A'})"
        )

        return config

    def _validate_config(self, key: str, value: Any) -> None:
        """
        验证配置值。

        Args:
            key: 配置键
            value: 配置值

        Raises:
            ValueError: 配置值无效
        """
        if key not in self.VALIDATION_RULES:
            return

        rules = self.VALIDATION_RULES[key]
        min_val = rules.get("min")
        max_val = rules.get("max")

        try:
            num_value = float(value)
            if min_val is not None and num_value < min_val:
                raise ValueError(f"配置值 {value} 小于最小值 {min_val}")
            if max_val is not None and num_value > max_val:
                raise ValueError(f"配置值 {value} 大于最大值 {max_val}")
        except (ValueError, TypeError) as e:
            raise ValueError(f"配置值 {value} 无效: {e}")

    async def get_config_history(
        self,
        session: AsyncSession,
        key: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        获取配置变更历史。

        Args:
            session: 数据库会话
            key: 配置键（可选，如果为 None 则返回所有配置的历史）
            limit: 最大返回数量

        Returns:
            变更历史列表
        """
        query = select(ConfigChangeHistory)

        if key:
            query = query.where(ConfigChangeHistory.config_key == key)

        query = query.order_by(ConfigChangeHistory.changed_at.desc()).limit(limit)

        result = await session.execute(query)
        history = result.scalars().all()

        return [h.to_dict() for h in history]


# 全局配置服务实例
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    """
    获取配置服务实例。

    Returns:
        配置服务实例
    """
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service
