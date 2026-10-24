# -*- coding: utf-8 -*-
"""
THƯ VIỆN BLOCK NỘI THẤT CHUẨN cho Skill 06 (nội thất, thiết bị vệ sinh).

Quy ước chung cho mọi block trong LIBRARY:
  - Đơn vị mm, hình học nằm trọn trong hộp [0, X] × [0, Y] với size = [X, Y] (kể cả vòng tròn bao của
    circle/arc — plan.iter_points lấy tâm ± bán kính), điểm chèn (0, 0) = góc dưới-trái của hộp.
    Nhờ vậy geom.footprint(insert, size, rotation) đúng là vết chiếm chỗ của block sau khi chèn.
  - Chỉ dùng line / pline / circle / arc (không chữ) để Validator và mọi bộ xuất đọc được.
  - Nét đủ thưa để còn nhận ra khi in 1:100 (chi tiết nhỏ nhất ≈ 20–25 mm model = 0,2–0,25 mm giấy).

Hướng "lưng" của từng block — chọn khớp đề bài mẫu (examples/DUNG_CAD_NHA_MAU), nơi mỗi đồ vật được chèn
sát mặt tường:
  - GIUONG_DOI, SOFA_3: lưng (đầu giường + 2 gối / tựa lưng) ở cạnh y LỚN (y = Y).
  - TU_BEP, BON_CAU, LAVABO: lưng sát tường ở cạnh y = 0 (két nước, vòi nước nằm phía y nhỏ), mặt sử dụng
    quay về phía y lớn.
  - TU_AO, BAN_TRA, BAN_AN_4: đối xứng theo trục y (lưng ở phía nào cũng được).
Khi chèn với góc xoay r, block xoay quanh điểm chèn ngược chiều kim đồng hồ: trục +X của block → hướng r,
trục +Y của block → hướng r + 90°.

`get_block(name, store)` ưu tiên block trong template của người dùng (store.blocks) rồi mới tới LIBRARY;
trả BẢN SAO để skill thêm vào plan mà không làm đổi thư viện; không có → None (skill phải ghi bỏ qua kèm lý do).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from tools.cad_drafting.plan import BlockDef
from tools.cad_drafting.store import ProjectStore

Point = Tuple[float, float]
Item = Dict[str, Any]


# ── trợ giúp dựng hình học block ─────────────────────────────────────────────

def _line(p1: Point, p2: Point) -> Item:
    return {"kind": "line", "data": {"p1": list(p1), "p2": list(p2)}}


def _pline(points: Sequence[Point], closed: bool = True) -> Item:
    return {"kind": "pline", "data": {"points": [list(p) for p in points], "closed": closed}}


def _circle(center: Point, r: float) -> Item:
    return {"kind": "circle", "data": {"center": list(center), "r": r}}


def _arc(center: Point, r: float, start_angle: float, end_angle: float) -> Item:
    return {"kind": "arc", "data": {"center": list(center), "r": r,
                                    "start_angle": start_angle, "end_angle": end_angle}}


def _rect(x0: float, y0: float, x1: float, y1: float) -> Item:
    """Hình chữ nhật kín."""
    return _pline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _chamfer_rect(x0: float, y0: float, x1: float, y1: float, c: float) -> Item:
    """Hình chữ nhật kín vát 4 góc một đoạn c (gần giống bo góc, vẫn chỉ là pline)."""
    return _pline([(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c),
                   (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)])


# ── từng block ───────────────────────────────────────────────────────────────

def _giuong_doi() -> List[Item]:
    """Giường đôi 1600×2000: khung, đầu giường + 2 gối ở cạnh y lớn, mép chăn và góc chăn gấp."""
    return [
        _rect(0, 0, 1600, 2000),                       # khung giường
        _line((0, 1920), (1600, 1920)),                # đầu giường
        _chamfer_rect(120, 1530, 760, 1880, 50),       # gối trái
        _chamfer_rect(840, 1530, 1480, 1880, 50),      # gối phải
        _line((0, 1400), (1600, 1400)),                # mép chăn
        _line((1150, 1400), (1600, 950)),              # góc chăn gấp
    ]


def _tu_ao() -> List[Item]:
    """Tủ áo 1200×600: thân tủ, thanh treo ở giữa chiều sâu, 7 móc áo xiên (đối xứng theo trục y)."""
    items = [_rect(0, 0, 1200, 600), _line((60, 300), (1140, 300))]
    for k in range(7):
        x = 180.0 + 140.0 * k
        items.append(_line((x - 40, 120), (x + 40, 480)))
    return items


def _sofa_3() -> List[Item]:
    """Sofa 3 chỗ 2100×850: tay vịn hai đầu, tựa lưng ở cạnh y lớn, 3 đệm ngồi."""
    return [
        _rect(0, 0, 2100, 850),                        # đường bao
        _line((150, 0), (150, 850)),                   # tay vịn trái
        _line((1950, 0), (1950, 850)),                 # tay vịn phải
        _line((150, 650), (1950, 650)),                # tựa lưng (dày 200, phía y lớn)
        _line((750, 0), (750, 650)),                   # ranh đệm 1–2
        _line((1350, 0), (1350, 650)),                 # ranh đệm 2–3
    ]


def _ban_tra() -> List[Item]:
    """Bàn trà 1000×600: mặt bàn và mặt kính lùi vào 60 mm."""
    return [_rect(0, 0, 1000, 600), _rect(60, 60, 940, 540)]


def _chair(x0: float, y_seat0: float, y_seat1: float, back_at_low: bool) -> List[Item]:
    """Ghế ăn rộng 450 (kéo hẳn ra khỏi bàn): mặt ngồi + tựa lưng dày 80 ở phía xa bàn."""
    items = [_chamfer_rect(x0, y_seat0, x0 + 450, y_seat1, 40)]
    if back_at_low:
        items.append(_rect(x0, y_seat0, x0 + 450, y_seat0 + 80))
    else:
        items.append(_rect(x0, y_seat1 - 80, x0 + 450, y_seat1))
    return items


def _ban_an_4() -> List[Item]:
    """Bộ bàn ăn 4 ghế 1200×1600: bàn 1200×800 ở giữa (y 400–1200), 2 ghế dưới, 2 ghế trên, tựa lưng quay ra ngoài."""
    items = [_rect(0, 400, 1200, 1200)]
    for x0 in (105.0, 645.0):
        items += _chair(x0, 0, 400, back_at_low=True)        # ghế phía dưới
        items += _chair(x0, 1200, 1600, back_at_low=False)   # ghế phía trên
    return items


def _tu_bep() -> List[Item]:
    """Tủ bếp 2400×600, lưng sát tường ở y = 0: mép mặt đá phía trước, chậu rửa (lòng chậu, lỗ thoát, vòi phía
    tường) và bếp 2 vùng nấu (mỗi vùng 2 vòng tròn)."""
    return [
        _rect(0, 0, 2400, 600),                        # thân tủ
        _line((0, 560), (2400, 560)),                  # mép mặt đá phía trước
        _rect(350, 80, 1150, 500),                     # chậu rửa
        _chamfer_rect(400, 120, 1100, 460, 60),        # lòng chậu
        _circle((750, 290), 25),                       # lỗ thoát nước
        _circle((750, 45), 20),                        # vòi nước (phía tường)
        _rect(1500, 80, 2200, 500),                    # mặt bếp
        _circle((1675, 290), 120),                     # vùng nấu 1
        _circle((1675, 290), 60),
        _circle((2025, 290), 120),                     # vùng nấu 2
        _circle((2025, 290), 60),
    ]


def _bon_cau() -> List[Item]:
    """Bồn cầu 400×700: KÉT NƯỚC ở cạnh y nhỏ (sát tường, y 0–180) — khớp đề bài mẫu, nơi bồn cầu chèn xoay 90°
    với điểm chèn trên mặt tường; thân bồn loe về phía y lớn, mép trước là cung tròn; lòng bồn; nút xả trên két."""
    return [
        _chamfer_rect(20, 0, 380, 180, 30),            # két nước
        _circle((200, 90), 25),                        # nút xả
        _line((70, 180), (0, 500)),                    # thành bồn trái
        _line((330, 180), (400, 500)),                 # thành bồn phải
        _arc((200, 500), 200, 0, 180),                 # mép trước bồn (nửa trên vòng tròn, y 500–700)
        _circle((200, 480), 120),                      # lòng bồn
    ]


def _lavabo() -> List[Item]:
    """Lavabo 500×400, lưng sát tường ở y = 0: mặt chậu vát góc phía trước, lòng chậu tròn, lỗ thoát, vòi phía tường."""
    return [
        _pline([(0, 0), (500, 0), (500, 320), (420, 400), (80, 400), (0, 320)]),   # mặt chậu
        _circle((250, 220), 150),                      # lòng chậu
        _circle((250, 220), 20),                       # lỗ thoát nước
        _circle((250, 40), 20),                        # vòi nước
    ]


_SPECS = (
    ("GIUONG_DOI", (1600.0, 2000.0), _giuong_doi, "Giường đôi 1600×2000 (đầu giường, 2 gối ở cạnh y lớn)"),
    ("TU_AO", (1200.0, 600.0), _tu_ao, "Tủ áo 1200×600 (thanh treo + móc áo)"),
    ("SOFA_3", (2100.0, 850.0), _sofa_3, "Sofa 3 chỗ 2100×850 (tựa lưng ở cạnh y lớn)"),
    ("BAN_TRA", (1000.0, 600.0), _ban_tra, "Bàn trà 1000×600"),
    ("BAN_AN_4", (1200.0, 1600.0), _ban_an_4, "Bàn ăn 1200×800 + 4 ghế (2 trên, 2 dưới)"),
    ("TU_BEP", (2400.0, 600.0), _tu_bep, "Tủ bếp 2400×600 (chậu rửa + bếp 2 vùng nấu, lưng ở y = 0)"),
    ("BON_CAU", (400.0, 700.0), _bon_cau, "Bồn cầu 400×700 (két nước ở cạnh y nhỏ, sát tường)"),
    ("LAVABO", (500.0, 400.0), _lavabo, "Lavabo 500×400 (lưng sát tường ở y = 0)"),
)


def _build_library() -> Dict[str, BlockDef]:
    return {name: BlockDef(name=name, ops=build(), size=list(size), description=desc, source="thu_vien")
            for name, size, build, desc in _SPECS}


LIBRARY: Dict[str, BlockDef] = _build_library()


def library_names() -> List[str]:
    """Tên các block trong thư viện chuẩn, theo thứ tự khai báo."""
    return [name for name, _, _, _ in _SPECS]


def get_block(name: str, store: Optional[ProjectStore] = None) -> Optional[BlockDef]:
    """Định nghĩa block theo tên: ưu tiên template người dùng (store.blocks), rồi tới LIBRARY. Trả bản sao
    (sửa bản sao không làm đổi thư viện/kho dữ liệu); không có → None."""
    if store is not None and name in store.blocks:
        return BlockDef.from_dict(store.blocks[name].to_dict())
    if name in LIBRARY:
        return BlockDef.from_dict(LIBRARY[name].to_dict())
    return None


def block_origin(name: str, store: Optional[ProjectStore] = None) -> str:
    """Nguồn của block sẽ được dùng: "mau" (template người dùng) | "thu_vien" | "" (không có)."""
    if store is not None and name in store.blocks:
        return "mau"
    return "thu_vien" if name in LIBRARY else ""
