"""网口管理路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...database import get_db

router = APIRouter(prefix="/api/v1/network-interfaces", tags=["network_interfaces"])


class NetworkInterfaceRequest(BaseModel):
    """网口配置请求体。"""

    name: str
    label: str
    iface_name: str
    ip_address: Optional[str] = None
    purpose: str = "other"
    enabled: bool = True


class NetworkInterfaceResponse(BaseModel):
    """网口配置响应体。"""

    iface_id: int
    name: str
    label: str
    iface_name: str
    ip_address: Optional[str] = None
    purpose: str
    enabled: bool
    created_at: str
    updated_at: str


@router.get("")
async def list_network_interfaces(db=Depends(get_db)) -> dict:
    """获取所有网口配置。"""
    from ...services_video_sources import get_network_interface_service

    svc = get_network_interface_service()
    ifaces = await svc.list_all(db)
    return {"interfaces": ifaces, "total": len(ifaces)}


@router.post("", status_code=201)
async def create_network_interface(
    body: NetworkInterfaceRequest,
    db=Depends(get_db),
) -> dict:
    """新增网口配置。"""
    from ...services_video_sources import get_network_interface_service

    svc = get_network_interface_service()
    try:
        iface = await svc.create(db, body.model_dump())
        return {"success": True, "interface": iface}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{iface_id}")
async def update_network_interface(
    iface_id: int,
    body: NetworkInterfaceRequest,
    db=Depends(get_db),
) -> dict:
    """更新网口配置。"""
    from ...services_video_sources import get_network_interface_service

    svc = get_network_interface_service()
    result = await svc.update(db, iface_id, body.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail=f"网口 id={iface_id} 不存在")
    return {"success": True, "interface": result}


@router.delete("/{iface_id}")
async def delete_network_interface(
    iface_id: int,
    db=Depends(get_db),
) -> dict:
    """删除网口配置。"""
    from ...services_video_sources import get_network_interface_service

    svc = get_network_interface_service()
    deleted = await svc.delete(db, iface_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"网口 id={iface_id} 不存在")
    return {"success": True, "deleted_iface_id": iface_id}
