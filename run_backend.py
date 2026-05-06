#!/usr/bin/env python3
"""
启动脚本 - BotDog 后端系统
"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    import uvicorn
    from backend.logging_config import get_logger, setup_logging

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

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=False,
    )
