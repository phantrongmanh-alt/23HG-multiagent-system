# -*- coding: utf-8 -*-
"""
SKILL 03 — TƯỜNG: đường bao thân tường (vai trò "tuong") = geom.wall_outline_lines(store), tức hợp các tường
đã trừ ô cửa và cột, BỎ các đoạn trùng mặt cột (cột do Skill 02 vẽ — tránh trùng nét).

Quy ước:
  - Mỗi đường bao → một Op pline; closed=True nếu điểm đầu ≡ điểm cuối (khi đó bỏ điểm lặp cuối).
  - Thứ tự và eid tất định: sắp các đường theo (round(min x), round(min y), số điểm), hoà thì theo dãy toạ độ;
    eid "tuong/outline/<i>" (đã có tiền tố "03/" do DraftSkill.add gắn).
  - Tường thiếu số liệu → result.skip("tuong:<id>", lý do). Lý do bắt đầu bằng geom.wall_reason và kèm khoá số
    liệu còn thiếu (chiều dày, nhịp trục) để người dùng biết phải nhập gì.
  - Ô cửa thiếu số liệu KHÔNG làm bỏ tường: tường vẫn vẽ (liền qua vị trí cửa) và result.notes ghi rõ
    "ô cửa <id> chưa trừ khỏi tường <tường> vì ...". Chính ô cửa đó do Skill 04 bỏ qua kèm lý do.
  - Dữ liệu sai cấu trúc (tham chiếu trục không tồn tại, cú pháp điểm sai — StoreError) chỉ loại đúng đối tượng
    đó khỏi phép tính hình học (kèm lý do), không làm hỏng cả lượt vẽ. Store KHÔNG bị sửa: phép tính chạy trên
    một bản sao nông đã lọc (geometry_view).
  - KHÔNG vẽ hatch tường (Skill 07), không vẽ cửa (Skill 04).

Ghi chú kết quả: số tường vẽ được / tổng, số đường bao, tường và ô cửa dựa trên số liệu nội suy CHƯA xác nhận.
"""

from __future__ import annotations

import copy
import re
from typing import Iterable, List, Tuple

from tools.cad_drafting import geom
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s01_luoi_truc import axis_unconfirmed_keys, missing_span_key
from tools.cad_drafting.store import SRC_INTERP, Entity, Opening, ProjectStore, StoreError, Wall

Point = Tuple[float, float]

CLOSE_EPS = 1e-6          # mm — hai đầu đường bao trùng nhau (≡) thì coi là đường kín

_AXES_IN_REF = re.compile(r"^\s*([^/@\s]+)\s*/\s*([^/@\s]+)")


# ── trợ giúp dùng chung (Skill 04 và kiểm thử cũng dùng) ────────────────────

def ref_axis_names(ref) -> List[str]:
    """Tên các trục mà một tham chiếu điểm dựa vào ("1/A@dx,dy" → ["1", "A"]; toạ độ [x, y] → [])."""
    if isinstance(ref, (list, tuple)):
        return []
    m = _AXES_IN_REF.match(str(ref))
    return [m.group(1), m.group(2)] if m else []


def _add_unique(out: List[str], items: Iterable[str]) -> None:
    for k in items:
        if k not in out:
            out.append(k)


def entity_unconfirmed_keys(collection: str, ent: Entity) -> List[str]:
    """Khoá số liệu NỘI SUY CHƯA XÁC NHẬN của chính một đối tượng (cả đối tượng và từng trường)."""
    keys: List[str] = []
    if ent.prov.source == SRC_INTERP and not ent.prov.confirmed:
        keys.append(f"{collection}:{ent.id}")
    for name, p in sorted(ent.field_prov.items()):
        if p.source == SRC_INTERP and not p.confirmed:
            keys.append(f"{collection}:{ent.id}.{name}")
    return keys


def wall_unconfirmed_keys(store: ProjectStore, wall: Wall) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà vị trí/chiều dày tường phụ thuộc (tường + nhịp trục của hai đầu)."""
    keys = entity_unconfirmed_keys("walls", wall)
    for ref in (wall.start, wall.end):
        for name in ref_axis_names(ref):
            _add_unique(keys, axis_unconfirmed_keys(store, name))
    return keys


def opening_unconfirmed_keys(store: ProjectStore, op: Opening) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà vị trí/bề rộng ô cửa phụ thuộc (ô cửa + tường chứa nó)."""
    keys = entity_unconfirmed_keys("openings", op)
    wall = store.get("walls", op.wall_id)
    if wall is not None:
        _add_unique(keys, wall_unconfirmed_keys(store, wall))
    return keys


def wall_missing_keys(store: ProjectStore, wall: Wall) -> List[str]:
    """Khoá số liệu còn THIẾU làm tường chưa vẽ được (chiều dày, nhịp trục của hai đầu tường)."""
    keys: List[str] = []
    if wall.thickness is None:
        keys.append(f"walls:{wall.id}.thickness")
    for ref in (wall.start, wall.end):
        for name in ref_axis_names(ref):
            group = store.axis_group_of(name)
            found = missing_span_key(group, name) if group is not None else None
            if found is not None:
                _add_unique(keys, [found[0]])
    return keys


def wall_skip_reason(store: ProjectStore, wall: Wall) -> str:
    """Lý do tường chưa vẽ được ("" nếu vẽ được) = geom.wall_reason + khoá số liệu còn thiếu. Dữ liệu sai cấu trúc
    (StoreError) trả về thành lý do thay vì làm hỏng cả lượt vẽ."""
    try:
        why = geom.wall_reason(store, wall)
    except StoreError as e:
        return f"dữ liệu tường sai cấu trúc: {e}"
    if not why:
        return ""
    keys = wall_missing_keys(store, wall)
    return f"{why} (khoá {', '.join(keys)})" if keys else why


def opening_skip_reason(store: ProjectStore, op: Opening) -> str:
    """Lý do ô cửa chưa dựng được ("" nếu dựng được). Bắt đầu bằng geom.opening_reason (lý do ĐẦU TIÊN), rồi kể
    THÊM mọi số liệu riêng của ô cửa còn thiếu — vd. tường chưa có toạ độ VÀ ô cửa thiếu bề rộng — để người dùng
    nhập một lần là đủ. geom.opening_reason chỉ ném StoreError qua tường chứa ô cửa."""
    wall = store.get("walls", op.wall_id)
    try:
        primary = geom.opening_reason(store, op)
    except StoreError as e:
        primary = f"tường {op.wall_id}: dữ liệu tường sai cấu trúc: {e}"
    if not primary:
        return ""
    parts = [primary]
    if wall is not None and primary.startswith(f"tường {wall.id}: "):
        keys = wall_missing_keys(store, wall)
        if keys:
            parts[0] = f"{primary} (khoá {', '.join(keys)})"
    for name, desc in (("offset", "thiếu vị trí cửa (offset)"), ("width", "thiếu bề rộng cửa")):
        if getattr(op, name) is None:
            item = f"{desc} (khoá openings:{op.id}.{name})"
            if parts[0] == desc:
                parts[0] = item
            else:
                parts.append(item)
    width = geom._num(op.width)
    if width is not None and width <= 0 and parts[0] != "bề rộng cửa ≤ 0":
        parts.append("bề rộng cửa ≤ 0")
    return "; ".join(parts)


def geometry_view(store: ProjectStore) -> Tuple[ProjectStore, List[Tuple[str, str, str]]]:
    """Bản sao NÔNG của store đã loại tường / cột / ô cửa sai cấu trúc (StoreError) để các hàm geom chạy được cho
    phần còn lại. Store gốc không bị sửa. Trả (bản sao — hoặc chính store nếu không có gì sai —,
    [(tập hợp, mã, lý do)] của tường và cột bị loại). Ô cửa bị loại khi tường chứa nó sai cấu trúc; lý do của ô cửa
    lấy bằng opening_skip_reason."""
    bad: List[Tuple[str, str, str]] = []
    walls = []
    prefix = "dữ liệu sai cấu trúc: "        # geom.*_reason trả lý do này thay vì ném StoreError
    for w in store.walls:
        why = geom.wall_reason(store, w)
        if why.startswith(prefix):
            bad.append(("walls", w.id, f"dữ liệu tường sai cấu trúc: {why[len(prefix):]}"))
        else:
            walls.append(w)
    columns = []
    for c in store.columns:
        why = geom.column_reason(store, c)
        if why.startswith(prefix):
            bad.append(("columns", c.id, f"dữ liệu cột sai cấu trúc: {why[len(prefix):]}"))
        else:
            columns.append(c)
    if not bad:
        return store, bad
    good_walls = {w.id for w in walls}
    view = copy.copy(store)
    view.walls = walls
    view.columns = columns
    view.openings = [o for o in store.openings
                     if o.wall_id in good_walls or store.get("walls", o.wall_id) is None]
    return view, bad


def outline_polylines(lines: List[List[Point]]) -> List[Tuple[List[Point], bool]]:
    """Các đường bao → [(điểm, kín?)] theo thứ tự tất định. Đường có điểm đầu ≡ điểm cuối là đường kín: bỏ điểm
    lặp cuối. Sắp theo (round(min x), round(min y), số điểm), hoà thì theo dãy toạ độ."""
    out: List[Tuple[List[Point], bool]] = []
    for line in lines:
        pts = [(float(x), float(y)) for x, y in line]
        if len(pts) < 2:
            continue
        closed = len(pts) >= 4 and geom.length(geom.sub(pts[0], pts[-1])) <= CLOSE_EPS
        if closed:
            pts = pts[:-1]
        out.append((pts, closed))

    def key(item):
        pts, _ = item
        return (round(min(p[0] for p in pts)), round(min(p[1] for p in pts)), len(pts),
                tuple((round(x, 6), round(y, 6)) for x, y in pts))

    return sorted(out, key=key)


# ── skill ────────────────────────────────────────────────────────────────────

class TuongSkill(DraftSkill):
    code = "03"
    name = "Tường"
    reads = ("project", "axes", "columns", "walls", "openings")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        view, bad = geometry_view(store)

        # ── tường không vẽ được → bỏ qua kèm lý do ──
        drawable: List[Wall] = []
        for w in store.walls:
            why = wall_skip_reason(store, w)
            if why:
                result.skip(f"tuong:{w.id}", why)
            else:
                drawable.append(w)
        drawable_ids = {w.id for w in drawable}

        # ── đường bao thân tường ──
        polylines = outline_polylines(geom.wall_outline_lines(view))
        for i, (pts, closed) in enumerate(polylines):
            self.add(plan, "pline", "tuong", f"tuong/outline/{i}", points=pts, closed=closed)
        n_closed = sum(1 for _, c in polylines if c)
        result.notes.append(f"đã vẽ {len(drawable)}/{len(store.walls)} tường")
        result.notes.append(f"đường bao thân tường: {len(polylines)} đường ({n_closed} đường kín)")

        # ── ô cửa chưa trừ được khỏi tường: nói rõ, KHÔNG bỏ tường ──
        for o in store.openings:
            why = opening_skip_reason(store, o)
            if not why:
                continue
            if o.wall_id in drawable_ids:
                tail = f" — đường bao tường {o.wall_id} đang vẽ liền qua vị trí cửa"
            elif store.get("walls", o.wall_id) is None:
                tail = ""
            else:
                tail = f" (tường {o.wall_id} cũng chưa vẽ)"
            result.notes.append(f"ô cửa {o.id} chưa trừ khỏi tường {o.wall_id} vì {why}{tail}")

        # ── cột sai cấu trúc: không trừ được khỏi tường ──
        for coll, eid, why in bad:
            if coll == "columns":
                result.notes.append(f"cột {eid} chưa trừ khỏi tường vì {why}")

        # ── số liệu nội suy chưa xác nhận ──
        doubtful = []
        for w in drawable:
            keys = wall_unconfirmed_keys(store, w)
            if keys:
                doubtful.append(f"{w.id} ({', '.join(keys)})")
        if doubtful:
            result.notes.append("tường dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
        cut = []
        for o in store.openings:
            if o.wall_id in drawable_ids and not opening_skip_reason(store, o):
                keys = entity_unconfirmed_keys("openings", o)
                if keys:
                    cut.append(f"{o.id} ({', '.join(keys)})")
        if cut:
            result.notes.append("ô cửa trừ khỏi tường theo số liệu nội suy CHƯA xác nhận: " + "; ".join(cut))
