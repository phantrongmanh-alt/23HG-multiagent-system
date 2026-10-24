# -*- coding: utf-8 -*-
"""
HÌNH HỌC DÙNG CHUNG cho skill dựng hình và Validator (shapely).

Mọi hàm nhận ProjectStore và trả None khi đối tượng chưa đủ số liệu (thiếu kích thước, trục chưa có
toạ độ) — người gọi phải ghi đối tượng đó vào danh sách "bỏ qua kèm lý do", không được bỏ im lặng.

Quy ước tường: tim tường từ start → end; u = vectơ đơn vị dọc tường, n = pháp tuyến TRÁI (xoay u +90°).
Ở đầu tường gặp tường khác, hình chữ nhật tường được kéo dài thêm nửa chiều dày lớn nhất của các tường
đi qua điểm đó để góc/ngã ba khép kín; đầu tự do không kéo dài.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point as ShPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from tools.cad_drafting.store import Column, Furniture, Opening, ProjectStore, Room, StairFlight, Wall

TOL = 1.0          # mm — dung sai coi hai điểm trùng nhau / điểm nằm trên đường
Point = Tuple[float, float]


# ── vectơ ────────────────────────────────────────────────────────────────────

def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Point, k: float) -> Point:
    return (a[0] * k, a[1] * k)


def length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def unit(a: Point) -> Point:
    n = length(a)
    if n == 0:
        raise ValueError("vectơ 0")
    return (a[0] / n, a[1] / n)


def left_normal(u: Point) -> Point:
    return (-u[1], u[0])


def angle_deg(u: Point) -> float:
    return math.degrees(math.atan2(u[1], u[0])) % 360.0


def dir_from_angle(deg: float) -> Point:
    a = math.radians(deg)
    return (math.cos(a), math.sin(a))


def dist_point_segment(p: Point, a: Point, b: Point) -> float:
    ab = sub(b, a)
    L2 = ab[0] ** 2 + ab[1] ** 2
    if L2 == 0:
        return length(sub(p, a))
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / L2))
    return length(sub(p, add(a, mul(ab, t))))


def rect_polygon(origin: Point, u: Point, a_len: float, n: Point, b_from: float, b_to: float) -> Polygon:
    """Hình chữ nhật: dọc u từ 0 → a_len, dọc n từ b_from → b_to, tính từ origin."""
    p0 = add(origin, mul(n, b_from))
    p1 = add(p0, mul(u, a_len))
    p2 = add(p1, mul(n, b_to - b_from))
    p3 = add(p0, mul(n, b_to - b_from))
    return Polygon([p0, p1, p2, p3])


# ── tường ────────────────────────────────────────────────────────────────────

def wall_axis(store: ProjectStore, wall: Wall) -> Optional[Tuple[Point, Point]]:
    a, b = store.point(wall.start), store.point(wall.end)
    if a is None or b is None or length(sub(b, a)) < TOL:
        return None
    return a, b


def wall_reason(store: ProjectStore, wall: Wall) -> str:
    """Lý do tường chưa vẽ được ("" nếu vẽ được)."""
    if wall.thickness is None:
        return "thiếu chiều dày tường"
    if wall.thickness <= 0:
        return "chiều dày tường ≤ 0"
    for ref in (wall.start, wall.end):
        p, why = store.point_or_reason(ref)
        if p is None:
            return why
    a, b = store.point(wall.start), store.point(wall.end)
    if length(sub(b, a)) < TOL:
        return "tường dài 0"
    return ""


def _walls_through(store: ProjectStore, p: Point, exclude: Wall) -> List[Wall]:
    out = []
    for w in store.walls:
        if w is exclude or wall_reason(store, w):
            continue
        a, b = wall_axis(store, w)
        if dist_point_segment(p, a, b) <= TOL:
            out.append(w)
    return out


def wall_polygon(store: ProjectStore, wall: Wall) -> Optional[Polygon]:
    if wall_reason(store, wall):
        return None
    a, b = wall_axis(store, wall)
    u = unit(sub(b, a))
    n = left_normal(u)
    ext_a = max((w.thickness / 2.0 for w in _walls_through(store, a, wall)), default=0.0)
    ext_b = max((w.thickness / 2.0 for w in _walls_through(store, b, wall)), default=0.0)
    start = sub(a, mul(u, ext_a))
    total = length(sub(b, a)) + ext_a + ext_b
    t = float(wall.thickness)
    return rect_polygon(start, u, total, n, -t / 2.0, t / 2.0)


def walls_union(store: ProjectStore) -> BaseGeometry:
    polys = [p for p in (wall_polygon(store, w) for w in store.walls) if p is not None]
    return unary_union(polys) if polys else Polygon()


# ── ô cửa ────────────────────────────────────────────────────────────────────

def opening_reason(store: ProjectStore, op: Opening) -> str:
    wall = store.get("walls", op.wall_id)
    if wall is None:
        return f"không có tường '{op.wall_id}'"
    why = wall_reason(store, wall)
    if why:
        return f"tường {wall.id}: {why}"
    if op.offset is None:
        return "thiếu vị trí cửa (offset)"
    if op.width is None:
        return "thiếu bề rộng cửa"
    if op.width <= 0:
        return "bề rộng cửa ≤ 0"
    return ""


def opening_frame(store: ProjectStore, op: Opening) -> Optional[Dict[str, object]]:
    """Khung hình học của ô cửa: a/b = hai mép trên tim tường (a phía điểm đầu tường), u, n, t (dày tường),
    poly = ô chữ nhật cắt xuyên chiều dày tường. None nếu thiếu số liệu."""
    if opening_reason(store, op):
        return None
    wall = store.get("walls", op.wall_id)
    p0, p1 = wall_axis(store, wall)
    u = unit(sub(p1, p0))
    n = left_normal(u)
    a = add(p0, mul(u, float(op.offset)))
    b = add(a, mul(u, float(op.width)))
    t = float(wall.thickness)
    poly = rect_polygon(a, u, float(op.width), n, -t / 2.0 - 0.5, t / 2.0 + 0.5)
    return {"a": a, "b": b, "u": u, "n": n, "t": t, "wall_length": length(sub(p1, p0)), "poly": poly}


def door_leaves(store: ProjectStore, op: Opening) -> Optional[List[Dict[str, object]]]:
    """Các cánh cửa đi (1 hoặc 2). Mỗi cánh: hinge = điểm bản lề trên MẶT tường phía cánh mở,
    closed = đầu cánh khi đóng (trên mặt tường), open = đầu cánh khi mở 90°, r = bề rộng cánh,
    start_angle/end_angle = cung mở vẽ ngược chiều kim đồng hồ (độ). None nếu không phải cửa đi / thiếu số liệu."""
    if op.kind != "cua_di":
        return None
    f = opening_frame(store, op)
    if f is None:
        return None
    u, n, t = f["u"], f["n"], f["t"]
    side = n if op.opens_to == "trai" else mul(n, -1.0)
    face = mul(side, t / 2.0)
    if op.leaves == 2:
        r = float(op.width) / 2.0
        specs = [(f["a"], u), (f["b"], mul(u, -1.0))]
    else:
        r = float(op.width)
        specs = [(f["a"], u)] if op.hinge == "dau" else [(f["b"], mul(u, -1.0))]
    leaves = []
    for jamb, closed_dir in specs:
        hinge = add(jamb, face)
        closed = add(hinge, mul(closed_dir, r))
        opened = add(hinge, mul(side, r))
        a_closed, a_open = angle_deg(closed_dir), angle_deg(side)
        if round((a_open - a_closed) % 360.0, 6) == 90.0:
            start, end = a_closed, a_open
        else:
            start, end = a_open, a_closed
        leaves.append({"hinge": hinge, "closed": closed, "open": opened, "r": r,
                       "start_angle": start, "end_angle": end})
    return leaves


def door_swing_polygon(store: ProjectStore, op: Opening, segments: int = 16) -> Optional[Polygon]:
    """Vùng quét của cánh cửa đi (hợp các góc phần tư). None nếu không phải cửa đi / thiếu số liệu."""
    leaves = door_leaves(store, op)
    if not leaves:
        return None
    parts = []
    for lf in leaves:
        cx, cy = lf["hinge"]
        a0, a1 = math.radians(lf["start_angle"]), math.radians(lf["end_angle"])
        if a1 < a0:
            a1 += 2 * math.pi
        pts = [(cx, cy)] + [(cx + lf["r"] * math.cos(a0 + (a1 - a0) * i / segments),
                             cy + lf["r"] * math.sin(a0 + (a1 - a0) * i / segments)) for i in range(segments + 1)]
        parts.append(Polygon(pts))
    return unary_union(parts)


def openings_union(store: ProjectStore) -> BaseGeometry:
    polys = [f["poly"] for f in (opening_frame(store, o) for o in store.openings) if f is not None]
    return unary_union(polys) if polys else Polygon()


# ── cột ──────────────────────────────────────────────────────────────────────

def column_reason(store: ProjectStore, col: Column) -> str:
    if col.b is None or col.h is None:
        return "thiếu kích thước cột"
    if col.b <= 0 or col.h <= 0:
        return "kích thước cột ≤ 0"
    p, why = store.point_or_reason(f"{col.axis_v}/{col.axis_h}")
    return why if p is None else ""


def column_polygon(store: ProjectStore, col: Column) -> Optional[Polygon]:
    if column_reason(store, col):
        return None
    cx, cy = store.column_center(col)
    b, h = float(col.b), float(col.h)
    return Polygon([(cx - b / 2, cy - h / 2), (cx + b / 2, cy - h / 2),
                    (cx + b / 2, cy + h / 2), (cx - b / 2, cy + h / 2)])


def columns_union(store: ProjectStore) -> BaseGeometry:
    polys = [p for p in (column_polygon(store, c) for c in store.columns) if p is not None]
    return unary_union(polys) if polys else Polygon()


# ── thân tường (để vẽ đường bao và hatch) ───────────────────────────────────

def wall_body(store: ProjectStore) -> BaseGeometry:
    """Phần tường xây thật: hợp các tường − ô cửa − cột."""
    return walls_union(store).difference(openings_union(store)).difference(columns_union(store))


def wall_body_by_kind(store: ProjectStore, kind: str) -> BaseGeometry:
    """Thân tường của một loại ("xay" | "btct"), đã trừ ô cửa và cột."""
    polys = [p for w in store.walls if w.kind == kind for p in [wall_polygon(store, w)] if p is not None]
    if not polys:
        return Polygon()
    return unary_union(polys).difference(openings_union(store)).difference(columns_union(store))


def wall_outline_lines(store: ProjectStore) -> List[List[Point]]:
    """Đường bao thân tường, BỎ các đoạn trùng mặt cột (cột do skill 02 vẽ) — tránh trùng nét."""
    body = wall_body(store)
    if body.is_empty:
        return []
    lines = body.boundary.difference(columns_union(store).boundary)
    return lines_to_paths(lines)


# ── phòng, thang, nội thất ───────────────────────────────────────────────────

def room_polygon(store: ProjectStore, room: Room) -> Optional[Polygon]:
    pts = [store.point(r) for r in room.boundary]
    if len(pts) < 3 or any(p is None for p in pts):
        return None
    poly = Polygon(pts)
    return poly if poly.is_valid and poly.area > 0 else None


def flight_polygon(store: ProjectStore, fl: StairFlight) -> Optional[Polygon]:
    o = store.point(fl.origin)
    if o is None or fl.width is None or fl.going is None or fl.n_treads is None:
        return None
    u = dir_from_angle(fl.angle)
    right = (u[1], -u[0])
    return rect_polygon(o, u, fl.n_treads * float(fl.going), right, 0.0, float(fl.width))


def footprint(insert: Point, size: Tuple[float, float], rotation: float) -> Polygon:
    """Vết chiếm chỗ của block: hình chữ nhật size [X, Y] có góc dưới-trái tại điểm chèn, xoay quanh điểm chèn."""
    x, y = insert
    w, d = size
    rect = Polygon([(x, y), (x + w, y), (x + w, y + d), (x, y + d)])
    return affinity.rotate(rect, rotation, origin=(x, y))


# ── tiện ích chuyển hình shapely → danh sách điểm ───────────────────────────

def lines_to_paths(geom: BaseGeometry) -> List[List[Point]]:
    """LineString/MultiLineString/GeometryCollection → các đường gấp khúc (đã nối đoạn liền nhau)."""
    if geom.is_empty:
        return []
    parts = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if isinstance(g, LineString):
            parts.append(g)
        elif hasattr(g, "geoms"):
            stack.extend(g.geoms)
    if not parts:
        return []
    merged = linemerge(MultiLineString(parts)) if len(parts) > 1 else parts[0]
    lines = [merged] if isinstance(merged, LineString) else list(merged.geoms)
    return [[(float(x), float(y)) for x, y in ln.coords] for ln in lines if ln.length > 0]


def polygon_loops(geom: BaseGeometry) -> List[List[List[Point]]]:
    """Polygon/MultiPolygon → [[vòng ngoài, lỗ 1, lỗ 2...], ...] (mỗi vòng không lặp điểm cuối)."""
    out = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g.is_empty:
            continue
        if isinstance(g, Polygon):
            loops = [list(g.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in g.interiors]
            out.append([[(float(x), float(y)) for x, y in loop] for loop in loops])
        elif hasattr(g, "geoms"):
            stack.extend(g.geoms)
    return out


def shapely_point(p: Point) -> ShPoint:
    return ShPoint(p)
