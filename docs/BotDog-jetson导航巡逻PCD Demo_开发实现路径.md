# BotDog-jetson 导航巡逻 PCD Demo 开发实现路径

## 1. 开发目标

本开发路径基于 `Timekeeperxxx/BotDog-jetson` 当前仓库结构，目标是在现有项目内实现一个“PCD 点云地图选择与标点 Demo”。

第一版只做：

```text
从后端指定目录读取 .pcd
  ↓
前端选择 PCD 文件
  ↓
显示三维点云
  ↓
显示二维俯视投影
  ↓
在 map 坐标系下添加导航点
  ↓
保存导航点
```

第一版不做：

```text
真实 ROS2 导航
真实建图
真实重定位
巡检任务自动执行
点云实时流
```

---

## 2. 必须遵守的项目约束

Codex 实现时必须遵守：

```text
1. 不新建独立项目。
2. 不新建单独 mock 后端。
3. 不绕开现有 backend/main.py。
4. 不在前端写死后端 IP。
5. 不直接让浏览器读取 /home/jetson/maps/1.pcd。
6. 不影响现有控制台、驱离系统、档案库、后台管理。
7. API 路径使用现有 /api/v1 风格。
8. 前端请求必须通过 frontend/src/config/api.ts 的 getApiUrl()。
9. Demo 阶段导航点使用 JSON 存储，先不改数据库表结构。
10. 点云必须降采样，不能一次性把完整 PCD 发给浏览器。
```

---

## 3. 总开发顺序

按照下面顺序做：

```text
第 1 步：增加后端配置项
第 2 步：新增 PCD 服务 services_pcd_maps.py
第 3 步：新增导航点 JSON 服务 services_nav_waypoints.py
第 4 步：schemas.py 增加 DTO
第 5 步：main.py 注册 /api/v1/nav/pcd-maps 接口
第 6 步：前端安装 three
第 7 步：新增前端类型和 API 封装
第 8 步：新增 3D 点云组件
第 9 步：新增 2D 俯视图组件
第 10 步：新增 PcdMapDemoPage
第 11 步：在 IndustrialConsoleComplete.tsx 增加“导航巡逻”tab
第 12 步：联调验收
```

---

# 第一部分：后端开发

## 4. 修改 backend/config.py

在 Settings 类中增加：

```python
# ==================== 导航巡逻 / PCD 点云地图 Demo ====================
PCD_MAP_ROOT: str = "./data/pcd_maps"
PCD_FRAME_ID: str = "map"
PCD_PREVIEW_DEFAULT_POINTS: int = 100000
PCD_PREVIEW_MAX_POINTS: int = 200000
NAV_WAYPOINT_STORE_DIR: str = "./data/nav_waypoints"
```

要求：

```text
1. 命名全部大写，符合现有配置风格。
2. 默认值可在开发机运行。
3. 部署到 Jetson 时用 .env 覆盖。
```

---

## 5. 修改 backend/.env.example

追加：

```env
# ==================== 导航巡逻 / PCD 点云地图 Demo ====================
# 同事建好的 PCD 点云地图所在目录。Demo 阶段不上传、不拷贝，后端直接扫描该目录。
PCD_MAP_ROOT=/home/jetson/maps

# 当前点云和导航点默认使用的坐标系
PCD_FRAME_ID=map

# 点云预览默认返回点数
PCD_PREVIEW_DEFAULT_POINTS=100000

# 点云预览最大允许返回点数
PCD_PREVIEW_MAX_POINTS=200000

# Demo 阶段导航点 JSON 存储目录
NAV_WAYPOINT_STORE_DIR=./data/nav_waypoints
```

---

## 6. 新增 backend/services_pcd_maps.py

### 6.1 文件职责

这个文件只负责 PCD 文件相关逻辑：

```text
1. 扫描 PCD 文件；
2. 校验 map_id；
3. 解析 PCD header；
4. 读取 ascii PCD；
5. 降采样；
6. 计算 bounds。
```

不要在这里写 FastAPI route。

---

### 6.2 推荐代码结构

```python
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any

from .config import settings


class PcdMapError(Exception):
    pass


def _utc_from_timestamp(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).isoformat(timespec="milliseconds") + "Z"


def get_pcd_root() -> Path:
    root = Path(settings.PCD_MAP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_pcd_path(map_id: str) -> Path:
    ...
```

---

### 6.3 实现 resolve_pcd_path()

必须防止路径穿越：

```python
def resolve_pcd_path(map_id: str) -> Path:
    if not map_id:
        raise PcdMapError("map_id 不能为空")

    if "/" in map_id or "\\" in map_id or ".." in map_id:
        raise PcdMapError("非法 map_id")

    if not map_id.lower().endswith(".pcd"):
        raise PcdMapError("只允许读取 .pcd 文件")

    root = get_pcd_root()
    path = (root / map_id).resolve()

    if path.parent != root:
        raise PcdMapError("禁止读取 PCD_MAP_ROOT 以外的文件")

    if not path.exists():
        raise FileNotFoundError(f"PCD 文件不存在: {map_id}")

    if not path.is_file():
        raise PcdMapError("map_id 不是文件")

    return path
```

---

### 6.4 实现 list_pcd_maps()

```python
def list_pcd_maps() -> dict[str, Any]:
    root = get_pcd_root()
    items = []

    for path in root.iterdir():
        if not path.is_file():
            continue

        if path.suffix.lower() != ".pcd":
            continue

        stat = path.stat()
        items.append({
            "id": path.name,
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_at": _utc_from_timestamp(stat.st_mtime),
        })

    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return {
        "root": str(root),
        "items": items,
    }
```

---

### 6.5 实现 parse_pcd_header()

PCD header 以 `DATA` 行结束。

```python
def parse_pcd_header(path: Path) -> tuple[dict[str, Any], int]:
    header_lines: list[str] = []
    data_start_offset = 0

    with path.open("rb") as f:
        while True:
            line = f.readline()
            if not line:
                break

            decoded = line.decode("utf-8", errors="ignore").strip()
            header_lines.append(decoded)
            data_start_offset = f.tell()

            if decoded.upper().startswith("DATA "):
                break

    header: dict[str, list[str]] = {}

    for line in header_lines:
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if not parts:
            continue

        key = parts[0].upper()
        values = parts[1:]
        header[key] = values

    if "FIELDS" not in header:
        raise PcdMapError("PCD header 缺少 FIELDS")

    if "DATA" not in header:
        raise PcdMapError("PCD header 缺少 DATA")

    fields = header["FIELDS"]

    for required in ("x", "y", "z"):
        if required not in fields:
            raise PcdMapError(f"PCD 文件不包含字段: {required}")

    return header, data_start_offset
```

---

### 6.6 实现 header 标准化

```python
def normalize_pcd_header(header: dict[str, list[str]]) -> dict[str, Any]:
    fields = header.get("FIELDS", [])
    data_type = header.get("DATA", ["unknown"])[0].lower()

    if "POINTS" in header:
        point_count = int(header["POINTS"][0])
    else:
        width = int(header.get("WIDTH", ["0"])[0])
        height = int(header.get("HEIGHT", ["1"])[0])
        point_count = width * height

    return {
        "fields": fields,
        "data_type": data_type,
        "point_count": point_count,
    }
```

---

### 6.7 bounds 工具函数

```python
def _empty_bounds() -> dict[str, float]:
    return {
        "min_x": float("inf"),
        "max_x": float("-inf"),
        "min_y": float("inf"),
        "max_y": float("-inf"),
        "min_z": float("inf"),
        "max_z": float("-inf"),
    }


def _update_bounds(bounds: dict[str, float], x: float, y: float, z: float) -> None:
    bounds["min_x"] = min(bounds["min_x"], x)
    bounds["max_x"] = max(bounds["max_x"], x)
    bounds["min_y"] = min(bounds["min_y"], y)
    bounds["max_y"] = max(bounds["max_y"], y)
    bounds["min_z"] = min(bounds["min_z"], z)
    bounds["max_z"] = max(bounds["max_z"], z)


def _finalize_bounds(bounds: dict[str, float]) -> dict[str, float]:
    if bounds["min_x"] == float("inf"):
        raise PcdMapError("PCD 文件没有可解析点")
    return bounds
```

---

### 6.8 实现 ascii 点云扫描

```python
def read_ascii_preview(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")

    normalized = normalize_pcd_header(header)
    point_count = normalized["point_count"]

    step = max(1, point_count // max_points)

    bounds = _empty_bounds()
    points: list[list[float]] = []
    parsed_index = 0

    with path.open("rb") as f:
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

            _update_bounds(bounds, x, y, z)

            if parsed_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

            parsed_index += 1

    return points, _finalize_bounds(bounds)
```

---

### 6.9 实现 get_pcd_metadata()

第一版 metadata 可以通过读取 preview 顺带计算 bounds。

```python
def get_pcd_metadata(map_id: str) -> dict[str, Any]:
    path = resolve_pcd_path(map_id)
    header, data_start_offset = parse_pcd_header(path)
    normalized = normalize_pcd_header(header)

    data_type = normalized["data_type"]

    if data_type != "ascii":
        return {
            "map_id": map_id,
            "name": map_id,
            "frame_id": settings.PCD_FRAME_ID,
            "type": "pcd",
            "point_count": normalized["point_count"],
            "fields": normalized["fields"],
            "data_type": data_type,
            "bounds": None,
            "supported": False,
            "message": f"当前 Demo 暂不支持 DATA {data_type} PCD",
        }

    _, bounds = read_ascii_preview(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=settings.PCD_PREVIEW_MAX_POINTS,
    )

    return {
        "map_id": map_id,
        "name": map_id,
        "frame_id": settings.PCD_FRAME_ID,
        "type": "pcd",
        "point_count": normalized["point_count"],
        "fields": normalized["fields"],
        "data_type": data_type,
        "bounds": bounds,
        "supported": True,
    }
```

如果不想在 metadata 中返回 `supported`，也可以不加。但建议加上，前端能明确提示。

---

### 6.10 实现 get_pcd_preview()

```python
def get_pcd_preview(map_id: str, max_points: int | None = None) -> dict[str, Any]:
    path = resolve_pcd_path(map_id)
    header, data_start_offset = parse_pcd_header(path)
    normalized = normalize_pcd_header(header)

    data_type = normalized["data_type"]

    if data_type != "ascii":
        raise PcdMapError(f"当前 Demo 暂不支持 DATA {data_type} PCD")

    if max_points is None:
        max_points = settings.PCD_PREVIEW_DEFAULT_POINTS

    max_points = max(1000, min(max_points, settings.PCD_PREVIEW_MAX_POINTS))

    points, bounds = read_ascii_preview(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=max_points,
    )

    return {
        "map_id": map_id,
        "frame_id": settings.PCD_FRAME_ID,
        "points": points,
        "bounds": bounds,
    }
```

---

## 7. 新增 backend/services_nav_waypoints.py

### 7.1 文件职责

```text
1. 读取某张 PCD 地图的导航点；
2. 创建导航点；
3. 删除导航点；
4. 用 JSON 文件持久化；
5. 不改数据库。
```

---

### 7.2 推荐代码骨架

```python
from __future__ import annotations

import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any

from .config import settings
from .services_pcd_maps import resolve_pcd_path


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_WAYPOINT_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_waypoint_file(map_id: str) -> Path:
    # 复用 PCD 校验，确保 map_id 合法且文件存在
    resolve_pcd_path(map_id)
    safe_name = map_id.replace("/", "_").replace("\\", "_")
    return _store_dir() / f"{safe_name}.json"
```

---

### 7.3 读取导航点

```python
def list_waypoints(map_id: str) -> dict[str, Any]:
    path = _safe_waypoint_file(map_id)

    if not path.exists():
        return {"items": []}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return {
        "items": data.get("items", [])
    }
```

---

### 7.4 写入导航点文件

```python
def _write_waypoints(map_id: str, items: list[dict[str, Any]]) -> None:
    path = _safe_waypoint_file(map_id)

    payload = {
        "map_id": map_id,
        "items": items,
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
```

---

### 7.5 创建导航点

```python
def create_waypoint(map_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = list_waypoints(map_id)["items"]

    now = _utc_now_iso()

    waypoint = {
        "id": f"wp_{uuid.uuid4().hex[:12]}",
        "map_id": map_id,
        "name": payload["name"],
        "x": float(payload["x"]),
        "y": float(payload["y"]),
        "z": float(payload.get("z", 0.0)),
        "yaw": float(payload.get("yaw", 0.0)),
        "frame_id": payload.get("frame_id", settings.PCD_FRAME_ID),
        "created_at": now,
        "updated_at": now,
    }

    if waypoint["frame_id"] != settings.PCD_FRAME_ID:
        raise ValueError(f"frame_id 必须是 {settings.PCD_FRAME_ID}")

    existing.append(waypoint)
    _write_waypoints(map_id, existing)

    return waypoint
```

---

### 7.6 删除导航点

```python
def delete_waypoint(map_id: str, waypoint_id: str) -> bool:
    existing = list_waypoints(map_id)["items"]
    next_items = [item for item in existing if item.get("id") != waypoint_id]

    if len(next_items) == len(existing):
        return False

    _write_waypoints(map_id, next_items)
    return True
```

---

## 8. 修改 backend/schemas.py

添加 DTO。为了不破坏现有 DTO，直接追加到文件末尾即可。

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


class PcdMetadataResponse(BaseModel):
    map_id: str
    name: str
    frame_id: str = "map"
    type: str = "pcd"
    point_count: int
    fields: list[str]
    data_type: str
    bounds: PcdBoundsDTO | None = None
    supported: bool = True
    message: str | None = None


class PcdPreviewResponse(BaseModel):
    map_id: str
    frame_id: str = "map"
    points: list[list[float]]
    bounds: PcdBoundsDTO


class NavWaypointCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
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


class DeleteWaypointResponse(BaseModel):
    success: bool
```

---

## 9. 修改 backend/main.py 注册接口

### 9.1 增加 import

在 schemas import 中加入：

```python
PcdMapListResponse,
PcdMetadataResponse,
PcdPreviewResponse,
NavWaypointCreateRequest,
NavWaypointListResponse,
NavWaypointDTO,
DeleteWaypointResponse,
```

或者为了减少 import 冲突，局部 import 也可以。

---

### 9.2 在 register_routes(app) 内增加 PCD 路由

建议在 `register_routes(app)` 内靠近任务管理接口之前或之后增加：

```python
# ── 导航巡逻 / PCD 点云地图 Demo ─────────────────────────────────────
```

代码结构：

```python
@app.get("/api/v1/nav/pcd-maps", response_model=PcdMapListResponse)
async def nav_list_pcd_maps():
    from .services_pcd_maps import list_pcd_maps, PcdMapError

    try:
        return list_pcd_maps()
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/nav/pcd-maps/{map_id}/metadata", response_model=PcdMetadataResponse)
async def nav_get_pcd_metadata(map_id: str):
    from .services_pcd_maps import get_pcd_metadata, PcdMapError

    try:
        return get_pcd_metadata(map_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/nav/pcd-maps/{map_id}/preview", response_model=PcdPreviewResponse)
async def nav_get_pcd_preview(map_id: str, max_points: int | None = None):
    from .services_pcd_maps import get_pcd_preview, PcdMapError

    try:
        return get_pcd_preview(map_id, max_points=max_points)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/nav/pcd-maps/{map_id}/waypoints", response_model=NavWaypointListResponse)
async def nav_list_waypoints(map_id: str):
    from .services_nav_waypoints import list_waypoints

    return list_waypoints(map_id)


@app.post("/api/v1/nav/pcd-maps/{map_id}/waypoints", response_model=NavWaypointDTO)
async def nav_create_waypoint(map_id: str, body: NavWaypointCreateRequest):
    from .services_nav_waypoints import create_waypoint
    from .services_pcd_maps import PcdMapError

    try:
        return create_waypoint(map_id, body.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}", response_model=DeleteWaypointResponse)
async def nav_delete_waypoint(map_id: str, waypoint_id: str):
    from .services_nav_waypoints import delete_waypoint

    ok = delete_waypoint(map_id, waypoint_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")

    return {"success": True}
```

---

## 10. 后端手动验证

### 10.1 准备 PCD 目录

```bash
mkdir -p /home/jetson/maps
cp /path/to/1.pcd /home/jetson/maps/
```

开发机可以：

```bash
mkdir -p data/pcd_maps
cp 1.pcd data/pcd_maps/
```

---

### 10.2 启动后端

```bash
source .venv/bin/activate
python run_backend.py
```

或：

```bash
uvicorn backend.main:app --reload
```

---

### 10.3 测试接口

```bash
curl http://127.0.0.1:8000/api/v1/nav/pcd-maps
```

```bash
curl http://127.0.0.1:8000/api/v1/nav/pcd-maps/1.pcd/metadata
```

```bash
curl "http://127.0.0.1:8000/api/v1/nav/pcd-maps/1.pcd/preview?max_points=1000"
```

创建导航点：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/nav/pcd-maps/1.pcd/waypoints \
  -H "Content-Type: application/json" \
  -d '{"name":"测试点1","x":1.2,"y":-0.5,"z":0,"yaw":0,"frame_id":"map"}'
```

---

# 第二部分：前端开发

## 11. 安装 three.js

当前 `frontend/package.json` 没有 `three`，所以需要：

```bash
cd frontend
npm install three
```

---

## 12. 新增 frontend/src/types/pcdMap.ts

```ts
export type PcdBounds = {
  min_x: number
  max_x: number
  min_y: number
  max_y: number
  min_z: number
  max_z: number
}

export type PcdMapItem = {
  id: string
  name: string
  size_bytes: number
  modified_at: string
}

export type PcdMapListResponse = {
  root: string
  items: PcdMapItem[]
}

export type PcdMetadata = {
  map_id: string
  name: string
  frame_id: string
  type: 'pcd'
  point_count: number
  fields: string[]
  data_type: string
  bounds: PcdBounds | null
  supported?: boolean
  message?: string | null
}

export type PcdPreview = {
  map_id: string
  frame_id: string
  points: [number, number, number][]
  bounds: PcdBounds
}

export type NavWaypoint = {
  id: string
  map_id: string
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: string
  created_at: string
  updated_at: string
}

export type NavWaypointCreatePayload = {
  name: string
  x: number
  y: number
  z: number
  yaw: number
  frame_id: 'map'
}
```

---

## 13. 新增 frontend/src/api/pcdMapApi.ts

如果没有 `api` 目录，先新建。

```ts
import { getApiUrl } from '../config/api'
import type {
  PcdMapListResponse,
  PcdMetadata,
  PcdPreview,
  NavWaypointCreatePayload,
} from '../types/pcdMap'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const data = await res.json()
      message = data.detail || message
    } catch {
      // ignore
    }
    throw new Error(message)
  }
  return res.json()
}

export function listPcdMaps(): Promise<PcdMapListResponse> {
  return requestJson(getApiUrl('/api/v1/nav/pcd-maps'))
}

export function getPcdMetadata(mapId: string): Promise<PcdMetadata> {
  return requestJson(getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/metadata`))
}

export function getPcdPreview(mapId: string, maxPoints = 100000): Promise<PcdPreview> {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/preview?max_points=${maxPoints}`)
  )
}

export async function listWaypoints(mapId: string) {
  return requestJson<{ items: any[] }>(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints`)
  )
}

export async function createWaypoint(mapId: string, payload: NavWaypointCreatePayload) {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }
  )
}

export async function deleteWaypoint(mapId: string, waypointId: string) {
  return requestJson(
    getApiUrl(`/api/v1/nav/pcd-maps/${encodeURIComponent(mapId)}/waypoints/${encodeURIComponent(waypointId)}`),
    { method: 'DELETE' }
  )
}
```

---

## 14. 新增 frontend/src/utils/pointCloudTransform.ts

```ts
export function mapToThree(x: number, y: number, z: number) {
  return {
    x,
    y: z,
    z: -y,
  }
}

export function threeToMap(x: number, y: number, z: number) {
  return {
    x,
    y: -z,
    z: y,
  }
}
```

---

## 15. 新增 frontend/src/utils/topDownCoordinate.ts

```ts
import type { PcdBounds } from '../types/pcdMap'

export function getTopDownScale(
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30
) {
  const usableWidth = canvasWidth - padding * 2
  const usableHeight = canvasHeight - padding * 2

  const rangeX = Math.max(0.0001, bounds.max_x - bounds.min_x)
  const rangeY = Math.max(0.0001, bounds.max_y - bounds.min_y)

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

  return {
    x: padding + (x - bounds.min_x) * scale,
    y: canvasHeight - padding - (y - bounds.min_y) * scale,
  }
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

  return {
    x: bounds.min_x + (canvasX - padding) / scale,
    y: bounds.min_y + (canvasHeight - padding - canvasY) / scale,
  }
}
```

---

## 16. 新增 frontend/src/components/pcd/PcdFileListPanel.tsx

职责：

```text
1. 显示 PCD 文件列表；
2. 显示刷新按钮；
3. 高亮当前 selectedMapId；
4. 点击文件时调用 onSelect(map.id)。
```

Props：

```ts
type Props = {
  maps: PcdMapItem[]
  selectedMapId: string | null
  loading: boolean
  onRefresh: () => void
  onSelect: (mapId: string) => void
}
```

---

## 17. 新增 frontend/src/components/pcd/PcdMetadataPanel.tsx

职责：

```text
1. 显示当前 PCD 文件名；
2. 显示 point_count；
3. 显示 fields；
4. 显示 data_type；
5. 显示 frame_id；
6. 显示 bounds；
7. 如果 supported=false，显示错误提示。
```

Props：

```ts
type Props = {
  metadata: PcdMetadata | null
  mouseMapPosition?: { x: number; y: number } | null
}
```

---

## 18. 新增 frontend/src/components/pcd/PointCloud3DViewer.tsx

职责：

```text
1. 用 three.js 显示点云；
2. 支持 OrbitControls 旋转/缩放/平移；
3. 显示导航点；
4. points 变化时更新 BufferGeometry；
5. 组件卸载时释放 renderer、geometry、material。
```

Props：

```ts
type Props = {
  points: [number, number, number][]
  waypoints: NavWaypoint[]
}
```

核心实现：

```ts
const positions = new Float32Array(points.length * 3)

points.forEach((p, index) => {
  const converted = mapToThree(p[0], p[1], p[2])
  positions[index * 3 + 0] = converted.x
  positions[index * 3 + 1] = converted.y
  positions[index * 3 + 2] = converted.z
})

const geometry = new THREE.BufferGeometry()
geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

const material = new THREE.PointsMaterial({
  size: 0.03,
})

const cloud = new THREE.Points(geometry, material)
scene.add(cloud)
```

导航点显示：

```text
1. 用 SphereGeometry 小球；
2. 用 mapToThree 转换；
3. z 默认 0；
4. 后续可以加文字 label。
```

注意：

```text
不要在 React 每次 render 时重新创建完整 Scene。
使用 useEffect + ref 管理 three 生命周期。
```

---

## 19. 新增 frontend/src/components/pcd/PointCloudTopDownCanvas.tsx

职责：

```text
1. 把点云 x/y 投影到 Canvas；
2. 鼠标移动显示 map x/y；
3. addMode 下点击添加导航点；
4. 显示已有导航点。
```

Props：

```ts
type Props = {
  points: [number, number, number][]
  bounds: PcdBounds | null
  waypoints: NavWaypoint[]
  addMode: boolean
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onAddWaypoint: (pos: { x: number; y: number }) => void
}
```

绘制逻辑：

```text
1. 清空 canvas；
2. 绘制黑色或深色背景；
3. 绘制点云 XY 投影；
4. 绘制 bounds 边界；
5. 绘制 x/y 坐标轴；
6. 绘制导航点；
7. 如果 addMode，鼠标变十字。
```

点击逻辑：

```ts
const rect = canvas.getBoundingClientRect()
const canvasX = event.clientX - rect.left
const canvasY = event.clientY - rect.top
const mapPos = canvasToMap(canvasX, canvasY, bounds, canvas.width, canvas.height)
onAddWaypoint(mapPos)
```

---

## 20. 新增 frontend/src/components/pcd/NavWaypointPanel.tsx

职责：

```text
1. 显示导航点列表；
2. 显示 x/y/z/yaw；
3. 支持删除；
4. 后续预留“前往”按钮，但第一版按钮禁用或不显示。
```

Props：

```ts
type Props = {
  waypoints: NavWaypoint[]
  onDelete: (waypointId: string) => void
}
```

---

## 21. 新增 frontend/src/pages/PcdMapDemoPage.tsx

页面状态：

```ts
const [maps, setMaps] = useState<PcdMapItem[]>([])
const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
const [preview, setPreview] = useState<PcdPreview | null>(null)
const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
const [loading, setLoading] = useState(false)
const [addMode, setAddMode] = useState(false)
const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
const [localLogs, setLocalLogs] = useState<string[]>([])
```

核心函数：

```ts
async function refreshMaps() {
  ...
}

async function selectMap(mapId: string) {
  ...
}

async function handleAddWaypoint(pos: { x: number; y: number }) {
  ...
}

async function handleDeleteWaypoint(waypointId: string) {
  ...
}
```

`selectMap()` 流程：

```text
1. setSelectedMapId(mapId)
2. getPcdMetadata(mapId)
3. 如果 metadata.supported === false，显示提示，不请求 preview
4. getPcdPreview(mapId, 100000)
5. listWaypoints(mapId)
6. 更新页面状态
```

`handleAddWaypoint()` 流程：

```text
1. 如果没有 selectedMapId，返回；
2. window.prompt 输入点名；
3. name 为空则取消；
4. createWaypoint(selectedMapId, { name, x, y, z:0, yaw:0, frame_id:'map' })
5. 重新 listWaypoints；
6. addMode = false；
7. 写日志。
```

---

## 22. 修改 frontend/src/IndustrialConsoleComplete.tsx

### 22.1 增加 import

```ts
import { Map } from 'lucide-react'
import { PcdMapDemoPage } from './pages/PcdMapDemoPage'
```

如果 `Map` 命名冲突，可以用：

```ts
import { Map as MapIcon } from 'lucide-react'
```

---

### 22.2 修改 activeTab 类型

原来类似：

```ts
const [activeTab, setActiveTab] = useState<'console' | 'history' | 'simulate' | 'admin' | 'guard'>('console')
```

改为：

```ts
const [activeTab, setActiveTab] = useState<'console' | 'history' | 'simulate' | 'admin' | 'guard' | 'nav'>('console')
```

---

### 22.3 左侧导航增加按钮

在侧边栏中新增：

```tsx
<SidebarBtn
  icon={<MapIcon />}
  active={activeTab === 'nav'}
  onClick={() => setActiveTab('nav')}
  label="导航巡逻"
/>
```

建议位置：

```text
控制台
导航巡逻
驱离系统
档案库
后台管理
设置
告警
```

---

### 22.4 主内容区增加 nav 分支

当前主区域已经按 activeTab 分支渲染。新增：

```tsx
{activeTab === 'nav' ? (
  <PcdMapDemoPage addLog={addLog} />
) : activeTab === 'console' ? (
  ...
)}
```

如果分支结构比较复杂，可以先在 `console/history/admin/guard` 的分支外包一层判断。

---

## 23. 前端样式原则

当前项目是暗色工业控制台风格，所以 PCD 页面也按这个风格：

```text
背景：黑 / zinc-950
边框：white/10
文字：white/80
强调：cyan / emerald / amber
按钮：uppercase 小字号
卡片：rounded-2xl border border-white/10
```

不要引入额外 UI 库。

---

## 24. 联调验收

### 24.1 后端验收

```bash
curl http://127.0.0.1:8000/api/v1/nav/pcd-maps
```

预期：

```json
{
  "items": [
    {
      "id": "1.pcd"
    }
  ]
}
```

```bash
curl http://127.0.0.1:8000/api/v1/nav/pcd-maps/1.pcd/metadata
```

预期：

```text
point_count 有值
fields 包含 x/y/z
data_type 正确
bounds 有值或 supported=false 提示
```

```bash
curl "http://127.0.0.1:8000/api/v1/nav/pcd-maps/1.pcd/preview?max_points=1000"
```

预期：

```text
points 数量 <= 1000
bounds 有值
frame_id = map
```

---

### 24.2 前端验收

```bash
cd frontend
npm run dev
```

打开：

```text
http://localhost:5174
```

测试：

```text
1. 左侧出现“导航巡逻”。
2. 点击后进入 PCD Demo 页面。
3. 左侧能显示 1.pcd。
4. 点击 1.pcd 后显示 metadata。
5. 3D 视图显示点云。
6. 2D 俯视图显示 XY 投影。
7. 鼠标移动显示 map x/y。
8. 点击“添加导航点”。
9. 在俯视图点击。
10. 输入“测试点1”。
11. 右侧出现导航点。
12. 2D 图上出现点。
13. 3D 图上出现点。
14. 刷新页面后重新选择 1.pcd，导航点仍存在。
```

---

## 25. 常见问题处理

### 25.1 页面能看到文件，但 metadata 报 binary 不支持

说明同事给的是 binary PCD。

当前解决方式：

```text
1. 让同事导出 ascii PCD；
2. 或第二阶段实现 binary parser。
```

可以让同事用 PCL 转换：

```bash
pcl_convert_pcd_ascii_binary input.pcd output_ascii.pcd 0
```

其中 `0` 通常表示 ascii，具体以本机 PCL 工具说明为准。

---

### 25.2 点云显示很慢

处理：

```text
1. max_points 降到 30000；
2. Canvas 俯视图最多画 50000 点；
3. three.js PointsMaterial size 调小；
4. 避免每次鼠标移动都重绘完整点云。
```

---

### 25.3 点云方向看起来反了

重点检查：

```text
mapToThree:
map x -> three x
map y -> three -z
map z -> three y
```

以及 2D 俯视图：

```text
canvas y = height - padding - (mapY - minY) * scale
```

---

### 25.4 标点坐标和同事导航坐标对不上

必须让同事确认：

```text
1. PCD 内的 x/y/z 是否就是 map 坐标？
2. 导航目标是否也是 map frame 下的 x/y/yaw？
3. 建图和导航时是否发生了坐标变换？
4. 点云是否经过后处理、裁剪、旋转或平移？
```

这不是前端问题，而是坐标系交接问题。

---

## 26. Codex 直接执行任务清单

可以把下面这段直接丢给 Codex。

```text
请在现有 BotDog-jetson 项目中实现 PCD 点云地图选择和标点 Demo，不要新建独立项目。

后端要求：
1. 修改 backend/config.py，增加：
   PCD_MAP_ROOT
   PCD_FRAME_ID
   PCD_PREVIEW_DEFAULT_POINTS
   PCD_PREVIEW_MAX_POINTS
   NAV_WAYPOINT_STORE_DIR

2. 修改 backend/.env.example，追加对应配置说明。

3. 新增 backend/services_pcd_maps.py：
   - list_pcd_maps()
   - resolve_pcd_path(map_id)
   - parse_pcd_header(path)
   - get_pcd_metadata(map_id)
   - get_pcd_preview(map_id, max_points)
   - 第一版必须支持 DATA ascii
   - binary / binary_compressed 返回明确错误
   - 必须校验 map_id，禁止路径穿越
   - preview 必须降采样，不能超过 PCD_PREVIEW_MAX_POINTS

4. 新增 backend/services_nav_waypoints.py：
   - list_waypoints(map_id)
   - create_waypoint(map_id, payload)
   - delete_waypoint(map_id, waypoint_id)
   - 用 JSON 保存到 NAV_WAYPOINT_STORE_DIR
   - 每张 PCD 一个 JSON 文件

5. 修改 backend/schemas.py：
   - 增加 PcdBoundsDTO
   - PcdMapItemDTO
   - PcdMapListResponse
   - PcdMetadataResponse
   - PcdPreviewResponse
   - NavWaypointCreateRequest
   - NavWaypointDTO
   - NavWaypointListResponse
   - DeleteWaypointResponse

6. 修改 backend/main.py：
   在 register_routes(app) 中新增接口：
   GET /api/v1/nav/pcd-maps
   GET /api/v1/nav/pcd-maps/{map_id}/metadata
   GET /api/v1/nav/pcd-maps/{map_id}/preview?max_points=100000
   GET /api/v1/nav/pcd-maps/{map_id}/waypoints
   POST /api/v1/nav/pcd-maps/{map_id}/waypoints
   DELETE /api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}

前端要求：
1. 安装 three：
   cd frontend && npm install three

2. 新增 frontend/src/types/pcdMap.ts。

3. 新增 frontend/src/api/pcdMapApi.ts，必须使用 getApiUrl()，不能写死后端 IP。

4. 新增 frontend/src/utils/pointCloudTransform.ts：
   map x -> three x
   map y -> three -z
   map z -> three y

5. 新增 frontend/src/utils/topDownCoordinate.ts：
   实现 mapToCanvas 和 canvasToMap。

6. 新增组件目录 frontend/src/components/pcd/，包括：
   - PcdFileListPanel.tsx
   - PcdMetadataPanel.tsx
   - PointCloud3DViewer.tsx
   - PointCloudTopDownCanvas.tsx
   - NavWaypointPanel.tsx

7. 新增 frontend/src/pages/PcdMapDemoPage.tsx：
   - 左侧 PCD 文件列表
   - 中间 3D 点云
   - 中间 2D 俯视图
   - 右侧 metadata 和导航点
   - 底部操作日志
   - 支持添加/删除导航点

8. 修改 frontend/src/IndustrialConsoleComplete.tsx：
   - activeTab 增加 nav
   - 左侧导航增加“导航巡逻”
   - activeTab === 'nav' 时渲染 <PcdMapDemoPage addLog={addLog} />

验收：
1. /home/jetson/maps/1.pcd 存在时，前端能看到 1.pcd。
2. 点击 1.pcd 后能显示 metadata。
3. 3D 视图能显示点云。
4. 2D 俯视图能显示 XY 投影。
5. 鼠标移动显示 map x/y。
6. 点击添加导航点，能保存 frame_id=map 的 x/y/z/yaw。
7. 刷新页面后导航点不丢。
8. 原有控制台、驱离系统、档案库、后台管理不受影响。
```

---

## 27. 当前阶段完成后的下一步

PCD Demo 完成后，下一步才是：

```text
1. 确认 PCD 坐标等于 map 坐标；
2. 在前端显示机器人当前位姿；
3. 接入设置位姿；
4. 接入单点导航；
5. 接入巡检任务；
6. 接入建图控制；
7. 接入真实点云/地图更新。
```

不要跳过第 1 步。

只要坐标确认错了，后面的导航全都会错。
