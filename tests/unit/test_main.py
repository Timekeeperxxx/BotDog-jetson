"""主 HTTP 端点单元测试。"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_200(async_client: AsyncClient) -> None:
    """健康检查接口应返回 200 且字段完整。"""
    response = await async_client.get("/api/v1/system/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("healthy", "offline", "degraded")
    assert isinstance(data["mavlink_connected"], bool)
    assert isinstance(data["uptime"], (int, float))
    assert data["uptime"] >= 0


@pytest.mark.asyncio
async def test_session_stop_missing_task_404(async_client: AsyncClient) -> None:
    """停止不存在的任务应返回 404 和 detail。"""
    response = await async_client.post(
        "/api/v1/session/stop",
        json={"task_id": 99999},
    )

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "task_id=99999 not found"
