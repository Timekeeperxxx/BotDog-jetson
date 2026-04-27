# 导航巡逻 PCD 点云 Demo 开发实现路径文档

## 1. Demo 目标

本文档用于指导 Codex 或开发人员实现第一版“PCD 点云地图选择与预览 Demo”。

当前重点不是完整导航巡逻，而是先验证：

```text
同事建好的 .pcd 点云地图
  ↓
你的后端能从指定目录读取
  ↓
后端能解析和降采样
  ↓
前端能显示三维点云
  ↓
前端能在 map 坐标系下标导航点
  ↓
导航点能保存
```

第一版 Demo 不接真实 ROS2，不执行真实导航，不启动建图，只做地图交接和坐标验证。

---

## 2. 当前输入条件

```text
1. 地图文件：1.pcd
2. 地图类型：三维点云
3. 文件来源：后端直接访问同事生成的文件路径
4. 不考虑二维 map.yaml / pgm / resolution / origin
5. 不上传、不拷贝地图
6. 前端临时从文件夹中选择点云图
7. 坐标系：map
```

因此 Demo 只考虑：

```text
PCD_MAP_ROOT 下的 .pcd 文件
```

---

## 3. 最终要实现的功能清单

### 3.1 后端功能

```text
1. 配置 PCD_MAP_ROOT
2. 扫描 PCD_MAP_ROOT 下所有 .pcd 文件
3. 提供 PCD 文件列表接口
4. 解析 PCD header
5. 返回 PCD metadata
6. 读取 PCD 点云数据
7. 计算 bounds
8. 按 maxPoints 降采样
9. 提供点云 preview 接口
10. 保存导航点
11. 获取导航点
12. 删除导航点
```

### 3.2 前端功能

```text
1. 显示 PCD 文件列表
2. 点击选择某个 .pcd
3. 加载 metadata
4. 加载 preview 点云
5. three.js 显示三维点云
6. Canvas 显示 2D 俯视投影
7. 鼠标移动时显示 map x/y
8. 点击俯视图添加导航点
9. 在 2D 和 3D 中显示导航点
10. 删除导航点
11. 显示操作日志
```

---

## 4. 推荐开发顺序

请严格按照下面顺序开发，不要一开始就做完整巡检。

```text
第 1 步：后端 PCD 文件列表
第 2 步：后端 PCD header 解析
第 3 步：后端 PCD preview 降采样
第 4 步：前端 PCD 文件列表页面
第 5 步：前端 three.js 点云显示
第 6 步：前端 2D 俯视图
第 7 步：前端添加导航点
第 8 步：后端保存导航点
第 9 步：页面刷新后恢复导航点
第 10 步：验收和调试
```

---

# 第一阶段：后端基础结构

## 5. 后端目录结构

在现有后端中增加以下结构。

如果当前是 FastAPI 项目，建议：

```text
backend/
├── config.py
├── routers/
│   └── pcd_maps.py
├── services/
│   ├── pcd_map_service.py
│   ├── pcd_parser.py
│   └── waypoint_store.py
└── data/
    └── waypoints/
```

如果当前项目已有类似目录，就按现有风格合并。

---

## 6. 配置 PCD_MAP_ROOT

增加配置项：

```bash
PCD_MAP_ROOT=/home/jetson/maps
```

开发环境可以先设置为：

```bash
PCD_MAP_ROOT=./mock_maps
```

要求：

```text
1. 后端启动时读取 PCD_MAP_ROOT；
2. 如果目录不存在，可以自动创建或给出明确错误；
3. 所有 PCD 文件扫描都只能发生在这个目录内；
4. 禁止前端传任意绝对路径。
```

伪代码：

```python
import os
from pathlib import Path

PCD_MAP_ROOT = Path(os.getenv("PCD_MAP_ROOT", "./mock_maps")).resolve()

def ensure_root_exists():
    PCD_MAP_ROOT.mkdir(parents=True, exist_ok=True)
```

---

## 7. mapId 安全处理

mapId 第一版可以直接用文件名，例如：

```text
1.pcd
```

但是必须做安全检查。

要求：

```text
1. mapId 不能包含 /
2. mapId 不能包含 ..
3. mapId 必须以 .pcd 结尾
4. 拼接后的路径必须仍在 PCD_MAP_ROOT 下
```

伪代码：

```python
from pathlib import Path

def resolve_pcd_path(map_id: str) -> Path:
    if "/" in map_id or "\\" in map_id or ".." in map_id:
        raise ValueError("invalid mapId")

    if not map_id.lower().endswith(".pcd"):
        raise ValueError("only .pcd is allowed")

    path = (PCD_MAP_ROOT / map_id).resolve()

    if PCD_MAP_ROOT not in path.parents and path != PCD_MAP_ROOT:
        raise ValueError("path outside PCD_MAP_ROOT")

    if not path.exists():
        raise FileNotFoundError("pcd not found")

    return path
```

---

# 第二阶段：后端接口

## 8. 接口 1：获取 PCD 文件列表

实现：

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
      "sizeBytes": 123456789,
      "modifiedAt": "2026-04-27 15:20:00"
    }
  ]
}
```

实现逻辑：

```text
1. 扫描 PCD_MAP_ROOT；
2. 找到所有 .pcd 文件；
3. 读取文件大小；
4. 读取修改时间；
5. 按修改时间倒序返回；
6. 不递归子目录，第一版只扫一级目录。
```

伪代码：

```python
def list_pcd_maps():
    items = []

    for path in PCD_MAP_ROOT.iterdir():
        if not path.is_file():
            continue

        if path.suffix.lower() != ".pcd":
            continue

        stat = path.stat()

        items.append({
            "id": path.name,
            "name": path.name,
            "sizeBytes": stat.st_size,
            "modifiedAt": format_time(stat.st_mtime),
        })

    items.sort(key=lambda x: x["modifiedAt"], reverse=True)

    return {
        "root": str(PCD_MAP_ROOT),
        "items": items
    }
```

---

## 9. 接口 2：获取 PCD metadata

实现：

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

实现步骤：

```text
1. 根据 mapId 找到 PCD 文件；
2. 读取 PCD header；
3. 解析 FIELDS、SIZE、TYPE、COUNT、WIDTH、HEIGHT、POINTS、DATA；
4. 判断 dataType；
5. 扫描点数据，计算 bounds；
6. 返回 metadata。
```

### 9.1 PCD header 解析

PCD header 以 `DATA` 行结束。

伪代码：

```python
def read_pcd_header(path):
    header = {}
    header_lines = []
    data_start_offset = 0

    with open(path, "rb") as f:
        while True:
            line = f.readline()
            if not line:
                break

            decoded = line.decode("utf-8", errors="ignore").strip()
            header_lines.append(decoded)
            data_start_offset = f.tell()

            if decoded.startswith("DATA"):
                break

    for line in header_lines:
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        key = parts[0].upper()
        values = parts[1:]
        header[key] = values

    return header, data_start_offset
```

### 9.2 解析关键字段

```python
def parse_header_fields(header):
    fields = header.get("FIELDS", [])
    size = [int(x) for x in header.get("SIZE", [])]
    type_ = header.get("TYPE", [])
    count = [int(x) for x in header.get("COUNT", ["1"] * len(fields))]

    point_count = int(header.get("POINTS", [0])[0])
    data_type = header.get("DATA", ["unknown"])[0].lower()

    return {
        "fields": fields,
        "size": size,
        "type": type_,
        "count": count,
        "pointCount": point_count,
        "dataType": data_type,
    }
```

### 9.3 bounds 计算

第一版优先支持：

```text
DATA ascii
```

计算逻辑：

```text
1. 找到 x、y、z 在 fields 中的索引；
2. 从 DATA 后逐行读取；
3. 解析 x/y/z；
4. 更新 min/max；
5. 遇到非法行跳过；
6. 文件过大时可以抽样扫描，但第一版可全量扫描。
```

伪代码：

```python
def compute_ascii_bounds(path, header, data_start_offset):
    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    with open(path, "rb") as f:
        f.seek(data_start_offset)

        for raw in f:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) <= max(x_idx, y_idx, z_idx):
                continue

            try:
                x = float(parts[x_idx])
                y = float(parts[y_idx])
                z = float(parts[z_idx])
            except ValueError:
                continue

            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            min_z = min(min_z, z)
            max_z = max(max_z, z)

    return {
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "minZ": min_z,
        "maxZ": max_z,
    }
```

---

## 10. 接口 3：获取 PCD preview

实现：

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
    [1.3, 0.6, 0.1]
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

实现要求：

```text
1. maxPoints 默认 100000；
2. maxPoints 最大不超过 200000；
3. 如果原始点数少于 maxPoints，全部返回；
4. 如果原始点数大于 maxPoints，按固定步长采样；
5. 返回 points 只包含 x/y/z；
6. 同时返回 bounds。
```

采样逻辑：

```python
step = max(1, point_count // max_points)
```

读取时：

```text
第 0 个点保留；
第 step 个点保留；
第 2*step 个点保留；
直到达到 maxPoints。
```

伪代码：

```python
def read_ascii_preview(path, header, data_start_offset, max_points):
    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")
    point_count = header["pointCount"]

    step = max(1, point_count // max_points)

    points = []
    bounds = init_bounds()

    current_index = 0

    with open(path, "rb") as f:
        f.seek(data_start_offset)

        for raw in f:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) <= max(x_idx, y_idx, z_idx):
                continue

            try:
                x = float(parts[x_idx])
                y = float(parts[y_idx])
                z = float(parts[z_idx])
            except ValueError:
                continue

            update_bounds(bounds, x, y, z)

            if current_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

            current_index += 1

    return points, bounds
```

---

## 11. binary PCD 处理建议

同事给的 PCD 很可能是 binary。

第一版至少要做到：

```text
1. 能识别 DATA binary；
2. 不要错误按 ascii 解析；
3. 返回明确错误，或者实现 binary 解析。
```

推荐返回：

```json
{
  "ok": false,
  "message": "当前 Demo 暂不支持 binary PCD，请先转换为 ascii PCD 或扩展 binary parser。"
}
```

如果要支持 binary，需要根据 PCD header 的：

```text
FIELDS
SIZE
TYPE
COUNT
```

计算每个点的字节结构，然后用 Python `struct` 或 `numpy.fromfile` 解析。

推荐第二阶段再实现 binary 支持。

---

# 第三阶段：导航点存储

## 12. 导航点文件存储

Demo 阶段不用数据库，直接 JSON 文件存储。

目录：

```text
backend/data/waypoints/
```

每张地图一个文件：

```text
backend/data/waypoints/1.pcd.json
```

内容：

```json
{
  "mapId": "1.pcd",
  "items": [
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
  ]
}
```

---

## 13. 接口 4：获取导航点

```http
GET /api/pcd-maps/{mapId}/waypoints
```

返回：

```json
{
  "items": []
}
```

如果文件不存在，返回空数组。

---

## 14. 接口 5：创建导航点

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

后端处理：

```text
1. 校验 mapId 对应 PCD 存在；
2. 校验 name 非空；
3. 校验 x/y/z/yaw 是数字；
4. frameId 必须是 map；
5. 生成 waypoint id；
6. 写入 JSON 文件；
7. 返回完整 waypoint。
```

---

## 15. 接口 6：删除导航点

```http
DELETE /api/pcd-maps/{mapId}/waypoints/{waypointId}
```

处理：

```text
1. 读取该 mapId 的 waypoint 文件；
2. 删除对应 id；
3. 写回文件；
4. 返回 ok。
```

---

# 第四阶段：前端页面

## 16. 前端页面结构

新增页面：

```text
PcdMapDemoPage
```

推荐布局：

```text
┌────────────────────────────────────────────────────────────┐
│ 顶部：PCD 点云地图 Demo / 当前状态 / 加载状态               │
├───────────────┬──────────────────────────────┬─────────────┤
│ 左侧文件列表   │ 中间显示区                    │ 右侧信息面板 │
│               │ ┌──────────────────────────┐ │             │
│ 1.pcd          │ │ 3D 点云 three.js          │ │ metadata    │
│ test.pcd       │ └──────────────────────────┘ │ bounds      │
│               │ ┌──────────────────────────┐ │ waypoints   │
│ 刷新按钮       │ │ 2D 俯视图 Canvas          │ │ buttons     │
│               │ └──────────────────────────┘ │             │
├───────────────┴──────────────────────────────┴─────────────┤
│ 底部日志                                                     │
└────────────────────────────────────────────────────────────┘
```

---

## 17. 前端文件建议

如果是 React 项目：

```text
src/
├── pages/
│   └── PcdMapDemoPage.tsx
├── components/
│   ├── PcdFileListPanel.tsx
│   ├── PointCloud3DViewer.tsx
│   ├── PointCloudTopDownCanvas.tsx
│   ├── PcdMetadataPanel.tsx
│   ├── WaypointPanel.tsx
│   └── LogPanel.tsx
├── api/
│   └── pcdMapApi.ts
├── utils/
│   ├── pointCloudTransforms.ts
│   └── topDownCoordinate.ts
└── types/
    └── pcdMap.ts
```

---

## 18. 前端类型定义

```ts
export type PcdBounds = {
  minX: number
  maxX: number
  minY: number
  maxY: number
  minZ: number
  maxZ: number
}

export type PcdMapItem = {
  id: string
  name: string
  sizeBytes: number
  modifiedAt: string
}

export type PcdMetadata = {
  mapId: string
  name: string
  frameId: "map"
  type: "pcd"
  pointCount: number
  fields: string[]
  dataType: string
  bounds: PcdBounds
}

export type PointCloudPreview = {
  mapId: string
  frameId: "map"
  points: [number, number, number][]
  bounds: PcdBounds
}

export type Waypoint = {
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

## 19. 前端 API 封装

`pcdMapApi.ts`：

```ts
const API_BASE = "/api"

export async function listPcdMaps() {
  const res = await fetch(`${API_BASE}/pcd-maps`)
  if (!res.ok) throw new Error("获取 PCD 文件列表失败")
  return res.json()
}

export async function getPcdMetadata(mapId: string) {
  const res = await fetch(`${API_BASE}/pcd-maps/${encodeURIComponent(mapId)}/metadata`)
  if (!res.ok) throw new Error("获取 PCD metadata 失败")
  return res.json()
}

export async function getPcdPreview(mapId: string, maxPoints = 100000) {
  const res = await fetch(
    `${API_BASE}/pcd-maps/${encodeURIComponent(mapId)}/preview?maxPoints=${maxPoints}`
  )
  if (!res.ok) throw new Error("获取 PCD preview 失败")
  return res.json()
}

export async function listWaypoints(mapId: string) {
  const res = await fetch(`${API_BASE}/pcd-maps/${encodeURIComponent(mapId)}/waypoints`)
  if (!res.ok) throw new Error("获取导航点失败")
  return res.json()
}

export async function createWaypoint(mapId: string, payload: {
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frameId: "map"
}) {
  const res = await fetch(`${API_BASE}/pcd-maps/${encodeURIComponent(mapId)}/waypoints`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  })

  if (!res.ok) throw new Error("创建导航点失败")
  return res.json()
}

export async function deleteWaypoint(mapId: string, waypointId: string) {
  const res = await fetch(
    `${API_BASE}/pcd-maps/${encodeURIComponent(mapId)}/waypoints/${encodeURIComponent(waypointId)}`,
    { method: "DELETE" }
  )

  if (!res.ok) throw new Error("删除导航点失败")
  return res.json()
}
```

---

# 第五阶段：three.js 三维点云显示

## 20. 安装依赖

如果项目没有 three.js：

```bash
npm install three
```

如果需要轨道控制器：

```ts
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls"
```

---

## 21. 坐标转换

创建：

```text
src/utils/pointCloudTransforms.ts
```

内容：

```ts
export function mapToThree(x: number, y: number, z: number) {
  return {
    x,
    y: z,
    z: -y
  }
}

export function threeToMap(x: number, y: number, z: number) {
  return {
    x,
    y: -z,
    z: y
  }
}
```

要求：

```text
1. 点云显示使用 mapToThree；
2. 3D 导航点显示使用 mapToThree；
3. 后续机器人模型显示也使用 mapToThree。
```

---

## 22. PointCloud3DViewer 实现逻辑

输入：

```ts
type Props = {
  points: [number, number, number][]
  waypoints: Waypoint[]
}
```

核心流程：

```text
1. 初始化 Scene
2. 初始化 Camera
3. 初始化 Renderer
4. 初始化 OrbitControls
5. 根据 points 生成 Float32Array
6. 创建 BufferGeometry
7. 创建 PointsMaterial
8. 创建 THREE.Points
9. 添加到 Scene
10. 根据 waypoints 添加球体/标记
11. 启动 requestAnimationFrame
12. 组件卸载时释放 geometry/material/renderer
```

点云构造：

```ts
const positions = new Float32Array(points.length * 3)

points.forEach((p, index) => {
  const converted = mapToThree(p[0], p[1], p[2])

  positions[index * 3 + 0] = converted.x
  positions[index * 3 + 1] = converted.y
  positions[index * 3 + 2] = converted.z
})

const geometry = new THREE.BufferGeometry()
geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3))

const material = new THREE.PointsMaterial({
  size: 0.03
})

const cloud = new THREE.Points(geometry, material)
scene.add(cloud)
```

注意：

```text
1. 不要每次 render 都重新初始化 three.js；
2. points 改变时更新 geometry；
3. 页面切换时释放资源；
4. 点数太多会卡，前端不要主动请求超过 200000。
```

---

# 第六阶段：2D 俯视图

## 23. 俯视图用途

2D 俯视图用于：

```text
1. 看点云 XY 投影；
2. 显示地图边界；
3. 显示鼠标 map 坐标；
4. 点击添加导航点；
5. 显示已保存导航点。
```

不要让用户直接在 3D 里标点。第一版在 3D 里标点不稳定。

---

## 24. 2D 坐标转换工具

创建：

```text
src/utils/topDownCoordinate.ts
```

实现：

```ts
export function getTopDownScale(
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = bounds.maxX - bounds.minX
  const rangeY = bounds.maxY - bounds.minY

  return Math.min(usableWidth / rangeX, usableHeight / rangeY)
}

export function mapToCanvas(
  x: number,
  y: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const scale = getTopDownScale(bounds, canvasWidth, canvasHeight, padding)

  const canvasX = padding + (x - bounds.minX) * scale
  const canvasY = canvasHeight - padding - (y - bounds.minY) * scale

  return { x: canvasX, y: canvasY }
}

export function canvasToMap(
  canvasX: number,
  canvasY: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const scale = getTopDownScale(bounds, canvasWidth, canvasHeight, padding)

  const x = bounds.minX + (canvasX - padding) / scale
  const y = bounds.minY + (canvasHeight - padding - canvasY) / scale

  return { x, y }
}
```

---

## 25. PointCloudTopDownCanvas 实现逻辑

输入：

```ts
type Props = {
  points: [number, number, number][]
  bounds: PcdBounds
  waypoints: Waypoint[]
  addMode: boolean
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onAddWaypoint: (pos: { x: number; y: number }) => void
}
```

绘制逻辑：

```text
1. 清空 Canvas；
2. 绘制背景；
3. 绘制坐标轴；
4. 遍历 points，把 x/y 投影到 Canvas；
5. 绘制点云散点；
6. 绘制已保存导航点；
7. 如果 addMode=true，鼠标样式改为 crosshair；
8. 鼠标移动时调用 canvasToMap；
9. 鼠标点击时调用 onAddWaypoint。
```

为了避免 Canvas 绘制过慢：

```text
1. 只绘制 preview 点；
2. 点半径为 1px；
3. points 太多时前端再抽样，例如最多画 50000 个；
4. 不要在 mousemove 时重绘全部点云。
```

---

# 第七阶段：添加导航点

## 26. 页面交互流程

```text
1. 用户选择 PCD 文件；
2. 加载点云 preview；
3. 用户点击“添加导航点”；
4. 页面进入 addMode；
5. 用户在 2D 俯视图点击；
6. canvasToMap 得到 x/y；
7. 弹窗输入导航点名称；
8. z 默认 0；
9. yaw 默认 0；
10. frameId 固定 map；
11. 调用 createWaypoint；
12. 后端保存；
13. 前端刷新 waypoint 列表；
14. 2D 和 3D 都显示该点。
```

---

## 27. 添加导航点请求

```json
{
  "name": "巡检点1",
  "x": 2.35,
  "y": -1.20,
  "z": 0,
  "yaw": 0,
  "frameId": "map"
}
```

Demo 阶段：

```text
z 固定为 0
yaw 固定为 0
```

后续改进：

```text
1. 鼠标拖动设置 yaw；
2. 自动从附近点云估计地面高度 z；
3. 判断该点是否在可通行区域。
```

---

# 第八阶段：页面状态管理

## 28. PcdMapDemoPage 状态

页面需要维护：

```ts
const [pcdMaps, setPcdMaps] = useState<PcdMapItem[]>([])
const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
const [preview, setPreview] = useState<PointCloudPreview | null>(null)
const [waypoints, setWaypoints] = useState<Waypoint[]>([])
const [loading, setLoading] = useState(false)
const [addMode, setAddMode] = useState(false)
const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
const [logs, setLogs] = useState<LogItem[]>([])
```

---

## 29. 选择 PCD 文件时的流程

```ts
async function handleSelectMap(mapId: string) {
  setSelectedMapId(mapId)
  setLoading(true)

  try {
    addLog(`开始加载点云：${mapId}`)

    const metadata = await getPcdMetadata(mapId)
    setMetadata(metadata)

    const preview = await getPcdPreview(mapId, 100000)
    setPreview(preview)

    const waypointResult = await listWaypoints(mapId)
    setWaypoints(waypointResult.items)

    addLog(`点云加载完成：${mapId}`)
  } catch (error) {
    addLog(`点云加载失败：${String(error)}`, "error")
  } finally {
    setLoading(false)
  }
}
```

---

# 第九阶段：操作日志

## 30. 日志类型

```ts
type LogItem = {
  time: string
  level: "info" | "warning" | "error"
  message: string
}
```

操作都应记录：

```text
刷新 PCD 文件列表
选择 PCD 文件
加载 metadata
加载 preview
添加导航点
删除导航点
接口失败
```

示例：

```text
[15:20:01] 刷新 PCD 文件列表
[15:20:03] 选择点云：1.pcd
[15:20:04] 点云加载完成，共 100000 个预览点
[15:20:10] 新增导航点：巡检点1 x=2.35 y=-1.20
[15:20:20] 删除导航点：巡检点1
```

---

# 第十阶段：错误处理

## 31. 后端错误

后端需要明确返回错误信息。

常见错误：

```text
PCD_MAP_ROOT 不存在
mapId 非法
PCD 文件不存在
PCD header 缺少 FIELDS
PCD header 缺少 DATA
PCD 不包含 x/y/z 字段
PCD 是 binary_compressed，Demo 暂不支持
PCD 文件过大导致解析失败
```

建议返回：

```json
{
  "ok": false,
  "message": "PCD 文件不包含 x/y/z 字段"
}
```

---

## 32. 前端错误

前端捕获错误后：

```text
1. 页面弹出错误提示；
2. 日志区记录错误；
3. 不要让页面白屏；
4. 保留上一次已加载的点云。
```

---

# 第十一阶段：验收流程

## 33. 验收 1：PCD 文件列表

准备目录：

```bash
mkdir -p /home/jetson/maps
cp 1.pcd /home/jetson/maps/
```

启动后端后访问：

```http
GET /api/pcd-maps
```

预期返回：

```json
{
  "items": [
    {
      "id": "1.pcd",
      "name": "1.pcd"
    }
  ]
}
```

页面左侧应显示：

```text
1.pcd
```

---

## 34. 验收 2：metadata

访问：

```http
GET /api/pcd-maps/1.pcd/metadata
```

预期：

```text
1. pointCount 正确；
2. fields 包含 x/y/z；
3. dataType 能识别；
4. bounds 数值合理；
5. frameId = map。
```

页面右侧显示：

```text
当前文件：1.pcd
frameId：map
pointCount：xxxx
x 范围：minX ~ maxX
y 范围：minY ~ maxY
z 范围：minZ ~ maxZ
```

---

## 35. 验收 3：点云显示

点击 `1.pcd` 后：

```text
1. 页面显示加载中；
2. 加载完成；
3. 3D 视图出现点云；
4. 可以旋转、缩放、平移；
5. 2D 俯视图出现 XY 投影。
```

---

## 36. 验收 4：鼠标坐标

鼠标在 2D 俯视图移动时，页面显示：

```text
map x = 2.35
map y = -1.20
```

数值应随着鼠标移动连续变化。

---

## 37. 验收 5：添加导航点

操作：

```text
1. 点击“添加导航点”；
2. 在 2D 俯视图点击；
3. 输入名称“测试点1”；
4. 点击确认。
```

预期：

```text
1. 右侧导航点列表出现“测试点1”；
2. 2D 俯视图出现导航点标记；
3. 3D 点云中出现导航点标记；
4. 日志出现新增导航点；
5. 后端 data/waypoints/1.pcd.json 写入该点。
```

---

## 38. 验收 6：刷新页面数据不丢

操作：

```text
1. 添加一个导航点；
2. 刷新浏览器；
3. 重新选择 1.pcd。
```

预期：

```text
导航点仍然存在。
```

---

# 第十二阶段：Codex 任务描述

可以直接把下面内容发给 Codex。

```text
请实现一个 PCD 点云地图选择与预览 Demo。

背景：
当前系统需要接入导航巡逻功能，但第一阶段只验证同事建好的 PCD 三维点云地图能否被我的系统读取、显示和标点。
地图不是二维栅格图，不需要 map.yaml / pgm。
地图文件不上传、不拷贝，由后端直接从指定目录读取。
导航坐标系按 map 处理。

后端要求：
1. 增加配置项 PCD_MAP_ROOT，默认 ./mock_maps。
2. 后端只允许读取 PCD_MAP_ROOT 下的 .pcd 文件。
3. 实现 GET /api/pcd-maps，返回 PCD 文件列表。
4. 实现 GET /api/pcd-maps/{mapId}/metadata，解析 PCD header，返回 pointCount、fields、dataType、bounds、frameId=map。
5. 实现 GET /api/pcd-maps/{mapId}/preview?maxPoints=100000，读取 PCD 点云并降采样，返回最多 maxPoints 个 [x,y,z] 点。
6. 如果 PCD 不包含 x/y/z 字段，返回明确错误。
7. 如果 PCD 是暂不支持的格式，例如 binary_compressed，返回明确错误。
8. 实现 GET /api/pcd-maps/{mapId}/waypoints，返回该地图的导航点。
9. 实现 POST /api/pcd-maps/{mapId}/waypoints，保存导航点。
10. 实现 DELETE /api/pcd-maps/{mapId}/waypoints/{waypointId}，删除导航点。
11. Demo 阶段导航点保存到 backend/data/waypoints/{mapId}.json。

前端要求：
1. 新增 PcdMapDemoPage。
2. 左侧显示 PCD 文件列表。
3. 点击 PCD 文件后加载 metadata、preview、waypoints。
4. 中间上方使用 three.js 显示 3D 点云。
5. 中间下方使用 Canvas 显示 2D 俯视图，使用点云 x/y 投影。
6. 点云坐标转换为 three.js 时使用：
   map x -> three x
   map y -> three -z
   map z -> three y
7. 2D 俯视图鼠标移动时显示当前 map x/y。
8. 点击“添加导航点”后，在 2D 俯视图点击位置添加导航点。
9. 导航点结构：
   {
     id,
     mapId,
     name,
     x,
     y,
     z,
     yaw,
     frameId: "map"
   }
10. z 默认 0，yaw 默认 0。
11. 导航点需要同时显示在 2D 俯视图和 3D 点云中。
12. 右侧显示 metadata、bounds、导航点列表。
13. 支持删除导航点。
14. 底部显示操作日志。
15. 页面刷新后，重新选择同一个 PCD，导航点仍能加载出来。

验收标准：
1. /home/jetson/maps/1.pcd 存在时，页面左侧能看到 1.pcd。
2. 点击 1.pcd 后，能显示 metadata 和 bounds。
3. 3D 视图能显示点云。
4. 2D 俯视图能显示点云 XY 投影。
5. 鼠标在俯视图移动时能显示 map x/y。
6. 点击俯视图能新增导航点。
7. 导航点保存后刷新页面不丢。
8. 所有坐标都按 frameId=map 保存。
```

---

# 第十三阶段：后续扩展路径

Demo 验收通过后，再按下面顺序继续。

## 39. 接入真实机器人位姿

新增接口：

```http
GET /api/robot/status
```

或 WebSocket：

```text
/ws/robot_state
```

前端显示：

```text
机器人当前位置 x/y/yaw
机器人在 2D 俯视图中的位置
机器人在 3D 点云中的位置
```

---

## 40. 接入设置位姿

前端：

```text
点击“设置位姿”
  ↓
在 2D 俯视图选择位置
  ↓
输入/拖动 yaw
  ↓
发送给后端
```

后端：

```text
POST /api/localization/set_pose
  ↓
发布 /initialpose
```

---

## 41. 接入单点导航

前端：

```text
点击导航点右侧“前往”
```

后端：

```text
POST /api/nav/go_to
  ↓
调用 NavigateToPose
```

---

## 42. 接入巡检任务

巡检任务数据：

```json
{
  "name": "测试巡检",
  "loop": false,
  "waypoints": [
    {
      "waypointId": "wp_001",
      "staySeconds": 5,
      "action": "none"
    }
  ]
}
```

后端调度：

```text
逐点调用 NavigateToPose
  ↓
到点停留
  ↓
执行动作
  ↓
继续下一个点
```

---

## 43. 接入建图控制

建图控制最后接：

```http
POST /api/mapping/start
POST /api/mapping/stop
POST /api/mapping/save
```

因为建图涉及 ROS2 launch、进程管理、地图保存路径，不应该放在第一阶段。

---

# 第十四阶段：当前结论

当前 Demo 第一优先级是：

```text
PCD 地图文件选择 + 点云预览 + map 坐标标点
```

不要先做：

```text
完整巡检任务
真实导航
真实建图
自动重定位
```

原因：

```text
如果 PCD 地图显示和 map 坐标标点没验证通过，
后面的导航点、位姿、巡检路线都会存在坐标偏差风险。
```

第一版完成后，你要让同事一起确认：

```text
1. 前端显示的 PCD 是否就是他建好的地图；
2. 俯视图方向是否正确；
3. 点云坐标是否就是 map 坐标；
4. 你标的点 x/y 是否可以直接作为导航目标；
5. 后续导航目标格式是否为 x/y/yaw + frame_id=map。
```
