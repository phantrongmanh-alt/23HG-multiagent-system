# -*- coding: utf-8 -*-
"""
CHUẨN LAYER, CHỮ, KÍCH THƯỚC VÀ HATCH CHO AGENT DỰNG CAD.

Skill không ghi thẳng tên layer mà ghi theo VAI TRÒ (role). Mỗi vai trò thuộc đúng một skill
(ROLE_OWNER) — Validator dựa vào đây để bắt một skill vẽ lấn sang phần của skill khác.
Tên layer thật lấy từ template của người dùng (store.layers) nếu có, ngược lại dùng DEFAULT_LAYERS.

Kích thước chữ/ký hiệu khai báo theo mm TRÊN GIẤY; nhân với tỷ lệ bản vẽ để ra mm trong model space.
Kiểu kích thước theo mục 6A của skills/aec-cad-automation/SKILL.md (gạch chéo kiến trúc, chữ 2,2 mm
phía trên đường kích thước, số nguyên mm, font VN_ARIAL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class LayerSpec:
    name: str
    color: int = 7                    # ACI
    linetype: str = "Continuous"
    lineweight: int = 25              # 1/100 mm (25 = 0,25 mm)
    plot: bool = True
    description: str = ""


# vai trò → (skill sở hữu, layer mặc định)
DEFAULT_ROLES: Dict[str, Tuple[str, LayerSpec]] = {
    "anh_nen":    ("00", LayerSpec("00-ANH-NEN", 8, "Continuous", 9, False, "Ảnh/PDF nền tham chiếu (không in)")),
    "truc":       ("01", LayerSpec("KT-TRUC", 1, "CENTER", 18, True, "Đường trục định vị")),
    "truc_kh":    ("01", LayerSpec("KT-TRUC-KH", 1, "Continuous", 18, True, "Vòng tròn và tên trục")),
    "cot":        ("02", LayerSpec("KC-COT", 7, "Continuous", 50, True, "Đường bao cột")),
    "tuong":      ("03", LayerSpec("KT-TUONG", 7, "Continuous", 50, True, "Đường bao tường (đã trừ ô cửa, cột)")),
    "cua":        ("04", LayerSpec("KT-CUA", 3, "Continuous", 25, True, "Cánh cửa, cung mở, khung cửa sổ")),
    "cua_kh":     ("04", LayerSpec("KT-CUA-KH", 3, "Continuous", 18, True, "Ký hiệu cửa D1/S1")),
    "thang":      ("05", LayerSpec("KT-THANG", 6, "Continuous", 25, True, "Cầu thang: bậc, mũi tên, đường cắt")),
    "noi_that":   ("06", LayerSpec("KT-NOI-THAT", 8, "Continuous", 13, True, "Nội thất, thiết bị vệ sinh")),
    "hatch":      ("07", LayerSpec("KT-HATCH", 8, "Continuous", 9, True, "Hatch cột, tường, sàn")),
    "dim":        ("08", LayerSpec("KT-DIM", 3, "Continuous", 18, True, "Kích thước (DIMENSION nguyên bản)")),
    "hoan_thien": ("09", LayerSpec("KT-HOAN-THIEN", 2, "Continuous", 18, True, "Tên phòng, diện tích, cote, hoàn thiện")),
    "khung_ten":  ("10", LayerSpec("KT-KHUNG-TEN", 7, "Continuous", 35, True, "Khung tên, khung bản vẽ")),
    "kiem_tra":   ("10", LayerSpec("KT-KIEM-TRA", 1, "Continuous", 25, False, "Đánh dấu lỗi của Validator (không in)")),
}

ROLE_OWNER: Dict[str, str] = {role: owner for role, (owner, _) in DEFAULT_ROLES.items()}


def default_layers() -> Dict[str, LayerSpec]:
    """Bản sao bộ layer mặc định (vai trò → LayerSpec)."""
    return {role: LayerSpec(**vars(spec)) for role, (_, spec) in DEFAULT_ROLES.items()}


def roles_of(skill_code: str) -> Tuple[str, ...]:
    """Các vai trò layer mà skill được phép ghi."""
    return tuple(r for r, owner in ROLE_OWNER.items() if owner == skill_code)


# ── Chữ ──────────────────────────────────────────────────────────────────────

TEXT_STYLE = {"name": "VN_ARIAL", "font": "arial.ttf"}

# chiều cao chữ trên giấy (mm)
TEXT_PAPER_MM: Dict[str, float] = {
    "truc": 3.5,          # tên trục trong vòng tròn
    "dim": 2.2,           # chữ kích thước (DIMTXT)
    "cua_kh": 2.0,        # ký hiệu cửa
    "thang": 2.5,         # chữ LÊN / XUỐNG
    "ten_phong": 3.0,     # tên phòng
    "dien_tich": 2.2,     # diện tích, cote
    "ghi_chu": 2.0,       # ghi chú hoàn thiện
    "tieu_de": 5.0,       # tên bản vẽ dưới hình
    "khung_ten": 2.5,     # chữ trong khung tên
}
AXIS_BUBBLE_DIAMETER_PAPER_MM = 8.0


def paper_to_model(paper_mm: float, scale: int) -> float:
    """mm trên giấy → mm trong model space ở tỷ lệ 1:scale."""
    return float(paper_mm) * float(scale)


def text_height(kind: str, scale: int) -> float:
    return paper_to_model(TEXT_PAPER_MM[kind], scale)


# ── Kích thước (DIMSTYLE) ────────────────────────────────────────────────────

def dimstyle_name(scale: int) -> str:
    return f"TCVN_KT_{int(scale)}"


def dimstyle_tcvn(scale: int) -> Dict[str, object]:
    """Biến DIMSTYLE (tên biến ezdxf/AutoCAD, chữ thường) — số đo trên giấy, DIMSCALE = tỷ lệ bản vẽ."""
    return {
        "dimblk": "ARCHTICK",     # gạch chéo kiến trúc
        "dimtad": 1,              # chữ phía trên đường kích thước
        "dimexo": 2.0,            # hở chân gióng
        "dimexe": 1.5,            # nhô đuôi gióng
        "dimtxt": 2.2,            # chiều cao chữ
        "dimasz": 1.5,            # cỡ ký hiệu đầu đo
        "dimgap": 0.8,
        "dimdec": 0,              # số nguyên mm
        "dimlunit": 2,            # thập phân
        "dimzin": 8,
        "dimtih": 0,
        "dimtoh": 0,
        "dimtxsty": TEXT_STYLE["name"],
        "dimclrd": 3,
        "dimclre": 3,
        "dimclrt": 7,
        "dimscale": float(scale),
        # cố định thêm các biến dễ bị kế thừa từ bản vẽ đích khi AutoLISP lưu kiểu bằng -DIMSTYLE Save
        "dimlfac": 1.0,           # không co giãn số đo (lỗi DIMLFAC ≠ 1 là cờ đỏ trong SKILL.md)
        "dimrnd": 0.0,
        "dimalt": 0,
        "dimse1": 0,
        "dimse2": 0,
        "dimtsz": 0.0,            # dùng khối đầu đo (DIMBLK), không dùng gạch tick DIMTSZ
        "dimsah": 0,
        "dimdle": 0.0,
        "dimtfac": 1.0,
        "dimtvp": 0.0,
        "dimjust": 0,
    }


# ── Hatch ────────────────────────────────────────────────────────────────────
# base = khoảng cách đường của mẫu ở scale 1 (bảng mẫu ISO của ezdxf/AutoCAD acadiso.pat).
# spacing_model = khoảng cách thật (mm) — viên gạch lát 600 là 600 mm bất kể tỷ lệ in.
# spacing_paper = khoảng cách trên giấy (mm) — gạch chéo tường in ra 1 mm ở mọi tỷ lệ.

HATCH_PATTERNS: Dict[str, Dict[str, object]] = {
    "cot_btct":   {"pattern": "SOLID", "mo_ta": "Cột BTCT tô đặc"},
    "tuong_btct": {"pattern": "SOLID", "mo_ta": "Tường BTCT tô đặc"},
    "tuong_xay":  {"pattern": "ANSI31", "base": 3.175, "spacing_paper": 1.0, "angle": 0.0,
                   "mo_ta": "Tường xây gạch — gạch chéo 45°"},
    "gach_600":   {"pattern": "NET", "base": 3.175, "spacing_model": 600.0, "angle": 0.0,
                   "mo_ta": "Lát gạch 600×600"},
    "gach_300":   {"pattern": "NET", "base": 3.175, "spacing_model": 300.0, "angle": 0.0,
                   "mo_ta": "Lát gạch 300×300 (khu vệ sinh)"},
    "go":         {"pattern": "LINE", "base": 3.175, "spacing_model": 150.0, "angle": 0.0,
                   "mo_ta": "Sàn gỗ ván 150"},
}


def hatch_params(key: str, scale: int) -> Tuple[str, float, float]:
    """(tên mẫu, hệ số scale của mẫu, góc) cho một khóa trong HATCH_PATTERNS. KeyError nếu khóa lạ."""
    spec = HATCH_PATTERNS[key]
    pattern = str(spec["pattern"])
    if pattern == "SOLID":
        return pattern, 1.0, 0.0
    base = float(spec["base"])
    if "spacing_model" in spec:
        spacing = float(spec["spacing_model"])
    else:
        spacing = paper_to_model(float(spec["spacing_paper"]), scale)
    return pattern, spacing / base, float(spec.get("angle", 0.0))


# ── Khổ giấy ─────────────────────────────────────────────────────────────────

SHEET_SIZES_MM: Dict[str, Tuple[float, float]] = {
    "A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0),
}


# ── Bố cục quanh hình vẽ (mm trên giấy, tính ra ngoài từ trục ngoài cùng) ──────
# Skill 08 đặt 3 cấp kích thước, Skill 01 đặt vòng tròn tên trục ngoài cùng — dùng chung bảng này để không đè nhau.
LAYOUT_PAPER_MM: Dict[str, float] = {
    "dim_level_1": 12.0,          # cấp 1: chi tiết (ô cửa, mép tường) dọc tường ngoài
    "dim_level_2": 20.0,          # cấp 2: nhịp trục
    "dim_level_3": 28.0,          # cấp 3: kích thước tổng
    "axis_bubble_center": 38.0,   # tâm vòng tròn tên trục
    "sheet_margin_left": 25.0,    # lề đóng gáy
    "sheet_margin": 5.0,          # lề ba cạnh còn lại
}
