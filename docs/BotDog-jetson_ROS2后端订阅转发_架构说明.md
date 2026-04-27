# BotDog-jetson ROS2 后端订阅转发架构说明

## 1. 文档定位

本文档用于说明在 `BotDog-jetson` 项目中，如何在已经完成 PCD 点云地图选择、预览、标点 Demo 的基础上，继续接入 ROS2 实时话题数据。

当前阶段的目标不是让前端 TypeScript 直接订阅 ROS2 topic，而是采用：

```text
ROS2 topic
  ↓
BotDog 后端 rclpy 订阅
  ↓
后端标准化数据
  ↓
后端缓存最新状态
  ↓
后端 WebSocket 广播
  ↓
前端显示机器人实时状态
```

也就是说：

```text
前端不直接接 ROS2
前端只接 BotDog 后端
BotDog 后端负责 ROS2 适配
```

---

## 2. 当前前置条件

默认以下功能已经完成：

```text
1. 后端可以扫描 PCD_MAP_ROOT 下的 .pcd 文件；
2. 前端可以选择 PCD 点云地图；
3. 后端可以解析 PCD metadata；
4. 后端可以返回降采样点云 preview；
5. 前端 three.js 可以显示三维点云；
6. 前端 Canvas 可以显示 2D 俯视图；
7. 前端可以在 map 坐标系下标记导航点；
8. 后端可以保存和读取导航点。
```

本阶段新增内容：

```text
1. 后端订阅 ROS2 位姿话题；
2. 后端将 ROS2 原始消息转换成统一 RobotPose；
3. 后端缓存 latest_robot_pose；
4. 后端通过 WebSocket 推送 nav.robot_pose；
5. 前端在 PCD 3D 视图和 2D 俯视图中显示机器人实时位置；
6. 为后续设置位姿、单点导航、巡检任务预留数据基础。
```

---

## 3. 总体架构

```text
┌──────────────────────────────────────────────────────┐
│                       ROS2                            │
│                                                      │
│  /tf                                                 │
│  /odom                                               │
│  /amcl_pose                                          │
│  /lio/pose                                           │
│  /navigation/status                                  │
│                                                      │
└───────────────────────┬──────────────────────────────┘
                        │ rclpy subscriber
                        ↓
┌──────────────────────────────────────────────────────┐
│                 BotDog FastAPI 后端                   │
│                                                      │
│  services_ros_nav.py                                 │
│  ├── ROS2 节点初始化                                  │
│  ├── 订阅位姿 / 状态话题                              │
│  ├── 四元数转 yaw                                     │
│  ├── frame_id 校验                                    │
│  └── 转换为 BotDog 标准事件                           │
│                                                      │
│  services_nav_state.py                               │
│  ├── latest_robot_pose                                │
│  ├── latest_navigation_status                         │
│  ├── latest_localization_status                       │
│  └── 状态查询接口                                     │
│                                                      │
│  ws_event_broadcaster.py                             │
│  └── 广播 nav.* 事件                                  │
│                                                      │
└───────────────────────┬──────────────────────────────┘
                        │ WebSocket
                        ↓
┌──────────────────────────────────────────────────────┐
│                    React / TypeScript 前端            │
│                                                      │
│  useNavWebSocket.ts                                  │
│  ├── 接收 nav.robot_pose                              │
│  ├── 接收 nav.navigation_status                       │
│  └── 更新前端导航状态                                 │
│                                                      │
│  PcdMapDemoPage                                      │
│  ├── 3D 点云显示机器人位置                            │
│  ├── 2D 俯视图显示机器人箭头                          │
│  ├── 右侧状态面板显示 x/y/z/yaw                       │
│  └── 后续显示导航目标、任务进度                        │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

## 4. 为什么采用后端转发

前端 TypeScript 不适合直接接 ROS2，原因包括：

```text
1. 浏览器不能原生加入 ROS2 DDS 网络；
2. 前端直接接 rosbridge 会暴露 ROS2 topic 和控制能力；
3. 导航、设置位姿、巡检任务属于控制指令，必须由后端统一管理；
4. 点云、TF、odom 等话题频率高，前端不能直接承受高频原始消息；
5. 后端可以做节流、坐标转换、异常过滤和权限控制；
6. BotDog-jetson 当前已经有 FastAPI 后端和 WebSocket 广播机制。
```

所以正式架构应为：

```text
前端只处理业务事件
后端处理 ROS2 原始消息
```

---

## 5. 后端模块划分

### 5.1 services_ros_nav.py

职责：

```text
1. 初始化 ROS2；
2. 创建导航 ROS2 订阅节点；
3. 订阅机器人位姿话题；
4. 订阅导航状态话题；
5. 订阅定位状态话题；
6. 将 ROS2 原始消息转换为 BotDog 标准结构；
7. 将标准结构写入 services_nav_state；
8. 触发 WebSocket 广播。
```

这个模块是 ROS2 适配层。

不要在这里写前端格式化逻辑，也不要在这里管理巡检任务状态。

---

### 5.2 services_nav_state.py

职责：

```text
1. 保存 latest_robot_pose；
2. 保存 latest_navigation_status；
3. 保存 latest_localization_status；
4. 提供线程安全读写；
5. 给 HTTP 接口提供当前状态；
6. 给 WebSocket 广播层提供最新状态。
```

这个模块相当于导航状态缓存中心。

---

### 5.3 ws_event_broadcaster.py

职责：

```text
1. 复用现有 WebSocket 广播机制；
2. 新增 nav.* 事件类型；
3. 向前端广播标准业务事件；
4. 不直接暴露 ROS2 原始消息。
```

推荐事件类型：

```text
nav.robot_pose
nav.navigation_status
nav.localization_status
nav.patrol_status
nav.mapping_status
nav.error
```

第一阶段只需要：

```text
nav.robot_pose
nav.localization_status
```

---

### 5.4 frontend/src/hooks/useNavWebSocket.ts

职责：

```text
1. 连接 BotDog 后端 WebSocket；
2. 过滤 nav.* 事件；
3. 更新前端 robotPose；
4. 更新导航状态；
5. 处理断线重连；
6. 给 PcdMapDemoPage 使用。
```

---

## 6. 数据标准化设计

### 6.1 RobotPose 标准格式

无论后端订阅的是 `/tf`、`/odom`、`/amcl_pose` 还是同事自定义位姿 topic，最终给前端的数据都必须统一为：

```json
{
  "type": "nav.robot_pose",
  "data": {
    "x": 1.25,
    "y": -0.82,
    "z": 0.0,
    "yaw": 1.57,
    "frame_id": "map",
    "source": "/amcl_pose",
    "timestamp": 1710000000.123
  }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `x` | map 坐标系下 x |
| `y` | map 坐标系下 y |
| `z` | map 坐标系下 z |
| `yaw` | 机器人朝向，单位弧度 |
| `frame_id` | 必须尽量统一为 `map` |
| `source` | 该数据来自哪个 ROS2 topic |
| `timestamp` | 数据时间戳 |

---

### 6.2 NavigationStatus 标准格式

后续导航状态统一为：

```json
{
  "type": "nav.navigation_status",
  "data": {
    "status": "idle",
    "target_waypoint_id": null,
    "target_name": null,
    "message": "导航空闲",
    "timestamp": 1710000000.123
  }
}
```

状态建议：

```text
idle
navigating
arrived
failed
cancelled
paused
unknown
```

---

### 6.3 LocalizationStatus 标准格式

```json
{
  "type": "nav.localization_status",
  "data": {
    "status": "ok",
    "frame_id": "map",
    "source": "/amcl_pose",
    "message": "定位正常",
    "timestamp": 1710000000.123
  }
}
```

状态建议：

```text
ok
lost
initializing
relocalizing
error
unknown
```

---

## 7. ROS2 话题选择原则

你需要先让同事确认机器人当前定位输出 topic。

常见候选：

```text
/tf
/odom
/amcl_pose
/lio/pose
/lio_sam/mapping/odometry
/Odometry
/robot_pose
```

选择优先级：

```text
1. 如果有明确 map 坐标系下的 PoseStamped / PoseWithCovarianceStamped，优先订阅它；
2. 如果只有 /tf，则从 TF 树中取 map -> base_link；
3. 如果只有 /odom，则必须确认 odom 是否等价于 map，否则不能直接作为 map 坐标；
4. 如果使用 LIO / SuperLIO 输出 Odometry，需要确认 header.frame_id 是否为 map。
```

关键要求：

```text
最终发给前端的 pose 必须是 map 坐标系。
```

不能把 `odom` 坐标冒充为 `map` 坐标。

---

## 8. 后端运行模型

FastAPI 和 ROS2 都有自己的事件循环，不能在 FastAPI 主线程中直接阻塞执行 ROS2 spin。

正确运行模型：

```text
FastAPI 启动
  ↓
startup 阶段启动 ROS2 后台线程
  ↓
ROS2 node 在线程中 spin
  ↓
收到 topic 后更新 latest state
  ↓
按固定频率广播给前端
```

关闭时：

```text
FastAPI shutdown
  ↓
通知 ROS2 后台线程退出
  ↓
destroy node
  ↓
rclpy shutdown
  ↓
线程结束
```

如果不处理关闭，容易出现：

```text
1. Ctrl+C 后进程无法退出；
2. ROS2 节点重复初始化；
3. 端口释放但后台线程仍然运行；
4. 开发时热重载出错。
```

---

## 9. 节流和缓存设计

ROS2 原始话题可能频率很高：

```text
/odom: 30Hz ~ 100Hz
/tf: 30Hz ~ 100Hz
/pointcloud: 数据巨大
```

前端不需要完整高频数据。

推荐策略：

```text
1. 后端每条 ROS2 消息都可以接收；
2. 后端只更新 latest_robot_pose；
3. WebSocket 广播以 10Hz 左右发送最新 pose；
4. 导航状态变化时立即推送；
5. 定位状态 1Hz ~ 2Hz 即可；
6. 点云实时流第一阶段不接。
```

推荐频率：

| 数据 | 前端推送频率 |
|---|---|
| 机器人位姿 | 5Hz ~ 10Hz |
| 导航状态 | 状态变化时推送，或 2Hz |
| 定位状态 | 1Hz ~ 2Hz |
| 巡检状态 | 状态变化时推送 |
| 点云实时预览 | 第一阶段不做；后续 1Hz 以下 |

---

## 10. 前端显示设计

PCD 页面在接收 `nav.robot_pose` 后，应更新：

```text
1. 右侧状态栏显示 x/y/z/yaw；
2. 2D 俯视图绘制机器人箭头；
3. 3D 点云视图绘制机器人模型或方向箭头；
4. 如果 frame_id 不是 map，显示警告；
5. 如果长时间没有收到 pose，显示“位姿超时”。
```

### 10.1 2D 俯视图显示

机器人在 2D 俯视图中显示为：

```text
圆点 + 朝向箭头
```

绘制逻辑：

```text
map x/y
  ↓
mapToCanvas()
  ↓
画机器人圆点
  ↓
根据 yaw 画朝向箭头
```

### 10.2 3D 点云显示

机器人在 3D 点云中显示为：

```text
小模型 / 圆柱 / 箭头
```

坐标转换继续复用：

```text
map x -> three x
map y -> three -z
map z -> three y
```

---

## 11. HTTP 当前状态接口

WebSocket 之外，还应该提供 HTTP 查询接口。

推荐：

```http
GET /api/v1/nav/state
```

返回：

```json
{
  "robot_pose": {
    "x": 1.25,
    "y": -0.82,
    "z": 0.0,
    "yaw": 1.57,
    "frame_id": "map",
    "source": "/amcl_pose",
    "timestamp": 1710000000.123
  },
  "navigation_status": {
    "status": "idle",
    "target_waypoint_id": null,
    "target_name": null,
    "message": "导航空闲",
    "timestamp": 1710000000.123
  },
  "localization_status": {
    "status": "ok",
    "frame_id": "map",
    "source": "/amcl_pose",
    "message": "定位正常",
    "timestamp": 1710000000.123
  }
}
```

前端打开页面时：

```text
1. 先 GET /api/v1/nav/state 获取当前状态；
2. 再建立 WebSocket；
3. 后续实时接收 nav.* 事件。
```

这样页面刷新后不会空白。

---

## 12. 和后续控制逻辑的关系

### 12.1 设置位姿

设置位姿属于控制请求，不是 WebSocket 订阅。

数据流：

```text
前端在 2D 俯视图选择位置和 yaw
  ↓
POST /api/v1/nav/localization/set-pose
  ↓
后端发布 /initialpose
  ↓
定位系统更新
  ↓
后端继续订阅定位输出
  ↓
前端通过 nav.robot_pose 看到位置变化
```

---

### 12.2 单点导航

```text
前端点击导航点“前往”
  ↓
POST /api/v1/nav/go-to
  ↓
后端调用 NavigateToPose action
  ↓
后端监听 feedback/result
  ↓
WebSocket 推送 nav.navigation_status
```

不要由前端根据距离自行判断是否到达。

---

### 12.3 巡检任务

```text
前端创建任务
  ↓
后端保存任务
  ↓
前端点击开始
  ↓
后端依次执行多个导航点
  ↓
WebSocket 推送 nav.patrol_status
```

巡检状态机必须在后端，不要放前端。

---

## 13. 推荐新增文件

后端建议新增：

```text
backend/services_ros_nav.py
backend/services_nav_state.py
```

后端建议修改：

```text
backend/config.py
backend/.env.example
backend/schemas.py
backend/main.py
backend/ws_event_broadcaster.py
```

前端建议新增：

```text
frontend/src/hooks/useNavWebSocket.ts
frontend/src/types/navState.ts
```

前端建议修改：

```text
frontend/src/pages/PcdMapDemoPage.tsx
frontend/src/components/pcd/PointCloudTopDownCanvas.tsx
frontend/src/components/pcd/PointCloud3DViewer.tsx
frontend/src/components/pcd/PcdMetadataPanel.tsx
```

---

## 14. 风险点

### 14.1 frame_id 不一致

最大风险：

```text
后端拿到的是 odom 坐标
前端按 map 坐标显示
```

后果：

```text
PCD 地图上的机器人位置不对
导航点和机器人位置对不上
后续单点导航偏移
```

必须确认：

```text
后端最终发给前端的数据是 map 坐标系。
```

---

### 14.2 ROS2 spin 阻塞 FastAPI

错误做法：

```text
FastAPI 主线程中直接 rclpy.spin()
```

正确做法：

```text
后台线程或独立进程运行 ROS2 node。
```

---

### 14.3 高频消息导致前端卡顿

后端必须节流。

不要每收到一条 `/odom` 就推一次 WebSocket。

---

### 14.4 点云实时流过大

本阶段不做实时点云话题转发。

静态 PCD 地图继续从文件加载。

---

## 15. 当前推荐结论

本阶段应完成：

```text
ROS2 位姿 topic
  ↓
后端订阅
  ↓
统一 RobotPose
  ↓
latest state 缓存
  ↓
WebSocket 推送
  ↓
前端显示机器人实时位置
```

不应该完成：

```text
前端直连 ROS2
前端直接使用 rosbridge 控制机器人
前端直接解析 ROS2 原始消息
高频转发点云
完整巡检任务状态机
```

最重要原则：

```text
ROS2 负责产生数据
后端负责订阅、转换、节流、缓存、广播
前端负责显示和交互
```
