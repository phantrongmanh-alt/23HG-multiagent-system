# -*- coding: utf-8 -*-
"""
SKILL 08 — KÍCH THƯỚC: ghi kích thước bằng DIMENSION nguyên bản (Op dim_linear, vai trò "dim").

KHÔNG vẽ kích thước giả bằng line + text (skills/aec-cad-automation/SKILL.md mục 6). Kiểu kích thước =
layers.dimstyle_name(tỷ lệ) ("TCVN_KT_100" ở 1:100). KHÔNG ghi text_override — chữ là số đo hình học thật.

Bố cục theo SKILL.md mục 6B: 3 cấp, 4 phía ("duoi", "tren", "trai", "phai").
  - Khung trục = [min, max] toạ độ các trục ĐÃ CÓ toạ độ của mỗi nhóm (giống Skill 01).
  - Đường kích thước cấp k đặt ra ngoài cạnh khung trục một khoảng paper_to_model(LAYOUT_PAPER_MM["dim_level_k"]).
  - Phía dưới / trên: angle 0 (đo theo X) các trục V; điểm đo cấp 2, 3 = giao trục V với cạnh dưới / trên của
    khung trục H. Phía trái / phải: angle 90 (đo theo Y) các trục H; điểm đo = giao trục H với cạnh trái / phải
    của khung trục V.

Cấp 3 (tổng): trục đầu → trục cuối của nhóm, chỉ khi MỌI trục của nhóm có toạ độ; nếu không →
  result.skip("dim/L3/<phía>", lý do kèm khoá nhịp thiếu). Kích thước tổng ghi trong store (overall) KHÔNG dùng để
  suy ngược nhịp thiếu; nếu có mà lệch tổng nhịp > geom.TOL → ghi CẢNH BÁO.
Cấp 2 (nhịp trục): mỗi cặp trục liền kề đều có toạ độ; cặp thiếu → result.skip("dim/L2/<phía>/<i>", lý do)
  (i = chỉ số nhịp, khớp khoá axes:<V|H>.spans[i]).
Cấp 1 (chi tiết): tường nằm trên trục NGOÀI CÙNG phía đó (hai đầu tim tường cách đường trục ≤ geom.TOL) → chuỗi
  điểm gồm: các trục cùng phương đo nằm trên đoạn tường + hai mép mỗi ô cửa (geom.opening_frame) + mép ngoài tường
  ở hai đầu (biên geom.wall_polygon dọc tường — đã kéo dài nửa chiều dày tường vuông góc, tức mặt ngoài tường vuông
  góc). Đầu tường nối tiếp một tường thẳng hàng khác trên cùng trục không phải mép ngoài nên không lấy. Điểm đo đặt
  trên MẶT NGOÀI tường (chân gióng bắt đầu từ mặt tường). Sắp, bỏ điểm trùng (≤ geom.TOL; khi trùng ưu tiên trục →
  đầu tường → mép cửa), ghi kích thước từng đoạn liên tiếp.
  - Ô cửa thiếu số liệu → result.notes (ô cửa đó do Skill 04 bỏ qua kèm lý do).
  - Trục ngoài cùng chưa xác định được (còn trục chưa có toạ độ ở phía đó) hoặc không có tường dựng được trên trục
    ngoài cùng → result.skip("dim/L1/<phía>", lý do).
  - Cột trên trục ngoài cùng nhô ra ngoài mặt tường → CẢNH BÁO (cấp 1 chưa ghi mép cột).
Nhóm trục thiếu hẳn / nhóm kia không có trục nào có toạ độ (không biết đặt đường kích thước ở đâu) →
  result.skip("dim/<phía>", lý do).

eid (đã có tiền tố "08/" do DraftSkill.add gắn): "dim/L<k>/<phía>/<i>".
  Cấp 2: i = chỉ số nhịp; cấp 3: i = 0; cấp 1: i = số thứ tự đoạn trong chuỗi (từ trái sang / dưới lên).

Số liệu nội suy CHƯA xác nhận (store.unconfirmed()) vẫn được ghi kích thước (Skill 10 đánh dấu) — result.notes liệt
kê từng khoá nội suy và các kích thước phụ thuộc nó. Phụ thuộc được TÍNH: mỗi toạ độ dọc phương đo là tổng có hệ số
của các số liệu (nhịp trục, offset/bề rộng cửa, chiều dày tường); một kích thước phụ thuộc khoá k khi hệ số của k ở
hai điểm đo khác nhau. Nội suy cả đối tượng (khoá "walls:W1" không kèm trường) chưa lần theo từng kích thước.

Skill không sửa store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import LineString

from tools.cad_drafting import geom
from tools.cad_drafting.layers import LAYOUT_PAPER_MM, dimstyle_name, paper_to_model
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.store import AxisGroup, ProjectStore, Wall

Point = Tuple[float, float]

SIDE_ORDER = ("duoi", "tren", "trai", "phai")
# phía → nhóm trục được đo, nhóm trục cho cạnh khung, cạnh (min | max), góc đường kích thước
SIDES: Dict[str, Dict[str, Any]] = {
    "duoi": {"group": "V", "edge_group": "H", "edge": "min", "angle": 0.0},
    "tren": {"group": "V", "edge_group": "H", "edge": "max", "angle": 0.0},
    "trai": {"group": "H", "edge_group": "V", "edge": "min", "angle": 90.0},
    "phai": {"group": "H", "edge_group": "V", "edge": "max", "angle": 90.0},
}
SIDE_NAME = {"duoi": "phía dưới", "tren": "phía trên", "trai": "phía trái", "phai": "phía phải"}
LEVELS = (1, 2, 3)

_RANK_AXIS, _RANK_END, _RANK_OPENING = 0, 1, 2     # ưu tiên giữ khi hai điểm chuỗi cấp 1 trùng nhau
_COEF_EPS = 1e-9
_REF_AXES = re.compile(r"^\s*([^/@\s]+)\s*/\s*([^/@\s]+)")


# ── trợ giúp dùng chung (Skill 10 và kiểm thử cũng dùng) ────────────────────

def known_axes(group: Optional[AxisGroup]) -> List[Tuple[str, float]]:
    """(tên, toạ độ) các trục đã có toạ độ của nhóm, theo thứ tự trong nhóm."""
    if group is None:
        return []
    return [(n, float(o)) for n, o in zip(group.names, group.offsets()) if o is not None]


def axis_frames(store: ProjectStore) -> Dict[str, Optional[Tuple[float, float]]]:
    """Khung trục {"V": (xmin, xmax) | None, "H": (ymin, ymax) | None} — chỉ tính trên trục đã có toạ độ."""
    out: Dict[str, Optional[Tuple[float, float]]] = {}
    for o in ("V", "H"):
        known = known_axes(store.axes.get(o))
        out[o] = (min(v for _, v in known), max(v for _, v in known)) if known else None
    return out


def side_sign(side: str) -> float:
    """−1 nếu phía nằm về phía toạ độ nhỏ (dưới, trái), +1 nếu về phía toạ độ lớn (trên, phải)."""
    return -1.0 if SIDES[side]["edge"] == "min" else 1.0


def frame_edge(store: ProjectStore, side: str,
               frames: Optional[Dict[str, Optional[Tuple[float, float]]]] = None) -> Optional[float]:
    """Toạ độ cạnh khung trục của một phía (y cho dưới/trên, x cho trái/phải); None nếu nhóm kia chưa có trục nào."""
    frames = frames if frames is not None else axis_frames(store)
    fr = frames.get(SIDES[side]["edge_group"])
    if fr is None:
        return None
    return fr[0] if SIDES[side]["edge"] == "min" else fr[1]


def dim_line_position(store: ProjectStore, side: str, level: int,
                      frames: Optional[Dict[str, Optional[Tuple[float, float]]]] = None) -> Optional[float]:
    """Toạ độ đường kích thước cấp `level` của một phía (y cho dưới/trên, x cho trái/phải); None nếu chưa xác định."""
    edge = frame_edge(store, side, frames)
    if edge is None:
        return None
    d = paper_to_model(LAYOUT_PAPER_MM[f"dim_level_{int(level)}"], int(store.project.scale))
    return edge + side_sign(side) * d


def side_point(side: str, s: float, t: float) -> Point:
    """Điểm từ toạ độ dọc phương đo s và toạ độ vuông góc t của một phía."""
    return (s, t) if SIDES[side]["group"] == "V" else (t, s)


FACE_PROBE_MM = 1e-3   # dò mép ngoài trên đường song song mặt ngoài, lùi vào trong 0,001 mm (tránh trùng biên đa giác)


def face_extent(poly, meas: str, across_value: float) -> Tuple[float, float]:
    """(min, max) dọc phương đo của phần tường nằm trên đường mặt ngoài (across = across_value). Với mối nối xiên,
    bao hình đa giác có thể là mũi vát ở MẶT TRONG — phải lấy giao với chính đường mặt ngoài mới ra mép ngoài thật."""
    minx, miny, maxx, maxy = poly.bounds
    far = 1e6
    if meas == "V":
        probe = LineString([(minx - far, across_value), (maxx + far, across_value)])
    else:
        probe = LineString([(across_value, miny - far), (across_value, maxy + far)])
    inter = poly.intersection(probe)
    if inter.is_empty:
        return (minx, maxx) if meas == "V" else (miny, maxy)
    ix0, iy0, ix1, iy1 = inter.bounds
    return (ix0, ix1) if meas == "V" else (iy0, iy1)


def along(side: str, p: Point) -> float:
    """Toạ độ của điểm p dọc phương đo của phía (x cho dưới/trên, y cho trái/phải)."""
    return p[0] if SIDES[side]["group"] == "V" else p[1]


def across(side: str, p: Point) -> float:
    """Toạ độ của điểm p vuông góc phương đo (y cho dưới/trên, x cho trái/phải)."""
    return p[1] if SIDES[side]["group"] == "V" else p[0]


def outer_axis(store: ProjectStore, side: str) -> Tuple[Optional[str], Optional[float], str]:
    """(tên, toạ độ, "") của trục NGOÀI CÙNG phía `side` trong nhóm cạnh khung, hoặc (None, None, lý do).

    Mọi trục có toạ độ → trục có toạ độ nhỏ nhất (phía dưới/trái) / lớn nhất (phía trên/phải).
    Còn trục chưa có toạ độ → chỉ xác định được khi các nhịp đã biết đều dương (trục xếp tăng dần) VÀ trục đầu nhóm
    (phía dưới/trái) / cuối nhóm (phía trên/phải) có toạ độ; không đoán trục chưa có toạ độ nằm ở đâu."""
    cfg = SIDES[side]
    g = store.axes.get(cfg["edge_group"])
    if g is None or not g.names:
        return None, None, f"không có nhóm trục {cfg['edge_group']}"
    offs = g.offsets()
    want_max = cfg["edge"] == "max"
    if all(o is not None for o in offs):
        pairs = list(zip(g.names, (float(o) for o in offs)))
        if want_max:
            best = max(v for _, v in pairs)
            name = [n for n, v in pairs if v == best][-1]
        else:
            best = min(v for _, v in pairs)
            name = [n for n, v in pairs if v == best][0]
        return name, best, ""
    if any(s is not None and s <= 0 for s in g.spans):
        return None, None, (f"nhóm trục {g.orientation} có nhịp ≤ 0 và còn trục chưa có toạ độ — chưa xác định được "
                            f"trục ngoài cùng {SIDE_NAME[side]}")
    name = g.names[-1] if want_max else g.names[0]
    off = g.offset_of(name)
    if off is None:
        key = store.missing_span_key(name)
        return None, None, (f"trục ngoài cùng {SIDE_NAME[side]} ({name}) chưa có toạ độ"
                            + (f" (thiếu khoá {key})" if key else ""))
    return name, float(off), ""


def unknown_axis_reason(store: ProjectStore, group: AxisGroup, names: List[str]) -> str:
    """Mô tả các trục chưa có toạ độ kèm khoá nhịp thiếu (không trùng lặp)."""
    keys: List[str] = []
    for n in names:
        k = store.missing_span_key(n)
        if k and k not in keys:
            keys.append(k)
    return (f"trục {', '.join(names)} chưa có toạ độ"
            + (f" (thiếu khoá {', '.join(keys)})" if keys else ""))


# ── phụ thuộc số liệu (để báo kích thước nào dựa trên số liệu nội suy) ──────

def _axis_terms(store: ProjectStore, name: str) -> Dict[str, float]:
    """Toạ độ trục = origin + Σ nhịp trước nó → {khoá nhịp: 1}."""
    g = store.axis_group_of(name)
    if g is None:
        return {}
    return {f"axes:{g.orientation}.spans[{j}]": 1.0 for j in range(g.names.index(name))}


def _ref_terms(store: ProjectStore, ref, orientation: str) -> Dict[str, float]:
    """Các số hạng tạo nên toạ độ X (orientation "V") hoặc Y ("H") của một điểm tham chiếu."""
    if isinstance(ref, (list, tuple)):
        return {}
    m = _REF_AXES.match(str(ref))
    if not m:
        return {}
    for name in m.groups():
        g = store.axis_group_of(name)
        if g is not None and g.orientation == orientation:
            return _axis_terms(store, name)
    return {}


def _plus(base: Dict[str, float], extra: Dict[str, float]) -> Dict[str, float]:
    out = dict(base)
    for k, c in extra.items():
        out[k] = out.get(k, 0.0) + c
    return out


def _depends(p_terms: Dict[str, float], q_terms: Dict[str, float], keys) -> List[str]:
    """Khoá (trong `keys`) mà hiệu q − p phụ thuộc: hệ số ở hai điểm khác nhau."""
    out = []
    for k in sorted(set(p_terms) | set(q_terms)):
        if k in keys and abs(q_terms.get(k, 0.0) - p_terms.get(k, 0.0)) > _COEF_EPS:
            out.append(k)
    return out


# ── chuỗi điểm cấp 1 ─────────────────────────────────────────────────────────

@dataclass
class ChainPoint:
    s: float                                   # toạ độ dọc phương đo
    p: Point                                   # điểm đo (trên mặt ngoài tường)
    rank: int                                  # ưu tiên khi trùng: 0 trục, 1 đầu tường, 2 mép cửa
    label: str
    terms: Dict[str, float] = field(default_factory=dict)


def _ref_mentions(ref, name: str) -> bool:
    if isinstance(ref, (list, tuple)):
        return False
    m = _REF_AXES.match(str(ref))
    return bool(m) and name in m.groups()


def _wall_missing_keys(store: ProjectStore, wall: Wall) -> List[str]:
    keys: List[str] = []
    if wall.thickness is None:
        keys.append(f"walls:{wall.id}.thickness")
    for ref in (wall.start, wall.end):
        if isinstance(ref, (list, tuple)):
            continue
        m = _REF_AXES.match(str(ref))
        if not m:
            continue
        for name in m.groups():
            k = store.missing_span_key(name)
            if k and k not in keys:
                keys.append(k)
    return keys


def _end_ext_wall(store: ProjectStore, wall: Wall, p: Point, ext: float) -> Optional[Wall]:
    """Tường (khác `wall`) đi qua điểm đầu p có nửa chiều dày = ext — tường quyết định mép ngoài ở đầu đó."""
    if ext <= _COEF_EPS:
        return None
    for w in sorted(store.walls, key=lambda x: x.id):
        if w is wall or geom.wall_reason(store, w):
            continue
        a, b = geom.wall_axis(store, w)
        if geom.dist_point_segment(p, a, b) <= geom.TOL and abs(float(w.thickness) / 2.0 - ext) <= 1e-6:
            return w
    return None


def detail_chain(store: ProjectStore, side: str) -> Dict[str, Any]:
    """Chuỗi điểm cấp 1 của một phía (không vẽ).

    Trả về {"axis", "axis_offset", "walls": [id...], "points": [ChainPoint...] (đã sắp, bỏ trùng),
            "notes": [...], "reason": ""}; reason khác "" khi không lập được chuỗi (khi đó points rỗng)."""
    out: Dict[str, Any] = {"axis": None, "axis_offset": None, "walls": [], "points": [], "notes": [], "reason": ""}
    cfg = SIDES[side]
    name, off, why = outer_axis(store, side)
    if name is None:
        out["reason"] = why
        return out
    out["axis"], out["axis_offset"] = name, off
    sign = side_sign(side)
    meas = cfg["group"]
    d = (1.0, 0.0) if meas == "V" else (0.0, 1.0)

    on_axis: List[Wall] = []
    unresolved: List[str] = []
    for w in sorted(store.walls, key=lambda x: x.id):
        why_w = geom.wall_reason(store, w)
        if why_w:
            if _ref_mentions(w.start, name) and _ref_mentions(w.end, name):
                keys = _wall_missing_keys(store, w)
                unresolved.append(f"{w.id} ({why_w}" + (f"; khoá {', '.join(keys)}" if keys else "") + ")")
            continue
        a, b = geom.wall_axis(store, w)
        if abs(across(side, a) - off) <= geom.TOL and abs(across(side, b) - off) <= geom.TOL:
            on_axis.append(w)
    if not on_axis:
        out["reason"] = (f"không có tường nào dựng được nằm trên trục ngoài cùng {name}"
                         + (f": {'; '.join(unresolved)}" if unresolved else ""))
        return out
    if unresolved:
        out["notes"].append(f"cấp 1 {SIDE_NAME[side]}: tường trên trục {name} chưa dựng được nên chuỗi có thể thiếu "
                            f"điểm — {'; '.join(unresolved)}")

    pts: List[ChainPoint] = []
    axes_meas = known_axes(store.axes.get(meas))
    spans_of: Dict[str, Tuple[float, float]] = {}
    for w in on_axis:
        a, b = geom.wall_axis(store, w)
        spans_of[w.id] = (min(along(side, a), along(side, b)), max(along(side, a), along(side, b)))

    def continues(wall_id: str, s_end: float) -> bool:
        """Đầu tường nối tiếp một tường khác cùng nằm trên trục (không phải đầu ngoài cùng của dãy tường)."""
        return any(v != wall_id and lo_v - geom.TOL <= s_end <= hi_v + geom.TOL for v, (lo_v, hi_v) in spans_of.items())

    for w in on_axis:
        out["walls"].append(w.id)
        a, b = geom.wall_axis(store, w)
        u = geom.unit(geom.sub(b, a))
        ud = u[0] * d[0] + u[1] * d[1]
        face_t = off + sign * float(w.thickness) / 2.0
        a_s, b_s = along(side, a), along(side, b)
        lo, hi = min(a_s, b_s), max(a_s, b_s)
        poly = geom.wall_polygon(store, w)
        s_lo, s_hi = face_extent(poly, meas, face_t - sign * FACE_PROBE_MM)
        start_terms = _ref_terms(store, w.start, meas)
        end_terms = _ref_terms(store, w.end, meas)
        lo_ref_terms, hi_ref_terms = (start_terms, end_terms) if ud > 0 else (end_terms, start_terms)
        lo_pt, hi_pt = (a, b) if a_s <= b_s else (b, a)
        for s_val, ext, ref_terms, end_pt, coef, s_end in ((s_lo, lo - s_lo, lo_ref_terms, lo_pt, -0.5, lo),
                                                           (s_hi, s_hi - hi, hi_ref_terms, hi_pt, 0.5, hi)):
            if continues(w.id, s_end):
                continue          # mối nối hai tường thẳng hàng: biên wall_polygon ở đây nằm TRONG tường kia
            terms = dict(ref_terms)
            ew = _end_ext_wall(store, w, end_pt, ext)
            if ew is not None:
                terms = _plus(terms, {f"walls:{ew.id}.thickness": coef})
            elif ext <= _COEF_EPS:
                out["notes"].append(f"cấp 1 {SIDE_NAME[side]}: đầu tường {w.id} tại ({end_pt[0]:g}, {end_pt[1]:g}) là "
                                    f"đầu tự do (không có tường dựng được đi qua) — mép ngoài lấy tại đầu tim tường")
            pts.append(ChainPoint(s_val, side_point(side, s_val, face_t), _RANK_END, f"đầu tường {w.id}", terms))
        for ax_name, ax_off in axes_meas:
            if lo - geom.TOL <= ax_off <= hi + geom.TOL:
                pts.append(ChainPoint(ax_off, side_point(side, ax_off, face_t), _RANK_AXIS, f"trục {ax_name}",
                                      _axis_terms(store, ax_name)))
        for op in sorted((o for o in store.openings if o.wall_id == w.id), key=lambda o: o.id):
            frame = geom.opening_frame(store, op)
            if frame is None:
                out["notes"].append(f"ô cửa {op.id} trên tường {w.id} chưa ghi kích thước cấp 1 {SIDE_NAME[side]}: "
                                    f"{geom.opening_reason(store, op)}")
                continue
            t_a = _plus(start_terms, {f"openings:{op.id}.offset": ud})
            t_b = _plus(t_a, {f"openings:{op.id}.width": ud})
            for edge, terms in (("a", t_a), ("b", t_b)):
                s_val = along(side, frame[edge])
                pts.append(ChainPoint(s_val, side_point(side, s_val, face_t), _RANK_OPENING,
                                      f"mép ô cửa {op.id}", terms))

    pts.sort(key=lambda c: (c.s, c.rank))
    kept: List[ChainPoint] = []
    for c in pts:
        if kept and abs(c.s - kept[-1].s) <= geom.TOL:
            if c.rank < kept[-1].rank:
                kept[-1] = c
            continue
        kept.append(c)
    out["points"] = kept

    # cột trên trục ngoài cùng nhô ra ngoài mặt tường
    face_out = max(sign * (off + sign * float(w.thickness) / 2.0) for w in on_axis)   # mặt tường xa nhất (theo sign)
    for col in sorted(store.columns, key=lambda c: c.id):
        if (col.axis_h if meas == "V" else col.axis_v) != name:
            continue
        poly = geom.column_polygon(store, col)
        if poly is None:
            continue
        minx, miny, maxx, maxy = poly.bounds
        col_out = (maxy if sign > 0 else -miny) if meas == "V" else (maxx if sign > 0 else -minx)
        if col_out - face_out > geom.TOL:
            out["notes"].append(f"CẢNH BÁO cột {col.id} nhô ra ngoài mặt tường {SIDE_NAME[side]} "
                                f"{col_out - face_out:g} mm — cấp 1 chưa ghi mép cột")
    return out


# ── skill ────────────────────────────────────────────────────────────────────

class DimensionSkill(DraftSkill):
    code = "08"
    name = "Kích thước"
    reads = ("project", "axes", "walls", "openings", "columns")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        scale = int(store.project.scale)
        ds = dimstyle_name(scale)
        if ds not in plan.dimstyles:
            result.notes.append(f"CẢNH BÁO plan chưa khai báo kiểu kích thước {ds} (dùng skills.base.new_plan)")
        frames = axis_frames(store)
        unconf = {k for k, _ in store.unconfirmed()}
        deps: Dict[str, List[str]] = {}
        counts = {1: 0, 2: 0, 3: 0}

        def dim(side: str, level: int, i: int, p1: Point, p2: Point, line_t: float, dep_keys: List[str]) -> None:
            cfg = SIDES[side]
            mid_s = (along(side, p1) + along(side, p2)) / 2.0
            eid = f"dim/L{level}/{side}/{i}"
            self.add(plan, "dim_linear", "dim", eid, p1=p1, p2=p2, base=side_point(side, mid_s, line_t),
                     angle=cfg["angle"], dimstyle=ds)
            counts[level] += 1
            for k in dep_keys:
                deps.setdefault(k, []).append(eid)

        for side in SIDE_ORDER:
            cfg = SIDES[side]
            g = store.axes.get(cfg["group"])
            edge = frame_edge(store, side, frames)
            if g is None:
                result.skip(f"dim/{side}", f"không có nhóm trục {cfg['group']} — không ghi được kích thước "
                                           f"{SIDE_NAME[side]}")
                continue
            if edge is None:
                result.skip(f"dim/{side}", f"nhóm trục {cfg['edge_group']} không có trục nào có toạ độ — không xác "
                                           f"định được vị trí đường kích thước {SIDE_NAME[side]}")
                continue
            eg = store.axes.get(cfg["edge_group"])
            if eg is not None and any(o is None for o in eg.offsets()):
                result.notes.append(f"{SIDE_NAME[side]}: cạnh khung trục lấy theo trục {cfg['edge_group']} đã có toạ độ "
                                    f"xa nhất ({edge:g}) — nhóm {cfg['edge_group']} còn trục chưa có toạ độ nên vị trí "
                                    f"đường kích thước phía này sẽ đổi khi đủ số liệu")
            self._axis_levels(store, side, g, edge, frames, unconf, dim, result)
            self._detail_level(store, side, unconf, dim, result)

        for o in ("V", "H"):
            g = store.axes.get(o)
            if g is not None and len(g.names) < 2:
                result.notes.append(f"nhóm trục {o} chỉ có {len(g.names)} trục — không có nhịp / kích thước tổng để ghi")
        result.notes.append(f"đã ghi {sum(counts.values())} kích thước DIMENSION (kiểu {ds}): cấp 1: {counts[1]}, "
                            f"cấp 2: {counts[2]}, cấp 3: {counts[3]}; không có text_override")
        for key in sorted(deps):
            eids = deps[key]
            result.notes.append(f"kích thước ghi theo số liệu NỘI SUY CHƯA xác nhận {key} ({len(eids)} kích thước, "
                                f"Skill 10 đánh dấu): {', '.join(eids)}")

    # ── cấp 2 và cấp 3 ───────────────────────────────────────────────────────

    def _axis_levels(self, store: ProjectStore, side: str, g: AxisGroup, edge: float, frames, unconf, dim,
                     result: SkillResult) -> None:
        offs = g.offsets()
        t2 = dim_line_position(store, side, 2, frames)
        t3 = dim_line_position(store, side, 3, frames)
        for i in range(len(g.spans)):
            n1, n2 = g.names[i], g.names[i + 1]
            o1, o2 = offs[i], offs[i + 1]
            if o1 is None or o2 is None:
                unknown = [n for n, o in ((n1, o1), (n2, o2)) if o is None]
                why = f"nhịp {n1}–{n2}: {unknown_axis_reason(store, g, unknown)}"
                if g.spans[i] is not None:
                    why += f"; nhịp {n1}–{n2} = {float(g.spans[i]):g} mm đã biết nhưng chưa định vị được trục"
                result.skip(f"dim/L2/{side}/{i}", why)
                continue
            if abs(float(o2) - float(o1)) <= geom.TOL:
                result.skip(f"dim/L2/{side}/{i}", f"nhịp {n1}–{n2} = {float(o2) - float(o1):g} mm: hai trục trùng "
                                                  f"nhau, không ghi được kích thước (khoá axes:{g.orientation}.spans[{i}])")
                continue
            key = f"axes:{g.orientation}.spans[{i}]"
            dim(side, 2, i, side_point(side, float(o1), edge), side_point(side, float(o2), edge), t2,
                [key] if key in unconf else [])

        if len(g.names) < 2:
            return
        first, last = g.names[0], g.names[-1]
        unknown = [n for n, o in zip(g.names, offs) if o is None]
        if unknown:
            missing = [f"axes:{g.orientation}.spans[{i}]" for i, s in enumerate(g.spans) if s is None]
            why = (f"kích thước tổng trục {first}–{last}: trục {', '.join(unknown)} chưa có toạ độ"
                   + (f" (thiếu khoá {', '.join(missing)})" if missing else ""))
            if g.overall is not None:
                why += (f"; kích thước tổng có ghi {float(g.overall):g} mm nhưng không tự suy ngược nhịp thiếu — cần "
                        f"nhập nhịp hoặc nội suy qua Skill 00 và xác nhận")
            result.skip(f"dim/L3/{side}", why)
            return
        x0, x1 = float(offs[0]), float(offs[-1])
        if abs(x1 - x0) <= geom.TOL:
            result.skip(f"dim/L3/{side}", f"kích thước tổng trục {first}–{last} = 0 mm: trục đầu và cuối trùng nhau")
            return
        keys = [f"axes:{g.orientation}.spans[{i}]" for i in range(len(g.spans))]
        dim(side, 3, 0, side_point(side, x0, edge), side_point(side, x1, edge), t3, [k for k in keys if k in unconf])
        if g.overall is not None and side in ("duoi", "trai"):
            total = abs(x1 - x0)
            if abs(total - float(g.overall)) > geom.TOL:
                result.notes.append(f"CẢNH BÁO nhóm trục {g.orientation}: kích thước tổng ghi {float(g.overall):g} mm ≠ "
                                    f"tổng nhịp {total:g} mm (khoá axes:{g.orientation}.overall) — kích thước cấp 3 ghi "
                                    f"theo toạ độ trục")

    # ── cấp 1 ────────────────────────────────────────────────────────────────

    def _detail_level(self, store: ProjectStore, side: str, unconf, dim, result: SkillResult) -> None:
        chain = detail_chain(store, side)
        result.notes.extend(chain["notes"])
        if chain["reason"]:
            result.skip(f"dim/L1/{side}", chain["reason"])
            return
        pts: List[ChainPoint] = chain["points"]
        if len(pts) < 2:
            result.skip(f"dim/L1/{side}", f"chuỗi cấp 1 trên trục {chain['axis']} chỉ có {len(pts)} điểm")
            return
        t1 = dim_line_position(store, side, 1)
        for i, (p, q) in enumerate(zip(pts, pts[1:])):
            dim(side, 1, i, p.p, q.p, t1, _depends(p.terms, q.terms, unconf))
