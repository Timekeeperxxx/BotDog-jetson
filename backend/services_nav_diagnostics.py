"""Current localization attempt, derived from ordered runtime log events."""
from __future__ import annotations

import math
import re
import threading
import time
from pathlib import Path


class LocalizationDiagnostics:
    def __init__(self):
        self.lock = threading.RLock()
        self.offset = 0
        self.identity = None
        self.scene_id = None
        self.reset()

    def reset(self):
        self.events = []
        self.phase = "idle"
        self.match = None
        self.fallback = None
        self.started = time.monotonic()

    def event(self, phase, message, level="info"):
        self.phase = phase
        if self.events and self.events[-1]["message"] == message:
            return
        self.events.append(dict(timestamp=time.time(), phase=phase, message=message, level=level))
        self.events = self.events[-30:]

    def begin(self, path: Path, scene_id, phase="receiving"):
        with self.lock:
            self.reset()
            self.scene_id = scene_id
            try:
                stat = path.stat()
                self.offset = stat.st_size
                self.identity = (stat.st_dev, stat.st_ino)
            except FileNotFoundError:
                self.offset = 0
                self.identity = None
            self.event(phase, "[接收层] 已提交初始位姿，等待定位节点接收" if phase == "receiving"
                       else "[启动层] 正在检查雷达、地图并启动导航进程")

    def consume(self, line):
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if "[Navigation][run:" in line and " launch" in line:
            self.reset()
            self.event("starting", "[启动层] 新一轮导航进程启动，等待雷达点云和 IMU")
        elif "GET Initial guess from" in line:
            self.reset()
            self.event("data", "[接收层] 定位节点已收到初始位姿；等待 10 帧点云和至少 20 个 IMU 样本")
        elif "Waiting for initial pose from topic" in line:
            self.event("awaiting_pose", "[接收层] 雷达初始化数据已积累，等待在地图上标记位置和朝向")
        elif "INIT start..." in line:
            self.event("matching", "[匹配层] 正在将现场点云与已有地图对齐（NDT → ICP）")
        elif "Initialization NDT start" in line:
            self.event("ndt", "[匹配层/NDT] 正在进行粗匹配")
        elif "Initialization ICP start" in line:
            self.event("icp", "[匹配层/ICP] 粗匹配结束，正在精匹配")
        elif "Global ICP Converged Fail" in line:
            self.match = "failed"
            reason = "ICP 未收敛" if "converged=0" in line else "ICP 评分超过 1.5" if "converged=1" in line else "ICP 不收敛或评分超过 1.5"
            self.event("match_failed", "[匹配层] " + reason + "；" + line.split("Global ICP Converged Fail", 1)[1].strip(" !")
                       + "。正在重新积累数据重试；请核对场景、标点位置和朝向。", "error")
        elif "Global ICP result rejected as an alias match" in line:
            self.match = "fallback"
            detail = line.split("alias match.", 1)[-1].strip()
            numbers = re.search(r"correction_xyz=\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+rotation=([-+\d.eE]+)", detail)
            if numbers:
                x, y, z, angle = map(float, numbers.groups())
                detail = f"水平偏移 {math.hypot(x, y):.3f} m，垂直偏移 {abs(z):.3f} m，角度偏移 {math.degrees(abs(angle)):.1f}°"
            self.fallback = ("[偏移检查层] 匹配修正超限：" + detail
                             + "；阈值为水平 2 m、垂直 0.75 m、旋转 60°。已拒绝匹配结果，回退到手动位姿；请核对点云对齐，必要时重启定位重新标点。")
            self.event("fallback", self.fallback, "error")
        elif "Global ICP Converged Succeed" in line:
            self.match = "matched"
            self.event("tf", "[匹配层] ICP 匹配成功；" + line.split("Global ICP Converged Succeed", 1)[1].strip(" !") + "。等待定位 TF。")
        elif "Using initial pose from topic directly" in line:
            self.match = "fallback"
            self.fallback = "[匹配层] 跳过地图匹配，直接使用手动位姿；定位精度尚未经匹配验证。"
            self.event("fallback", self.fallback, "error")
        elif "SCAN body pose TF ready:" in line:
            self.event("planning", "[TF 层] map → base_footprint 已恢复；等待全局静态图和规划控制链就绪")
        elif "Published static graph with" in line:
            self.event("runtime", "[规划层] 全局静态图已发布，正在核对 TF、SCAN 控制和安全监控")
        elif "[Navigation][错误]" in line or "process has died" in line:
            detail = line.split("[Navigation][错误]", 1)[-1].split(", cmd ", 1)[0].strip()
            self.event("process_error", "[进程/数据层] " + detail, "error")

    def read(self, path: Path):
        try:
            with path.open("rb") as stream:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity != self.identity or stat.st_size < self.offset:
                    self.reset()
                    self.offset = 0
                    self.identity = identity
                stream.seek(self.offset)
                for raw in stream:
                    if not raw.endswith(b"\n"):
                        break
                    self.offset += len(raw)
                    self.consume(raw.decode("utf-8", errors="replace"))
        except FileNotFoundError:
            return

    def snapshot(self, ready=False, health_error=None):
        if self.fallback:
            message = self.fallback + (" 链路已恢复，但这不代表地图匹配成功。" if ready else " " + (health_error or "等待导航链路恢复。"))
            phase, level = "fallback", "error"
        elif ready and self.match == "matched":
            phase, level, message = "ready", "info", "[就绪] 地图匹配成功，TF、规划控制和安全监控均已就绪"
        elif self.match == "matched" and self.phase in {"tf", "planning", "runtime"} and health_error:
            phase, level, message = self.phase, "info", "[TF/规划控制层] 匹配完成；" + health_error
        else:
            phase = self.phase
            last = self.events[-1] if self.events else {}
            level, message = last.get("level", "info"), last.get("message", "[定位层] 尚无本轮定位诊断，请重启导航定位")
            if ready and self.match is None:
                message = "[匹配层] 链路已恢复，但没有本轮地图匹配结果，不能确认匹配成功。"
                level = "error"
            elif self.phase not in {"idle", "awaiting_pose", "process_error"} and time.monotonic() - self.started > 600:
                message += " 等待已超过 10 分钟，请根据上述层级检查后重试。"
                level = "error"
        return dict(scene_id=self.scene_id, phase=phase, level=level, message=message,
                    navigation_ready=ready, match=self.match, events=list(self.events))


diagnostics = LocalizationDiagnostics()
