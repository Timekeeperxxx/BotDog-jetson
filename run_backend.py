#!/usr/bin/env python3
"""
BotDog Python 应用入口。

职责：
- 导入并启动 FastAPI/Uvicorn；
- 输出启动日志；
- 不负责网卡、DDS 路由、ROS 环境等系统级准备。

真机正式启动请走：
systemd -> scripts/start_backend.sh -> run_backend.py

直接执行 `python run_backend.py` 仅适合已完成环境准备的调试场景。
"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    import uvicorn
    from uvicorn.main import STARTUP_FAILURE
    from backend.logging_config import get_logger, setup_logging
    from backend.uvicorn_server import BotDogUvicornServer

    setup_logging()
    env_logger = get_logger("启动环境")
    app_logger = get_logger("应用服务")
    from backend.main import app

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    env_logger.info("启动脚本已加载：path={}", os.path.abspath(__file__))
    env_logger.info("服务地址：http://0.0.0.0:8000")
    env_logger.info("接口文档：http://0.0.0.0:8000/api/docs")
    env_logger.info("前端目录：{}", os.path.abspath(frontend_dist))
    env_logger.info("CYCLONEDDS_HOME={}", os.getenv("CYCLONEDDS_HOME", "未设置"))
    env_logger.info("LD_LIBRARY_PATH={}", os.getenv("LD_LIBRARY_PATH", "未设置"))
    app_logger.info("即将启动 Uvicorn：host=0.0.0.0，port=8000，access_log=false")

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=5.0,
    )
    server = BotDogUvicornServer(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)
