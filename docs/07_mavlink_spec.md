# 巡检系统 MAVLink 通讯协议规范 v1.0

## 1. 核心链路心跳 (Heartbeat)

* ​**消息名称**​: `HEARTBEAT` (#0)
* ​**发送频率**​: 1Hz
* ​**字段**​: `type`, `autopilot`, `base_mode`
* ​**逻辑**​: 若 3 秒未收到报文，前端 UI 必须进入“通讯中断”模式。

## 2. 导航与定位数据 (Position)

* ​**消息名称**​: `GLOBAL_POSITION_INT` (#33)
* ​**频率**​: 5-10Hz
* ​**字段**​: `lat` (纬度), `lon` (经度), `alt` (高度), `hdg` (航向角)
* ​**映射**​: 对应地图坐标及 HUD 航向指南针。

## 3. 姿态与运动状态 (Attitude)

* ​**消息名称**​: `VFR_HUD` (#74) & `ATTITUDE` (#30)
* ​**频率**​: 10-20Hz
* ​**字段**​: `pitch` (俯仰), `roll` (横滚), `yaw` (偏航), `groundspeed` (地速)
* ​**映射**​: 对应 HUD 中央姿态仪动态线条。

## 4. 红外与热感应扩展 (Thermal)

* ​**消息名称**​: 自定义 ID #224 或 `NAMED_VALUE_FLOAT` #251
* ​**字段**​: `name` ("T\_MAX"), `value` (摄氏度)
* ​**逻辑**​: 当 `value > 60.0` 时，自动触发异常截图证据链。

## 5. WebSocket JSON 报文标准

```
{
  "timestamp": 1714560000.123,
  "msg_type": "TELEMETRY_UPDATE",
  "seq": 1024,
  "source": "BACKEND_HUB",
  "payload": {
    "attitude": { "pitch": 0.1, "roll": -0.05, "yaw": 184.5 },
    "position": { "lat": 39.9, "lon": 116.4, "alt": 1.2, "hdg": 184 },
    "battery": { "voltage": 84.2, "remaining_pct": 82 }
  }
}
```

## 6. 安全失效保护 (Failsafe)

* ​**链路丢失**​: 飞控自动执行 `BRAKE` (刹车) 或 `RTL` (返航)。
* ​**低电量**​: UI 红色闪烁告警并限制运动指令。

