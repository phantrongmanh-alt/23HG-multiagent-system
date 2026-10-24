# -*- coding: utf-8 -*-
"""10 skill dựng CAD theo thứ tự chạy (mã "01".."10"). Nạp lười để từng skill có thể dùng/kiểm thử riêng."""

import importlib

from tools.cad_drafting.skills.base import DraftSkill, SkillResult, new_plan

SKILL_MODULES = (
    ("01", "s01_luoi_truc", "LuoiTrucSkill"),
    ("02", "s02_cot", "CotSkill"),
    ("03", "s03_tuong", "TuongSkill"),
    ("04", "s04_cua", "CuaSkill"),
    ("05", "s05_cau_thang", "CauThangSkill"),
    ("06", "s06_noi_that", "NoiThatSkill"),
    ("07", "s07_hatch", "HatchSkill"),
    ("08", "s08_dimension", "DimensionSkill"),
    ("09", "s09_hoan_thien", "HoanThienSkill"),
    ("10", "s10_kiem_tra_xuat", "KiemTraXuatSkill"),
)


def skill_class(code: str):
    for c, mod, cls in SKILL_MODULES:
        if c == code:
            return getattr(importlib.import_module(f"tools.cad_drafting.skills.{mod}"), cls)
    raise KeyError(f"không có skill mã '{code}'")


def all_skills():
    """Một thể hiện của mỗi skill, theo thứ tự mã."""
    return [skill_class(c)() for c, _, _ in SKILL_MODULES]


__all__ = ["DraftSkill", "SkillResult", "SKILL_MODULES", "skill_class", "all_skills", "new_plan"]
