"""重点区 CRUD 路由。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...database import get_db
from ...schemas import utc_now_iso

router = APIRouter(tags=["focus_zones"])


class FocusZoneRequest(BaseModel):
    zone_name: str = "default"
    enabled: bool = True
    polygon_json: str


class FocusZoneResponse(BaseModel):
    zone_id: int
    zone_name: str
    enabled: bool
    polygon_json: str
    created_at: str
    updated_at: str


@router.get("/api/v1/focus-zones", response_model=list[FocusZoneResponse])
async def list_focus_zones(db=Depends(get_db)) -> list[FocusZoneResponse]:
    """查询所有重点区配置。"""
    from sqlalchemy import select
    from ...models import FocusZone

    result = await db.execute(select(FocusZone))
    zones = result.scalars().all()
    return [
        FocusZoneResponse(
            zone_id=z.zone_id,
            zone_name=z.zone_name,
            enabled=bool(z.enabled),
            polygon_json=z.polygon_json,
            created_at=z.created_at,
            updated_at=z.updated_at,
        )
        for z in zones
    ]


@router.post("/api/v1/focus-zones", response_model=FocusZoneResponse, status_code=201)
async def create_focus_zone(
    body: FocusZoneRequest,
    db=Depends(get_db),
) -> FocusZoneResponse:
    """新增重点区。polygon_json 坐标为图像像素坐标。"""
    import json
    from ...models import FocusZone
    from ...zone_service import get_zone_service

    try:
        pts = json.loads(body.polygon_json)
        if len(pts) < 3:
            raise ValueError("polygon 至少需要 3 个顶点")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"polygon_json 格式错误: {e}")

    ts = utc_now_iso()
    zone = FocusZone(
        zone_name=body.zone_name,
        enabled=1 if body.enabled else 0,
        polygon_json=body.polygon_json,
        created_at=ts,
        updated_at=ts,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)

    zs = get_zone_service()
    if zs:
        await zs.load_from_db(db)

    return FocusZoneResponse(
        zone_id=zone.zone_id,
        zone_name=zone.zone_name,
        enabled=bool(zone.enabled),
        polygon_json=zone.polygon_json,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


@router.put("/api/v1/focus-zones/{zone_id}", response_model=FocusZoneResponse)
async def update_focus_zone(
    zone_id: int,
    body: FocusZoneRequest,
    db=Depends(get_db),
) -> FocusZoneResponse:
    """更新重点区配置。"""
    import json
    from sqlalchemy import select
    from ...models import FocusZone
    from ...zone_service import get_zone_service

    result = await db.execute(select(FocusZone).where(FocusZone.zone_id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail=f"zone_id={zone_id} 不存在")

    try:
        pts = json.loads(body.polygon_json)
        if len(pts) < 3:
            raise ValueError("polygon 至少需要 3 个顶点")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"polygon_json 格式错误: {e}")

    zone.zone_name = body.zone_name
    zone.enabled = 1 if body.enabled else 0
    zone.polygon_json = body.polygon_json
    zone.updated_at = utc_now_iso()
    await db.commit()
    await db.refresh(zone)

    zs = get_zone_service()
    if zs:
        await zs.load_from_db(db)

    return FocusZoneResponse(
        zone_id=zone.zone_id,
        zone_name=zone.zone_name,
        enabled=bool(zone.enabled),
        polygon_json=zone.polygon_json,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


@router.delete("/api/v1/focus-zones/{zone_id}")
async def delete_focus_zone(
    zone_id: int,
    db=Depends(get_db),
) -> dict:
    """删除重点区。"""
    from sqlalchemy import select
    from ...models import FocusZone
    from ...zone_service import get_zone_service

    result = await db.execute(select(FocusZone).where(FocusZone.zone_id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=404, detail=f"zone_id={zone_id} 不存在")
    await db.delete(zone)
    await db.commit()

    zs = get_zone_service()
    if zs:
        await zs.load_from_db(db)

    return {"success": True, "deleted_zone_id": zone_id}
