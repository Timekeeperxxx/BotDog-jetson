# ROS2 接口契约

## 一、总体职责

BotDog 后端与 ROS2 / 同事导航模块之间的职责边界如下：

- BotDog 后端接收前端导航相关操作。
- BotDog 后端根据操作发布 ROS2 topic。
- BotDog 后端通过 TF 或位姿 topic 获取机器人当前位置。
- BotDog 后端将位姿、定位状态、导航状态转发给前端。
- BotDog 后端不直接实现路径规划。
- BotDog 后端不替代同事的导航模块、雷达模块、建图模块。

## 二、统一消息规则

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

## 三、坐标系约定

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

## 四、Bool 指令类 topic 契约

### 1. 页面打开 / 雷达准备

| 项目 | 内容 |
|---|---|
| 配置项 | `ROS_NAV_PAGE_OPEN_TOPIC` |
| 默认 topic | `/lidar_start` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/Bool` |
| 数据 | `true` |
| 触发时机 | 前端打开导航页或刷新导航页 |
| 作用 | 通知雷达/导航侧准备工作 |

### 2. 导航开始

| 项目 | 内容 |
|---|---|
| 配置项 | `ROS_NAV_START_TOPIC` |
| 默认 topic | `/nav_start` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/Bool` |
| 数据 | `true` |
| 触发时机 | 用户点击开始导航 |
| 作用 | 通知导航模块进入导航流程 |

### 3. 导航停止 / 急停

| 项目 | 内容 |
|---|---|
| 配置项 | `ROS_NAV_STOP_TOPIC` |
| 默认 topic | `/nav_stop` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/Bool` |
| 数据 | `true` |
| 触发时机 | 用户点击导航停止或急停 |
| 作用 | 通知导航模块停止当前导航动作 |

### 4. 重定位触发

| 项目 | 内容 |
|---|---|
| 配置项 | `ROS_NAV_SET_POSE_TOPIC` |
| 默认 topic | `/initialpose_start` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/Bool` |
| 数据 | `true` |
| 触发时机 | 用户设置重定位位姿后 |
| 作用 | 通知 ROS2 侧执行重定位流程 |

### 5. 建图开关

| 项目 | 内容 |
|---|---|
| 配置项 | `ROS_NAV_MAPPING_TOPIC` |
| 默认 topic | `/mapping_start` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/Bool` |
| 数据 | `true/false` |
| 触发时机 | 用户开启或关闭建图 |
| 作用 | 通知建图模块开始或停止 |

## 五、JSON 数据类 topic 契约

约定：

- Demo 阶段 ROS2 复杂数据统一采用 `std_msgs/msg/String`。
- `data` 字段中放 JSON 字符串。
- 复杂数据包括坐标、参数、状态、结果、错误原因。

注意：

- 当前代码里的 `/goal_pose` 仍是 `geometry_msgs/msg/PoseStamped`。
- 团队后续约定是：凡是传递坐标或复杂数据，优先使用 JSON 文档。
- 当前 `PoseStamped` 方案属于“当前实现兼容项”，不是后续统一契约的推荐终态。

### 1. 导航目标点，推荐新增或后续替换

| 项目 | 内容 |
|---|---|
| 推荐 topic | `/nav_goal_json` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/String` |
| data | JSON 字符串 |
| 用途 | 传递目标点坐标和导航点信息 |

JSON 示例：

```json
{
  "goal_id": "wp_001",
  "map_id": "map_001",
  "name": "门口巡逻点",
  "frame_id": "map",
  "x": 1.25,
  "y": 3.40,
  "z": 0.0,
  "yaw": 1.57,
  "timestamp": 1770000000.123
}
```

字段说明：

- `goal_id`：导航点 ID
- `map_id`：地图 ID
- `name`：导航点名称
- `frame_id`：默认 `map`
- `x/y/z`：单位米
- `yaw`：单位弧度
- `timestamp`：Unix seconds

当前兼容说明：

- 当前 `services_ros_nav.py` 仍通过 `ROS_NAV_GOAL_TOPIC`，默认 `/goal_pose`，发布 `geometry_msgs/msg/PoseStamped`。
- 如果暂时继续使用 `/goal_pose`，它属于当前兼容实现。
- 后续如果改成 JSON，建议新增 `ROS_NAV_GOAL_JSON_TOPIC` 配置，不要直接破坏旧接口。

### 2. 重定位位姿，推荐新增

| 项目 | 内容 |
|---|---|
| 推荐 topic | `/initialpose_json` |
| 方向 | BotDog 后端 -> ROS2 |
| 消息类型 | `std_msgs/msg/String` |
| data | JSON 字符串 |

JSON 示例：

```json
{
  "map_id": "map_001",
  "frame_id": "map",
  "x": 1.25,
  "y": 3.40,
  "yaw": 1.57,
  "timestamp": 1770000000.123
}
```

说明：

- 当前 `/initialpose_start` 只负责 `Bool` 触发。
- 真正的重定位坐标建议通过 `/initialpose_json` 传递。

### 3. 导航状态反馈，推荐新增

| 项目 | 内容 |
|---|---|
| 推荐 topic | `/nav_status` |
| 方向 | ROS2 -> BotDog 后端 |
| 消息类型 | `std_msgs/msg/String` |
| data | JSON 字符串 |

JSON 示例：

```json
{
  "status": "accepted",
  "goal_id": "wp_001",
  "distance_to_goal": 1.25,
  "message": "导航目标已接收",
  "error_code": null,
  "timestamp": 1770000000.123
}
```

状态枚举：

- `accepted`：导航模块已接收目标
- `moving`：正在导航
- `reached`：到达目标点
- `failed`：导航失败
- `canceled`：用户取消
- `estop`：急停中断

### 4. 错误反馈，推荐通过 `/nav_status` 承载

JSON 示例：

```json
{
  "status": "failed",
  "goal_id": "wp_001",
  "error_code": "PLAN_FAILED",
  "message": "路径规划失败",
  "timestamp": 1770000000.123
}
```

## 六、当前实现与推荐契约的差异

当前代码已实现：

- `/lidar_start`：`Bool`
- `/nav_start`：`Bool`
- `/nav_stop`：`Bool`
- `/initialpose_start`：`Bool`
- `/mapping_start`：`Bool`
- `/goal_pose`：`PoseStamped`
- 位姿来源：TF 或 pose topic

推荐后续补充：

- `/nav_goal_json`：`String(JSON)`，用于传递目标点完整信息
- `/initialpose_json`：`String(JSON)`，用于传递重定位坐标
- `/nav_status`：`String(JSON)`，用于 ROS2 向后端反馈导航状态

说明：

- 为了避免一次性破坏已有功能，当前阶段不强制删除 `/goal_pose`。
- 后续可以采用“双发模式”：
- 继续发布 `/goal_pose` 给 Nav2 兼容
- 同时发布 `/nav_goal_json` 给同事模块读取完整字段

## 七、前后端完整链路

```text
前端点击导航点
  -> FastAPI nav go-to 接口
  -> 后端发布 /nav_start Bool(true)
  -> 后端发布目标点信息
     当前：/goal_pose PoseStamped
     推荐：/nav_goal_json String(JSON)
  -> ROS2 导航模块执行
  -> ROS2 发布 /nav_status String(JSON)
  -> 后端订阅 /nav_status
  -> 更新 navigation_status
  -> WebSocket 推送给前端
  -> 前端显示导航进度、到达、失败原因
```

## 八、同事接入 checklist

- `ROS_DOMAIN_ID` 是否一致
- 后端启动前是否 `source` ROS2 环境
- topic 名称是否和 `.env` 配置一致
- `Bool` topic 是否只用 `true/false`
- JSON topic 是否是合法 JSON
- 坐标系是否统一 `map`
- `x/y/z` 是否为米
- `yaw` 是否为弧度
- 是否能查到 `map -> base_link` TF
- 是否能收到 `/nav_start`
- 是否能收到 `/nav_stop`
- 是否能解析 `/nav_goal_json`
- 是否能发布 `/nav_status`

## 九、排查命令

```bash
ros2 topic list
ros2 topic echo /lidar_start
ros2 topic echo /nav_start
ros2 topic echo /nav_stop
ros2 topic echo /mapping_start
ros2 topic echo /goal_pose
ros2 topic echo /nav_goal_json
ros2 topic echo /nav_status
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
