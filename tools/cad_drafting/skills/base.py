# -*- coding: utf-8 -*-
"""
GIAO DIỆN CHUNG CỦA 10 SKILL DỰNG CAD.

Mỗi skill:
  - đọc ProjectStore (không sửa store);
  - chỉ ghi Op vào các vai trò layer của mình (layers.roles_of(code)) — `self.add` từ chối vai trò khác;
  - chạy lại được: `run` xoá Op cũ của chính skill rồi vẽ lại (chỉ sửa phần liên quan);
  - đối tượng thiếu số liệu → ghi vào result.skipped kèm lý do, KHÔNG bỏ im lặng.

`reads` liệt kê các mục dữ liệu trong store mà skill dùng (xem store.DATA_SECTIONS); Master dùng nó để
biết skill nào phải chạy lại khi một mục dữ liệu thay đổi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from tools.cad_drafting.layers import TEXT_STYLE, LayerSpec, dimstyle_name, dimstyle_tcvn, roles_of
from tools.cad_drafting.plan import DrawingPlan, Op, PlanError
from tools.cad_drafting.store import ProjectStore


def new_plan(store: ProjectStore) -> DrawingPlan:
    """Plan rỗng mang layer (từ store/template), kiểu chữ, kiểu kích thước TCVN theo tỷ lệ và thông tin dự án."""
    scale = int(store.project.scale)
    return DrawingPlan(
        layers={r: LayerSpec(**vars(s)) for r, s in store.layers.items()},
        dimstyles={dimstyle_name(scale): dimstyle_tcvn(scale)},
        text_style=dict(TEXT_STYLE),
        meta={"project": vars(store.project).copy(), "scale": scale},
    )


@dataclass
class SkillResult:
    code: str
    name: str
    ops_added: int = 0
    skipped: List[Dict[str, str]] = field(default_factory=list)   # [{"id": ..., "ly_do": ...}]
    notes: List[str] = field(default_factory=list)

    def skip(self, item_id: str, reason: str) -> None:
        self.skipped.append({"id": item_id, "ly_do": reason})

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "name": self.name, "ops_added": self.ops_added,
                "skipped": list(self.skipped), "notes": list(self.notes)}


class DraftSkill(ABC):
    code: str = ""
    name: str = ""
    reads: Tuple[str, ...] = ()

    @property
    def roles(self) -> Tuple[str, ...]:
        return roles_of(self.code)

    def run(self, store: ProjectStore, plan: DrawingPlan) -> SkillResult:
        plan.remove_skill(self.code)
        result = SkillResult(self.code, self.name)
        self._result = result
        self.draw(store, plan, result)
        result.ops_added = len(plan.ops_of(skill=self.code))
        return result

    @abstractmethod
    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        ...

    def add(self, plan: DrawingPlan, kind: str, role: str, eid: str, **data) -> Op:
        """Thêm Op của skill này. eid tự gắn tiền tố mã skill ("03/" + eid)."""
        if role not in self.roles:
            raise PlanError(f"skill {self.code} không được ghi vào vai trò '{role}' "
                            f"(được phép: {', '.join(self.roles)})")
        return plan.add(kind, role, self.code, f"{self.code}/{eid}", **data)
