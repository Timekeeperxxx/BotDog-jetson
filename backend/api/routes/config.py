"""系统配置管理路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_admin, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...database import get_db
from ...logging_config import logger

router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"布尔值无效: {value}")


def _apply_runtime_update(key: str, value) -> dict:
    """
    根据配置键尝试执行运行时更新。

    DB 保存成功后调用，失败不影响主流程。
    """
    if key == "unitree_network_iface":
        return {
            "applied": False,
            "target": "hardware",
            "message": "需重启后端或重新初始化硬件适配器",
        }

    if key == "mavlink_endpoint":
        return {
            "applied": False,
            "target": "hardware",
            "message": "需重启后端生效",
        }

    if key.startswith("zone_draw_"):
        return {
            "applied": True,
            "target": "frontend",
            "message": "前端配置将在下一次配置刷新后生效",
        }

    if key.startswith("zone_"):
        try:
            from ...guard_mission_service import get_guard_mission_service

            guard_service = get_guard_mission_service()
            if guard_service and guard_service.update_zone_detector_config(key, value):
                return {
                    "applied": True,
                    "target": "zone",
                    "message": "运行时已生效",
                }
            return {
                "applied": False,
                "target": "zone",
                "message": "当前检测器实例未接入运行时热更新",
            }
        except Exception as exc:  # pragma: no cover - 仅在运行环境异常时触发
            logger.warning(f"[config] zone 热更新失败: key={key} error={exc}")
            return {
                "applied": False,
                "target": "zone",
                "message": "当前检测器实例未接入运行时热更新",
            }

    if key.startswith("auto_track_"):
        try:
            from ...auto_track_service import get_auto_track_service

            auto_track_service = get_auto_track_service()
            if auto_track_service:
                auto_track_service.update_params(key, value)
                return {
                    "applied": True,
                    "target": "auto_track",
                    "message": "运行时已生效",
                }
            return {
                "applied": False,
                "target": "auto_track",
                "message": "自动跟踪服务未初始化，运行时未生效",
            }
        except Exception as exc:  # pragma: no cover - 仅在运行环境异常时触发
            logger.warning(f"[config] auto_track 热更新失败: key={key} error={exc}")
            return {
                "applied": False,
                "target": "auto_track",
                "message": "自动跟踪服务未初始化，运行时未生效",
            }

    if key == "safety_block_motion_when_disconnected":
        settings.SAFETY_BLOCK_MOTION_WHEN_DISCONNECTED = _parse_bool(value)
        return {
            "applied": True,
            "target": "backend",
            "message": "运行时已生效",
        }

    return {
        "applied": False,
        "target": "backend",
        "message": "已保存，运行时未接入",
    }


@router.get("")
async def get_system_config(
    category: Optional[str] = None,
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
):
    """
    获取系统配置。

    查询参数:
        category: 配置类别过滤 (backend/hardware/frontend/frontend_draw/zone/storage/auto_track)

    Returns:
        配置字典
    """
    from ...services_config import get_config_service

    config_service = get_config_service()
    all_configs = await config_service.get_all_configs(db)

    if category:
        all_configs = {
            k: v for k, v in all_configs.items()
            if v.get("category") == category
        }

    return {
        "configs": all_configs,
        "total": len(all_configs),
    }


@router.post("")
async def update_system_config(
    request: dict,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
):
    """
    更新系统配置。

    请求体:
        key: 配置键
        value: 新值
        changed_by: 修改者（可选，默认 admin）
        reason: 修改原因（可选）

    Returns:
        更新后的配置
    """
    from ...services_config import get_config_service

    config_service = get_config_service()

    key = request.get("key")
    value = request.get("value")
    changed_by = user.username
    reason = request.get("reason", "")

    if not key or value is None:
        raise HTTPException(
            status_code=400,
            detail="缺少必要参数: key, value",
        )

    try:
        config = await config_service.update_config(
            session=db,
            key=key,
            value=value,
            changed_by=changed_by,
            reason=reason,
        )

        runtime_apply = _apply_runtime_update(key, value)

        await safe_write_audit_log(
            db,
            level="INFO",
            module="BACKEND",
            message=(
                f"用户={user.username} 角色={user.role} 操作=config.update "
                f"目标={key} runtime_target={runtime_apply['target']} "
                f"runtime_applied={runtime_apply['applied']} 结果=success"
            ),
        )
        return {
            "success": True,
            "message": f"配置 {key} 已更新",
            "config": config.to_dict(),
            "runtime_apply": runtime_apply,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.get("/history")
async def get_config_history(
    key: Optional[str] = None,
    limit: int = 50,
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
):
    """
    获取配置变更历史。

    查询参数:
        key: 配置键过滤
        limit: 最大返回数量

    Returns:
        变更历史列表
    """
    from ...services_config import get_config_service

    config_service = get_config_service()
    history = await config_service.get_config_history(
        session=db,
        key=key,
        limit=limit,
    )

    return {
        "history": history,
        "total": len(history),
    }
