"""端到端集成测试。"""

import pytest


@pytest.mark.asyncio
class TestCorsPreflight:
    """CORS 预检请求头验证集成测试。"""

    async def test_cors_preflight_headers(self, async_client) -> None:
        """对允许的 origin 发送 OPTIONS 请求，验证响应头符合预期。"""
        response = await async_client.options(
            "/api/v1/system/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
