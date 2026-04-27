# BotDog-jetson ROS2 后端订阅转发开发实现路径

## 1. 开发目标

本文档用于指导在 `BotDog-jetson` 项目中实现：

```text
后端订阅 ROS2 话题
  ↓
标准化机器人位姿和导航状态
  ↓
缓存最新状态
  ↓
通过 WebSocket 推送给前端
  ↓
前端在已完成的 PCD 点云 Demo 中显示机器人实时位置
```

默认 PCD 点云地图选择、预览和导航点标记功能已经完成。

---

## 2. 本阶段不做什么

本阶段不实现：

```text
1. 前端直接订阅 ROS2；
2. 前端连接 rosbridge；
3. 前端直接发布 /initialpose；
4. 前端直接调用 NavigateToPose；
5. 真实单点导航；
6. 真实巡检任务；
7. 实时 PointCloud2 全量推送；
8. 复杂 TF 树完整可视化。
```

本阶段只做：

```text
1. 后端订阅机器人位姿；
2. 后端转换为 map 坐标系下的 RobotPose；
3. 后端通过 WebSocket 推送；
4. 前端显示机器人位置。
```

---

## 3. 开发顺序

请按下面顺序实现：

```text
第 1 步：确认 ROS2 位姿来源 topic
第 2 步：新增后端导航状态缓存模块
第 3 步：新增后端 ROS2 订阅模块
第 4 步：后端启动时启动 ROS2 后台线程
第 5 步：新增 /api/v1/nav/state 当前状态接口
第 6 步：扩展 WebSocket 事件类型 nav.robot_pose
第 7 步：前端新增 navState 类型
第 8 步：前端新增 useNavWebSocket
第 9 步：PCD 页面接入 robotPose 状态
第 10 步：2D 俯视图显示机器人箭头
第 11 步：3D 点云显示机器人位置
第 12 步：联调和验收
```

---

## 4. 第 1 步：确认 ROS2 位姿来源

先让同事确认当前机器人定位输出 topic。

需要确认：

```text
1. 位姿 topic 名称是什么？
2. 消息类型是什么？
3. header.frame_id 是什么？
4. 该位姿是否已经在 map 坐标系下？
5. 四元数 orientation 是否正常？
6. 更新频率是多少？
```

常见候选：

```text
/amcl_pose
/odom
/tf
/lio/pose
/lio_sam/mapping/odometry
/Odometry
/robot_pose
```

优先级：

```text
1. 优先选择已经是 map 坐标系下的 PoseStamped / PoseWithCovarianceStamped；
2. 如果只能用 /tf，则取 map -> base_link；
3. 如果只能用 /odom，必须确认 odom 是否可以等价为 map；
4. 如果是 LIO 输出 Odometry，必须确认 header.frame_id。
```

当前阶段需要的最终结果是：

```text
x
y
z
yaw
frame_id = map
```

---

## 5. 第 2 步：新增 backend/services_nav_state.py

### 5.1 文件职责

新增：

```text
backend/services_nav_state.py
```

职责：

```text
1. 缓存 latest_robot_pose；
2. 缓存 latest_navigation_status；
3. 缓存 latest_localization_status；
4. 提供线程安全更新；
5. 提供当前状态查询；
6. 供 WebSocket 推送模块读取。
```

### 5.2 内部状态

逻辑上维护：

```text
latest_robot_pose
latest_navigation_status
latest_localization_status
```

`latest_robot_pose` 结构：

```json
{
  "x": 1.25,
  "y": -0.82,
  "z": 0.0,
  "yaw": 1.57,
  "frame_id": "map",
  "source": "/amcl_pose",
  "timestamp": 1710000000.123
}
```

`latest_navigation_status` 结构：

```json
{
  "status": "idle",
  "target_waypoint_id": null,
  "target_name": null,
  "message": "导航空闲",
  "timestamp": 1710000000.123
}
```

`latest_localization_status` 结构：

```json
{
  "status": "unknown",
  "frame_id": "map",
  "source": null,
  "message": "尚未收到定位数据",
  "timestamp": null
}
```

### 5.3 线程安全要求

因为 ROS2 后台线程会写状态，FastAPI 主线程会读状态，所以必须保证：

```text
1. 写入状态时加锁；
2. 读取状态时返回拷贝；
3. 不要让前端读到半更新状态。
```

---

## 6. 第 3 步：新增 backend/services_ros_nav.py

### 6.1 文件职责

新增：

```text
backend/services_ros_nav.py
```

职责：

```text
1. 初始化 rclpy；
2. 创建 ROS2 Node；
3. 根据配置订阅位姿 topic；
4. 将 ROS2 消息转换成 RobotPose；
5. 更新 services_nav_state；
6. 触发 WebSocket 广播；
7. 后端关闭时正确销毁 node。
```

### 6.2 配置项

在 `backend/config.py` 增加：

```text
ROS_NAV_ENABLED=true
ROS_NAV_POSE_TOPIC=/amcl_pose
ROS_NAV_POSE_TYPE=PoseWithCovarianceStamped
ROS_NAV_FRAME_ID=map
ROS_NAV_BASE_FRAME_ID=base_link
ROS_NAV_BROADCAST_HZ=10
```

含义：

| 配置 | 说明 |
|---|---|
| `ROS_NAV_ENABLED` | 是否启用 ROS2 后端订阅 |
| `ROS_NAV_POSE_TOPIC` | 位姿来源 topic |
| `ROS_NAV_POSE_TYPE` | 位姿消息类型标识 |
| `ROS_NAV_FRAME_ID` | 目标坐标系，默认 map |
| `ROS_NAV_BASE_FRAME_ID` | 机器人本体坐标系 |
| `ROS_NAV_BROADCAST_HZ` | WebSocket 广播频率 |

在 `.env.example` 中同步追加。

---

## 7. 第 4 步：ROS2 消息转换逻辑

### 7.1 PoseWithCovarianceStamped

如果订阅：

```text
/amcl_pose
```

一般提取：

```text
msg.header.frame_id
msg.pose.pose.position.x
msg.pose.pose.position.y
msg.pose.pose.position.z
msg.pose.pose.orientation
```

处理逻辑：

```text
1. 读取 position；
2. 读取 quaternion；
3. quaternion 转 yaw；
4. 判断 header.frame_id 是否为 map；
5. 生成 RobotPose；
6. 更新 latest_robot_pose。
```

---

### 7.2 Odometry

如果订阅：

```text
/odom
```

一般提取：

```text
msg.header.frame_id
msg.child_frame_id
msg.pose.pose.position
msg.pose.pose.orientation
```

注意：

```text
如果 header.frame_id 是 odom，不能直接当成 map。
```

除非同事确认：

```text
当前系统中 odom 和 map 等价
```

否则需要通过 TF 计算 `map -> base_link`。

---

### 7.3 TF

如果使用 `/tf`，逻辑是：

```text
1. 后端维护 TF buffer；
2. 查询 map -> base_link；
3. 得到 translation 和 rotation；
4. 转成 x/y/z/yaw；
5. 更新 RobotPose。
```

TF 是最标准但实现复杂度更高。

第一版建议：

```text
优先订阅已经是 map 坐标系下的 pose topic。
```

---

## 8. 第 5 步：后端启动和关闭

### 8.1 启动逻辑

在 FastAPI 启动阶段：

```text
1. 判断 ROS_NAV_ENABLED；
2. 如果启用，启动 ROS2 后台线程；
3. 后台线程中初始化 rclpy；
4. 创建 ROS2 node；
5. 注册 subscriber；
6. 开始 spin；
7. 同时启动节流广播定时逻辑。
```

### 8.2 关闭逻辑

在 FastAPI shutdown 阶段：

```text
1. 通知 ROS2 后台线程停止；
2. 停止 spin；
3. destroy node；
4. rclpy shutdown；
5. 等待线程退出。
```

必须避免：

```text
1. rclpy 重复初始化；
2. 后台线程无法退出；
3. 开发时热重载残留旧节点；
4. Ctrl+C 无法结束。
```

---

## 9. 第 6 步：新增 /api/v1/nav/state

在 `backend/main.py` 中新增：

```http
GET /api/v1/nav/state
```

返回当前缓存状态。

返回结构：

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

用途：

```text
1. 前端页面打开时先获取一次当前状态；
2. WebSocket 断线重连后重新同步；
3. 调试后端是否收到 ROS2 数据。
```

---

## 10. 第 7 步：扩展 WebSocket 事件

### 10.1 推荐事件结构

WebSocket 事件统一结构：

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

### 10.2 事件类型

第一版实现：

```text
nav.robot_pose
nav.localization_status
```

后续扩展：

```text
nav.navigation_status
nav.patrol_status
nav.mapping_status
nav.error
```

### 10.3 广播频率

```text
robot_pose: 5Hz ~ 10Hz
localization_status: 1Hz ~ 2Hz
navigation_status: 状态变化时立即推送
```

不要 ROS2 每来一条消息就直接广播。

---

## 11. 第 8 步：前端新增 navState 类型

新增：

```text
frontend/src/types/navState.ts
```

包含：

```text
RobotPose
NavigationStatus
LocalizationStatus
NavStateResponse
NavWebSocketEvent
```

逻辑结构：

```text
RobotPose:
  x
  y
  z
  yaw
  frame_id
  source
  timestamp

NavigationStatus:
  status
  target_waypoint_id
  target_name
  message
  timestamp

LocalizationStatus:
  status
  frame_id
  source
  message
  timestamp
```

---

## 12. 第 9 步：前端新增 navApi

新增或扩展：

```text
frontend/src/api/navApi.ts
```

接口：

```text
getNavState()
```

内部请求：

```text
GET /api/v1/nav/state
```

必须使用：

```text
getApiUrl()
```

不要写死后端地址。

---

## 13. 第 10 步：前端新增 useNavWebSocket

新增：

```text
frontend/src/hooks/useNavWebSocket.ts
```

职责：

```text
1. 连接现有 BotDog 后端 WebSocket；
2. 接收消息；
3. 过滤 type 以 nav. 开头的事件；
4. 更新 robotPose；
5. 更新 localizationStatus；
6. 处理断线；
7. 暴露给 PcdMapDemoPage。
```

对外暴露状态：

```text
robotPose
localizationStatus
navigationStatus
connected
lastMessageAt
```

---

## 14. 第 11 步：PcdMapDemoPage 接入机器人位姿

在已完成的 `PcdMapDemoPage` 中新增：

```text
1. 页面加载时调用 getNavState()；
2. 建立 useNavWebSocket；
3. 获取 robotPose；
4. 传给 2D 俯视图；
5. 传给 3D 点云视图；
6. 右侧面板显示机器人当前坐标。
```

页面右侧新增：

```text
机器人实时状态
- x
- y
- z
- yaw
- frame_id
- source
- 更新时间
- WebSocket 连接状态
```

如果长时间没有位姿：

```text
显示“未收到机器人位姿”
```

如果 frame_id 不是 map：

```text
显示红色警告：“当前位姿不是 map 坐标系”
```

---

## 15. 第 12 步：2D 俯视图显示机器人位置

修改：

```text
PointCloudTopDownCanvas
```

新增输入：

```text
robotPose
```

显示逻辑：

```text
1. 如果没有 robotPose，不绘制；
2. 如果 robotPose.frame_id 不是 map，提示但不强制绘制；
3. 使用 mapToCanvas(robotPose.x, robotPose.y)；
4. 绘制机器人圆点；
5. 根据 yaw 绘制朝向箭头；
6. 可显示机器人坐标文字。
```

朝向箭头逻辑：

```text
arrow_x = cos(yaw)
arrow_y = sin(yaw)
```

Canvas y 轴向下，所以绘制时要注意 y 方向反转。

---

## 16. 第 13 步：3D 点云显示机器人位置

修改：

```text
PointCloud3DViewer
```

新增输入：

```text
robotPose
```

显示逻辑：

```text
1. 使用 mapToThree(robotPose.x, robotPose.y, robotPose.z)；
2. 绘制一个小圆柱、球体或箭头；
3. 根据 yaw 设置朝向；
4. 每次 robotPose 更新时只更新机器人对象位置，不重建整个点云。
```

关键要求：

```text
点云 geometry 不要因为 robotPose 更新而重建。
```

否则每秒更新多次会导致卡顿。

---

## 17. 第 14 步：节流策略

后端：

```text
ROS2 收到高频消息
  ↓
更新 latest_robot_pose
  ↓
广播线程每 100ms 推送一次
```

前端：

```text
收到 nav.robot_pose
  ↓
更新状态
  ↓
React 局部更新机器人对象
```

不要：

```text
每条 ROS2 消息都触发全页面重绘
每次 pose 更新都重建 three.js scene
每次 pose 更新都重画完整点云
```

---

## 18. 第 15 步：验收流程

### 18.1 后端接口验收

启动后端后：

```text
GET /api/v1/nav/state
```

如果还没收到 ROS2：

```text
robot_pose 可以是 null
localization_status.status = unknown
```

收到 ROS2 后：

```text
robot_pose.x/y/yaw 有值
frame_id = map
source = 配置的位姿 topic
```

---

### 18.2 WebSocket 验收

前端或调试工具应能收到：

```json
{
  "type": "nav.robot_pose",
  "data": {
    "x": 1.25,
    "y": -0.82,
    "z": 0.0,
    "yaw": 1.57,
    "frame_id": "map"
  }
}
```

频率应为：

```text
约 5Hz ~ 10Hz
```

不要达到 `/odom` 原始频率。

---

### 18.3 前端验收

打开导航巡逻页面：

```text
1. 选择已完成的 PCD 地图；
2. 3D 点云正常显示；
3. 2D 俯视图正常显示；
4. 右侧显示机器人实时坐标；
5. 2D 俯视图中出现机器人箭头；
6. 3D 点云中出现机器人标记；
7. 机器人移动时，前端位置实时更新；
8. WebSocket 断开时页面显示连接异常；
9. WebSocket 恢复后继续更新。
```

---

## 19. 常见问题

### 19.1 robot_pose 显示在地图外

可能原因：

```text
1. 位姿不是 map 坐标；
2. PCD 点云坐标不是导航 map 坐标；
3. mapToCanvas 转换错误；
4. 点云经过平移、旋转或裁剪；
5. 后端把 odom 当成 map。
```

优先排查：

```text
ROS2 pose 的 frame_id 是否为 map。
```

---

### 19.2 后端启动卡住

可能原因：

```text
FastAPI 主线程中直接执行了 rclpy.spin()
```

解决原则：

```text
ROS2 spin 必须在后台线程或独立进程中运行。
```

---

### 19.3 前端卡顿

可能原因：

```text
1. WebSocket 推送太频繁；
2. 每次 pose 更新都重建点云；
3. Canvas 每次 mousemove 都重画全部点；
4. 3D 场景对象没有复用。
```

解决：

```text
1. 限制 robot_pose 推送到 10Hz；
2. 点云 geometry 只在换地图时创建；
3. 机器人模型只更新 transform；
4. Canvas 静态点云层和动态机器人层分开绘制。
```

---

### 19.4 frame_id 不是 map

处理策略：

```text
1. 前端显示警告；
2. 后端不要强行标记为 map；
3. 如果确实需要，从 TF 转换到 map；
4. 让同事确认定位输出坐标系。
```

---

## 20. Codex 执行任务清单

可以把下面内容直接交给 Codex：

```text
请在已经完成 PCD 点云地图 Demo 的 BotDog-jetson 项目中，实现 ROS2 后端订阅并通过 WebSocket 转发机器人实时位姿。

后端要求：
1. 修改 backend/config.py，增加：
   ROS_NAV_ENABLED
   ROS_NAV_POSE_TOPIC
   ROS_NAV_POSE_TYPE
   ROS_NAV_FRAME_ID
   ROS_NAV_BASE_FRAME_ID
   ROS_NAV_BROADCAST_HZ

2. 修改 backend/.env.example，追加以上配置说明。

3. 新增 backend/services_nav_state.py：
   - 缓存 latest_robot_pose
   - 缓存 latest_navigation_status
   - 缓存 latest_localization_status
   - 提供线程安全 get/set
   - 提供 get_nav_state()

4. 新增 backend/services_ros_nav.py：
   - 初始化 rclpy
   - 创建 ROS2 订阅节点
   - 订阅 ROS_NAV_POSE_TOPIC
   - 根据 ROS_NAV_POSE_TYPE 解析 PoseWithCovarianceStamped / Odometry / PoseStamped
   - 四元数转换 yaw
   - 校验 frame_id
   - 更新 services_nav_state
   - 按 ROS_NAV_BROADCAST_HZ 节流广播 nav.robot_pose
   - FastAPI shutdown 时正确停止线程、销毁 node、关闭 rclpy

5. 修改 backend/schemas.py：
   - 增加 RobotPoseDTO
   - NavigationStatusDTO
   - LocalizationStatusDTO
   - NavStateResponse

6. 修改 backend/main.py：
   - FastAPI startup 时，如果 ROS_NAV_ENABLED=true，启动 ROS2 后台订阅线程
   - FastAPI shutdown 时停止 ROS2 后台线程
   - 新增 GET /api/v1/nav/state

7. 复用或扩展 ws_event_broadcaster.py：
   - 支持广播 nav.robot_pose
   - 支持广播 nav.localization_status
   - 事件结构为 { type, data }

前端要求：
1. 新增 frontend/src/types/navState.ts：
   - RobotPose
   - NavigationStatus
   - LocalizationStatus
   - NavStateResponse
   - NavWebSocketEvent

2. 新增 frontend/src/api/navApi.ts：
   - getNavState()
   - 必须使用 getApiUrl('/api/v1/nav/state')

3. 新增 frontend/src/hooks/useNavWebSocket.ts：
   - 连接现有后端 WebSocket
   - 过滤 nav.* 事件
   - 更新 robotPose
   - 更新 localizationStatus
   - 暴露 connected、lastMessageAt

4. 修改 PcdMapDemoPage：
   - 页面打开时调用 getNavState()
   - 使用 useNavWebSocket()
   - 把 robotPose 传给 PointCloudTopDownCanvas
   - 把 robotPose 传给 PointCloud3DViewer
   - 右侧面板显示机器人实时 x/y/z/yaw/frame_id/source

5. 修改 PointCloudTopDownCanvas：
   - 接收 robotPose
   - 在 2D 俯视图中绘制机器人圆点和朝向箭头
   - 使用现有 mapToCanvas 坐标转换

6. 修改 PointCloud3DViewer：
   - 接收 robotPose
   - 使用 mapToThree 显示机器人位置
   - robotPose 更新时只更新机器人对象位置，不重建点云 geometry

验收标准：
1. 后端 /api/v1/nav/state 能返回当前导航状态。
2. 后端能接收到 ROS2 位姿 topic。
3. 后端能通过 WebSocket 推送 nav.robot_pose。
4. 前端右侧面板能显示机器人实时 x/y/yaw。
5. 2D 俯视图能显示机器人位置和朝向。
6. 3D 点云中能显示机器人标记。
7. ROS2 高频 topic 不会导致前端卡顿。
8. frame_id 不是 map 时前端有明确警告。
9. 原有 PCD 地图选择、点云显示、导航点保存功能不受影响。
```

---

## 21. 当前阶段完成后的下一步

本阶段完成后，再进入：

```text
1. 设置位姿接口；
2. 单点导航接口；
3. 导航 action feedback/result 转发；
4. 巡检任务状态机；
5. 建图控制；
6. 实时点云叠加。
```

不要直接跳到巡检任务。

如果机器人实时位姿无法正确显示在 PCD 地图上，说明坐标闭环还没有打通，后续导航一定会出问题。
