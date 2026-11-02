"""Map polygons and robot-position membership; no camera or I/O."""
from __future__ import annotations

import math
import numpy as np


def validate_polygon(vertices: list[dict[str, float]]) -> tuple[list[list[float]], list[float]]:
    if not 3 <= len(vertices) <= 128:
        raise ValueError("区域需要3至128个地面顶点")
    points = np.asarray([[p['x'], p['y'], p['z']] for p in vertices], dtype=float)
    if not np.isfinite(points).all() or np.max(np.abs(points)) > 1e6:
        raise ValueError("区域坐标必须为有限地图坐标")
    xy = points[:, :2]
    if any(np.linalg.norm(xy[i] - xy[j]) < 1e-6 for i in range(len(xy)) for j in range(i)):
        raise ValueError("区域顶点不能重复")
    area = abs(sum(xy[i,0]*xy[(i+1)%len(xy),1] - xy[i,1]*xy[(i+1)%len(xy),0] for i in range(len(xy)))) / 2
    if area < 1e-4:
        raise ValueError("区域面积过小或顶点共线")
    def orient(a, b, c):
        u,v=b-a,c-a
        return float(u[0]*v[1]-u[1]*v[0])
    def on_segment(a, b, p):
        return abs(orient(a, b, p)) <= 1e-9 and np.all(p >= np.minimum(a,b)-1e-9) and np.all(p <= np.maximum(a,b)+1e-9)
    def intersects(a,b,c,d):
        v = [orient(a,b,c), orient(a,b,d), orient(c,d,a), orient(c,d,b)]
        return (v[0]*v[1] < 0 and v[2]*v[3] < 0) or any((on_segment(a,b,c), on_segment(a,b,d), on_segment(c,d,a), on_segment(c,d,b)))
    for i in range(len(xy)):
        for j in range(i+1, len(xy)):
            if j == i+1 or (i == 0 and j == len(xy)-1):
                continue
            if intersects(xy[i], xy[(i+1)%len(xy)], xy[j], xy[(j+1)%len(xy)]):
                raise ValueError("区域边界不能自相交")
    matrix = np.column_stack((xy, np.ones(len(points))))
    plane, _, rank, _ = np.linalg.lstsq(matrix, points[:, 2], rcond=None)
    if rank != 3:
        raise ValueError("区域顶点不能共线")
    # Retain plane metadata for existing records; membership uses map XY only.
    return points.tolist(), plane.tolist()


def polygon_location(point: tuple[float, float], polygon: list[list[float]], margin: float) -> str:
    x, y = point
    inside = False
    distance = math.inf
    for i, a in enumerate(polygon):
        b = polygon[(i+1) % len(polygon)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        t = max(0., min(1., ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        distance = min(distance, math.hypot(x-a[0]-t*dx, y-a[1]-t*dy))
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    if distance <= max(1e-8, margin):
        return 'boundary'
    return 'inside' if inside else 'outside'


def locate_robot_regions(pose: dict, zones: list[dict]) -> dict:
    if pose.get('frame_id') != 'map':
        return {'status':'indeterminate','reason':'robot_pose_frame_mismatch','zones':[]}
    try:
        point = [float(pose[k]) for k in ('x','y','z')]
    except (KeyError,ValueError,TypeError,OverflowError):
        return {'status':'indeterminate','reason':'invalid_robot_pose','zones':[]}
    if not all(math.isfinite(v) for v in point):
        return {'status':'indeterminate','reason':'invalid_robot_pose','zones':[]}
    hits, boundaries = [], []
    for zone in zones:
        state = polygon_location((point[0],point[1]),zone['vertices'],zone['boundary_margin_m'])
        record = {'id':zone['id'],'name':zone['name'],'access_level':zone.get('access_level')}
        if state == 'inside': hits.append(record)
        elif state == 'boundary': boundaries.append(record)
    position = {'map_position':point,'robot_map_position':point,
                'robot_pose_timestamp':pose.get('timestamp'),'robot_pose_source':pose.get('source'),
                'robot_frame_id':pose['frame_id'],'robot_source_frame':pose.get('source_frame')}
    if boundaries:
        return {**position,'status':'indeterminate','reason':'region_boundary','zones':hits+boundaries}
    if hits:
        return {**position,'status':'located','zones':hits}
    return {**position,'status':'outside','reason':'outside_controlled_regions','zones':[]}
