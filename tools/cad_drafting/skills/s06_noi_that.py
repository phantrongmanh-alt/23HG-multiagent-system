# -*- coding: utf-8 -*-
"""
SKILL 06 — NỘI THẤT: chèn block nội thất / thiết bị vệ sinh (vai trò "noi_that").

Mỗi đồ vật (store.Furniture):
  - định nghĩa block lấy theo block_library.get_block: ưu tiên template người dùng (store.blocks), rồi thư viện
    chuẩn (block_library.LIBRARY); không có → result.skip("noi_that:<id>",
    "không có block '<tên>' trong template lẫn thư viện");
  - điểm chèn chưa có toạ độ (trục thiếu nhịp) / sai cấu trúc, góc xoay không phải số → result.skip kèm lý do;
  - ngược lại plan.add_block(định nghĩa) và một Op insert (block, insert, rotation, scale [1, 1])
    eid "noi_that/<id>" (đã có tiền tố "06/" do DraftSkill.add gắn).

Chạy lại không nhân đôi: Op cũ của skill bị xoá (DraftSkill.run); định nghĩa block cũ cùng tên nhưng khác nội dung
(vd template vừa đổi) được THAY khi không còn Op nào khác tham chiếu, kèm ghi chú; còn Op của skill khác tham chiếu
thì KHÔNG ghi đè — đồ vật đó bị bỏ qua kèm lý do. Block do lượt trước của skill này thêm mà nay không còn ai dùng
thì gỡ khỏi plan (kèm ghi chú).

Va chạm (nội thất đè tường, cột, thang, chắn cửa) do Validator kiểm — skill KHÔNG tự dời đồ. Skill không sửa store.
Ghi chú kết quả: số đồ vật đã chèn / tổng; block lấy từ template; block template thiếu size (Validator không kiểm
được va chạm); đồ vật dựa trên số liệu nội suy CHƯA xác nhận.
"""

from __future__ import annotations

import math
from typing import List, Optional, Set, Tuple

from tools.cad_drafting.block_library import get_block
from tools.cad_drafting.plan import BlockDef, DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s01_luoi_truc import axis_unconfirmed_keys
from tools.cad_drafting.skills.s03_tuong import entity_unconfirmed_keys, ref_axis_names
from tools.cad_drafting.store import Furniture, ProjectStore, StoreError

Point = Tuple[float, float]


# ── trợ giúp dùng chung (kiểm thử cũng dùng) ────────────────────────────────

def insert_point(store: ProjectStore, f: Furniture) -> Tuple[Optional[Point], str]:
    """(điểm chèn, "") hoặc (None, lý do chưa xác định được — kèm khoá nhịp trục còn thiếu)."""
    try:
        p, why = store.point_or_reason(f.insert)
    except StoreError as e:
        return None, f"điểm chèn sai cấu trúc: {e}"
    if p is not None:
        return p, ""
    keys = [k for k in (store.missing_span_key(a) for a in ref_axis_names(f.insert)
                        if store.axis_group_of(a) is not None) if k]
    return None, (f"điểm chèn {f.insert!r} chưa có toạ độ: {why}" + (f" (khoá {', '.join(keys)})" if keys else ""))


def rotation_of(f: Furniture) -> Optional[float]:
    """Góc xoay (độ) hoặc None nếu không phải số hữu hạn."""
    if isinstance(f.rotation, (str, bytes, bool)) or f.rotation is None:
        return None
    try:
        v = float(f.rotation)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def furniture_unconfirmed_keys(store: ProjectStore, f: Furniture) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà vị trí đồ vật phụ thuộc (đồ vật + nhịp trục của điểm chèn)."""
    keys = entity_unconfirmed_keys("furniture", f)
    for a in ref_axis_names(f.insert):
        for k in axis_unconfirmed_keys(store, a):
            if k not in keys:
                keys.append(k)
    return keys


def _referenced_blocks(plan: DrawingPlan) -> Set[str]:
    return {o.data["block"] for o in plan.ops if o.kind == "insert"}


# ── skill ────────────────────────────────────────────────────────────────────

class NoiThatSkill(DraftSkill):
    code = "06"
    name = "Nội thất"
    reads = ("project", "axes", "furniture", "blocks")

    def run(self, store: ProjectStore, plan: DrawingPlan) -> SkillResult:
        # nhớ các block mà lượt trước của skill này đã chèn, để gỡ định nghĩa không còn dùng sau khi vẽ lại
        self._previous_blocks = {o.data["block"] for o in plan.ops_of(skill=self.code, kind="insert")}
        return super().run(store, plan)

    def _place_block(self, plan: DrawingPlan, blk: BlockDef, result: SkillResult) -> str:
        """Đưa định nghĩa block vào plan. Trả "" nếu được, ngược lại lý do không đưa được."""
        old = plan.blocks.get(blk.name)
        if old is None or old.to_dict() == blk.to_dict():
            plan.add_block(blk)
            return ""
        users = sorted({o.skill for o in plan.ops if o.kind == "insert" and o.data["block"] == blk.name})
        if users:
            return (f"block '{blk.name}' đã có trong plan với nội dung khác và đang được skill "
                    f"{', '.join(users)} dùng — không ghi đè")
        plan.blocks[blk.name] = blk          # không ai còn dùng bản cũ: thay bằng định nghĩa hiện hành
        result.notes.append(f"cập nhật định nghĩa block '{blk.name}' trong plan (nguồn hiện hành: "
                            f"{'template' if blk.source == 'mau' else blk.source})")
        return ""

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        drawn = 0
        from_template: List[str] = []
        no_size: List[str] = []
        doubtful: List[str] = []
        used: Set[str] = set()
        for f in store.furniture:
            item = f"noi_that:{f.id}"
            blk = get_block(f.block, store)
            if blk is None:
                result.skip(item, f"không có block '{f.block}' trong template lẫn thư viện")
                continue
            p, why = insert_point(store, f)
            if p is None:
                result.skip(item, why)
                continue
            rot = rotation_of(f)
            if rot is None:
                result.skip(item, f"góc xoay {f.rotation!r} không phải số")
                continue
            why = self._place_block(plan, blk, result)
            if why:
                result.skip(item, why)
                continue
            self.add(plan, "insert", "noi_that", f"noi_that/{f.id}", block=blk.name, insert=p,
                     rotation=rot, scale=[1.0, 1.0])
            drawn += 1
            used.add(blk.name)
            if f.block in store.blocks and f.block not in from_template:
                from_template.append(f.block)
            if (blk.size[0] <= 0 or blk.size[1] <= 0) and blk.name not in no_size:
                no_size.append(blk.name)
            keys = furniture_unconfirmed_keys(store, f)
            if keys:
                doubtful.append(f"{f.id} ({', '.join(keys)})")

        stale = sorted(n for n in getattr(self, "_previous_blocks", set()) - used
                       if n in plan.blocks and n not in _referenced_blocks(plan))
        for n in stale:
            del plan.blocks[n]
        result.notes.append(f"đã chèn {drawn}/{len(store.furniture)} đồ vật nội thất")
        if from_template:
            result.notes.append("block lấy từ template người dùng (ưu tiên hơn thư viện): " + ", ".join(from_template))
        if no_size:
            result.notes.append("CẢNH BÁO block chưa có kích thước bao (size), Validator không kiểm được va chạm: "
                                + ", ".join(no_size))
        if stale:
            result.notes.append("gỡ định nghĩa block không còn đồ vật nào dùng: " + ", ".join(stale))
        if doubtful:
            result.notes.append("đồ vật dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
