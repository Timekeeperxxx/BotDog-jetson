# 导航巡逻 PCD 点云接入架构说明文档

## 1. 文档目的

本文档用于说明当前机器狗前端系统接入“导航巡逻”功能时，围绕同事已建好的 `.pcd` 三维点云地图，应采用的整体系统架构、数据流、模块划分、接口设计和关键技术约束。

当前优先目标不是直接完成完整导航巡逻闭环，而是先验证：

1. 同事建好的 PCD 点云地图是否能够被你的系统访问；
2. 后端是否能够从指定目录读取 `.pcd` 文件；
3. 后端是否能够解析、降采样并提供给前端；
4. 前端是否能够显示三维点云；
5. 前端是否能够基于 `map` 坐标系标记导航点；
6. 后续导航、巡检、重定位、任务编排能否建立在同一套坐标体系上。

---

## 2. 当前已确认条件

根据当前沟通，地图交接条件如下：

| 项目 | 当前结论 |
|---|---|
| 地图文件格式 | `.pcd` |
| 地图类型 | 三维点云地图 |
| 文件交接方式 | 不上传、不拷贝，后端直接访问同事生成地图的文件路径 |
| 地图元数据 | 暂不考虑 `resolution`、`origin` 等二维栅格地图参数 |
| 地图选择方式 | 临时在指定文件夹内选择点云图 |
| 导航坐标系 | `map` |
| 前端重点 | 加载 PCD、显示点云、标记导航点、验证坐标 |

因此，不采用传统二维地图的：

```text
map.yaml
map.pgm
map.png
OccupancyGrid
```

作为第一阶段重点。

第一阶段采用：

```text
PCD 文件目录
  ↓
后端扫描 .pcd
  ↓
后端读取和降采样
  ↓
前端 three.js 显示
  ↓
前端 2D 俯视图标点
  ↓
保存 map 坐标系下的导航点
```

---

## 3. 总体架构

推荐整体架构如下：

```text
┌───────────────────────────────────────────────┐
│                    前端系统                    │
│                                               │
│  PcdMapDemoPage                                │
│  ├── PCD 文件列表                              │
│  ├── 3D 点云视图 three.js                      │
│  ├── 2D 俯视投影视图 Canvas                    │
│  ├── 导航点标记/删除/列表                       │
│  ├── 点云元数据显示                            │
│  └── 操作日志                                  │
└───────────────────────┬───────────────────────┘
                        │ HTTP / WebSocket
                        ↓
┌───────────────────────────────────────────────┐
│                    后端网关                    │
│                                               │
│  FastAPI / Flask / Node                        │
│  ├── PCD 文件扫描                              │
│  ├── PCD 头部解析                              │
│  ├── PCD 点云读取                              │
│  ├── 点云降采样                                │
│  ├── 点云 bounds 计算                          │
│  ├── 导航点保存                                │
│  └── 后续 ROS2 网关封装                         │
└───────────────────────┬───────────────────────┘
                        │ 文件系统访问
                        ↓
┌───────────────────────────────────────────────┐
│               PCD 点云地图目录                 │
│                                               │
│  /home/jetson/maps/                            │
│  ├── 1.pcd                                     │
│  ├── test_area.pcd                             │
│  └── warehouse_map.pcd                         │
└───────────────────────────────────────────────┘
```

后续接真实 ROS2 后，架构扩展为：

```text
前端
  ↓ HTTP / WebSocket
后端导航网关
  ↓ rclpy / ros2 action / ros2 service / subprocess
ROS2 定位、导航、建图节点
  ↓
机器狗 / 雷达 / 点云地图
```

---

## 4. 设计原则

### 4.1 前端不直接访问文件系统

浏览器前端不能直接读取：

```text
/home/jetson/maps/1.pcd
```

原因是浏览器安全模型禁止网页任意访问服务器本地文件系统。

正确方式：

```text
前端请求后端接口
  ↓
后端读取本机或挂载目录中的 .pcd 文件
  ↓
后端处理后返回给前端
```

---

### 4.2 后端必须限制读取目录

后端不能允许前端传入任意路径，例如：

```json
{
  "path": "/etc/passwd"
}
```

必须采用白名单根目录，例如：

```bash
PCD_MAP_ROOT=/home/jetson/maps
```

后端只扫描和读取该目录下的 `.pcd` 文件。

推荐约束：

```text
1. 只返回 PCD_MAP_ROOT 下的文件；
2. 只允许扩展名为 .pcd；
3. mapId 只能是文件名或后端生成的安全 ID；
4. 后端解析路径时必须防止 ../ 路径穿越；
5. 不允许前端直接提交完整绝对路径。
```

---

### 4.3 PCD 点云必须降采样

PCD 文件可能包含几十万、几百万甚至上千万个点。如果完整传给前端，会导致：

```text
1. HTTP 响应过大；
2. JSON 解析过慢；
3. 浏览器内存飙升；
4. three.js 渲染卡顿；
5. 页面崩溃。
```

因此后端必须提供预览接口，并限制最大点数：

```http
GET /api/pcd-maps/{mapId}/preview?maxPoints=100000
```

Demo 阶段建议默认：

```text
maxPoints = 100000
```

正式阶段可以优化为：

```text
1. 二进制 Float32Array 传输；
2. 体素滤波 voxel downsample；
3. 分块加载；
4. WebSocket 流式加载；
5. LOD 多层级点云。
```

---

### 4.4 坐标系统一为 map

当前已确认导航坐标系是：

```text
frame_id = map
```

因此 Demo 中所有导航点都必须保存为：

```json
{
  "x": 2.35,
  "y": -1.20,
  "z": 0.0,
  "yaw": 1.57,
  "frameId": "map"
}
```

注意：

PCD 文件本身通常只存点坐标，不一定显式存 `frame_id`。所以 Demo 阶段默认：

```text
PCD 点云坐标 = map 坐标
```

但后续真实导航前，必须让同事确认：

```text
PCD 里的 x/y/z 是否就是导航系统使用的 map 坐标？
导航目标点是否可以直接使用这些 x/y/yaw？
```

如果不是同一坐标系，后续需要加入坐标变换。

---

## 5. 核心模块划分

### 5.1 前端模块

建议新增页面：

```text
PcdMapDemoPage
```

页面组件建议：

```text
PcdMapDemoPage
├── PcdFileListPanel              # 左侧 PCD 文件列表
├── PcdMetadataPanel              # 点云元数据显示
├── PointCloud3DViewer            # three.js 三维点云显示
├── PointCloudTopDownCanvas       # 2D 俯视图标点
├── WaypointPanel                 # 导航点列表/删除
├── OperationToolbar              # 刷新、加载、添加点
└── LogPanel                      # 操作日志
```

前端数据层：

```text
pcdMapApi.ts
├── listPcdMaps()
├── getPcdMetadata(mapId)
├── getPcdPreview(mapId, maxPoints)
├── listWaypoints(mapId)
├── createWaypoint(mapId, waypoint)
└── deleteWaypoint(mapId, waypointId)
```

状态建议：

```ts
type PcdMapItem = {
  id: string
  name: string
  sizeBytes: number
  modifiedAt: string
}

type PcdBounds = {
  minX: number
  maxX: number
  minY: number
  maxY: number
  minZ: number
  maxZ: number
}

type PcdMetadata = {
  mapId: string
  name: string
  frameId: "map"
  type: "pcd"
  pointCount: number
  fields: string[]
  dataType: "ascii" | "binary" | "binary_compressed" | "unknown"
  bounds: PcdBounds
}

type PointCloudPreview = {
  mapId: string
  frameId: "map"
  points: [number, number, number][]
  bounds: PcdBounds
}

type Waypoint = {
  id: string
  mapId: string
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frameId: "map"
}
```

---

### 5.2 后端模块

建议新增后端模块：

```text
backend/
├── routers/
│   └── pcd_maps.py
├── services/
│   ├── pcd_map_service.py
│   ├── pcd_parser.py
│   └── waypoint_store.py
├── data/
│   └── waypoints/
│       └── {mapId}.json
└── config.py
```

模块职责：

| 模块 | 职责 |
|---|---|
| `pcd_maps.py` | 定义 HTTP API |
| `pcd_map_service.py` | 扫描 PCD 文件、读取 metadata、读取 preview |
| `pcd_parser.py` | 解析 PCD header 和点数据 |
| `waypoint_store.py` | 保存/读取/删除导航点 |
| `config.py` | 管理 `PCD_MAP_ROOT` |

---

## 6. 后端接口设计

### 6.1 获取 PCD 文件列表

```http
GET /api/pcd-maps
```

返回：

```json
{
  "root": "/home/jetson/maps",
  "items": [
    {
      "id": "1.pcd",
      "name": "1.pcd",
      "sizeBytes": 125829120,
      "modifiedAt": "2026-04-27 15:20:00"
    }
  ]
}
```

说明：

```text
1. id 可以暂时使用文件名；
2. 后端必须保证 id 不能包含路径穿越；
3. 只列出 .pcd 文件；
4. 不建议前端依赖完整绝对路径。
```

---

### 6.2 获取 PCD 元数据

```http
GET /api/pcd-maps/{mapId}/metadata
```

返回：

```json
{
  "mapId": "1.pcd",
  "name": "1.pcd",
  "frameId": "map",
  "type": "pcd",
  "pointCount": 2350000,
  "fields": ["x", "y", "z", "intensity"],
  "dataType": "ascii",
  "bounds": {
    "minX": -12.5,
    "maxX": 18.2,
    "minY": -8.4,
    "maxY": 10.7,
    "minZ": -1.2,
    "maxZ": 3.8
  }
}
```

说明：

```text
1. metadata 需要解析 PCD header；
2. pointCount 对应 POINTS 字段；
3. fields 来自 FIELDS；
4. dataType 来自 DATA；
5. bounds 需要扫描点数据后计算；
6. 如果文件很大，bounds 计算可以缓存。
```

---

### 6.3 获取 PCD 预览点云

```http
GET /api/pcd-maps/{mapId}/preview?maxPoints=100000
```

返回：

```json
{
  "mapId": "1.pcd",
  "frameId": "map",
  "points": [
    [1.2, 0.5, 0.1],
    [1.3, 0.6, 0.1],
    [1.4, 0.7, 0.1]
  ],
  "bounds": {
    "minX": -12.5,
    "maxX": 18.2,
    "minY": -8.4,
    "maxY": 10.7,
    "minZ": -1.2,
    "maxZ": 3.8
  }
}
```

要求：

```text
1. 返回点数不能超过 maxPoints；
2. maxPoints 需要设置上限，例如 200000；
3. 默认 maxPoints 建议 100000；
4. 如果原始点数量大于 maxPoints，需要均匀采样或随机采样；
5. Demo 阶段可以 JSON 返回；
6. 正式版建议改成二进制。
```

---

### 6.4 获取导航点列表

```http
GET /api/pcd-maps/{mapId}/waypoints
```

返回：

```json
{
  "items": [
    {
      "id": "wp_001",
      "mapId": "1.pcd",
      "name": "巡检点1",
      "x": 2.35,
      "y": -1.20,
      "z": 0.0,
      "yaw": 0.0,
      "frameId": "map"
    }
  ]
}
```

---

### 6.5 创建导航点

```http
POST /api/pcd-maps/{mapId}/waypoints
```

请求：

```json
{
  "name": "巡检点1",
  "x": 2.35,
  "y": -1.20,
  "z": 0.0,
  "yaw": 0.0,
  "frameId": "map"
}
```

返回：

```json
{
  "id": "wp_001",
  "mapId": "1.pcd",
  "name": "巡检点1",
  "x": 2.35,
  "y": -1.20,
  "z": 0.0,
  "yaw": 0.0,
  "frameId": "map"
}
```

---

### 6.6 删除导航点

```http
DELETE /api/pcd-maps/{mapId}/waypoints/{waypointId}
```

返回：

```json
{
  "ok": true
}
```

---

## 7. PCD 解析设计

PCD 文件通常由 header 和 data 两部分组成。

典型 ASCII PCD：

```text
# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z intensity
SIZE 4 4 4 4
TYPE F F F F
COUNT 1 1 1 1
WIDTH 2350000
HEIGHT 1
VIEWPOINT 0 0 0 1 0 0 0
POINTS 2350000
DATA ascii
1.2 0.5 0.1 88
1.3 0.6 0.1 90
...
```

Demo 阶段优先支持：

```text
DATA ascii
```

如果同事的 PCD 是 binary，需要后端进一步支持：

```text
DATA binary
```

建议后端先做 header 解析，识别 `DATA` 类型：

```text
ascii：可以直接逐行解析；
binary：需要按 SIZE/TYPE/COUNT 解析二进制；
binary_compressed：Demo 阶段可以先提示暂不支持。
```

Demo 第一版可以明确：

```text
优先支持 ASCII PCD。
如果检测到 binary PCD，返回明确错误：
"当前 Demo 暂不支持 binary PCD，请先转换为 ascii 或扩展 parser。"
```

但从工程角度，如果同事使用 PCL/FAST-LIO/LIO-SAM，生成的 PCD 很可能是 binary。为了减少后续返工，建议让 Codex 至少把 `DATA binary` 的识别逻辑写好，解析逻辑可以作为第二阶段。

---

## 8. 点云坐标到 three.js 坐标转换

ROS/地图坐标通常理解为：

```text
map x：前后/东西方向
map y：左右/南北方向
map z：高度
```

three.js 默认：

```text
three x：水平右
three y：竖直上
three z：屏幕深度
```

为了让点云在 three.js 里正常显示，建议统一转换：

```ts
function mapToThree(x: number, y: number, z: number) {
  return {
    x: x,
    y: z,
    z: -y
  }
}

function threeToMap(x: number, y: number, z: number) {
  return {
    x: x,
    y: -z,
    z: y
  }
}
```

要求：

```text
1. 点云渲染使用这个转换；
2. 导航点在 3D 中显示也使用这个转换；
3. 机器人位姿后续接入也使用这个转换；
4. 不允许不同组件各写一套坐标换算。
```

---

## 9. 2D 俯视图设计

三维点云适合观察环境，但不适合精确标导航点。因此必须提供 2D 俯视图。

俯视图逻辑：

```text
点云 [x, y, z]
  ↓
忽略 z
  ↓
使用 x/y 投影到 Canvas
  ↓
显示为二维散点图
  ↓
用户在 Canvas 点击
  ↓
反算出 map x/y
  ↓
生成导航点
```

### 9.1 map 坐标转 Canvas 坐标

```ts
function mapToCanvas(
  x: number,
  y: number,
  bounds: Bounds,
  canvasWidth: number,
  canvasHeight: number
) {
  const padding = 30

  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = bounds.maxX - bounds.minX
  const rangeY = bounds.maxY - bounds.minY

  const scale = Math.min(
    usableWidth / rangeX,
    usableHeight / rangeY
  )

  const canvasX = padding + (x - bounds.minX) * scale
  const canvasY = canvasHeight - padding - (y - bounds.minY) * scale

  return { x: canvasX, y: canvasY }
}
```

### 9.2 Canvas 坐标转 map 坐标

```ts
function canvasToMap(
  canvasX: number,
  canvasY: number,
  bounds: Bounds,
  canvasWidth: number,
  canvasHeight: number
) {
  const padding = 30

  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = bounds.maxX - bounds.minX
  const rangeY = bounds.maxY - bounds.minY

  const scale = Math.min(
    usableWidth / rangeX,
    usableHeight / rangeY
  )

  const x = bounds.minX + (canvasX - padding) / scale
  const y = bounds.minY + (canvasHeight - padding - canvasY) / scale

  return { x, y }
}
```

### 9.3 俯视图显示内容

俯视图至少显示：

```text
1. 点云 XY 投影；
2. 当前鼠标所在 map x/y；
3. 已标记导航点；
4. 当前选中的导航点；
5. 坐标轴方向；
6. 点云 bounds 外框。
```

---

## 10. 导航点数据设计

导航点是后续导航巡逻的核心数据。即使 Demo 不执行真实导航，也必须按照真实系统格式设计。

推荐数据结构：

```json
{
  "id": "wp_001",
  "mapId": "1.pcd",
  "name": "巡检点1",
  "x": 2.35,
  "y": -1.20,
  "z": 0.0,
  "yaw": 0.0,
  "frameId": "map",
  "createdAt": "2026-04-27 15:20:00",
  "updatedAt": "2026-04-27 15:20:00"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 导航点唯一 ID |
| `mapId` | 所属 PCD 地图 |
| `name` | 点位名称 |
| `x` | map 坐标系 x |
| `y` | map 坐标系 y |
| `z` | map 坐标系 z，Demo 阶段可为 0 |
| `yaw` | 机器人到达该点后的朝向 |
| `frameId` | 固定为 `map` |
| `createdAt` | 创建时间 |
| `updatedAt` | 更新时间 |

---

## 11. 后续接真实 ROS2 的扩展点

当前 Demo 不接 ROS2，但架构必须为真实接入预留。

后续模块：

```text
backend/
├── services/
│   ├── ros_bridge.py
│   ├── nav_service.py
│   ├── localization_service.py
│   ├── mapping_service.py
│   └── patrol_service.py
```

### 11.1 设置位姿

前端导航点或位姿数据：

```json
{
  "x": 2.35,
  "y": -1.20,
  "yaw": 1.57,
  "frameId": "map"
}
```

后端转换为 ROS2 位姿消息：

```text
geometry_msgs/PoseWithCovarianceStamped
```

发布到：

```text
/initialpose
```

---

### 11.2 单点导航

前端选择导航点：

```text
POST /api/nav/go_to
```

后端调用导航 action：

```text
NavigateToPose
```

目标位姿：

```text
frame_id = map
position.x = waypoint.x
position.y = waypoint.y
orientation = yaw 转四元数
```

yaw 转四元数：

```text
qz = sin(yaw / 2)
qw = cos(yaw / 2)
qx = 0
qy = 0
```

---

### 11.3 巡检任务

巡检任务本质：

```text
多个导航点按顺序执行
```

后端可选实现方式：

```text
方式 1：自己逐个调用 NavigateToPose
方式 2：使用 FollowWaypoints
方式 3：使用 NavigateThroughPoses
```

第一版建议：

```text
后端自己逐点调度 NavigateToPose
```

优点：

```text
1. 状态更好控制；
2. 到点后可以加停留、拍照、语音；
3. 出错后可以暂停/恢复；
4. 更适合你现在的业务。
```

---

## 12. 风险点和注意事项

### 12.1 PCD 坐标不等于导航 map 坐标

最大风险是：

```text
PCD 显示出来的位置和导航系统实际使用的 map 坐标不一致。
```

后果：

```text
前端标 A 点，机器人去 B 点。
```

必须向同事确认：

```text
1.pcd 内的点云坐标是否就是导航 map 坐标？
导航目标是否直接使用 map x/y/yaw？
```

---

### 12.2 PCD 文件过大

风险：

```text
后端解析慢，前端加载卡。
```

解决：

```text
1. 限制 maxPoints；
2. metadata 和 preview 结果缓存；
3. 后续改二进制传输；
4. 大文件分块加载。
```

---

### 12.3 PCD 格式不兼容

风险：

```text
同事给的是 binary 或 binary_compressed。
```

解决：

```text
1. 先解析 header 判断 DATA 类型；
2. ascii 立即支持；
3. binary 第二阶段支持；
4. binary_compressed 暂时提示转换。
```

---

### 12.4 三维点云不能直接等价于可导航区域

点云只是环境几何信息，不等于可通行区域。

Demo 标点时可能点到：

```text
墙上
障碍物内
高处
不可通行区域
```

第一版不解决这个问题，只验证坐标和交互。

后续真实导航时，需要：

```text
1. 可通行区域判断；
2. 局部代价地图；
3. 避障；
4. 导航失败反馈。
```

---

## 13. 阶段性目标

### 第一阶段：PCD 可访问

```text
1. 后端能扫描目录；
2. 前端能看到 1.pcd；
3. 能读取 metadata。
```

### 第二阶段：PCD 可显示

```text
1. 后端能降采样；
2. 前端 three.js 能显示；
3. 前端 2D 俯视图能显示。
```

### 第三阶段：PCD 可标点

```text
1. 鼠标移动显示 map 坐标；
2. 点击俯视图创建导航点；
3. 导航点保存到后端；
4. 刷新页面后导航点不丢。
```

### 第四阶段：接真实导航

```text
1. 设置位姿；
2. 单点导航；
3. 巡检任务；
4. 任务状态推送。
```

---

## 14. 当前推荐结论

当前应该优先实现：

```text
PCD 点云地图选择与预览 Demo
```

而不是优先实现完整巡检任务。

原因：

```text
如果 PCD 地图读取、显示、坐标标点没有打通，
后续所有导航、巡检、重定位都会建立在错误基础上。
```

第一版验收成功的标准：

```text
1. 页面能看到同事生成的 1.pcd；
2. 能加载并显示点云；
3. 能在俯视图上点击生成 map 坐标；
4. 导航点保存后坐标为 frame_id = map；
5. 刷新后导航点仍然存在。
```
