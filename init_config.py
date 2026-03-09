#!/usr/bin/env python3
"""
初始化配置数据库表并添加默认配置。
"""

import asyncio
import sys
sys.path.insert(0, '.')

from backend.database import get_session_factory
from backend.services_config import get_config_service


async def init_config():
    """初始化配置。"""
    print("🔧 初始化配置数据库...")

    session_factory = get_session_factory()
    async with session_factory() as session:
        config_service = get_config_service()

        # 初始化默认配置
        print("📝 创建默认配置...")
        await config_service.initialize_defaults(session)

        # 验证配置是否创建成功
        all_configs = await config_service.get_all_configs(session)
        print(f"\n✅ 成功！已创建 {len(all_configs)} 个配置项：")

        for key, config in sorted(all_configs.items()):
            print(f"   - {key}: {config['value']} ({config['description']})")

        return len(all_configs) > 0


if __name__ == "__main__":
    success = asyncio.run(init_config())
    sys.exit(0 if success else 1)
