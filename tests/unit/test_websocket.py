"""WebSocket 遥测消息流单元测试。"""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@asynccontextmanager
async def _websocket_client(app: FastAPI):
    """创建用于测试的 WebSocket 客户端。"""
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client


@pytest.mark.asyncio
class TestWebSocketTelemetry:
    """WebSocket /ws/telemetry 消息序列与格式测试。"""

    async def test_websocket_telemetry_messages_seq_increasing(self, test_app) -> None:
        """连接 /ws/telemetry 后应持续收到消息且 seq 严格递增。"""
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/telemetry") as websocket:
                messages = []
                for _ in range(5):
                    msg = websocket.receive_json()
                    messages.append(msg)

        # 验证 seq 严格递增
        seqs = [m["seq"] for m in messages]
        assert seqs == list(range(1, 6))

    async def test_websocket_telemetry_messages_schema(self, test_app) -> None:
        """WebSocket 消息顶层字段应符合协议约定。"""
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/telemetry") as websocket:
                msg = websocket.receive_json()

        assert "timestamp" in msg
        assert msg["msg_type"] == "TELEMETRY_UPDATE"
        assert isinstance(msg["seq"], int)
        assert msg["source"] == "BACKEND_HUB"
        assert "payload" in msg

        # 验证 payload 结构
        payload = msg["payload"]
        assert "attitude" in payload
        assert "position" in payload
        assert "battery" in payload
