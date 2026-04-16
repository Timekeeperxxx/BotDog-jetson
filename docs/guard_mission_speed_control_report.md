# BotDog 驱离模式（Guard Mission）速度控制配置报告

## 📋 执行摘要

在 BotDog 项目中，驱离模式的机器狗移动速度和转向速度通过以下方式控制：

1. **配置层**：`.env` 文件和 `config.py` 中的参数定义
2. **伺服层**：`visual_servo_controller.py` 计算动作指令
3. **发送层**：`guard_mission_service.py` 发送运动命令
4. **适配层**：`robot_adapter.py` 中的 `UnitreeB2Adapter` 实际转换为硬件速度指令

---

## 🔧 速度配置参数

### 配置位置
- **配置文件**：`backend/config.py` (第 160-161 行)
- **环境文件**：`backend/.env` 和 `backend/.env.example` (第 231-235 行)

### 关键参数

| 参数名 | 配置文件行号 | .env 行号 | 类型 | 默认值 | 有效范围 | 说明 |
|--------|-----------|---------|------|--------|--------|------|
| `UNITREE_B2_VX` | config.py:160 | .env:232 | float | 0.3 | 0~0.6 m/s | 前进/后退速度（米/秒）|
| `UNITREE_B2_VYAW` | config.py:161 | .env:235 | float | 0.5 | 0~0.8 rad/s | 偏航转速（弧度/秒）|

### 配置文件具体内容

**config.py:**
```python
# Line 160-161
UNITREE_B2_VX: float = 0.3                # 前进/后退速度（m/s）
UNITREE_B2_VYAW: float = 0.5              # 偏航转速（rad/s）
```

**当前 .env 配置（第 231-235 行）:**
```
UNITREE_NETWORK_IFACE=eno1
UNITREE_B2_VX=0.3
UNITREE_B2_VYAW=0.5
```

**现场机器狗配置显示:**
```
# 前进/后退速度（m/s），B2 支持 0~0.6
UNITREE_B2_VX=0.3
# 偏航转速（rad/s），B2 支持 0~0.8
UNITREE_B2_VYAW=0.5
```

---

## 📡 速度指令构建和发送流程

### 流程图
```
guard_mission_service.py (Line 334-342)
    ↓
visual_servo_controller.py::compute_advancing() (Line 17-51)
    ↓ 返回 (cmd, is_arrived)
command 指令 (forward/backward/left/right/stop)
    ↓
guard_mission_service.py::_send_command_safe() (Line 504-514)
    ↓
control_service.py::handle_command() (Line 69-132)
    ↓
robot_adapter.py::UnitreeB2Adapter::send_command() (Line 339-389)
    ↓
UnitreeB2Adapter._command_worker() (Line 249-337)
    ↓
SportClient.Move(vx, vy, vyaw) 或其他 SDK 调用
```

---

## 🎯 视觉伺服控制器核心逻辑

### 文件位置
`backend/visual_servo_controller.py`

### 关键函数：`compute_advancing()`

**文件位置：** `visual_servo_controller.py` 第 17-51 行

**函数签名：**
```python
def compute_advancing(self, 
                     curr_bbox: Tuple[int, int, int, int],
                     frame_width: int, 
                     frame_height: int, 
                     max_view_ratio: float, 
                     edge_margin_ratio: float = 0.08) -> Tuple[str, bool]
```

**逻辑流程：**

1. **贴脸保护** (Line 31-32)
   ```python
   if w >= frame_width * max_view_ratio or h >= frame_height * max_view_ratio:
       return "stop", True
   ```
   - 当区域宽度或高度达到画面 90% 时立即停止

2. **偏航纠正** (Line 35-38)
   ```python
   error_x = center_x - (frame_width // 2)
   if abs(error_x) > self._yaw_deadband_px:
       cmd = "left" if error_x < 0 else "right"
       return cmd, False
   ```
   - 如果中心偏离超过死区，发送转向指令
   - **死区参数**：`GUARD_YAW_DEADBAND_PX` = 40 像素（config.py Line 142）

3. **边缘裕量保护** (Line 41-49)
   ```python
   margin_x = int(frame_width * edge_margin_ratio)
   margin_y = int(frame_height * edge_margin_ratio)
   too_close_to_edge = (
       x < margin_x or 
       (x + w) > (frame_width - margin_x) or 
       (y + h) > (frame_height - margin_y)
   )
   if too_close_to_edge:
       return "stop", False
   ```
   - 区域边缘距屏幕边界小于 8% 时停止前进

4. **正常前进** (Line 51)
   ```python
   return "forward", False
   ```

### 关键函数：`compute_returning()`

**文件位置：** `visual_servo_controller.py` 第 53-104 行

**逻辑流程：**
- 通过对比当前和起始区域的**中心位置**和**面积**判断是否返回到位
- 返航允许偏差：
  - X 方向中心误差：`GUARD_RETURN_POS_TOLERANCE_PX` = 60 像素
  - 面积误差：`GUARD_RETURN_AREA_TOLERANCE_RATIO` = 0.15（±15%）
- 需要连续满足条件 `GUARD_RETURN_STABLE_FRAMES` = 15 帧才确认完成

---

## 🚀 驱离服务中的指令发送

### 主函数：`_on_advancing()`

**文件位置：** `guard_mission_service.py` 第 314-358 行

```python
async def _on_advancing(self, detections: List[TrackDetectionResult], frame: bytes):
    # ...
    # 第 335-341 行：核心控制逻辑
    cmd, is_arrived = self._servo.compute_advancing(
        curr_bbox=zone.bbox,
        frame_width=self._frame_width,
        frame_height=self._frame_height,
        max_view_ratio=self._config.GUARD_MAX_VIEW_RATIO,          # 0.90
        edge_margin_ratio=self._config.GUARD_ZONE_EDGE_MARGIN_RATIO, # 0.08
    )
    await self._send_command_safe(cmd)
```

**支持的命令：**
- `"forward"` - 前进
- `"backward"` - 后退
- `"left"` - 左转
- `"right"` - 右转
- `"stop"` - 停止

### 指令发送函数：`_send_command_safe()`

**文件位置：** `guard_mission_service.py` 第 504-514 行

```python
async def _send_command_safe(self, cmd: str):
    now = time.monotonic()
    if cmd == self._last_command and cmd != "stop":
        if (now - self._last_cmd_send_time) * 1000 < self._command_rate_limit_ms:
            return  # 速率限制：100ms 最小间隔
    self._last_cmd_send_time = now
    self._last_command = cmd
    try:
        await self._control_service.handle_command(cmd)
    except Exception as e:
        logger.debug(f"[GuardMission] cmd {cmd} err: {e}")
```

**关键参数：**
- `GUARD_COMMAND_RATE_LIMIT_MS` = 100 ms（config.py Line 143）- 命令最小间隔

---

## 🔌 适配层：硬件速度转换

### 文件位置
`backend/robot_adapter.py` 第 104-430 行 (`UnitreeB2Adapter` 类)

### 命令到速度的映射

**文件位置：** `robot_adapter.py` 第 249-337 行 (`_command_worker()` 方法)

```python
if cmd == "forward":
    client.Move(self._vx, 0.0, 0.0)                    # Line 272
elif cmd == "backward":
    client.Move(-self._vx, 0.0, 0.0)                   # Line 274
elif cmd == "left":
    client.Move(0.0, 0.0, self._vyaw)                  # Line 276
elif cmd == "right":
    client.Move(0.0, 0.0, -self._vyaw)                 # Line 278
elif cmd == "strafe_left":
    client.Move(0.0, self._vy, 0.0)                    # Line 280
elif cmd == "strafe_right":
    client.Move(0.0, -self._vy, 0.0)                   # Line 282
elif cmd == "stop":
    client.StopMove()                                  # Line 285
    client.BalanceStand()                              # Line 295
```

### 速度参数初始化

**文件位置：** `robot_adapter.py` 第 137-158 行

```python
def __init__(
    self,
    network_interface: str = "eth0",
    vx: float = 0.3,              # 前进/后退速度
    vy: float = 0.25,             # 横向平移速度
    vyaw: float = 0.5,            # 偏航转速
) -> None:
    self._vx = vx                 # Line 155
    self._vy = vy                 # Line 156
    self._vyaw = vyaw             # Line 157
```

### SportClient.Move() API 说明

**文件位置：** `robot_adapter.py` 第 116-119 行（注释）

```
官方速度范围（来自 AI 运控服务接口文档）：
    vx:   [-0.6 ~ 0.6]  m/s      (前进负值 = 后退)
    vy:   [-0.4 ~ 0.4]  m/s      (横向运动)
    vyaw: [-0.8 ~ 0.8]  rad/s    (转向，正值 = 逆时针左转)
```

---

## 📊 驱离任务时序参数

**文件位置：** `backend/config.py` 第 115-143 行，`.env` 第 73-136 行

| 参数 | 配置行号 | 当前值 | 类型 | 说明 |
|------|---------|--------|------|------|
| `GUARD_MISSION_ENABLED` | config.py:116 | False | bool | 驱离任务总开关 |
| `GUARD_CONFIRM_TIME_S` | config.py:117 | 1.5 | float | 入侵确认时间 |
| `GUARD_CLEAR_TIME_S` | config.py:118 | 5.0 | float | 人离开区域后确认时间 |
| `GUARD_MIN_DURATION_S` | config.py:119 | 3.0 | float | 最短驱离持续时间 |
| `GUARD_MAX_DURATION_S` | config.py:123 | 120.0 | float | 最长驱离持续时间 |
| `GUARD_COOLDOWN_S` | config.py:122 | 30.0 | float | 两次出动间的冷却时间 |
| `GUARD_MAX_VIEW_RATIO` | config.py:135 | 0.90 | float | 前进贴脸保护率 |
| `GUARD_ZONE_EDGE_MARGIN_RATIO` | config.py:136 | 0.08 | float | 边缘裕量比例 |
| `GUARD_YAW_DEADBAND_PX` | config.py:142 | 40 | int | 偏航死区（像素）|
| `GUARD_COMMAND_RATE_LIMIT_MS` | config.py:143 | 100 | int | 命令最小间隔 |

---

## 💾 配置修改指南

### 调整前进/后退速度

编辑 `.env` 文件第 232 行：
```
# 原值
UNITREE_B2_VX=0.3

# 改为更快（范围 0.1~0.6 m/s）
UNITREE_B2_VX=0.5
```

### 调整转向速度

编辑 `.env` 文件第 235 行：
```
# 原值
UNITREE_B2_VYAW=0.5

# 改为更快（范围 0.1~0.8 rad/s）
UNITREE_B2_VYAW=0.7
```

### 调整转向灵敏度

编辑 `.env` 文件第 134 行：
```
# 原值（较大的死区 = 不容易转向）
GUARD_YAW_DEADBAND_PX=160

# 改为更灵敏（较小的死区 = 更容易转向）
GUARD_YAW_DEADBAND_PX=40
```

---

## 🔍 调试命令

### 查看当前配置
```bash
cd /home/jetson/Project/BOTDOG/BotDog
grep -E "UNITREE_B2_VX|UNITREE_B2_VYAW|GUARD_YAW_DEADBAND_PX|GUARD_COMMAND_RATE_LIMIT_MS" backend/.env
```

### 查看默认配置
```bash
grep -E "UNITREE_B2_VX|UNITREE_B2_VYAW" backend/config.py
```

### 启用驱离任务
```bash
grep "GUARD_MISSION_ENABLED" backend/.env
# 改为 true 并重启后端
```

---

## 📍 关键代码位置快速导航

| 模块 | 文件 | 行号 | 功能 |
|-----|------|------|------|
| **配置定义** | `config.py` | 115-143 | 所有驱离参数 |
| **环境配置** | `.env` | 73-136 | 实际运行时参数 |
| **伺服计算** | `visual_servo_controller.py` | 17-51 | 前进逻辑 |
| **伺服返航** | `visual_servo_controller.py` | 53-104 | 返航逻辑 |
| **驱离主服务** | `guard_mission_service.py` | 30-627 | 完整驱离流程 |
| **前进处理** | `guard_mission_service.py` | 314-358 | 前进状态机 |
| **指令发送** | `guard_mission_service.py` | 504-514 | 速率限制和发送 |
| **控制服务** | `control_service.py` | 69-132 | 命令路由 |
| **硬件适配** | `robot_adapter.py` | 249-337 | 速度参数转换 |
| **初始化** | `robot_adapter.py` | 137-158 | 速度参数存储 |

---

## 📝 总结

**驱离模式速度控制的完整链路：**

1. ✅ **配置来源**：`.env` 第 232、235 行
   - `UNITREE_B2_VX = 0.3 m/s` (前进/后退)
   - `UNITREE_B2_VYAW = 0.5 rad/s` (转向)

2. ✅ **伺服策略**：`visual_servo_controller.py`
   - 计算前进/转向/停止命令
   - 基于区域中心、尺寸、屏幕位置

3. ✅ **命令发送**：`guard_mission_service.py`
   - 调用伺服控制器获取指令
   - 速率限制 100ms 间隔
   - 通过 `control_service` 发送

4. ✅ **硬件转换**：`robot_adapter.py`
   - `forward/backward/left/right` → `Move(vx/vyaw)`
   - 直接使用配置中的速度参数
   - 通过 SportClient SDK 下发硬件

所有参数均可通过 `.env` 文件实时调整，无需修改代码。
