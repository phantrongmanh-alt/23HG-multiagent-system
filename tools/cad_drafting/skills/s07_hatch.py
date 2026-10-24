# -*- coding: utf-8 -*-
"""
SKILL 07 — HATCH: tô vật liệu cho cột, tường và sàn phòng (vai trò "hatch").

Mẫu hatch lấy theo layers.hatch_params(khoá, tỷ lệ) (tên mẫu, hệ số scale của mẫu, góc); biên lấy theo
geom.polygon_loops — mỗi polygon (vòng ngoài + các lỗ) là MỘT Op hatch. Vòng ngoài ngược chiều kim đồng hồ, lỗ
cùng chiều kim đồng hồ; toạ độ làm tròn 6 chữ số thập phân (mm) để dấu vân tay ổn định.

  - Cột: khoá "cot_btct" (SOLID) theo từng geom.column_polygon               eid "hatch/cot/<id>"
  - Tường: geom.wall_body_by_kind(store, "xay") → "tuong_xay" (ANSI31), "btct" → "tuong_btct" (SOLID). Thân tường
    xây được trừ thêm phần tường BTCT (ở chỗ hai loại giao nhau) để không tô chồng hai mẫu. Polygon sắp theo bao
    hình (min x, min y, max x, max y, diện tích) rồi đánh số            eid "hatch/tuong/<xay|btct>/<i>"
  - Sàn phòng: vùng = geom.room_polygon − geom.walls_union − geom.columns_union − hợp các geom.flight_polygon
    (vế thang không phủ gạch) − vết nội thất (geom.footprint theo size block, để nét gạch không chạy xuyên đồ).
    Khoá room.hatch rỗng → không hatch (không phải lỗi)    eid "hatch/san/<room id>/<i>"
  - Polygon diện tích < 1 mm² (mảnh vụn hình học) bị bỏ, có ghi chú số lượng — KHÔNG im lặng.

eid có tiền tố "07/" do DraftSkill.add gắn. Thiếu số liệu → result.skip, KHÔNG bỏ im lặng:
  - "hatch:cot/<id>": cột thiếu kích thước / trục chưa có toạ độ (kèm khoá nhịp thiếu) / sai cấu trúc.
  - "hatch:tuong/<id>": tường thiếu chiều dày / điểm chưa có toạ độ / sai cấu trúc; loại tường lạ (không có mẫu).
  - "hatch:<room id>": khoá hatch lạ (không có trong HATCH_PATTERNS); phòng thiếu toạ độ / đường bao suy biến;
    vùng sàn rỗng sau khi trừ tường, cột, vế thang.
Ghi chú: số hatch từng nhóm; ô cửa chưa trừ được khỏi hatch tường; vế thang chưa dựng được nên chưa trừ khỏi hatch
sàn; phòng không khai báo hatch; số liệu nội suy CHƯA xác nhận mà hatch dựa vào. Skill không sửa store.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from tools.cad_drafting import geom
from tools.cad_drafting.block_library import get_block
from tools.cad_drafting.layers import HATCH_PATTERNS, hatch_params
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s02_cot import column_unconfirmed_keys
from tools.cad_drafting.skills.s03_tuong import opening_skip_reason, wall_skip_reason, wall_unconfirmed_keys
from tools.cad_drafting.skills.s09_hoan_thien import room_skip_reason, room_unconfirmed_keys
from tools.cad_drafting.store import Column, ProjectStore, StoreError

Point = Tuple[float, float]

MIN_AREA_MM2 = 1.0              # polygon nhỏ hơn coi là mảnh vụn hình học — bỏ, có ghi chú
NDIGITS = 6                     # làm tròn toạ độ biên hatch (mm)
WALL_HATCH = {"xay": "tuong_xay", "btct": "tuong_btct"}   # loại tường → khoá HATCH_PATTERNS
COLUMN_HATCH = "cot_btct"


# ── trợ giúp dùng chung (kiểm thử cũng dùng) ────────────────────────────────

def polygons_of(g: BaseGeometry) -> List[Polygon]:
    """Mọi Polygon trong một hình (Polygon / MultiPolygon / GeometryCollection), bỏ phần rỗng và phần không có
    diện tích (đường, điểm sinh ra khi trừ hình)."""
    out: List[Polygon] = []
    stack = [g]
    while stack:
        x = stack.pop()
        if x is None or x.is_empty:
            continue
        if isinstance(x, Polygon):
            out.append(x)
        elif hasattr(x, "geoms"):
            stack.extend(x.geoms)
    return out


def bbox_key(p: Polygon):
    """Khoá sắp xếp tất định theo bao hình (rồi diện tích)."""
    minx, miny, maxx, maxy = p.bounds
    return (round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3), round(p.area, 3))


def _clean_loop(loop: List[Point]) -> List[Point]:
    """Làm tròn và bỏ điểm lặp liên tiếp (kể cả điểm cuối trùng điểm đầu)."""
    out: List[Point] = []
    for x, y in loop:
        p = (round(x, NDIGITS) + 0.0, round(y, NDIGITS) + 0.0)
        if not out or p != out[-1]:
            out.append(p)
    while len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def hatch_loops(poly: Polygon) -> Optional[List[List[Point]]]:
    """Biên hatch của một polygon: [vòng ngoài (ngược chiều kim đồng hồ), lỗ (cùng chiều kim đồng hồ)...] theo
    geom.polygon_loops. None nếu vòng ngoài suy biến (< 3 điểm sau khi làm tròn); lỗ suy biến thì bỏ lỗ đó."""
    loops = geom.polygon_loops(orient(poly, sign=1.0))
    if not loops:
        return None
    rings = loops[0]
    outer = _clean_loop(rings[0])
    if len(outer) < 3:
        return None
    holes = [h for h in (_clean_loop(r) for r in rings[1:]) if len(h) >= 3]
    return [outer] + holes


def hatch_polygons(g: BaseGeometry) -> Tuple[List[Polygon], int]:
    """(các polygon đủ lớn để hatch, theo thứ tự bao hình; số polygon bị bỏ vì diện tích < MIN_AREA_MM2)."""
    keep: List[Polygon] = []
    dropped = 0
    for p in sorted(polygons_of(g), key=bbox_key):
        if p.area < MIN_AREA_MM2:
            dropped += 1
        else:
            keep.append(p)
    return keep, dropped


def column_skip_reason(store: ProjectStore, col: Column) -> str:
    """Lý do cột chưa hatch được ("" nếu được), kèm khoá số liệu còn thiếu."""
    why = geom.column_reason(store, col)
    if not why:
        return ""
    keys = [f"columns:{col.id}.{f}" for f in ("b", "h") if getattr(col, f) is None]
    for axis in (col.axis_v, col.axis_h):
        try:
            k = store.missing_span_key(axis)
        except (StoreError, ValueError):
            k = ""
        if k and k not in keys:
            keys.append(k)
    return why + (f" (khoá {', '.join(keys)})" if keys else "")


def wall_hatch_skip_reason(store: ProjectStore, wall) -> str:
    """Lý do tường chưa hatch được ("" nếu được): không dựng được hình tường, hoặc loại tường không có mẫu hatch."""
    why = wall_skip_reason(store, wall)
    if why:
        return why
    if wall.kind not in WALL_HATCH:
        return (f"loại tường lạ '{wall.kind}' — không có mẫu hatch (hợp lệ: {', '.join(sorted(WALL_HATCH))})")
    return ""


def flights_union(store: ProjectStore) -> Tuple[BaseGeometry, List[str]]:
    """(hợp các vế thang dựng được, ["<thang>/<i>: lý do"] của vế chưa dựng được)."""
    polys, bad = [], []
    for st in store.stairs:
        for i, fl in enumerate(st.flights):
            why = geom.flight_reason(store, fl)
            p = None if why else geom.flight_polygon(store, fl)
            if p is None:
                bad.append(f"{st.id}/{i}: {why or 'không dựng được hình vế thang'}")
            else:
                polys.append(p)
    return (unary_union(polys) if polys else Polygon()), bad


def furniture_union(store: ProjectStore) -> BaseGeometry:
    """Hợp vết nội thất dựng được (block có size > 0, điểm chèn có toạ độ). Đồ không dựng được do Skill 06 báo."""
    polys = []
    for f in store.furniture:
        block = get_block(f.block, store)
        try:
            ins = store.point(f.insert)
        except StoreError:
            ins = None
        if block is not None and ins is not None and block.size[0] > 0 and block.size[1] > 0:
            polys.append(geom.footprint(ins, (block.size[0], block.size[1]), float(f.rotation)))
    return unary_union(polys) if polys else Polygon()


# ── skill ────────────────────────────────────────────────────────────────────

class HatchSkill(DraftSkill):
    code = "07"
    name = "Hatch"
    reads = ("project", "axes", "columns", "walls", "openings", "rooms", "stairs", "furniture", "blocks")

    def _hatch(self, plan: DrawingPlan, eid: str, poly: Polygon, key: str, scale: int) -> bool:
        loops = hatch_loops(poly)
        if loops is None:
            return False
        pattern, pscale, angle = hatch_params(key, scale)
        self.add(plan, "hatch", "hatch", eid, boundaries=loops, pattern=pattern, pattern_scale=pscale, angle=angle)
        return True

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        scale = int(store.project.scale)
        dropped = {"cot": 0, "tuong": 0, "san": 0}
        doubtful: List[str] = []

        # ── cột ──
        n_col = 0
        bad_cols: List[str] = []
        for col in store.columns:
            why = column_skip_reason(store, col)
            if why:
                result.skip(f"hatch:cot/{col.id}", why)
                bad_cols.append(col.id)
                continue
            poly = geom.column_polygon(store, col)
            if poly is None:
                result.skip(f"hatch:cot/{col.id}", "không dựng được hình cột từ số liệu hiện có")
                bad_cols.append(col.id)
                continue
            if poly.area < MIN_AREA_MM2 or not self._hatch(plan, f"hatch/cot/{col.id}", poly, COLUMN_HATCH, scale):
                dropped["cot"] += 1
                result.skip(f"hatch:cot/{col.id}", "tiết diện cột < 1 mm² — không hatch được")
                continue
            n_col += 1
            keys = column_unconfirmed_keys(store, col)
            if keys:
                doubtful.append(f"cột {col.id} ({', '.join(keys)})")

        # ── tường ──
        drawable_walls = []
        for w in store.walls:
            why = wall_hatch_skip_reason(store, w)
            if why:
                result.skip(f"hatch:tuong/{w.id}", why)
            else:
                drawable_walls.append(w)
                keys = wall_unconfirmed_keys(store, w)
                if keys:
                    doubtful.append(f"tường {w.id} ({', '.join(keys)})")
        polys_by_id = geom.wall_polygons(store)
        btct_raw = unary_union([polys_by_id[w.id] for w in drawable_walls
                                if w.kind == "btct" and w.id in polys_by_id])
        n_wall = {}
        for kind, key in WALL_HATCH.items():
            body = geom.wall_body_by_kind(store, kind)
            if kind == "xay" and not btct_raw.is_empty:
                body = body.difference(btct_raw)
            polys, n_drop = hatch_polygons(body)
            dropped["tuong"] += n_drop
            i = 0
            for poly in polys:
                if self._hatch(plan, f"hatch/tuong/{kind}/{i}", poly, key, scale):
                    i += 1
                else:
                    dropped["tuong"] += 1
            n_wall[kind] = i
        drawable_ids = {w.id for w in drawable_walls}
        for o in store.openings:
            why = opening_skip_reason(store, o)
            if why and o.wall_id in drawable_ids:
                result.notes.append(f"ô cửa {o.id} chưa trừ khỏi hatch tường {o.wall_id} vì {why} — hatch tường "
                                    f"đang phủ liền qua vị trí cửa")
        if bad_cols and drawable_walls:
            result.notes.append("cột chưa dựng được nên chưa trừ khỏi hatch tường/sàn: " + ", ".join(bad_cols))

        # ── sàn phòng ──
        flights, bad_flights = flights_union(store)
        obstacles = unary_union([geom.walls_union(store), geom.columns_union(store), flights,
                                 furniture_union(store)])
        n_floor = 0
        no_hatch: List[str] = []
        solid_floor: List[str] = []
        for room in store.rooms:
            key = room.hatch
            if key is None or key == "":
                no_hatch.append(room.id)
                continue
            if not isinstance(key, str) or key not in HATCH_PATTERNS:
                result.skip(f"hatch:{room.id}", f"khoá hatch sàn lạ {key!r} — không có trong HATCH_PATTERNS "
                                                f"(hợp lệ: {', '.join(sorted(HATCH_PATTERNS))})")
                continue
            why = room_skip_reason(store, room)
            poly = None if why else geom.room_polygon(store, room)
            if poly is None:
                result.skip(f"hatch:{room.id}", why or "không dựng được đa giác phòng từ số liệu hiện có")
                continue
            polys, n_drop = hatch_polygons(poly.difference(obstacles))
            dropped["san"] += n_drop
            i = 0
            for p in polys:
                if self._hatch(plan, f"hatch/san/{room.id}/{i}", p, key, scale):
                    i += 1
                else:
                    dropped["san"] += 1
            if i == 0:
                result.skip(f"hatch:{room.id}", "vùng sàn sau khi trừ tường, cột, vế thang rỗng hoặc chỉ còn mảnh "
                                                f"< {MIN_AREA_MM2:g} mm²")
                continue
            n_floor += 1
            if HATCH_PATTERNS[key]["pattern"] == "SOLID":
                solid_floor.append(f"{room.id} ({key})")
            keys = room_unconfirmed_keys(store, room)
            if keys:
                doubtful.append(f"phòng {room.id} ({', '.join(keys)})")

        # ── ghi chú ──
        result.notes.append(f"hatch cột: {n_col}/{len(store.columns)} cột")
        result.notes.append(f"hatch tường: {len(drawable_walls)}/{len(store.walls)} tường — "
                            f"{n_wall.get('xay', 0)} vùng tường xây, {n_wall.get('btct', 0)} vùng tường BTCT")
        result.notes.append(f"hatch sàn: {n_floor}/{len(store.rooms)} phòng")
        if no_hatch:
            result.notes.append("phòng không khai báo hatch sàn (để trống, không phải lỗi): " + ", ".join(no_hatch))
        if solid_floor:
            result.notes.append("CẢNH BÁO sàn phòng dùng mẫu tô đặc (SOLID): " + ", ".join(solid_floor))
        if bad_flights:
            result.notes.append("vế thang chưa dựng được nên chưa trừ khỏi hatch sàn: " + "; ".join(bad_flights))
        total_drop = sum(dropped.values())
        if total_drop:
            parts = [f"{n} {name}" for name, n in (("cột", dropped["cot"]), ("tường", dropped["tuong"]),
                                                   ("sàn", dropped["san"])) if n]
            result.notes.append(f"bỏ {total_drop} vùng hatch diện tích < {MIN_AREA_MM2:g} mm² hoặc biên suy biến "
                                f"(mảnh vụn hình học): " + ", ".join(parts))
        if doubtful:
            result.notes.append("hatch dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
