#!/usr/bin/env python3
"""
初始化数据库脚本 - BotDog
"""

import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

async def main():
    from backend.database import init_db
    print("正在初始化数据库...")
    await init_db()
    print("数据库初始化完成！")

if __name__ == "__main__":
    asyncio.run(main())
