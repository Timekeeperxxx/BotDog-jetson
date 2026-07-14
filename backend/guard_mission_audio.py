from __future__ import annotations

import asyncio

from .logging_config import logger


class GuardMissionAudioMixin:
    @property
    def is_audio_playing(self) -> bool:
        """返回当前是否正在播放驱离音频（用 Task 状态判断，比 returncode 可靠）。"""
        return self._audio_task is not None and not self._audio_task.done()

    async def start_audio(self):
        """公开：启动驱离音频循环播放（供 API 手动触发）。"""
        if self.is_audio_playing:
            return
        await self._start_guard_audio()

    async def stop_audio(self):
        """公开：停止驱离音频（供 API 手动触发）。"""
        await self._stop_guard_audio()

    async def _audio_loop(self, path: str):
        """asyncio 任务：每次等 aplay 完整播完后再循环，被 cancel 时干净退出。"""
        import traceback

        while True:
            try:
                import os, signal
                from pathlib import Path as _OsPath

                # 通过 shell 中转脚本播放，自动发现 PulseAudio 套接字
                # start_new_session=True：让 bash 和其子进程（paplay）独占一个进程组
                # 这样 os.killpg 可以一次性杀死整个链路，实现立即停止
                script_path = _OsPath(__file__).resolve().parent.parent / "scripts" / "play_audio.sh"
                proc = await asyncio.create_subprocess_exec(
                    "bash", str(script_path), path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._audio_process = proc
                await proc.wait()          # 等待本轮播放完整结束
                self._audio_process = None

                # 如果 aplay 返回错误码意味着命令执行失败，增加等待以防止死循环爆 CPU
                if proc.returncode != 0:
                    logger.warning(f"[GuardMission] aplay 非正常退出(code={proc.returncode})，可能声卡被占用或文件错误。5秒后重试。")
                    await asyncio.sleep(5.0)
                else:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                if self._audio_process:
                    try:
                        # 杀死整个进程组（bash + paplay/aplay 子进程），立即停止
                        os.killpg(os.getpgid(self._audio_process.pid), signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        pass
                    self._audio_process = None
                raise
            except Exception as e:
                logger.error(f"[GuardMission] 音频播放异常，命令或环境出现错误: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5.0)  # 防止任务崩溃死掉，UI 会掉线

    async def _start_guard_audio(self):
        from pathlib import Path as _Path

        path = _Path(self._config.GUARD_ALERT_AUDIO_PATH)
        if not path.is_absolute():
            path = _Path(__file__).resolve().parent.parent / path

        if not path.exists():
            logger.error(f"[GuardMission] 严重错误：物理音频文件不存在：{path}")
            # 不直接返回，还是启动循环，将路径喂给 aplay，让它在循环里自然报错
            # 这样保证音频任务 Task 正在运行，前端状态就不会瞬间跳回 False

        self._audio_task = asyncio.create_task(self._audio_loop(str(path)))
        logger.info(f"[GuardMission] 音频循环任务已挂载：{path}")

    async def _stop_guard_audio(self):
        if self._audio_task and not self._audio_task.done():
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
        self._audio_task = None
        # 兜底：若 aplay 子进程仍在，强制终止
        if self._audio_process:
            try:
                self._audio_process.terminate()
            except ProcessLookupError:
                pass
            self._audio_process = None
        logger.info("[GuardMission] 音频已停止")
