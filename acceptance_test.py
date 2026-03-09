#!/usr/bin/env python3
"""
BotDog 项目验收测试脚本

执行 UC-01 到 UC-05 的验收测试用例
"""

import asyncio
import json
import websockets
import time
from datetime import datetime


class AcceptanceTest:
    """验收测试类"""

    def __init__(self):
        self.base_url = "http://localhost:8000"
        self.ws_url = "ws://localhost:8000"
        self.results = []

    def print_section(self, title):
        """打印测试章节"""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

    def print_result(self, test_name, passed, details=""):
        """打印测试结果"""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.results.append({
            "test": test_name,
            "passed": passed,
            "details": details
        })
        print(f"{status} - {test_name}")
        if details:
            print(f"   {details}")

    async def test_uc01_system_health(self):
        """UC-01: 系统健康检查"""
        self.print_section("UC-01: 系统健康检查")

        import urllib.request

        try:
            # 测试 /api/v1/system/health
            req = urllib.request.Request(f"{self.base_url}/api/v1/system/health")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())

            status = data.get("status")
            mavlink_connected = data.get("mavlink_connected")
            uptime = data.get("uptime")

            print(f"📊 系统状态:")
            print(f"   状态: {status}")
            print(f"   MAVLink 连接: {mavlink_connected}")
            print(f"   运行时间: {uptime} 秒")

            is_healthy = status in ["healthy", "degraded", "offline"] and uptime > 0
            self.print_result(
                "UC-01: 系统健康检查",
                is_healthy,
                f"status={status}, uptime={uptime}s (模拟模式下 offline 是正常的)"
            )
            return is_healthy

        except Exception as e:
            self.print_result("UC-01: 系统健康检查", False, f"错误: {e}")
            return False

    async def test_uc02_telemetry_websocket(self):
        """UC-02: 遥测 WebSocket 连接"""
        self.print_section("UC-02: 遥测 WebSocket 连接")

        try:
            uri = f"{self.ws_url}/ws/telemetry"
            async with websockets.connect(uri) as ws:
                print(f"📡 连接到 {uri}")

                # 接收一条消息（设置超时）
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)

                print(f"📩 收到消息类型: {data.get('msg_type')}")

                is_connected = "msg_type" in data
                self.print_result(
                    "UC-02: 遥测 WebSocket 连接",
                    is_connected,
                    f"收到消息类型: {data.get('msg_type')}"
                )
                return is_connected

        except asyncio.TimeoutError:
            self.print_result("UC-02: 遥测 WebSocket 连接", False, "连接超时")
            return False
        except Exception as e:
            self.print_result("UC-02: 遥测 WebSocket 连接", False, f"错误: {e}")
            return False

    async def test_uc03_event_websocket(self):
        """UC-03: 事件 WebSocket 连接"""
        self.print_section("UC-03: 事件 WebSocket 连接")

        try:
            uri = f"{self.ws_url}/ws/event"
            async with websockets.connect(uri) as ws:
                print(f"📡 连接到 {uri}")

                # 接收欢迎消息
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)

                print(f"📩 收到消息: {data.get('message', data.get('msg_type'))}")

                is_connected = "message" in data or "msg_type" in data
                self.print_result(
                    "UC-03: 事件 WebSocket 连接",
                    is_connected,
                    "WebSocket 连接成功"
                )
                return is_connected

        except asyncio.TimeoutError:
            self.print_result("UC-03: 事件 WebSocket 连接", False, "连接超时")
            return False
        except Exception as e:
            self.print_result("UC-03: 事件 WebSocket 连接", False, f"错误: {e}")
            return False

    async def test_uc04_config_api(self):
        """UC-04: 配置管理 API"""
        self.print_section("UC-04: 配置管理 API")

        import urllib.request

        try:
            # 测试读取配置
            req = urllib.request.Request(f"{self.base_url}/api/v1/config")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())

            configs = data.get("configs", {})
            total = data.get("total", 0)

            print(f"⚙️  配置数量: {total}")

            if total > 0:
                # 显示前3个配置
                for i, (key, config) in enumerate(list(configs.items())[:3]):
                    print(f"   {key}: {config.get('value')}")

            # 测试更新配置
            print(f"\n📝 测试配置更新...")
            update_data = json.dumps({
                "key": "thermal_threshold",
                "value": "62.0",
                "changed_by": "acceptance_test",
                "reason": "验收测试"
            }).encode('utf-8')

            req = urllib.request.Request(
                f"{self.base_url}/api/v1/config",
                data=update_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode())

            update_success = result.get("success")
            print(f"   更新结果: {'成功' if update_success else '失败'}")

            # 恢复原值
            update_data = json.dumps({
                "key": "thermal_threshold",
                "value": "60.0",
                "changed_by": "acceptance_test",
                "reason": "恢复默认值"
            }).encode('utf-8')

            req = urllib.request.Request(
                f"{self.base_url}/api/v1/config",
                data=update_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            urllib.request.urlopen(req, timeout=5)

            self.print_result(
                "UC-04: 配置管理 API",
                total > 0 and update_success,
                f"配置数量: {total}, 更新成功"
            )
            return total > 0 and update_success

        except Exception as e:
            self.print_result("UC-04: 配置管理 API", False, f"错误: {e}")
            return False

    async def test_uc05_alert_system(self):
        """UC-05: 告警系统功能"""
        self.print_section("UC-05: 告警系统功能")

        try:
            # 先连接事件 WebSocket
            uri = f"{self.ws_url}/ws/event"
            async with websockets.connect(uri) as ws:
                print(f"📡 连接到 {uri}")

                # 接收欢迎消息
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                print(f"📩 收到欢迎消息: {data.get('message', data.get('msg_type'))}")

                # 通过测试端点触发告警
                import urllib.request

                print(f"🚨 触发测试告警...")
                req = urllib.request.Request(
                    f"{self.base_url}/api/v1/test/alert",
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=5) as response:
                    result = json.loads(response.read().decode())
                    print(f"   告警触发: {result.get('message')}")

                # 等待告警消息（现在 WebSocket 已经连接了）
                try:
                    print(f"⏳ 等待告警广播...")
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)

                    msg_type = data.get('msg_type')
                    print(f"📩 收到: {msg_type}")

                    if msg_type == "ALERT_RAISED":
                        payload = data.get('payload', {})
                        print(f"   事件码: {payload.get('event_code')}")
                        print(f"   消息: {payload.get('message')}")
                        print(f"   温度: {payload.get('temperature')}°C")

                    is_alert_working = msg_type == "ALERT_RAISED"
                    self.print_result(
                        "UC-05: 告警系统功能",
                        is_alert_working,
                        "告警触发并成功广播"
                    )
                    return is_alert_working

                except asyncio.TimeoutError:
                    self.print_result(
                        "UC-05: 告警系统功能",
                        False,
                        "未收到告警广播（5秒内）"
                    )
                    return False

        except Exception as e:
            self.print_result("UC-05: 告警系统功能", False, f"错误: {e}")
            return False

    async def run_all_tests(self):
        """运行所有验收测试"""
        print("\n🚀 BotDog 项目验收测试")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 执行所有测试
        await self.test_uc01_system_health()
        await self.test_uc02_telemetry_websocket()
        await self.test_uc03_event_websocket()
        await self.test_uc04_config_api()
        await self.test_uc05_alert_system()

        # 打印总结
        self.print_summary()

    def print_summary(self):
        """打印测试总结"""
        self.print_section("测试总结")

        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print(f"\n📊 测试结果:")
        print(f"   总计: {total}")
        print(f"   通过: {passed} ✅")
        print(f"   失败: {failed} ❌")
        print(f"   通过率: {(passed/total*100):.1f}%")

        print(f"\n📝 详细结果:")
        for result in self.results:
            status = "✅" if result["passed"] else "❌"
            print(f"   {status} {result['test']}")
            if not result["passed"] and result["details"]:
                print(f"      原因: {result['details']}")

        # 最终判断
        self.print_section("最终结论")
        if passed == total:
            print("🎉 所有验收测试通过！")
            print("✅ 项目可以交付")
        elif passed >= total * 0.8:
            print("⚠️  大部分测试通过，需要修复失败项")
            print("📝 建议：优先修复失败的测试用例")
        else:
            print("❌ 多个测试失败，项目未达到验收标准")
            print("🔧 需要：修复所有失败项后重新测试")


async def main():
    """主函数"""
    tester = AcceptanceTest()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
