# -*- coding: utf-8 -*-
"""
SKILL 02 — CỘT: đường bao cột (vai trò "cot"), mỗi cột một pline kín theo geom.column_polygon.

Quy ước:
  - Cột thiếu kích thước hoặc nằm trên trục chưa có toạ độ → result.skip("cot:<id>", geom.column_reason(...)).
  - Cột tham chiếu trục không tồn tại (StoreError — dữ liệu sai cấu trúc) cũng bị bỏ qua kèm lý do, không làm
    hỏng cả lượt vẽ của các cột khác.
  - KHÔNG vẽ hatch cột (Skill 07 làm). Không sửa store.
  - eid: "cot/<id>" (đã có tiền tố "02/" do DraftSkill.add gắn).

Ghi chú kết quả: số cột đã vẽ / tổng; cột có kích thước hoặc toạ độ dựa trên số liệu nội suy chưa xác nhận.
"""

from __future__ import annotations

from typing import List, Tuple

from tools.cad_drafting import geom
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s01_luoi_truc import axis_unconfirmed_keys
from tools.cad_drafting.store import SRC_INTERP, Column, ProjectStore, StoreError


def column_outline(store: ProjectStore, col: Column) -> Tuple[List[Tuple[float, float]], str]:
    """(các đỉnh đường bao cột, "") hoặc ([], lý do chưa vẽ được). Đỉnh giữ thứ tự của geom.column_polygon,
    không lặp điểm cuối."""
    try:
        why = geom.column_reason(store, col)
    except StoreError as e:
        return [], f"dữ liệu cột sai cấu trúc: {e}"
    if why:
        return [], why
    poly = geom.column_polygon(store, col)
    if poly is None:          # phòng hờ: column_reason rỗng mà vẫn không dựng được hình
        return [], "không dựng được hình cột từ số liệu hiện có"
    pts = [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]
    return pts, ""


def column_unconfirmed_keys(store: ProjectStore, col: Column) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà vị trí/kích thước cột phụ thuộc."""
    keys: List[str] = []
    if col.prov.source == SRC_INTERP and not col.prov.confirmed:
        keys.append(f"columns:{col.id}")
    for name in ("b", "h", "dx", "dy"):
        p = col.field_prov.get(name)
        if p is not None and p.source == SRC_INTERP and not p.confirmed:
            keys.append(f"columns:{col.id}.{name}")
    for axis in (col.axis_v, col.axis_h):
        for k in axis_unconfirmed_keys(store, axis):
            if k not in keys:
                keys.append(k)
    return keys


class CotSkill(DraftSkill):
    code = "02"
    name = "Cột"
    reads = ("project", "axes", "columns")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        drawn = 0
        doubtful = []
        for col in store.columns:
            pts, why = column_outline(store, col)
            if why:
                result.skip(f"cot:{col.id}", why)
                continue
            self.add(plan, "pline", "cot", f"cot/{col.id}", points=pts, closed=True)
            drawn += 1
            keys = column_unconfirmed_keys(store, col)
            if keys:
                doubtful.append(f"{col.id} ({', '.join(keys)})")
        result.notes.append(f"đã vẽ {drawn}/{len(store.columns)} cột")
        if doubtful:
            result.notes.append("cột dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
