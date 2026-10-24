# -*- coding: utf-8 -*-
"""
HÌNH HỌC DÙNG CHUNG cho skill dựng hình và Validator (shapely).

Mọi hàm nhận ProjectStore và trả None khi đối tượng chưa đủ số liệu (thiếu kích thước, trục chưa có
toạ độ) hoặc dữ liệu sai cấu trúc (tham chiếu trục không tồn tại...) — các hàm *_reason trả lý do tương ứng,
không ném StoreError. Người gọi phải ghi đối tượng đó vào danh sách "bỏ qua kèm lý do", không được bỏ im lặng.

Quy ước tường: tim tường từ start → end; u = vectơ đơn vị dọc tường, n = pháp tuyến TRÁI (xoay u +90°).
Ở đầu tường gặp tường KHÔNG song song, hình tường được kéo dài tới mặt xa của tường kia (vuông góc: t_kia/2;
xiên góc θ: t_kia/(2 sinθ) + t_mình/(2 |tanθ|)) rồi cắt phần kéo dài theo dải tường kia — góc chữ L thành góc vát
khép kín, ngã ba không nhô ra ngoài mặt tường. Tường thẳng hàng nối tiếp (kể cả đổi chiều dày) không kéo dài; đầu
tự do không kéo dài. Ô cửa chỉ khoét tường của chính nó, không khoét tường khác.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point as ShPoint, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from tools.cad_drafting.store import (Column, Furniture, Opening, ProjectStore, Room, StairFlight, StoreError,
                                      Wall)

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


def _num(value) -> Optional[float]:
    """Số hữu hạn hoặc None (giá trị không phải số / NaN / vô cực)."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def wall_reason(store: ProjectStore, wall: Wall) -> str:
    """Lý do tường chưa vẽ được ("" nếu vẽ được)."""
    if wall.thickness is None:
        return "thiếu chiều dày tường"
    t = _num(wall.thickness)
    if t is None:
        return f"chiều dày tường {wall.thickness!r} không phải số"
    if t <= 0:
        return "chiều dày tường ≤ 0"
    for ref in (wall.start, wall.end):
        try:
            p, why = store.point_or_reason(ref)
        except StoreError as e:
            return f"dữ liệu sai cấu trúc: {e}"
        if p is None:
            return why
    a, b = store.point(wall.start), store.point(wall.end)
    if length(sub(b, a)) < TOL:
        return "tường dài 0"
    return ""


def _drawable_axes(store: ProjectStore) -> List[Tuple[Wall, Point, Point]]:
    """(tường, đầu, cuối) của mọi tường vẽ được — tính một lần cho cả lượt dựng hợp tường."""
    out = []
    for w in store.walls:
        if not wall_reason(store, w):
            a, b = wall_axis(store, w)
            out.append((w, a, b))
    return out


MIN_JOIN_SIN = 0.05        # hai tường lệch nhau dưới ~3° coi như thẳng hàng: không kéo dài mối nối


def _walls_through(axes: List[Tuple[Wall, Point, Point]], p: Point, exclude: Wall) -> List[Tuple[Wall, Point, Point]]:
    out = []
    for item in axes:
        w, a, b = item
        if w is exclude:
            continue
        if (min(a[0], b[0]) - TOL <= p[0] <= max(a[0], b[0]) + TOL and
                min(a[1], b[1]) - TOL <= p[1] <= max(a[1], b[1]) + TOL and dist_point_segment(p, a, b) <= TOL):
            out.append(item)
    return out


def _end_extension(p: Point, u_out: Point, t_self: float, others: List[Tuple[Wall, Point, Point]],
                   n: Point) -> List[Polygon]:
    """Phần kéo dài ở đầu tường tại p (u_out hướng ra ngoài tường), đã cắt theo dải từng tường gặp tại p."""
    pieces = []
    for w, a, b in others:
        v = unit(sub(b, a))
        sin_t = abs(u_out[0] * v[1] - u_out[1] * v[0])
        if sin_t < MIN_JOIN_SIN:                       # thẳng hàng / gần song song: không kéo dài
            continue
        cos_t = abs(u_out[0] * v[0] + u_out[1] * v[1])
        t_o = float(w.thickness)
        ext = t_o / (2.0 * sin_t) + t_self * cos_t / (2.0 * sin_t)
        piece = rect_polygon(p, u_out, ext, n, -t_self / 2.0, t_self / 2.0)
        span = length(sub(b, a)) + 2.0 * (ext + t_o + t_self)
        vn = left_normal(v)
        strip = rect_polygon(sub(a, mul(v, ext + t_o + t_self)), v, span, vn, -t_o / 2.0, t_o / 2.0)
        clipped = piece.intersection(strip)
        if not clipped.is_empty:
            pieces.append(clipped)
    return pieces


def wall_polygon(store: ProjectStore, wall: Wall,
                 _axes: Optional[List[Tuple[Wall, Point, Point]]] = None) -> Optional[BaseGeometry]:
    """Hình tường (chữ nhật dọc tim + phần kéo dài ở mối nối). None nếu tường chưa vẽ được."""
    if wall_reason(store, wall):
        return None
    axes = _drawable_axes(store) if _axes is None else _axes
    a, b = wall_axis(store, wall)
    u = unit(sub(b, a))
    n = left_normal(u)
    t = float(wall.thickness)
    parts = [rect_polygon(a, u, length(sub(b, a)), n, -t / 2.0, t / 2.0)]
    parts += _end_extension(a, mul(u, -1.0), t, _walls_through(axes, a, wall), n)
    parts += _end_extension(b, u, t, _walls_through(axes, b, wall), n)
    return parts[0] if len(parts) == 1 else unary_union(parts)


def wall_polygons(store: ProjectStore) -> Dict[str, BaseGeometry]:
    """Hình chữ nhật (đã kéo dài ở chỗ giao) của mọi tường vẽ được, theo mã tường."""
    axes = _drawable_axes(store)
    return {w.id: wall_polygon(store, w, axes) for w, _, _ in axes}


def walls_union(store: ProjectStore) -> BaseGeometry:
    polys = list(wall_polygons(store).values())
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
    if _num(op.offset) is None:
        return f"vị trí cửa {op.offset!r} không phải số"
    if _num(op.width) is None:
        return f"bề rộng cửa {op.width!r} không phải số"
    if float(op.width) <= 0:
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
    if any(_num(v) is None for v in (col.b, col.h, col.dx, col.dy)):
        return "kích thước / độ lệch cột không phải số"
    if float(col.b) <= 0 or float(col.h) <= 0:
        return "kích thước cột ≤ 0"
    try:
        p, why = store.point_or_reason(f"{col.axis_v}/{col.axis_h}")
    except StoreError as e:
        return f"dữ liệu sai cấu trúc: {e}"
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

def _openings_by_wall(store: ProjectStore) -> Dict[str, BaseGeometry]:
    by_wall: Dict[str, List[Polygon]] = {}
    for o in store.openings:
        f = opening_frame(store, o)
        if f is not None:
            by_wall.setdefault(o.wall_id, []).append(f["poly"])
    return {k: unary_union(v) for k, v in by_wall.items()}


def _walls_minus_own_openings(store: ProjectStore, kind: Optional[str] = None) -> List[BaseGeometry]:
    """Mỗi tường trừ ô cửa CỦA CHÍNH NÓ (ô cửa không khoét tường khác ở góc / ngã ba)."""
    holes = _openings_by_wall(store)
    out = []
    for wid, poly in wall_polygons(store).items():
        if kind is not None and store.get("walls", wid).kind != kind:
            continue
        out.append(poly.difference(holes[wid]) if wid in holes else poly)
    return out


def wall_body(store: ProjectStore) -> BaseGeometry:
    """Phần tường xây thật: hợp (mỗi tường − ô cửa của nó) − cột."""
    parts = _walls_minus_own_openings(store)
    return (unary_union(parts) if parts else Polygon()).difference(columns_union(store))


def wall_body_by_kind(store: ProjectStore, kind: str) -> BaseGeometry:
    """Thân tường của một loại ("xay" | "btct"), đã trừ ô cửa (của chính tường đó) và cột."""
    parts = _walls_minus_own_openings(store, kind)
    if not parts:
        return Polygon()
    return unary_union(parts).difference(columns_union(store))


def wall_outline_lines(store: ProjectStore) -> List[List[Point]]:
    """Đường bao thân tường, BỎ các đoạn trùng mặt cột (cột do skill 02 vẽ) — tránh trùng nét."""
    body = wall_body(store)
    if body.is_empty:
        return []
    lines = body.boundary.difference(columns_union(store).boundary)
    return lines_to_paths(lines)


# ── phòng, thang, nội thất ───────────────────────────────────────────────────

def _safe_point(store: ProjectStore, ref) -> Optional[Point]:
    try:
        return store.point(ref)
    except (StoreError, TypeError, ValueError):
        return None


def room_polygon(store: ProjectStore, room: Room) -> Optional[Polygon]:
    pts = [_safe_point(store, r) for r in room.boundary]
    if len(pts) < 3 or any(p is None for p in pts):
        return None
    poly = Polygon(pts)
    return poly if poly.is_valid and poly.area > 0 else None


def flight_reason(store: ProjectStore, fl: StairFlight) -> str:
    """Lý do vế thang chưa dựng được ("" nếu dựng được). Chi tiết kèm khoá: skills/s05_cau_thang.flight_skip_reason."""
    missing = [f for f in ("width", "going", "n_treads") if getattr(fl, f) is None]
    if missing:
        return "thiếu " + ", ".join(missing)
    try:
        width, going, n, angle = float(fl.width), float(fl.going), float(fl.n_treads), float(fl.angle)
    except (TypeError, ValueError):
        return "số liệu vế thang không phải số"
    if not all(math.isfinite(v) for v in (width, going, n, angle)):
        return "số liệu vế thang không hữu hạn"
    if width <= 0 or going <= 0:
        return "bề rộng vế / bề rộng bậc phải > 0"
    if n != int(n) or n < 1:
        return "số bậc phải là số nguyên ≥ 1"
    try:
        p, why = store.point_or_reason(fl.origin)
    except StoreError as e:
        return f"dữ liệu sai cấu trúc: {e}"
    return why if p is None else ""


def flight_polygon(store: ProjectStore, fl: StairFlight) -> Optional[Polygon]:
    if flight_reason(store, fl):
        return None
    o = store.point(fl.origin)
    u = dir_from_angle(float(fl.angle))
    right = (u[1], -u[0])
    return rect_polygon(o, u, int(float(fl.n_treads)) * float(fl.going), right, 0.0, float(fl.width))


def landing_polygon(store: ProjectStore, loop) -> Optional[Polygon]:
    """Chiếu nghỉ (đa giác các điểm tham chiếu). None nếu thiếu toạ độ / suy biến."""
    pts = [_safe_point(store, r) for r in loop]
    if len(pts) < 3 or any(p is None for p in pts):
        return None
    poly = Polygon(pts)
    return poly if poly.is_valid and poly.area > 0 else None


def stair_polygons(store: ProjectStore) -> List[Polygon]:
    """Mọi vế và chiếu nghỉ dựng được (để hatch sàn chừa ra, nhãn và nội thất tránh, Validator kiểm va chạm)."""
    out = []
    for st in store.stairs:
        out += [p for p in (flight_polygon(store, fl) for fl in st.flights) if p is not None]
        out += [p for p in (landing_polygon(store, lp) for lp in st.landings) if p is not None]
    return out


def footprint(insert: Point, size: Tuple[float, float], rotation: float,
              origin: Tuple[float, float] = (0.0, 0.0)) -> Polygon:
    """Vết chiếm chỗ của block: hình chữ nhật size [X, Y] có góc dưới-trái tại điểm chèn + origin (BlockDef.origin —
    góc dưới-trái bao hình so với điểm chèn của block), xoay quanh điểm chèn."""
    x, y = insert
    w, d = size
    x0, y0 = x + float(origin[0]), y + float(origin[1])
    rect = Polygon([(x0, y0), (x0 + w, y0), (x0 + w, y0 + d), (x0, y0 + d)])
    return affinity.rotate(rect, rotation, origin=(x, y))


def block_footprint(store: ProjectStore, furniture: Furniture, block) -> Optional[Polygon]:
    """Vết của một đồ nội thất theo block (BlockDef). None nếu điểm chèn / góc xoay không dùng được hoặc block chưa có
    size — người gọi phải báo (Skill 06 / Validator)."""
    if block is None or block.size[0] <= 0 or block.size[1] <= 0:
        return None
    ins = _safe_point(store, furniture.insert)
    rot = _num(furniture.rotation)
    if ins is None or rot is None:
        return None
    return footprint(ins, (block.size[0], block.size[1]), rot, tuple(getattr(block, "origin", (0.0, 0.0))))


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
