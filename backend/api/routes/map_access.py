from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from ...auth.dependencies import require_admin, require_viewer
from ...database import get_db
from ...models import MapAccessZone
from ...map_access_schemas import MapZoneRequest
from ...pcd_errors import PcdMapError
from ...map_access_geometry import validate_polygon
from ...services_map_access import get_map_access_service
from ...schemas import utc_now_iso
from ...auth.service import safe_write_audit_log

router = APIRouter(prefix='/api/v1/map-access',tags=['map-access'])


ZoneWrite = MapZoneRequest


@router.get('/status')
async def status(_=Depends(require_viewer)):
    service=get_map_access_service()
    await service.ensure_initialized()
    return service.status()


@router.get('/zones')
async def zones(scene_id: str | None=None,db=Depends(get_db),_=Depends(require_viewer)):
    query=select(MapAccessZone).order_by(MapAccessZone.id)
    if scene_id is not None: query=query.where(MapAccessZone.scene_id==scene_id)
    items=(await db.execute(query)).scalars().all()
    return [get_map_access_service().zone_dict(z) for z in items]


async def write_zone(body,db,admin,zone_id=None):
    from ...services_pcd_maps import resolve_scene_path
    try:
        path=resolve_scene_path(body.scene_id)
        if not (path/'ground.pcd').is_file(): raise FileNotFoundError()
    except (OSError, ValueError, PcdMapError) as exc:
        raise HTTPException(422,'区域必须绑定有地面地图的现有场景') from exc
    service=get_map_access_service()
    async with service.lock:
        zone=await db.get(MapAccessZone,zone_id) if zone_id else MapAccessZone()
        if zone is None: raise HTTPException(404,'区域不存在')
        if zone_id and zone.scene_id!=body.scene_id: raise HTTPException(422,'不能把现有区域移动到另一地图，请在目标地图新建')
        points,plane=validate_polygon([p.model_dump() for p in body.vertices])
        for key in ('scene_id','name','access_level','enabled','boundary_margin_m'): setattr(zone,key,getattr(body,key))
        zone.vertices,zone.plane,zone.updated_at=points,plane,utc_now_iso()
        db.add(zone);await db.flush()
        await db.commit()
        await service.reload(db)
        result=service.zone_dict(zone)
    await safe_write_audit_log(db,level='INFO',module='BACKEND',message=f'用户={admin.username} 操作=map_access.zone_save 区域={zone.id} scene={zone.scene_id} 区域级别={zone.access_level}')
    return result


@router.post('/zones',status_code=201)
async def create(body: ZoneWrite,db=Depends(get_db),admin=Depends(require_admin)):
    return await write_zone(body,db,admin)


@router.put('/zones/{zone_id}')
async def update(zone_id: int,body: ZoneWrite,db=Depends(get_db),admin=Depends(require_admin)):
    return await write_zone(body,db,admin,zone_id)


@router.delete('/zones/{zone_id}')
async def remove(zone_id: int,db=Depends(get_db),admin=Depends(require_admin)):
    service=get_map_access_service()
    async with service.lock:
        zone=await db.get(MapAccessZone,zone_id)
        if zone is None: raise HTTPException(404,'区域不存在')
        await db.delete(zone);await db.commit();await service.reload(db)
    await safe_write_audit_log(db,level='INFO',module='BACKEND',message=f'用户={admin.username} 操作=map_access.zone_delete 区域={zone_id}')
    return {'deleted':zone_id}
