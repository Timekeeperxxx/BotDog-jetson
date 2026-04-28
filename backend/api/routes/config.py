"""系统配置管理路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ...database import get_db

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("")
async def get_system_config(
    category: Optional[str] = None,
    db=Depends(get_db),
):
    """
    获取系统配置。

    查询参数:
        category: 配置类别过滤 (backend/frontend/storage)

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
    changed_by = request.get("changed_by", "admin")
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

        if key.startswith("auto_track_"):
            from ...auto_track_service import get_auto_track_service

            _at = get_auto_track_service()
            if _at:
                _at.update_params(key, value)

        return {
            "success": True,
            "message": f"配置 {key} 已更新",
            "config": config.to_dict(),
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
