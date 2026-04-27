# BotDog-jetson 导航巡逻 PCD 点云接入架构说明

## 1. 文档定位

本文档是基于 `https://github.com/Timekeeperxxx/BotDog-jetson` 当前项目结构重新整理的导航巡逻 PCD 点云接入方案。

它不是一个独立 Demo 项目说明，也不是通用前后端方案，而是说明：

```text
如何在现有 BotDog-jetson 项目内
增加一个 PCD 三维点云地图选择、预览、标点 Demo
并为后续导航巡逻、设置位姿、单点导航、巡检任务预留接口。
```

当前第一阶段目标不是直接跑真实导航，而是验证同事建好的 `.pcd` 三维点云地图能否被你的系统正确读取、显示和标点。

---

## 2. 当前仓库结构对齐

根据当前仓库结构，BotDog-jetson 不是前后端分离部署的空项目，而是已经有一套完整的机器狗控制系统。

当前仓库核心结构可以理解为：

```text
BotDog-jetson/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── services_tasks.py
│   ├── services_logs.py
│   ├── services_config.py
│   ├── services_video_sources.py
│   ├── control_service.py
│   ├── robot_adapter.py
│   ├── guard_mission_service.py
│   ├── ws_broadcaster.py
│   └── ws_event_broadcaster.py
│
├── frontend/
│   └── src/
│       ├── IndustrialConsoleComplete.tsx
│       ├── main.tsx
│       ├── config/
│       │   └── api.ts
│       ├── components/
│       ├── hooks/
│       ├── pages/
│       ├── stores/
│       ├── types/
│       └── utils/
│
├── docs/
├── scripts/
├── config/
└── data/
```

当前项目已有以下特点：

```text
1. 后端入口是 backend/main.py。
2. 后端配置集中在 backend/config.py 和 backend/.env.example。
3. 后端接口风格是 /api/v1/...。
4. 后端业务逻辑倾向拆到 services_xxx.py。
5. 后端 DTO 类型放在 backend/schemas.py。
6. 前端 API 地址统一通过 frontend/src/config/api.ts 的 getApiUrl() 生成。
7. 前端主界面由 frontend/src/IndustrialConsoleComplete.tsx 承载。
8. 当前前端是单页控制台，不是 React Router 多页面结构。
9. 当前前端已有左侧 tab：控制台、驱离系统、档案库、后台管理、设置、告警。
10. 当前项目支持后端托管 frontend/dist，实现 :8000 单端口访问。
```

所以本功能不应该写成：

```text
新建一个完全独立 nav_patrol_demo 项目
```

而应该写成：

```text
在 backend 下新增 PCD 点云服务和接口
在 frontend/src 下新增点云相关组件
在 IndustrialConsoleComplete.tsx 左侧 tab 中新增“导航巡逻”入口
```

---

## 3. 当前业务输入条件

你已经确认的地图交接条件如下：

| 项目 | 结论 |
|---|---|
| 地图文件格式 | `.pcd` |
| 地图类型 | 三维点云 |
| 文件交接方式 | 不上传、不拷贝，后端直接访问同事生成地图所在目录 |
| 地图选择方式 | 前端临时从指定目录中选择点云图 |
| 坐标系 | `map` |
| 是否考虑二维 map.yaml / pgm | 暂不考虑 |
| 第一阶段是否真实导航 | 不真实导航，只做点云读取、显示、标点验证 |

因此第一阶段功能范围应定义为：

```text
PCD 文件目录扫描
  ↓
选择某个 .pcd
  ↓
后端解析 metadata
  ↓
后端降采样 preview 点云
  ↓
前端 3D 点云显示
  ↓
前端 2D 俯视图显示
  ↓
在 map 坐标系下保存导航点
```

---

## 4. 为什么不先做完整巡检任务

当前最主要风险不是按钮能不能点，而是：

```text
前端显示出来的点云坐标
是否就是机器人导航系统使用的 map 坐标。
```

如果这个没有验证，后续功能都会偏：

```text
1. 导航点会偏；
2. 设置位姿会偏；
3. 单点导航目标会偏；
4. 巡检路线会偏；
5. 重定位结果会偏；
6. 机器人实际去的位置可能不是前端标的位置。
```

因此当前阶段只做：

```text
PCD 地图读取 + 点云显示 + map 坐标标点
```

暂不做：

```text
真实 ROS2 导航
真实建图控制
真实重定位
完整巡检任务调度
点云在线流式更新
```

---

## 5. 总体架构

### 5.1 当前阶段架构

```text
┌───────────────────────────────────────────────────────┐
│                    frontend/src                       │
│                                                       │
│  IndustrialConsoleComplete.tsx                        │
│  └── 新增 activeTab = "nav"                            │
│      └── PcdMapDemoPage                               │
│          ├── PcdFileListPanel                         │
│          ├── PointCloud3DViewer                       │
│          ├── PointCloudTopDownCanvas                  │
│          ├── PcdMetadataPanel                         │
│          └── NavWaypointPanel                         │
│                                                       │
│  api/pcdMapApi.ts                                     │
│  types/pcdMap.ts                                      │
│  utils/pointCloudTransform.ts                         │
│  utils/topDownCoordinate.ts                           │
└─────────────────────────────┬─────────────────────────┘
                              │ HTTP /api/v1/nav/pcd-maps/...
                              ↓
┌───────────────────────────────────────────────────────┐
│                       backend                         │
│                                                       │
│  main.py                                              │
│  ├── register_routes(app)                             │
│  └── 挂载 PCD 地图相关 API                             │
│                                                       │
│  schemas.py                                           │
│  └── PcdMapDTO / PcdMetadataDTO / NavWaypointDTO       │
│                                                       │
│  services_pcd_maps.py                                 │
│  ├── scan_pcd_maps()                                  │
│  ├── parse_pcd_header()                               │
│  ├── get_pcd_metadata()                               │
│  └── get_pcd_preview()                                │
│                                                       │
│  services_nav_waypoints.py                            │
│  ├── list_waypoints()                                 │
│  ├── create_waypoint()                                │
│  └── delete_waypoint()                                │
│                                                       │
│  config.py                                            │
│  └── PCD_MAP_ROOT / NAV_WAYPOINT_STORE_DIR             │
└─────────────────────────────┬─────────────────────────┘
                              │ 文件系统访问
                              ↓
┌───────────────────────────────────────────────────────┐
│                  PCD 点云地图目录                      │
│                                                       │
│  /home/jetson/maps/                                   │
│  ├── 1.pcd                                            │
│  ├── test_area.pcd                                    │
│  └── warehouse.pcd                                    │
│                                                       │
│  data/nav_waypoints/                                  │
│  ├── 1.pcd.json                                       │
│  └── warehouse.pcd.json                               │
└───────────────────────────────────────────────────────┘
```

---

### 5.2 后续真实导航阶段架构

当前 Demo 跑通后，才进入真实导航阶段：

```text
前端导航巡逻页面
  ↓
/api/v1/nav/waypoints
/api/v1/nav/go-to
/api/v1/nav/patrol/start
/api/v1/nav/localization/set-pose
  ↓
后端导航网关
  ↓
ROS2 / Nav2 / SuperLIO / 定位节点
  ↓
Unitree B2 / Jetson / 雷达 / 点云地图
```

后续要新增的服务可能是：

```text
backend/
├── services_nav_ros.py
├── services_nav_patrol.py
├── services_localization.py
└── services_mapping.py
```

但第一阶段不要写这些真实控制逻辑。

---

## 6. 后端接入设计

### 6.1 需要修改的现有文件

#### backend/config.py

新增配置项：

```python
PCD_MAP_ROOT: str = "./data/pcd_maps"
PCD_FRAME_ID: str = "map"
PCD_PREVIEW_DEFAULT_POINTS: int = 100000
PCD_PREVIEW_MAX_POINTS: int = 200000
NAV_WAYPOINT_STORE_DIR: str = "./data/nav_waypoints"
```

实际部署到 Jetson 或机器人主机时，建议改成：

```env
PCD_MAP_ROOT=/home/jetson/maps
PCD_FRAME_ID=map
PCD_PREVIEW_DEFAULT_POINTS=100000
PCD_PREVIEW_MAX_POINTS=200000
NAV_WAYPOINT_STORE_DIR=./data/nav_waypoints
```

---

#### backend/.env.example

在配置模板中追加：

```env
# ==================== 导航巡逻 / PCD 点云地图 Demo ====================
# 同事建好的 PCD 点云地图所在目录。Demo 阶段不上传、不拷贝，后端直接扫描该目录。
PCD_MAP_ROOT=/home/jetson/maps

# 当前点云与导航目标默认使用的坐标系
PCD_FRAME_ID=map

# 点云预览默认返回点数
PCD_PREVIEW_DEFAULT_POINTS=100000

# 点云预览最大允许返回点数，防止浏览器卡死
PCD_PREVIEW_MAX_POINTS=200000

# Demo 阶段导航点 JSON 存储目录
NAV_WAYPOINT_STORE_DIR=./data/nav_waypoints
```

---

#### backend/schemas.py

新增 Pydantic DTO：

```python
class PcdBoundsDTO(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float


class PcdMapItemDTO(BaseModel):
    id: str
    name: str
    size_bytes: int
    modified_at: str


class PcdMapListResponse(BaseModel):
    root: str
    items: list[PcdMapItemDTO]


class PcdMetadataDTO(BaseModel):
    map_id: str
    name: str
    frame_id: str = "map"
    type: str = "pcd"
    point_count: int
    fields: list[str]
    data_type: str
    bounds: PcdBoundsDTO | None = None


class PcdPreviewResponse(BaseModel):
    map_id: str
    frame_id: str = "map"
    points: list[list[float]]
    bounds: PcdBoundsDTO


class NavWaypointCreateRequest(BaseModel):
    name: str
    x: float
    y: float
    z: float = 0.0
    yaw: float = 0.0
    frame_id: str = "map"


class NavWaypointDTO(BaseModel):
    id: str
    map_id: str
    name: str
    x: float
    y: float
    z: float
    yaw: float
    frame_id: str
    created_at: str
    updated_at: str


class NavWaypointListResponse(BaseModel):
    items: list[NavWaypointDTO]
```

注意命名风格：

```text
后端 Python 内部建议 snake_case；
前端 TypeScript 可以转换成 camelCase，或者保持 snake_case。
```

为了减少转换成本，Demo 阶段前端可以直接使用后端 snake_case。

---

#### backend/main.py

当前 `main.py` 已经很长，但它本身负责 FastAPI 应用装配和路由注册。第一版可以在 `register_routes(app)` 中增加导航 PCD Demo 路由。

推荐新增一个函数：

```python
def register_pcd_map_routes(app: FastAPI) -> None:
    ...
```

然后在 `register_routes(app)` 内调用：

```python
register_pcd_map_routes(app)
```

这样比直接把所有 PCD 路由塞进 `register_routes()` 内部更清晰。

更推荐的工程化方式是新增：

```text
backend/routes_pcd_maps.py
```

里面定义：

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/nav", tags=["nav-pcd-maps"])
```

然后在 `main.py` 中：

```python
from .routes_pcd_maps import router as pcd_maps_router
app.include_router(pcd_maps_router)
```

但是为了贴合当前仓库现状，Codex 可以先采用“新增 services + main.py 注册路由”的方式，后面再拆 router。

---

### 6.2 需要新增的后端文件

#### backend/services_pcd_maps.py

职责：

```text
1. 扫描 PCD_MAP_ROOT 下的 .pcd 文件；
2. 安全解析 map_id；
3. 读取 PCD header；
4. 判断 DATA 类型；
5. 解析 ascii PCD 点数据；
6. 计算 bounds；
7. 降采样生成 preview；
8. 返回给 API 层。
```

关键函数：

```python
def list_pcd_maps() -> dict:
    ...

def get_pcd_metadata(map_id: str) -> dict:
    ...

def get_pcd_preview(map_id: str, max_points: int | None = None) -> dict:
    ...

def resolve_pcd_path(map_id: str) -> Path:
    ...

def parse_pcd_header(path: Path) -> tuple[dict, int]:
    ...
```

---

#### backend/services_nav_waypoints.py

职责：

```text
1. 按 map_id 保存导航点；
2. 从 JSON 文件读取导航点；
3. 删除导航点；
4. 保证 frame_id = map；
5. Demo 阶段不使用数据库，避免影响现有 models.py 和迁移。
```

存储目录：

```text
data/nav_waypoints/
```

存储文件：

```text
data/nav_waypoints/1.pcd.json
```

文件内容：

```json
{
  "map_id": "1.pcd",
  "items": [
    {
      "id": "wp_001",
      "map_id": "1.pcd",
      "name": "巡检点1",
      "x": 2.35,
      "y": -1.20,
      "z": 0.0,
      "yaw": 0.0,
      "frame_id": "map",
      "created_at": "2026-04-27T15:20:00.000Z",
      "updated_at": "2026-04-27T15:20:00.000Z"
    }
  ]
}
```

---

## 7. 后端 API 设计

所有接口保持现有项目 `/api/v1` 风格。

### 7.1 PCD 文件列表

```http
GET /api/v1/nav/pcd-maps
```

返回：

```json
{
  "root": "/home/jetson/maps",
  "items": [
    {
      "id": "1.pcd",
      "name": "1.pcd",
      "size_bytes": 125829120,
      "modified_at": "2026-04-27T15:20:00.000Z"
    }
  ]
}
```

---

### 7.2 PCD metadata

```http
GET /api/v1/nav/pcd-maps/{map_id}/metadata
```

返回：

```json
{
  "map_id": "1.pcd",
  "name": "1.pcd",
  "frame_id": "map",
  "type": "pcd",
  "point_count": 2350000,
  "fields": ["x", "y", "z", "intensity"],
  "data_type": "ascii",
  "bounds": {
    "min_x": -12.5,
    "max_x": 18.2,
    "min_y": -8.4,
    "max_y": 10.7,
    "min_z": -1.2,
    "max_z": 3.8
  }
}
```

---

### 7.3 PCD preview

```http
GET /api/v1/nav/pcd-maps/{map_id}/preview?max_points=100000
```

返回：

```json
{
  "map_id": "1.pcd",
  "frame_id": "map",
  "points": [
    [1.2, 0.5, 0.1],
    [1.3, 0.6, 0.1],
    [1.4, 0.7, 0.1]
  ],
  "bounds": {
    "min_x": -12.5,
    "max_x": 18.2,
    "min_y": -8.4,
    "max_y": 10.7,
    "min_z": -1.2,
    "max_z": 3.8
  }
}
```

Demo 阶段可以使用 JSON 返回。正式版如果点云很大，应改为：

```text
Float32Array 二进制
分块加载
WebSocket 流式推送
LOD 多层级点云
```

---

### 7.4 导航点列表

```http
GET /api/v1/nav/pcd-maps/{map_id}/waypoints
```

返回：

```json
{
  "items": [
    {
      "id": "wp_001",
      "map_id": "1.pcd",
      "name": "巡检点1",
      "x": 2.35,
      "y": -1.2,
      "z": 0.0,
      "yaw": 0.0,
      "frame_id": "map",
      "created_at": "2026-04-27T15:20:00.000Z",
      "updated_at": "2026-04-27T15:20:00.000Z"
    }
  ]
}
```

---

### 7.5 创建导航点

```http
POST /api/v1/nav/pcd-maps/{map_id}/waypoints
```

请求：

```json
{
  "name": "巡检点1",
  "x": 2.35,
  "y": -1.2,
  "z": 0.0,
  "yaw": 0.0,
  "frame_id": "map"
}
```

---

### 7.6 删除导航点

```http
DELETE /api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}
```

返回：

```json
{
  "success": true
}
```

---

## 8. PCD 解析策略

### 8.1 第一版支持范围

第一版优先支持：

```text
DATA ascii
FIELDS 中必须包含 x y z
```

如果检测到：

```text
DATA binary
DATA binary_compressed
```

可以先返回明确错误：

```json
{
  "detail": "当前 Demo 暂不支持 binary_compressed PCD，请先转换为 ascii，或扩展 binary parser"
}
```

但实际工程上，同事生成的 PCD 很可能是 binary。因此建议 Codex 在第一版至少做到：

```text
1. header 能识别 ascii / binary / binary_compressed；
2. ascii 完整支持；
3. binary 返回明确错误；
4. binary_compressed 返回明确错误；
5. 不允许把 binary 文件误当 ascii 解析。
```

第二版再支持 binary PCD。

---

### 8.2 PCD header 解析

PCD header 以 `DATA` 行结束，例如：

```text
VERSION .7
FIELDS x y z intensity
SIZE 4 4 4 4
TYPE F F F F
COUNT 1 1 1 1
WIDTH 2350000
HEIGHT 1
POINTS 2350000
DATA ascii
```

需要解析字段：

```text
FIELDS
SIZE
TYPE
COUNT
WIDTH
HEIGHT
POINTS
DATA
```

其中第一阶段最关键：

```text
FIELDS: 找 x/y/z 下标
POINTS: 点数量
DATA: 判断 ascii/binary
```

---

### 8.3 安全路径策略

不能允许前端传完整路径：

```json
{
  "path": "/home/jetson/maps/1.pcd"
}
```

只能允许：

```text
GET /api/v1/nav/pcd-maps/1.pcd/preview
```

后端自己拼接：

```text
settings.PCD_MAP_ROOT / map_id
```

并校验：

```text
1. map_id 不能包含 /
2. map_id 不能包含 ..
3. map_id 必须以 .pcd 结尾
4. resolve 后必须位于 PCD_MAP_ROOT 内部
```

---

## 9. 前端接入设计

### 9.1 不建议新建独立 Vite 项目

当前前端已经有：

```text
frontend/src/main.tsx
frontend/src/IndustrialConsoleComplete.tsx
frontend/src/config/api.ts
frontend/src/components/
frontend/src/pages/
frontend/src/types/
frontend/src/utils/
frontend/src/stores/
```

所以应该在现有 `frontend/src` 内新增：

```text
frontend/src/pages/PcdMapDemoPage.tsx

frontend/src/components/pcd/
├── PcdFileListPanel.tsx
├── PcdMetadataPanel.tsx
├── PointCloud3DViewer.tsx
├── PointCloudTopDownCanvas.tsx
└── NavWaypointPanel.tsx

frontend/src/api/pcdMapApi.ts

frontend/src/types/pcdMap.ts

frontend/src/utils/pointCloudTransform.ts
frontend/src/utils/topDownCoordinate.ts
```

如果当前没有 `frontend/src/api/`，可以新建。

---

### 9.2 入口方式

当前 `main.tsx` 直接渲染 `IndustrialConsoleComplete`，没有 React Router。

所以第一版不要引入路由系统，直接在 `IndustrialConsoleComplete.tsx` 的 tab 里新增一个：

```ts
type ActiveTab = 'console' | 'history' | 'simulate' | 'admin' | 'guard' | 'nav'
```

左侧导航新增按钮：

```tsx
<SidebarBtn
  icon={<Map />}
  active={activeTab === 'nav'}
  onClick={() => setActiveTab('nav')}
  label="导航巡逻"
/>
```

主内容区新增：

```tsx
{activeTab === 'nav' ? (
  <PcdMapDemoPage addLog={addLog} />
) : activeTab === 'console' ? (
  ...
)}
```

因为现有日志系统 `addLog()` 已经在 `IndustrialConsoleComplete.tsx` 内部使用，所以 `PcdMapDemoPage` 可以接收：

```ts
type Props = {
  addLog?: (message: string, level?: string, module?: string) => void
}
```

如果不想传入，也可以页面内部维护自己的日志。

---

### 9.3 API 封装

当前项目已有：

```ts
frontend/src/config/api.ts
```

其中有：

```ts
getApiUrl(path: string): string
```

所以新增 `frontend/src/api/pcdMapApi.ts` 时必须复用：

```ts
import { getApiUrl } from '../config/api'
```

不要在组件里写死：

```text
http://localhost:8000
192.168.144.104:8000
```

示例：

```ts
export async function listPcdMaps() {
  const res = await fetch(getApiUrl('/api/v1/nav/pcd-maps'))
  if (!res.ok) throw new Error(`获取 PCD 列表失败: HTTP ${res.status}`)
  return res.json()
}
```

---

### 9.4 three.js 依赖

当前 `frontend/package.json` 没有 `three`。

需要新增：

```bash
cd frontend
npm install three
```

`three` 自带 TypeScript 类型，通常不需要额外安装 `@types/three`。

如果 Codex 写了：

```ts
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
```

需要注意 Vite ESM 路径。

---

## 10. 前端核心坐标转换

### 10.1 map 坐标到 three.js 坐标

ROS / PCD map 坐标按：

```text
x: 地图 x
y: 地图 y
z: 高度
```

three.js 默认：

```text
x: 水平
y: 竖直
z: 深度
```

统一转换：

```ts
export function mapToThree(x: number, y: number, z: number) {
  return {
    x,
    y: z,
    z: -y,
  }
}
```

反向：

```ts
export function threeToMap(x: number, y: number, z: number) {
  return {
    x,
    y: -z,
    z: y,
  }
}
```

所有点云、导航点、后续机器人模型都必须用同一套转换函数。

---

### 10.2 map 坐标到 2D Canvas 坐标

俯视图用 x/y 投影，忽略 z。

```ts
export function mapToCanvas(
  x: number,
  y: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = bounds.max_x - bounds.min_x
  const rangeY = bounds.max_y - bounds.min_y

  const scale = Math.min(usableWidth / rangeX, usableHeight / rangeY)

  return {
    x: padding + (x - bounds.min_x) * scale,
    y: canvasHeight - padding - (y - bounds.min_y) * scale,
  }
}
```

反向：

```ts
export function canvasToMap(
  canvasX: number,
  canvasY: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = bounds.max_x - bounds.min_x
  const rangeY = bounds.max_y - bounds.min_y

  const scale = Math.min(usableWidth / rangeX, usableHeight / rangeY)

  return {
    x: bounds.min_x + (canvasX - padding) / scale,
    y: bounds.min_y + (canvasHeight - padding - canvasY) / scale,
  }
}
```

---

## 11. 前端页面布局

`PcdMapDemoPage` 建议布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ 导航巡逻 / PCD 点云地图 Demo                                  │
├───────────────┬──────────────────────────────┬───────────────┤
│ 左侧 PCD 列表  │ 中间 3D 点云视图               │ 右侧 metadata  │
│               │                              │               │
│ - 刷新        │ three.js PointCloud           │ - 文件名       │
│ - 1.pcd       │                              │ - point_count  │
│ - test.pcd    │                              │ - bounds       │
│               ├──────────────────────────────┤ - frame_id     │
│               │ 2D 俯视图 Canvas              │               │
│               │ - XY 投影                     │ 导航点列表      │
│               │ - 鼠标 map 坐标               │ - 添加点       │
│               │ - 点击添加导航点              │ - 删除点       │
├───────────────┴──────────────────────────────┴───────────────┤
│ 操作日志                                                       │
└──────────────────────────────────────────────────────────────┘
```

第一版页面重点是“能不能测通”，不是美观。

---

## 12. 后续真实导航接口预留

Demo 通过后，再加以下接口。第一版文档只预留，不让 Codex 立即实现真实控制。

### 12.1 设置位姿

```http
POST /api/v1/nav/localization/set-pose
```

请求：

```json
{
  "x": 2.35,
  "y": -1.20,
  "yaw": 1.57,
  "frame_id": "map"
}
```

后续接 ROS2 时发布：

```text
/initialpose
```

---

### 12.2 单点导航

```http
POST /api/v1/nav/go-to
```

请求：

```json
{
  "waypoint_id": "wp_001"
}
```

或：

```json
{
  "x": 2.35,
  "y": -1.20,
  "yaw": 0.0,
  "frame_id": "map"
}
```

后续接 ROS2 / Nav2：

```text
NavigateToPose
```

---

### 12.3 巡检任务

```http
POST /api/v1/nav/patrol/tasks
POST /api/v1/nav/patrol/tasks/{task_id}/start
POST /api/v1/nav/patrol/stop
```

巡检任务结构：

```json
{
  "name": "仓库巡检任务",
  "loop": false,
  "waypoints": [
    {
      "waypoint_id": "wp_001",
      "stay_seconds": 5,
      "action": "none"
    }
  ]
}
```

第一版不要接。因为当前最重要的是地图坐标闭环。

---

## 13. 与现有功能的关系

### 13.1 不影响现有遥控

新增 PCD Demo 不应该修改：

```text
control_service.py
robot_adapter.py
control_arbiter.py
useBotDogWebSocket.ts
ControlPad.tsx
```

避免影响现有 WASD / 控制面板。

---

### 13.2 不影响自动驱离

新增 PCD Demo 不应该修改：

```text
guard_mission_service.py
guard_mission_types.py
GuardControlCenter.tsx
ZoneDrawer.tsx
yellow_zone_detector.py
```

导航巡逻是新模块，不应该和当前黄色区域驱离逻辑混在一起。

---

### 13.3 不影响 AI 识别和证据库

新增 PCD Demo 不应该修改：

```text
workers_ai.py
services_evidence.py
alert_service.py
```

---

### 13.4 可复用现有日志风格

可以复用现有：

```text
services_logs.py
write_log()
```

但 Demo 阶段也可以先只在前端显示本地日志。

如果需要后端落盘日志，可以在 PCD API 中写：

```python
await write_log(db, level="INFO", module="NAV_PCD", message="...")
```

但这会让 PCD API 依赖数据库 session。第一版为了简单，可以暂不写后端日志。

---

## 14. 验收标准

第一版完成后必须满足：

```text
1. backend/.env 可以配置 PCD_MAP_ROOT。
2. /api/v1/nav/pcd-maps 能列出 1.pcd。
3. /api/v1/nav/pcd-maps/1.pcd/metadata 能返回 point_count、fields、data_type、bounds。
4. /api/v1/nav/pcd-maps/1.pcd/preview 能返回降采样点云。
5. 前端左侧能看到 1.pcd。
6. 点击 1.pcd 后能显示 3D 点云。
7. 2D 俯视图能显示 XY 投影。
8. 鼠标移动能显示 map x/y。
9. 点击俯视图能新增导航点。
10. 导航点保存为 frame_id=map。
11. 刷新页面后重新选择 1.pcd，导航点仍在。
12. 没有破坏现有控制台、驱离系统、档案库、后台管理功能。
```

---

## 15. 当前结论

本功能在 BotDog-jetson 中的正确接入方式是：

```text
后端：
  在现有 FastAPI 后端内新增 PCD 地图服务和 /api/v1/nav/... 接口。

前端：
  在现有 IndustrialConsoleComplete.tsx 控制台中新增“导航巡逻”tab，
  使用 three.js + Canvas 实现点云预览与标点。

数据：
  PCD 文件不上传、不拷贝，后端直接扫描 PCD_MAP_ROOT。
  导航点 Demo 阶段用 JSON 存 data/nav_waypoints/。
```

第一阶段只验证地图坐标闭环：

```text
PCD 文件可读
  ↓
点云可显示
  ↓
map 坐标可标点
  ↓
导航点可持久化
```

之后再进入真实 ROS2 导航、重定位、巡检任务。
