import asyncio
import logging
from typing import List, Tuple

from backend.control_service import ControlService

logger = logging.getLogger("botdog.motion_script")

class MotionScriptRunner:
    """按顺序执行一系列 (command, duration) 运动指令。"""

    def __init__(self, watchdog_timeout_s: float = 0.5):
        # 续命间隔由 Watchdog 超时时间推导，取超时的 1/2 ~ 1/3
        # 不在设计层写死固定值，确保与 ControlService 配置一致
        self._keepalive_interval = watchdog_timeout_s / 2
        self._max_reject_count = 3  # 连续被拒绝次数上限预防死锁

    async def run(self, script: List[Tuple[str, float]], 
                  control_service: ControlService,
                  cancel_event: asyncio.Event) -> bool:
        """
        开始运行一段定义好的状态序列命令
        returns True 认为脚本顺畅执行完毕，否则被腰斩（外界取消、或者是硬件连续拒绝受理）均为 False。
        """
        reject_count = 0
        for cmd, duration in script:
            if cancel_event.is_set():
                await control_service.handle_command("stop")
                return False
            ack = await control_service.handle_command(cmd)
            # 检查命令是否被接受
            if ack.result != "ACCEPTED":
                reject_count += 1
                if reject_count >= self._max_reject_count:
                    logger.error(f"[MotionScriptRunner] 指令 {cmd} 连续受理被拒超过 {self._max_reject_count} 次。结束脚本！")
                    await control_service.handle_command("stop")
                    return False  # 连续被拒绝，脚本执行失败
            else:
                reject_count = 0
            
            # 持续运动命令需要周期性续命（间隔 < Watchdog 超时）
            if cmd in ("forward", "backward", "left", "right"):
                elapsed = 0.0
                while elapsed < duration:
                    if cancel_event.is_set():
                        await control_service.handle_command("stop")
                        return False
                    
                    sleep_duration = min(self._keepalive_interval, duration - elapsed)
                    await asyncio.sleep(sleep_duration)
                    elapsed += sleep_duration
                    
                    ack = await control_service.handle_command(cmd)
                    if ack.result != "ACCEPTED":
                        reject_count += 1
                        if reject_count >= self._max_reject_count:
                            logger.error(f"[MotionScriptRunner] 续命指令 {cmd} 连续被拒。结束脚本！")
                            await control_service.handle_command("stop")
                            return False
                    else:
                        reject_count = 0
                # 持续命令完毕，主动喊停
                await control_service.handle_command("stop")
            else:
                # 一次性命令（stand/sit/stop），只发生了一次事件发送，不需要 Watchdog 轮询续命。纯等就行。
                await asyncio.sleep(duration)
        return True
