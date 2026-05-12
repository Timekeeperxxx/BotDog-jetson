# ROS2 接口契约

本文只描述当前 BotDog-jetson 项目中 ROS2 对接的真实实现与后续建议，不作为业务代码实现说明。

## 一、契约范围

BotDog 后端负责接收前端导航相关操作，并把操作转换成 ROS2 topic 发布或运行时文件写入。

- 后端不直接实现路径规划。
- 后端不替代 ROS2 导航、雷达、建图模块。
- 本文不修改任何业务代码，只约定接口行为。

## 二、当前已实现

### 2.1 页面打开

- 前端打开导航页后，后端发布 `/lidar_start`，或配置项 `ROS_NAV_PAGE_OPEN_TOPIC` 指定的 topic。
- 消息类型：`std_msgs/msg/Bool`
- 数据：`true`
- 作用：通知雷达或导航侧开始准备。

### 2.2 单点导航 go-to waypoint

当前真实链路是：

- 前端调用 `/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}/go-to`
- 后端发布目标点位置信息到 clicked_point 对应 topic，语义上等价于 `goal_xyz`
- 后端同步发布 `goal_yaw`
- **go-to 不发布 `/nav_start`**

补充说明：

- 这一行为已经被 `tests/test_nav_go_to.py` 保护。
- go-to 是单点目标触发，不是任务执行入口。

### 2.3 任务导航 execute task

当前真实链路是：

- 前端调用 `/api/v1/nav/tasks/{task_id}/execute`
- 后端根据任务和导航点生成 `data/nav_runtime/current_task.json`
- 后端发布 `/nav_start`，消息为 `std_msgs/msg/Bool` 的 `true`

`current_task.json` 是当前任务主路径文件，建议视为任务执行上下文，而不是单点导航上下文。

`current_task.json` 当前应包含的核心字段：

- `task_id`
- `task_name`
- `scene_id`
- `steps`
- `scene_dir`
- `map_pcd`
- `ground_pcd`
- `source_waypoints`

当前实现中，`steps` 只保留 `navigate_waypoint` 步骤，但每个步骤必须包含完整导航字段，不再只保留 waypoint 标识。

`navigate_waypoint` 步骤推荐结构：

```json
{
  "type": "navigate_waypoint",
  "waypoint_id": "xxx",
  "waypoint_name": "巡检点1",
  "x": 1.0,
  "y": 2.0,
  "z": -0.83,
  "yaw": 1.57,
  "frame_id": "map"
}
```

补充说明：

- 这一行为已经被 `tests/test_nav_task_execute.py` 保护。
- `execute task` 才是当前会发布 `/nav_start true` 的入口。

### 2.4 停止任务

当前真实链路是：

- 前端调用 `/api/v1/nav/tasks/{task_id}/stop`
- 后端发布 `/nav_start false`
- 后端清理 `global_path`
- 后端将 `navigation_status` 置为 `idle`

### 2.5 重定位

当前真实链路是：

- 后端保存 localization pose
- 后端发布 `/initialpose_start`，或配置项 `ROS_NAV_SET_POSE_TOPIC` 指定的 topic
- 消息类型：`std_msgs/msg/Bool`
- 数据：`true`

### 2.6 建图

当前真实链路是：

- 后端发布 `/mapping_start`，或配置项 `ROS_NAV_MAPPING_TOPIC` 指定的 topic
- 消息类型：`std_msgs/msg/Bool`
- 数据：`true` 或 `false`

### 2.7 导航状态闭环

当前真实链路是：

- ROS2 通过 `/nav_status std_msgs/msg/String` 向后端推送导航状态 JSON
- 后端订阅 `/nav_status`，解析后更新 `navigation_status`
- 后端向前端广播 WebSocket 事件 `nav.navigation_status`
- 前端通过现有导航 WebSocket 更新导航状态展示

`/nav_status` 支持的原始状态：

- `accepted`
- `moving`
- `reached`
- `failed`
- `canceled`
- `estop`

后端映射后的状态：

- `accepted` -> `navigating`
- `moving` -> `navigating`
- `reached` -> `reached`
- `failed` -> `error`
- `canceled` -> `idle`
- `estop` -> `estop`

`/nav_status` JSON 示例：

```json
{
  "status": "moving",
  "task_id": "task_001",
  "waypoint_id": "wp_001",
  "message": "导航中",
  "distance_to_goal": 1.25,
  "error_code": null,
  "timestamp": 1770000000.123
}
```

补充说明：

- 非法 JSON 只记录 warning，不会让 ROS bridge 崩溃。
- 未知 `status` 只记录 warning，并映射为 `error`。
- 当前不要把 `current_goal.json` 视为任务执行主路径。

## 三、运行时文件

### 3.1 `data/nav_runtime/current_task.json`

这是当前任务执行的运行时文件，由任务执行接口生成。

建议字段语义如下：

- `task_id`：任务 ID
- `task_name`：任务名称
- `scene_id`：场景 ID
- `steps`：任务步骤数组，当前只保留 `navigate_waypoint` 步骤，且每个步骤包含完整导航坐标字段
- `scene_dir`：场景目录
- `map_pcd`：地图点云文件
- `ground_pcd`：地面点云文件
- `source_waypoints`：来源巡检点列表

如果需要附加元信息，可以继续保留 `frame_id`、`created_at`、`updated_at` 等字段，但不要把无关字段写成主流程依赖。

### 3.2 `current_goal.json`

`current_goal.json` 不再应被描述为当前主路径。

在当前实现语境里：

- 单点导航 go-to 走实时 topic 发布
- 任务导航 execute task 走 `current_task.json + /nav_start`
- 不应再把 `current_goal.json + /nav_start` 作为当前主链路写进文档
- ROS2 侧执行任务时，优先只读 `current_task.json` 即可拿到 `waypoint_id`、`waypoint_name`、`x/y/z/yaw/frame_id`

如果历史环境中仍存在 `current_goal.json`，也只应视为兼容历史，不应作为新的对接依据。

## 四、统一消息规则

| 数据类型 | ROS2 消息类型 | 使用场景 |
|---|---|---|
| 开启/关闭/触发动作 | `std_msgs/msg/Bool` | `start`、`stop`、`enable`、`disable`、`trigger` |
| 坐标/参数/状态/结果 | `std_msgs/msg/String`，`data` 为 JSON 字符串 | `goal`、`pose`、`status`、`error`、`task result` |
| 位姿连续数据 | `TF` 或 pose topic | `map -> base_link` 或 `/amcl_pose` |

统一要求：

- `Bool` 只表达 `true/false`，不承载复杂字段。
- JSON topic 必须是合法 JSON 字符串。
- 坐标单位统一为米。
- `yaw` 单位统一为弧度。
- 时间戳使用 Unix seconds 或 ISO8601，并在字段中明确说明。
- 默认坐标系为 `map`。
- `Bool` topic 即使用于触发动作，也只能表达 `true/false`，不扩展其他字段。
- JSON topic 不用于简单开关，不应用 `String("true")` / `String("false")` 替代 `Bool`。

## 五、坐标系约定

- 默认地图坐标系：`map`
- 默认机器人本体坐标系：`base_link`
- TF 查询方向：`map -> base_link`
- PCD 点云、导航点、机器人位姿必须使用同一 `map` 坐标系
- `x/y/z` 单位：米
- `yaw` 单位：弧度
- 如果使用 quaternion，必须说明它由 `yaw` 转换得到
- 不允许前端、后端、ROS2 侧混用 `map` / `odom` / `base_link` 坐标

补充说明：

- 当前后端 TF 模式下查询的是 `ROS_NAV_FRAME_ID -> ROS_NAV_BASE_FRAME_ID`，默认即 `map -> base_link`。
- 如果 ROS2 侧输出的是 `PoseStamped`、`PoseWithCovarianceStamped`、`Odometry`，其 `frame_id` 必须与地图坐标系约定一致，默认应为 `map`。

## 六、后续建议

以下内容是推荐补充方向，不是当前主路径。

### 6.1 `/nav_goal_json`

建议在跨机器部署、或后端与 ROS2 模块不能共享文件系统时，增加：

- topic：`/nav_goal_json`
- 消息类型：`std_msgs/msg/String`
- 内容：JSON 字符串
- 方向：BotDog 后端 -> ROS2

这属于跨机器传递目标点信息的可选方案，不是当前主路径。

### 6.2 `/initialpose_json`

建议在需要传递重定位坐标时，增加：

- topic：`/initialpose_json`
- 消息类型：`std_msgs/msg/String`
- 内容：JSON 字符串
- 方向：BotDog 后端 -> ROS2

这属于后续增强方案，不是当前主路径。

## 七、对接关系总览

### 7.1 当前已实现链路

```text
前端打开导航页
  -> 后端发布 /lidar_start Bool(true)

前端点击单个巡检点 go-to
  -> 后端发布 clicked_point/goal_xyz 对应 topic
  -> 后端发布 goal_yaw
  -> 不发布 /nav_start

前端执行任务 execute task
  -> 后端生成 data/nav_runtime/current_task.json
  -> 后端发布 /nav_start Bool(true)

前端停止任务
  -> 后端发布 /nav_start Bool(false)
  -> 后端清理 global_path
  -> 后端将 navigation_status 置为 idle

前端设置重定位
  -> 后端保存 localization pose
  -> 后端发布 /initialpose_start Bool(true)

前端开启/关闭建图
  -> 后端发布 /mapping_start Bool(true/false)
```

### 7.2 后续建议链路

```text
ROS2 发布 /nav_status String(JSON)
  -> 后端订阅 /nav_status
  -> 后端更新 navigation_status
  -> WebSocket 推送给前端

需要跨机器传递目标点时
  -> 可选发布 /nav_goal_json String(JSON)

需要传递重定位坐标时
  -> 可选发布 /initialpose_json String(JSON)
```

## 八、同事接入 checklist

- `ROS_DOMAIN_ID` 是否一致
- 后端启动前是否 `source` ROS2 环境
- topic 名称是否和 `.env` 配置一致
- `Bool` topic 是否只用 `true/false`
- JSON topic 是否是合法 JSON
- 是否能读取 `data/nav_runtime/current_task.json`
- 单点 go-to 是否只发 clicked_point/goal_xyz 和 `goal_yaw`
- 单点 go-to 是否不会发 `/nav_start`
- execute task 是否会发 `/nav_start true`
- 坐标系是否统一 `map`
- `x/y/z` 是否为米
- `yaw` 是否为弧度
- 是否能查到 `map -> base_link` TF
- 如果采用后续建议，是否能解析 `/nav_goal_json`
- 如果采用后续建议，是否能发布 `/nav_status`

## 九、排查命令

```bash
ros2 topic list
ros2 topic echo /lidar_start
ros2 topic echo /nav_start
ros2 topic echo /nav_stop
ros2 topic echo /mapping_start
ros2 topic echo /initialpose_start
ros2 topic echo /nav_status
ros2 topic echo /nav_goal_json
ros2 topic echo /initialpose_json
ros2 run tf2_ros tf2_echo map base_link
```

发布 `Bool` 示例：

```bash
ros2 topic pub /nav_start std_msgs/msg/Bool "{data: true}"
```

发布 JSON 示例：

```bash
ros2 topic pub /nav_status std_msgs/msg/String "data: '{\"status\":\"moving\",\"goal_id\":\"wp_001\",\"distance_to_goal\":1.25,\"message\":\"导航中\",\"timestamp\":1770000000.123}'"
```

## 十、文档索引

- `ROS2_INTERFACE_CONTRACT.md`：ROS2 topic / Bool / JSON 对接契约。
