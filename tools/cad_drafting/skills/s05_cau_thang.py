# -*- coding: utf-8 -*-
"""
SKILL 05 — CẦU THANG: vế thang, mũi bậc, đường đi + mũi tên, chữ LÊN/XUỐNG, đường cắt, chiếu nghỉ
(vai trò "thang").

Hệ toạ độ của một vế (store.StairFlight): o = điểm gốc (góc đầu vế, mép TRÁI khi đi lên), u = hướng đi lên
(geom.dir_from_angle(angle)), r = bên PHẢI của u; vế dài L = n_treads × going theo u, rộng width theo r — đúng
hình của geom.flight_polygon.

Mỗi vế vẽ được (eid có tiền tố "05/" do DraftSkill.add gắn; i = chỉ số vế, đếm từ 0):
  - pline kín đường bao vế (đỉnh theo geom.flight_polygon)                     eid "thang/<id>/<i>/bao"
  - (n_treads − 1) line mũi bậc ngang hết bề rộng, tại k × going (k = 1..n−1)   eid "thang/<id>/<i>/bac/<k>"
  - pline đường đi dọc tim vế từ giữa bậc đầu (going/2) tới giữa bậc cuối (L − going/2);
    vế chỉ 1 bậc thì đi từ mép đầu tới mép cuối vế                              eid "thang/<id>/<i>/duong_di"
  - pline kín mũi tên (tam giác) ở cuối đường đi, dài 2,5 mm giấy × tỷ lệ, nửa bề rộng = 1/3 chiều dài;
    vế quá ngắn/hẹp thì thu nhỏ mũi tên và ghi CẢNH BÁO                         eid "thang/<id>/<i>/mui_ten"
Mỗi thang (không lặp theo vế):
  - text stair.label (cao layers.text_height("thang", tỷ lệ), MIDDLE_CENTER) đặt NGOÀI mép đầu của vế đầu tiên
    vẽ được, trên tim vế, cách mép 1 mm giấy; chữ chạy dọc mũi bậc, luôn đọc được    eid "thang/<id>/chu"
  - đường cắt thang (pline gấp khúc zigzag) xiên qua vế ĐẦU TIÊN (chỉ số 0) quanh 60 % chiều dài vế: mặt bằng
    cắt một lần ở cao độ khoảng 1,2–1,5 m nên chỉ vế đầu bị cắt; vế 0 chưa vẽ được thì KHÔNG vẽ đường cắt
    và ghi chú lý do                                                             eid "thang/<id>/cat"
  - mỗi chiếu nghỉ (stair.landings[j]) → pline kín                               eid "thang/<id>/chieu_nghi/<j>"

Thiếu số liệu → result.skip, KHÔNG bỏ im lặng:
  - "thang:<id>/<i>": lý do kể mọi thứ còn thiếu/sai của vế (width / going / n_treads kèm khoá
    "stairs:<id>.flights[i].<trường>", giá trị ≤ 0, số bậc không nguyên, điểm gốc chưa có toạ độ kèm khoá nhịp
    trục thiếu, tham chiếu trục sai cấu trúc).
  - "thang:<id>/chieu_nghi/<j>": điểm chiếu nghỉ chưa có toạ độ / < 3 điểm / đa giác suy biến.
  - "thang:<id>/chu": nhãn thang rỗng.
Ghi chú: "<id> vế <i+1>: bậc: n × going, cao bậc riser" (thiếu riser thì ghi rõ chưa có); số vế/chiếu nghỉ đã
vẽ; vế dựa trên số liệu nội suy CHƯA xác nhận. Va chạm thang–tường do Validator kiểm. Skill không sửa store.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Polygon

from tools.cad_drafting import geom
from tools.cad_drafting.layers import paper_to_model, text_height
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s01_luoi_truc import axis_unconfirmed_keys
from tools.cad_drafting.skills.s03_tuong import ref_axis_names
from tools.cad_drafting.skills.s04_cua import readable_angle
from tools.cad_drafting.store import SRC_INTERP, ProjectStore, Stair, StairFlight, StoreError

Point = Tuple[float, float]

ARROW_PAPER_MM = 2.5            # mm giấy — chiều dài mũi tên đường đi
ARROW_HALF_WIDTH_RATIO = 1.0 / 3.0
LABEL_GAP_PAPER_MM = 1.0        # mm giấy — chữ nhãn cách mép đầu vế
CUT_AT = 0.60                   # đường cắt ở 60 % chiều dài vế
CUT_SLOPE_DEG = 30.0            # độ xiên của đường cắt so với mũi bậc
CUT_ZIGZAG_PAPER_MM = 1.5       # mm giấy — cỡ nét gấp zigzag giữa đường cắt
CUT_FLIGHT_INDEX = 0            # vế bị mặt cắt bằng cắt qua
NDIGITS = 6                     # làm tròn toạ độ (mm) để bỏ sai số dấu phẩy động của sin/cos


# ── trợ giúp dùng chung (kiểm thử cũng dùng) ────────────────────────────────

def _r(p: Point) -> Point:
    return (round(p[0], NDIGITS) + 0.0, round(p[1], NDIGITS) + 0.0)


def _num(value) -> Optional[float]:
    """Số hữu hạn hoặc None (chuỗi, bool, None, NaN đều coi là không phải số)."""
    if isinstance(value, (str, bytes, bool)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def flight_skip_reason(store: ProjectStore, stair: Stair, i: int) -> str:
    """Lý do vế thứ i chưa vẽ được ("" nếu vẽ được) — kể MỌI số liệu thiếu/sai, kèm khoá số liệu."""
    fl = stair.flights[i]
    key = f"stairs:{stair.id}.flights[{i}]"
    reasons: List[str] = []
    missing = [f for f in ("width", "going", "n_treads") if getattr(fl, f) is None]
    if missing:
        reasons.append("thiếu " + ", ".join(f"{f} (khoá {key}.{f})" for f in missing))
    for f in ("width", "going"):
        v = getattr(fl, f)
        if v is not None and (_num(v) is None or _num(v) <= 0):
            reasons.append(f"{f} = {v!r} phải là số > 0")
    if fl.n_treads is not None:
        n = _num(fl.n_treads)
        if n is None or n != int(n) or n < 1:
            reasons.append(f"n_treads = {fl.n_treads!r} phải là số nguyên ≥ 1")
    if _num(fl.angle) is None:
        reasons.append(f"hướng vế (angle) = {fl.angle!r} không phải số")
    try:
        p, why = store.point_or_reason(fl.origin)
    except StoreError as e:
        p, why = None, f"dữ liệu sai cấu trúc: {e}"
    if p is None:
        keys = [k for k in (store.missing_span_key(a) for a in ref_axis_names(fl.origin)
                            if store.axis_group_of(a) is not None) if k]
        reasons.append(f"điểm gốc {fl.origin!r} chưa có toạ độ: {why}"
                       + (f" (khoá {', '.join(keys)})" if keys else ""))
    if not reasons and geom.flight_polygon(store, fl) is None:   # phòng hờ
        reasons.append("không dựng được hình vế thang từ số liệu hiện có")
    return "; ".join(reasons)


def flight_frame(store: ProjectStore, fl: StairFlight) -> Optional[Dict[str, object]]:
    """Khung hình học của vế: o, u, r (bên phải), L, W, going, n, poly (geom.flight_polygon). None nếu thiếu số liệu."""
    poly = geom.flight_polygon(store, fl)
    if poly is None:
        return None
    o = store.point(fl.origin)
    u = geom.dir_from_angle(float(fl.angle))
    n = int(fl.n_treads)
    going = float(fl.going)
    return {"o": o, "u": u, "r": (u[1], -u[0]), "L": n * going, "W": float(fl.width), "going": going,
            "n": n, "poly": poly}


def _at(f: Dict[str, object], s: float, w: float) -> Point:
    """Điểm cách gốc vế s mm theo hướng đi lên và w mm sang phải."""
    return _r(geom.add(geom.add(f["o"], geom.mul(f["u"], s)), geom.mul(f["r"], w)))


def outline_points(f: Dict[str, object]) -> List[Point]:
    return [_r((float(x), float(y))) for x, y in list(f["poly"].exterior.coords)[:-1]]


def nosing_lines(f: Dict[str, object]) -> List[Tuple[int, Point, Point]]:
    """[(k, p1, p2)] mũi bậc k = 1..n−1 tại k × going, từ mép trái tới mép phải."""
    return [(k, _at(f, k * f["going"], 0.0), _at(f, k * f["going"], f["W"])) for k in range(1, f["n"])]


def walk_line(f: Dict[str, object]) -> Tuple[Point, Point]:
    """Đường đi dọc tim vế: giữa bậc đầu → giữa bậc cuối (vế 1 bậc: mép đầu → mép cuối)."""
    if f["n"] >= 2:
        s0, s1 = f["going"] / 2.0, f["L"] - f["going"] / 2.0
    else:
        s0, s1 = 0.0, f["L"]
    return _at(f, s0, f["W"] / 2.0), _at(f, s1, f["W"] / 2.0)


def arrow_points(f: Dict[str, object], scale: int) -> Tuple[List[Point], float, float]:
    """(tam giác mũi tên [đỉnh, chân phải, chân trái], chiều dài dùng, chiều dài chuẩn). Chiều dài chuẩn 2,5 mm
    giấy × tỷ lệ; thu nhỏ để không dài hơn đường đi và không rộng quá 80 % bề rộng vế."""
    a_nom = paper_to_model(ARROW_PAPER_MM, scale)
    p0, p1 = walk_line(f)
    walk = geom.length(geom.sub(p1, p0))
    a = min(a_nom, walk, 0.8 * f["W"] / (2.0 * ARROW_HALF_WIDTH_RATIO))
    u, r = f["u"], f["r"]
    base = geom.sub(p1, geom.mul(u, a))
    half = a * ARROW_HALF_WIDTH_RATIO
    pts = [_r(p1), _r(geom.add(base, geom.mul(r, half))), _r(geom.sub(base, geom.mul(r, half)))]
    return pts, a, a_nom


def cut_line_points(f: Dict[str, object], scale: int) -> List[Point]:
    """Đường cắt thang: đoạn xiên CUT_SLOPE_DEG so với mũi bậc, đi hết bề rộng vế, tâm ở CUT_AT × L, có nét gấp
    zigzag ở giữa. Mọi điểm nằm trong vế (độ xiên và nét gấp được thu nhỏ cho vế ngắn)."""
    L, W = f["L"], f["W"]
    sc = CUT_AT * L
    rise = min((W / 2.0) * math.tan(math.radians(CUT_SLOPE_DEG)), 0.3 * L)    # lệch theo u ở mỗi mép
    z = min(paper_to_model(CUT_ZIGZAG_PAPER_MM, scale), 0.1 * L, W / 4.0)      # cỡ nét gấp
    # trong hệ (s, w): d = hướng đường cắt (đơn vị), e = pháp tuyến của nó
    dl = math.hypot(2.0 * rise, W)
    d = (2.0 * rise / dl, W / dl)
    e = (-d[1], d[0])

    def at(t: float, k: float) -> Point:            # t dọc đường cắt từ tâm, k theo pháp tuyến
        s = sc + d[0] * t + e[0] * k
        w = W / 2.0 + d[1] * t + e[1] * k
        return _at(f, s, w)

    half = dl / 2.0
    return [at(-half, 0.0), at(-z / 2.0, 0.0), at(-z / 6.0, z / 2.0), at(z / 6.0, -z / 2.0),
            at(z / 2.0, 0.0), at(half, 0.0)]


def label_placement(f: Dict[str, object], scale: int) -> Dict[str, object]:
    """Vị trí chữ nhãn: ngoài mép đầu vế, trên tim vế, cách mép 1 mm giấy; chữ chạy dọc mũi bậc."""
    h = text_height("thang", scale)
    gap = paper_to_model(LABEL_GAP_PAPER_MM, scale)
    return {"insert": _at(f, -(gap + h / 2.0), f["W"] / 2.0), "height": h, "rotation": readable_angle(f["r"])}


def landing_points(store: ProjectStore, landing) -> Tuple[List[Point], str]:
    """(các đỉnh chiếu nghỉ, "") hoặc ([], lý do chưa vẽ được)."""
    pts: List[Point] = []
    problems: List[str] = []
    for ref in landing:
        try:
            p, why = store.point_or_reason(ref)
        except StoreError as e:
            p, why = None, f"dữ liệu sai cấu trúc: {e}"
        if p is None:
            keys = [k for k in (store.missing_span_key(a) for a in ref_axis_names(ref)
                                if store.axis_group_of(a) is not None) if k]
            problems.append(f"điểm {ref!r} chưa có toạ độ: {why}" + (f" (khoá {', '.join(keys)})" if keys else ""))
        else:
            pts.append(_r(p))
    if problems:
        return [], "; ".join(problems)
    if len(pts) < 3:
        return [], f"chiếu nghỉ cần ít nhất 3 điểm, có {len(pts)}"
    poly = Polygon(pts)
    if not poly.is_valid or poly.area <= 0:
        return [], "đa giác chiếu nghỉ suy biến (diện tích 0 hoặc tự cắt)"
    return pts, ""


def flight_unconfirmed_keys(store: ProjectStore, stair: Stair, i: int) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà vế thứ i phụ thuộc (thang, trường của vế, nhịp trục của điểm gốc)."""
    keys: List[str] = []
    if stair.prov.source == SRC_INTERP and not stair.prov.confirmed:
        keys.append(f"stairs:{stair.id}")
    for name, p in sorted(stair.field_prov.items()):
        if name.startswith(f"flights[{i}].") and p.source == SRC_INTERP and not p.confirmed:
            keys.append(f"stairs:{stair.id}.{name}")
    for a in ref_axis_names(stair.flights[i].origin):
        for k in axis_unconfirmed_keys(store, a):
            if k not in keys:
                keys.append(k)
    return keys


def tread_note(stair: Stair, i: int) -> str:
    fl = stair.flights[i]
    text = f"{stair.id} vế {i + 1}: bậc: {int(fl.n_treads)} × {float(fl.going):g}"
    if fl.riser is not None and _num(fl.riser) is not None:
        return text + f", cao bậc {float(fl.riser):g}"
    return text + " (chưa có cao bậc riser)"


# ── skill ────────────────────────────────────────────────────────────────────

class CauThangSkill(DraftSkill):
    code = "05"
    name = "Cầu thang"
    reads = ("project", "axes", "stairs")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        scale = int(store.project.scale)
        n_flights = sum(len(st.flights) for st in store.stairs)
        n_landings = sum(len(st.landings) for st in store.stairs)
        drawn_flights = drawn_landings = 0
        doubtful: List[str] = []
        for st in store.stairs:
            base = f"thang/{st.id}"
            first: Optional[Dict[str, object]] = None
            for i, fl in enumerate(st.flights):
                why = flight_skip_reason(store, st, i)
                f = None if why else flight_frame(store, fl)
                if f is None:
                    result.skip(f"thang:{st.id}/{i}", why or "không dựng được hình vế thang từ số liệu hiện có")
                    if i == CUT_FLIGHT_INDEX:
                        result.notes.append(f"{st.id}: chưa vẽ đường cắt thang vì vế {i + 1} chưa vẽ được")
                    continue
                fb = f"{base}/{i}"
                self.add(plan, "pline", "thang", f"{fb}/bao", points=outline_points(f), closed=True)
                for k, p1, p2 in nosing_lines(f):
                    self.add(plan, "line", "thang", f"{fb}/bac/{k}", p1=p1, p2=p2)
                p0, p1 = walk_line(f)
                self.add(plan, "pline", "thang", f"{fb}/duong_di", points=[p0, p1], closed=False)
                arrow, a, a_nom = arrow_points(f, scale)
                self.add(plan, "pline", "thang", f"{fb}/mui_ten", points=arrow, closed=True)
                if a < a_nom - 1e-9:
                    result.notes.append(f"CẢNH BÁO {st.id} vế {i + 1}: vế ngắn/hẹp, mũi tên thu nhỏ còn {a:g} mm "
                                        f"(chuẩn {a_nom:g} mm)")
                if i == CUT_FLIGHT_INDEX:
                    self.add(plan, "pline", "thang", f"{base}/cat", points=cut_line_points(f, scale), closed=False)
                if first is None:
                    first = f
                drawn_flights += 1
                result.notes.append(tread_note(st, i))
                keys = flight_unconfirmed_keys(store, st, i)
                if keys:
                    doubtful.append(f"{st.id} vế {i + 1} ({', '.join(keys)})")
            if first is not None:
                label = (st.label or "").strip()
                if label:
                    lp = label_placement(first, scale)
                    self.add(plan, "text", "thang", f"{base}/chu", insert=lp["insert"], text=label,
                             height=lp["height"], rotation=lp["rotation"], align="MIDDLE_CENTER")
                else:
                    result.skip(f"thang:{st.id}/chu", "nhãn thang (label) rỗng — không ghi được LÊN/XUỐNG")
            for j, landing in enumerate(st.landings):
                pts, why = landing_points(store, landing)
                if why:
                    result.skip(f"thang:{st.id}/chieu_nghi/{j}", why)
                    continue
                self.add(plan, "pline", "thang", f"{base}/chieu_nghi/{j}", points=pts, closed=True)
                drawn_landings += 1
        result.notes.append(f"đã vẽ {drawn_flights}/{n_flights} vế thang, {drawn_landings}/{n_landings} chiếu nghỉ "
                            f"({len(store.stairs)} thang)")
        if doubtful:
            result.notes.append("vế thang dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
