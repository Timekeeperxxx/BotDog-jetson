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
    from backend.main import app
    
    print("=" * 80)
    print("启动 BotDog 后端系统")
    print("=" * 80)

    print("\n服务器地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print("\n按 Ctrl+C 停止服务器")
    print("=" * 80)
    print()

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
