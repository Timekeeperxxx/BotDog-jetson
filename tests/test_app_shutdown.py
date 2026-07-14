from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app_shutdown import shutdown_runtime_services
from backend.control_service import get_control_service, set_control_service
from backend.navigation_velocity_udp import (
    get_navigation_velocity_udp_service,
    set_navigation_velocity_udp_service,
)


@pytest.mark.asyncio
async def test_shutdown_closes_velocity_ingress_stops_and_releases_adapter():
    udp_service = MagicMock()
    control_service = MagicMock()
    control_service.force_stop = AsyncMock()
    set_navigation_velocity_udp_service(udp_service)
    set_control_service(control_service)

    await shutdown_runtime_services(tasks=[], ros_nav_bridge=None)

    udp_service.close.assert_called_once_with()
    control_service.force_stop.assert_awaited_once_with()
    control_service.set_adapter.assert_called_once_with(None)
    assert get_navigation_velocity_udp_service() is None
    assert get_control_service() is None
