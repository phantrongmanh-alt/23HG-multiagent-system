# -*- coding: utf-8 -*-
"""
SKILL 09 — HOÀN THIỆN: tên phòng, diện tích, cote sàn và BẢNG HOÀN THIỆN (vai trò "hoan_thien").

Nhãn phòng — mỗi phòng có geom.room_polygon (thiếu → result.skip("hoan_thien:<room id>", lý do kèm khoá nhịp thiếu)):
  - khối chữ 2–3 dòng căn MIDDLE_CENTER, xếp từ trên xuống: tên phòng (text_height("ten_phong")), diện tích
    "S = 30,24 m²" (text_height("dien_tich")), cote sàn nếu floor_level khác None (text_height("dien_tich")):
    "±0.000" khi 0, "+0.450" / "-0.020" (m, 3 chữ số, dấu chấm như ký hiệu cote). Dòng cách dòng 1 mm giấy.
    eid "hoan_thien/<room id>/ten", ".../dien_tich", ".../cote".
  - vị trí: room.label_at nếu người dùng chỉ định; ngược lại tâm khối chữ ưu tiên trọng tâm phần sàn TRỐNG
    (phòng − tường − cột − vết nội thất − vế thang, chiếu nghỉ − vùng quét cánh cửa − chữ của skill chạy trước như ký hiệu cửa), không vừa thì dò lưới điểm gần trọng tâm nhất
    sao cho khung chữ ước lượng (bề rộng ký tự ≈ 0,75 × chiều cao) nới thêm 1 mm giấy nằm TRỌN trong phần sàn trống.
    Không vừa → thử lại chỉ trừ tường (ghi chú "nhãn đè vật"), rồi mới tới representative_point (luôn nằm trong phòng),
    kèm CẢNH BÁO trong ghi chú. `reads` gồm cả columns, furniture, blocks, stairs, openings vì vị trí nhãn phụ thuộc
    vào chúng (chế độ cập nhật của Master chạy lại skill khi các mục này đổi).
  - diện tích TÍNH từ room_polygon theo đường bao NHẬP (m², 2 chữ số, làm tròn half-up bằng Decimal, dấu phẩy thập
    phân kiểu Việt Nam, dấu chấm phân nghìn). Không gọi là "thông thủy": phòng có mọi cạnh trùng tim trục / tim tường
    được ghi rõ là chưa trừ chiều dày tường.
  - số liệu dựa trên nội suy CHƯA xác nhận được đánh dấu "*" (nhãn và bảng) và chú thích trong bảng.

Bảng hoàn thiện — góc trên-trái tại x = (toạ độ trục V lớn nhất đã biết) + (LAYOUT_PAPER_MM["axis_bubble_center"] + 22)
mm giấy, y = (toạ độ trục H lớn nhất đã biết) + LAYOUT_PAPER_MM["axis_bubble_center"] mm giấy:
  - hàng tiêu đề "BẢNG HOÀN THIỆN" (text_height("ten_phong")), hàng tên cột STT | Phòng | Diện tích (m²) | Sàn | Tường |
    Trần | Cote (rộng 8, 24, 16, 36, 32, 26, 14 mm giấy), mỗi phòng một hàng (phòng chưa tính được diện tích vẫn có
    hàng, ô diện tích ghi "chưa tính"; ô trống ghi "chưa nhập"), hàng "Tổng diện tích" = tổng các diện tích ĐÃ làm tròn
    của phòng tính được (cộng tay khớp cột) kèm số phòng chưa tính, các hàng ghi chú (cơ sở diện tích, dấu "*").
  - chữ text_height("ghi_chu"), tự xuống dòng theo bề rộng ô (đệm 1 mm giấy mỗi bên) để không tràn ô; hàng cao theo
    số dòng (bước dòng 1,5 × chiều cao chữ, tối thiểu 6 mm giấy).
  - kẻ lưới: pline kín khung ngoài, line ngang giữa các hàng, line dọc theo ranh giới ô (ô gộp không kẻ).
    eid "hoan_thien/bang/khung", ".../ke_ngang/<k>", ".../ke_doc/<ranh giới cột>/<đoạn>",
    chữ ".../<ô>/<dòng>" với ô = "tieu_de", "cot/<c>", "hang/<room id>/<c>", "tong/<i>", "ghi_chu/<k>".
  - không nhóm trục V hoặc H nào có toạ độ → không đặt được bảng → ghi chú + result.skip("bang_hoan_thien", lý do).

Skill không sửa store.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from shapely import affinity, prepare
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from shapely.ops import unary_union

from tools.cad_drafting import geom
from tools.cad_drafting.block_library import get_block
from tools.cad_drafting.layers import LAYOUT_PAPER_MM, paper_to_model, text_height
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s01_luoi_truc import axis_unconfirmed_keys
from tools.cad_drafting.skills.s03_tuong import entity_unconfirmed_keys, ref_axis_names
from tools.cad_drafting.store import ProjectStore, Room, StoreError

Point = Tuple[float, float]

AREA_Q = Decimal("0.01")                # m², 2 chữ số
LEVEL_Q = Decimal("0.001")              # m, 3 chữ số
CHAR_WIDTH_RATIO = 0.75                 # bề rộng ký tự ước lượng = 0,75 × chiều cao chữ
LABEL_LINE_GAP_PAPER_MM = 1.0           # khoảng hở giữa các dòng nhãn phòng
LABEL_MARGIN_PAPER_MM = 1.0             # khung chữ nhãn cách mép phần sàn tối thiểu
LABEL_GRID = 24                         # số khoảng chia mỗi phương khi dò vị trí nhãn
TABLE_GAP_PAPER_MM = 22.0               # bảng cách tâm vòng tròn trục ngoài cùng (theo phương X)
TABLE_TITLE = "BẢNG HOÀN THIỆN"
TABLE_COLUMNS: Tuple[Tuple[str, float, str], ...] = (    # (tên cột, rộng mm giấy, căn chữ)
    ("STT", 8.0, "MIDDLE_CENTER"),
    ("Phòng", 24.0, "MIDDLE_LEFT"),
    ("Diện tích (m²)", 16.0, "MIDDLE_CENTER"),
    ("Sàn", 36.0, "MIDDLE_LEFT"),
    ("Tường", 32.0, "MIDDLE_LEFT"),
    ("Trần", 26.0, "MIDDLE_LEFT"),
    ("Cote", 14.0, "MIDDLE_CENTER"),
)
CELL_PAD_PAPER_MM = 1.0                 # đệm chữ trong ô (mỗi bên)
LINE_PITCH_RATIO = 1.5                  # bước dòng = 1,5 × chiều cao chữ
MIN_ROW_PAPER_MM = 6.0
DOUBT_MARK = "*"
NOT_COMPUTED = "chưa tính"
NOT_ENTERED = "chưa nhập"
NDIGITS = 6
UNIT_WORDS = frozenset({"m", "mm", "cm", "m²", "m2", "m³", "m3", "kg", "%"})   # không đứng đầu dòng một mình


# ── số liệu: diện tích, cote ────────────────────────────────────────────────

def area_m2(poly: Polygon) -> Decimal:
    """Diện tích (m²) làm tròn half-up 2 chữ số bằng Decimal. Diện tích mm² làm tròn 3 chữ số trước khi đổi để bỏ sai
    số dấu phẩy động (vd 12344999,9999999 mm² → 12,35 m², không phải 12,34)."""
    mm2 = Decimal(repr(round(float(poly.area), 3)))
    return (mm2 / Decimal(1_000_000)).quantize(AREA_Q, rounding=ROUND_HALF_UP)


def format_area(value: Decimal) -> str:
    """Decimal m² → "30,24" (dấu phẩy thập phân, dấu chấm phân nghìn: "1.234,50")."""
    s = format(Decimal(value).quantize(AREA_Q, rounding=ROUND_HALF_UP), ",.2f")
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def level_value(value) -> Optional[float]:
    """Cote sàn (mm) dạng số hữu hạn, hoặc None nếu không phải số."""
    if isinstance(value, (str, bytes, bool)) or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def format_level(level_mm: float) -> str:
    """Cote sàn mm → ký hiệu m: 0 → "±0.000", 450 → "+0.450", -20 → "-0.020" (half-up, 3 chữ số, dấu chấm)."""
    d = (Decimal(repr(float(level_mm))) / Decimal(1000)).quantize(LEVEL_Q, rounding=ROUND_HALF_UP)
    if d == 0:
        return "±0.000"
    return ("+" if d > 0 else "-") + format(abs(d), ".3f")


# ── phòng: lý do chưa dựng được, số liệu nội suy, cơ sở diện tích ──────────

def room_skip_reason(store: ProjectStore, room: Room) -> str:
    """Lý do phòng chưa dựng được đa giác ("" nếu được) — cùng điều kiện với geom.room_polygon, kèm khoá nhịp thiếu.
    Dữ liệu sai cấu trúc trả về thành lý do, không ném lỗi."""
    refs = room.boundary
    if not isinstance(refs, (list, tuple)) or len(refs) < 3:
        return "đường bao phòng cần ít nhất 3 điểm"
    pts: List[Point] = []
    axes_unknown: List[str] = []
    keys: List[str] = []
    other: List[str] = []
    for ref in refs:
        try:
            p, why = store.point_or_reason(ref)
        except (StoreError, TypeError, ValueError) as e:
            return f"đường bao phòng sai cấu trúc: {e}"
        if p is not None:
            pts.append(p)
            continue
        found = False
        for a in ref_axis_names(ref):
            g = store.axis_group_of(a)
            if g is not None and g.offset_of(a) is None:
                found = True
                if a not in axes_unknown:
                    axes_unknown.append(a)
                k = store.missing_span_key(a)
                if k and k not in keys:
                    keys.append(k)
        if not found and why not in other:
            other.append(why)
    if axes_unknown or other:
        parts = []
        if axes_unknown:
            parts.append(f"trục {', '.join(axes_unknown)} chưa có toạ độ (thiếu nhịp trục"
                         + (f"; khoá {', '.join(keys)}" if keys else "") + ")")
        parts += other
        return "đường bao phòng chưa có toạ độ: " + "; ".join(parts)
    poly = Polygon(pts)
    if not poly.is_valid:
        return "đường bao phòng tự cắt hoặc suy biến — đa giác không hợp lệ"
    if poly.area <= 0:
        return "đường bao phòng suy biến (diện tích 0)"
    return ""


def room_unconfirmed_keys(store: ProjectStore, room: Room) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà ĐƯỜNG BAO phòng (vị trí, diện tích, vùng hatch) phụ thuộc: cả phòng,
    trường boundary và nhịp trục của các điểm bao."""
    keys = [k for k in entity_unconfirmed_keys("rooms", room)
            if k in (f"rooms:{room.id}", f"rooms:{room.id}.boundary")]
    refs = room.boundary if isinstance(room.boundary, (list, tuple)) else []
    for ref in refs:
        for a in ref_axis_names(ref):
            for k in axis_unconfirmed_keys(store, a):
                if k not in keys:
                    keys.append(k)
    return keys


def level_unconfirmed_keys(room: Room) -> List[str]:
    """Khoá số liệu nội suy CHƯA xác nhận mà cote sàn phụ thuộc."""
    return [k for k in entity_unconfirmed_keys("rooms", room)
            if k in (f"rooms:{room.id}", f"rooms:{room.id}.floor_level")]


def edges_on_axes_or_walls(store: ProjectStore, poly: Polygon) -> bool:
    """True nếu MỌI cạnh đường bao nằm trên một đường trục đã biết hoặc trên tim một tường dựng được — tức diện tích là
    theo tim trục / tim tường (chưa trừ chiều dày tường), không phải thông thủy."""
    tol = geom.TOL
    offs: Dict[str, List[float]] = {}
    for o in ("V", "H"):
        g = store.axes.get(o)
        offs[o] = [v for v in (g.offsets() if g else []) if v is not None]
    wall_axes = [geom.wall_axis(store, w) for w in store.walls if not geom.wall_reason(store, w)]
    coords = list(poly.exterior.coords)
    for a, b in zip(coords, coords[1:]):
        on_axis = ((abs(a[0] - b[0]) <= tol and any(abs(a[0] - v) <= tol for v in offs["V"]))
                   or (abs(a[1] - b[1]) <= tol and any(abs(a[1] - h) <= tol for h in offs["H"])))
        on_wall = any(geom.dist_point_segment(a, p, q) <= tol and geom.dist_point_segment(b, p, q) <= tol
                      for p, q in wall_axes)
        if not (on_axis or on_wall):
            return False
    return True


# ── chữ: bề rộng ước lượng, xuống dòng ──────────────────────────────────────

def text_width(text: str, height: float) -> float:
    """Bề rộng ước lượng của một dòng chữ (mm model) = số ký tự × 0,75 × chiều cao."""
    return CHAR_WIDTH_RATIO * float(height) * len(unicodedata.normalize("NFC", str(text)))


def wrap_text(text: str, max_width: float, height: float) -> List[str]:
    """Tách chữ thành các dòng có bề rộng ước lượng ≤ max_width (ngắt ở dấu cách, không tách đơn vị khỏi số đứng
    trước; từ dài hơn một dòng thì cắt cứng). Chữ rỗng → []."""
    s = unicodedata.normalize("NFC", " ".join(str(text).split()))
    if not s:
        return []
    max_chars = max(1, int(math.floor(max_width / (CHAR_WIDTH_RATIO * float(height)) + 1e-9)))
    tokens: List[str] = []
    for word in s.split(" "):
        if tokens and word in UNIT_WORDS:          # giữ đơn vị liền số đứng trước ("1,5 m")
            tokens[-1] += " " + word
        else:
            tokens.append(word)
    lines: List[str] = []
    cur = ""
    for word in tokens:
        while len(word) > max_chars:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if not word:
            continue
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ── nhãn phòng: tìm vị trí ──────────────────────────────────────────────────

def _r(v: float) -> float:
    return round(float(v), NDIGITS) + 0.0


def _largest_polygon(g: BaseGeometry) -> Optional[Polygon]:
    best = None
    stack = [g]
    while stack:
        x = stack.pop()
        if x is None or x.is_empty:
            continue
        if isinstance(x, Polygon):
            if best is None or x.area > best.area:
                best = x
        elif hasattr(x, "geoms"):
            stack.extend(x.geoms)
    return best


def label_anchor(region: BaseGeometry, width: float, height: float, margin: float) -> Optional[Point]:
    """Tâm khối chữ rộng `width` × cao `height` sao cho khung chữ nới `margin` nằm trọn trong `region`: thử trọng tâm
    phần lớn nhất của vùng, rồi lưới (LABEL_GRID+1)² điểm theo khoảng cách tới trọng tâm (hoà thì theo x, y); lượt hai
    bỏ margin. Không chỗ nào vừa → None. Tất định."""
    main = _largest_polygon(region)
    if main is None:
        return None
    c = main.centroid
    cx, cy = c.x, c.y
    minx, miny, maxx, maxy = region.bounds
    grid = [(minx + (maxx - minx) * i / LABEL_GRID, miny + (maxy - miny) * j / LABEL_GRID)
            for i in range(LABEL_GRID + 1) for j in range(LABEL_GRID + 1)]
    grid.sort(key=lambda p: (round(math.hypot(p[0] - cx, p[1] - cy), 6), round(p[0], 6), round(p[1], 6)))
    candidates = [(cx, cy)] + grid
    target = region.buffer(0)
    prepare(target)
    for m in (margin, 0.0):
        hw, hh = width / 2.0 + m, height / 2.0 + m
        for x, y in candidates:
            if target.contains(box(x - hw, y - hh, x + hw, y + hh)):
                return (_r(x), _r(y))
    return None


TEXT_OVERLAP_WEIGHT = 100.0               # đè chữ khác (không đọc được) bị phạt nặng hơn đè nét vẽ


def label_anchor_min_overlap(region: BaseGeometry, obstacles: BaseGeometry, width: float, height: float,
                             margin: float, texts: Optional[BaseGeometry] = None) -> Optional[Point]:
    """Khi không có chỗ trống đủ: trong các vị trí khung chữ nằm trọn trong `region`, chọn chỗ đè vật ÍT nhất — diện tích
    đè vật + TEXT_OVERLAP_WEIGHT × diện tích đè chữ khác (`texts`) — hoà thì gần trọng tâm hơn. Tất định. Không vị trí
    nào nằm trọn → None."""
    main = _largest_polygon(region)
    if main is None:
        return None
    c = main.centroid
    minx, miny, maxx, maxy = region.bounds
    target = region.buffer(0)
    prepare(target)
    best = None
    for m in (margin, 0.0):
        hw, hh = width / 2.0 + m, height / 2.0 + m
        for i in range(LABEL_GRID + 1):
            for j in range(LABEL_GRID + 1):
                x = minx + (maxx - minx) * i / LABEL_GRID
                y = miny + (maxy - miny) * j / LABEL_GRID
                b = box(x - hw, y - hh, x + hw, y + hh)
                if not target.contains(b):
                    continue
                cost = b.intersection(obstacles).area
                if texts is not None and not texts.is_empty:
                    cost += TEXT_OVERLAP_WEIGHT * b.intersection(texts).area
                key = (round(cost, 3), round(math.hypot(x - c.x, y - c.y), 6), x, y)
                if best is None or key < best[0]:
                    best = (key, (_r(x), _r(y)))
        if best is not None:
            return best[1]
    return None


def stack_lines(anchor: Point, heights: Sequence[float], gap: float, centered: bool = True) -> List[Point]:
    """Điểm chèn MIDDLE_CENTER của các dòng xếp từ trên xuống. centered=True: tâm cả khối tại anchor; False: dòng đầu
    tại anchor."""
    total = sum(heights) + gap * max(len(heights) - 1, 0)
    top = anchor[1] + (total / 2.0 if centered else heights[0] / 2.0)
    out = []
    for h in heights:
        out.append((_r(anchor[0]), _r(top - h / 2.0)))
        top -= h + gap
    return out


# ── bảng hoàn thiện: bố cục ─────────────────────────────────────────────────

@dataclass
class TableCell:
    key: str                       # phần eid: "tieu_de", "cot/<c>", "hang/<room id>/<c>", "tong/<i>", "ghi_chu/<k>"
    c0: int                        # cột đầu (gồm)
    c1: int                        # cột cuối (không gồm) — ô gộp khi c1 − c0 > 1
    text: str
    height: float                  # chiều cao chữ (mm model)
    align: str                     # "MIDDLE_LEFT" | "MIDDLE_CENTER"
    lines: List[str] = field(default_factory=list)
    rect: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)     # (x0, y0 dưới, x1, y1 trên)
    inserts: List[Point] = field(default_factory=list)


@dataclass
class TableLayout:
    origin: Point                  # góc trên-trái
    col_edges: List[float]         # toạ độ x các ranh giới cột (len = số cột + 1)
    row_edges: List[float]         # toạ độ y các ranh giới hàng, từ trên xuống (len = số hàng + 1)
    rows: List[List[TableCell]]
    overflow: List[str] = field(default_factory=list)   # ô có dòng chữ vẫn rộng hơn ô (không xảy ra với cột mặc định)

    def frame(self) -> List[Point]:
        x0, x1 = self.col_edges[0], self.col_edges[-1]
        y1, y0 = self.row_edges[0], self.row_edges[-1]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def horizontal_lines(self) -> List[Tuple[Point, Point]]:
        x0, x1 = self.col_edges[0], self.col_edges[-1]
        return [((x0, y), (x1, y)) for y in self.row_edges[1:-1]]

    def vertical_lines(self) -> Dict[int, List[Tuple[Point, Point]]]:
        """{ranh giới cột b: [đoạn]} — chỉ kẻ ở hàng mà b là ranh giới giữa hai ô; các hàng liền nhau gộp một đoạn."""
        out: Dict[int, List[Tuple[Point, Point]]] = {}
        for b in range(1, len(self.col_edges) - 1):
            x = self.col_edges[b]
            segs: List[Tuple[Point, Point]] = []
            start = None
            for r, cells in enumerate(self.rows + [[]]):
                has = any(c.c0 == b for c in cells)
                if has and start is None:
                    start = r
                elif not has and start is not None:
                    segs.append(((x, self.row_edges[start]), (x, self.row_edges[r])))
                    start = None
            if segs:
                out[b] = segs
        return out


def build_table(origin: Point, scale: int, rows: List[List[TableCell]],
                col_widths_paper: Sequence[float] = tuple(w for _, w, _ in TABLE_COLUMNS)) -> TableLayout:
    """Bố cục bảng: ngắt dòng chữ từng ô theo bề rộng ô, tính chiều cao hàng, khung ô và điểm chèn từng dòng."""
    pad = paper_to_model(CELL_PAD_PAPER_MM, scale)
    min_row = paper_to_model(MIN_ROW_PAPER_MM, scale)
    col_edges = [float(origin[0])]
    for w in col_widths_paper:
        col_edges.append(col_edges[-1] + paper_to_model(w, scale))
    overflow: List[str] = []
    heights = []
    for cells in rows:
        need = min_row
        for c in cells:
            avail = col_edges[c.c1] - col_edges[c.c0] - 2 * pad
            c.lines = wrap_text(c.text, avail, c.height)
            if any(text_width(ln, c.height) > avail + 1e-6 for ln in c.lines):
                overflow.append(c.key)
            need = max(need, len(c.lines) * LINE_PITCH_RATIO * c.height + 2 * pad)
        heights.append(need)
    row_edges = [float(origin[1])]
    for h in heights:
        row_edges.append(row_edges[-1] - h)
    for r, cells in enumerate(rows):
        y1, y0 = row_edges[r], row_edges[r + 1]
        for c in cells:
            x0, x1 = col_edges[c.c0], col_edges[c.c1]
            c.rect = (x0, y0, x1, y1)
            pitch = LINE_PITCH_RATIO * c.height
            top = (y0 + y1) / 2.0 + len(c.lines) * pitch / 2.0
            x = x0 + pad if c.align == "MIDDLE_LEFT" else (x0 + x1) / 2.0
            c.inserts = [(_r(x), _r(top - (j + 0.5) * pitch)) for j in range(len(c.lines))]
    return TableLayout(origin=(float(origin[0]), float(origin[1])), col_edges=col_edges, row_edges=row_edges,
                       rows=rows, overflow=overflow)


def table_origin(store: ProjectStore) -> Tuple[Optional[Point], str, List[str]]:
    """(góc trên-trái bảng, "", [trục chưa có toạ độ]) hoặc (None, lý do không đặt được, [])."""
    scale = int(store.project.scale)
    known: Dict[str, Optional[float]] = {}
    unknown: List[str] = []
    for o in ("V", "H"):
        g = store.axes.get(o)
        offs = g.offsets() if g is not None else []
        vals = [v for v in offs if v is not None]
        known[o] = max(vals) if vals else None
        if g is not None:
            unknown += [n for n, v in zip(g.names, offs) if v is None]
    missing = [o for o in ("V", "H") if known[o] is None]
    if missing:
        names = {"V": "trục đứng (V)", "H": "trục ngang (H)"}
        return None, ("không có " + " và ".join(names[o] for o in missing) + " nào có toạ độ — không xác định được vị "
                      "trí bảng hoàn thiện (bên phải hình vẽ, theo trục ngoài cùng)"), []
    x = known["V"] + paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"] + TABLE_GAP_PAPER_MM, scale)
    y = known["H"] + paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"], scale)
    return (_r(x), _r(y)), "", unknown


# ── skill ────────────────────────────────────────────────────────────────────

@dataclass
class _RoomInfo:
    room: Room
    poly: Optional[Polygon]
    reason: str
    area: Optional[Decimal]
    area_doubt: List[str]
    level: Optional[float]
    level_text: str
    level_doubt: List[str]


def _clean(value) -> str:
    return "" if value is None else " ".join(str(value).split())


def _cell_text(value) -> str:
    return _clean(value) or NOT_ENTERED


class HoanThienSkill(DraftSkill):
    code = "09"
    name = "Hoàn thiện"
    reads = ("project", "axes", "rooms", "walls", "columns", "furniture", "blocks", "stairs", "openings")

    # ── thu thập số liệu từng phòng ──
    def _room_infos(self, store: ProjectStore, result: SkillResult) -> List[_RoomInfo]:
        infos = []
        for room in store.rooms:
            why = room_skip_reason(store, room)
            poly = None if why else geom.room_polygon(store, room)
            if poly is None and not why:
                why = "không dựng được đa giác phòng từ số liệu hiện có"
            area = area_m2(poly) if poly is not None else None
            level, level_text = None, ""
            if room.floor_level is not None:
                level = level_value(room.floor_level)
                if level is None:
                    result.skip(f"hoan_thien:{room.id}/cote", f"cote sàn {room.floor_level!r} không phải số")
                else:
                    level_text = format_level(level)
            area_doubt = room_unconfirmed_keys(store, room) if poly is not None else []
            level_doubt = level_unconfirmed_keys(room) if level_text else []
            infos.append(_RoomInfo(room, poly, why, area, area_doubt, level, level_text, level_doubt))
        return infos

    # ── nhãn phòng ──
    def _labels(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult,
                infos: List[_RoomInfo]) -> None:
        scale = int(store.project.scale)
        h_name, h_small = text_height("ten_phong", scale), text_height("dien_tich", scale)
        gap = paper_to_model(LABEL_LINE_GAP_PAPER_MM, scale)
        margin = paper_to_model(LABEL_MARGIN_PAPER_MM, scale)
        walls = geom.walls_union(store)
        obstacles = self._obstacles(store)
        texts = self._existing_text_boxes(plan)
        if not texts.is_empty:
            obstacles = obstacles.union(texts)
        labelled, not_fit, on_objects = 0, [], []
        for info in infos:
            room = info.room
            if info.poly is None:
                result.skip(f"hoan_thien:{room.id}", info.reason)
                continue
            name = _clean(room.name)
            lines: List[Tuple[str, str, float]] = []       # (phần eid, chữ, chiều cao)
            if name:
                lines.append(("ten", name, h_name))
            else:
                result.skip(f"hoan_thien:{room.id}/ten", "phòng chưa có tên")
            mark = DOUBT_MARK if info.area_doubt else ""
            lines.append(("dien_tich", f"S = {format_area(info.area)} m²{mark}", h_small))
            if info.level_text:
                lines.append(("cote", info.level_text + (DOUBT_MARK if info.level_doubt else ""), h_small))
            heights = [h for _, _, h in lines]
            width = max(text_width(t, h) for _, t, h in lines)
            height = sum(heights) + gap * (len(lines) - 1)
            region = info.poly.difference(walls)
            if region.is_empty:
                region = info.poly
            anchor = None
            if room.label_at is not None:
                try:
                    at = store.point(room.label_at)
                except StoreError as e:
                    at = None
                    result.notes.append(f"label_at của phòng {room.id} sai: {e} — tự tìm chỗ đặt nhãn")
                if at is not None:
                    anchor = (_r(at[0]), _r(at[1]))
            if anchor is None:
                free = region.difference(obstacles) if not obstacles.is_empty else region
                anchor = label_anchor(free, width, height, margin) if not free.is_empty else None
                if anchor is None:
                    anchor = label_anchor_min_overlap(region, obstacles, width, height, margin, texts)
                    if anchor is not None:
                        on_objects.append(room.id)
            if anchor is not None:
                inserts = stack_lines(anchor, heights, gap, centered=True)
            else:
                main = _largest_polygon(region) or info.poly
                rp = main.representative_point()
                inserts = stack_lines((rp.x, rp.y), heights, gap, centered=False)
                not_fit.append(room.id)
            for (part, text, h), ins in zip(lines, inserts):
                self.add(plan, "text", "hoan_thien", f"hoan_thien/{room.id}/{part}", insert=ins, text=text,
                         height=h, rotation=0.0, align="MIDDLE_CENTER")
            labelled += 1
        result.notes.append(f"đã ghi nhãn (tên, diện tích, cote) {labelled}/{len(infos)} phòng")
        if on_objects:
            result.notes.append("CẢNH BÁO không còn chỗ trống đủ cho nhãn, nhãn đè lên nội thất/thang/cửa (vẫn trong sàn) — "
                                "đặt room.label_at để chỉnh: " + ", ".join(on_objects))
        if not_fit:
            result.notes.append("CẢNH BÁO nhãn không vừa trọn trong phần sàn trống của phòng (tên đặt tại điểm trong "
                                "phòng, các dòng sau có thể ra ngoài) — cần chỉnh tay: " + ", ".join(not_fit))

    @staticmethod
    def _existing_text_boxes(plan: DrawingPlan) -> BaseGeometry:
        """Hộp chữ (ước lượng) của các skill chạy trước (ký hiệu cửa, chữ LÊN của thang...) để nhãn phòng không đè."""
        boxes = []
        for op in plan.ops:
            # chỉ chữ của skill chạy TRƯỚC 09 — chữ khung tên / dấu kiểm tra (skill 10) của lần trước không được ảnh
            # hưởng vị trí nhãn, để chạy cập nhật cho cùng kết quả như chạy lại toàn bộ
            if op.kind != "text" or op.skill >= "09":
                continue
            d = op.data
            w, h = text_width(d["text"], d["height"]), d["height"]
            x, y = d["insert"]
            align = d["align"]
            dx = {"LEFT": 0.0, "RIGHT": -w}.get(align, -w / 2.0)
            if align.endswith("_LEFT"):
                dx = 0.0
            elif align.endswith("_RIGHT"):
                dx = -w
            dy = -h / 2.0 if align.startswith("MIDDLE") else (-h if align.startswith("TOP") else 0.0)
            b = box(x + dx, y + dy, x + dx + w, y + dy + h)
            if d["rotation"]:
                b = affinity.rotate(b, d["rotation"], origin=(x, y))
            boxes.append(b)
        return unary_union(boxes) if boxes else Polygon()

    @staticmethod
    def _obstacles(store: ProjectStore) -> BaseGeometry:
        """Vùng nhãn phòng nên tránh: cột, vết nội thất, vế thang, vùng quét cánh cửa (đối tượng thiếu số liệu bỏ qua —
        chính skill vẽ chúng đã báo)."""
        parts = []
        for c in store.columns:
            p = geom.column_polygon(store, c)
            if p is not None:
                parts.append(p)
        for f in store.furniture:
            p = geom.block_footprint(store, f, get_block(f.block, store))
            if p is not None:
                parts.append(p)
        parts += geom.stair_polygons(store)                  # vế thang và chiếu nghỉ
        for op in store.openings:
            p = geom.door_swing_polygon(store, op)
            if p is not None:
                parts.append(p)
        return unary_union(parts) if parts else Polygon()

    # ── cơ sở diện tích ──
    @staticmethod
    def _basis_note(store: ProjectStore, infos: List[_RoomInfo]) -> str:
        done = [i for i in infos if i.poly is not None]
        if not done:
            return "Ghi chú: diện tích tính theo đường bao nhập của phòng — chưa tính được phòng nào."
        on = [i.room.id for i in done if edges_on_axes_or_walls(store, i.poly)]
        off = [i.room.id for i in done if i.room.id not in on]
        if not off:
            return (f"Ghi chú: diện tích tính theo đường bao nhập; {len(on)}/{len(done)} phòng có đường bao trùng tim "
                    f"trục/tim tường — chưa trừ chiều dày tường, KHÔNG phải diện tích thông thủy.")
        s = "Ghi chú: diện tích tính theo đường bao nhập; "
        if on:
            s += (f"{len(on)}/{len(done)} phòng có đường bao trùng tim trục/tim tường (chưa trừ chiều dày tường, không "
                  f"phải thông thủy); ")
        return s + (f"{len(off)} phòng ({', '.join(off)}) theo đường bao người nhập, chưa xác định là tim trục hay "
                    f"thông thủy.")

    # ── bảng ──
    def _table(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult, infos: List[_RoomInfo],
               basis: str) -> None:
        if not infos:
            result.notes.append("không có phòng nào trong dữ liệu — không lập bảng hoàn thiện")
            return
        origin, why, unknown_axes = table_origin(store)
        if origin is None:
            result.notes.append(f"không đặt được bảng hoàn thiện: {why}")
            result.skip("bang_hoan_thien", why)
            return
        scale = int(store.project.scale)
        h = text_height("ghi_chu", scale)
        h_title = text_height("ten_phong", scale)
        n_cols = len(TABLE_COLUMNS)
        rows: List[List[TableCell]] = [
            [TableCell("tieu_de", 0, n_cols, TABLE_TITLE, h_title, "MIDDLE_CENTER")],
            [TableCell(f"cot/{c}", c, c + 1, name, h, "MIDDLE_CENTER") for c, (name, _, _) in enumerate(TABLE_COLUMNS)],
        ]
        total = Decimal("0.00")
        done, pending, doubt_keys = 0, [], []
        for stt, info in enumerate(infos, start=1):
            room = info.room
            if info.area is not None:
                area_txt = format_area(info.area) + (DOUBT_MARK if info.area_doubt else "")
                total += info.area
                done += 1
            else:
                area_txt = NOT_COMPUTED
                pending.append(room.id)
            level_txt = (info.level_text + (DOUBT_MARK if info.level_doubt else "")) if info.level_text else NOT_ENTERED
            for k in info.area_doubt + info.level_doubt:
                if k not in doubt_keys:
                    doubt_keys.append(k)
            values = [str(stt), _cell_text(room.name), area_txt, _cell_text(room.floor_finish),
                      _cell_text(room.wall_finish), _cell_text(room.ceiling_finish), level_txt]
            rows.append([TableCell(f"hang/{room.id}/{c}", c, c + 1, v, h, TABLE_COLUMNS[c][2])
                         for c, v in enumerate(values)])
        total_doubt = any(i.area_doubt for i in infos if i.area is not None)
        total_txt = format_area(total) + (DOUBT_MARK if total_doubt else "")
        if pending:
            coverage = (f"tính {done}/{len(infos)} phòng; chưa tính {len(pending)} phòng ({', '.join(pending)}): "
                        f"thiếu toạ độ / đường bao không hợp lệ")
        else:
            coverage = f"tính {done}/{len(infos)} phòng"
        rows.append([TableCell("tong/0", 0, 2, "Tổng diện tích", h, "MIDDLE_LEFT"),
                     TableCell("tong/1", 2, 3, total_txt, h, "MIDDLE_CENTER"),
                     TableCell("tong/2", 3, n_cols, coverage, h, "MIDDLE_LEFT")])
        notes = [basis]
        if doubt_keys:
            notes.append(f"({DOUBT_MARK}) số liệu dựa trên nội suy CHƯA xác nhận: {', '.join(doubt_keys)}")
        for k, note in enumerate(notes):
            rows.append([TableCell(f"ghi_chu/{k}", 0, n_cols, note, h, "MIDDLE_LEFT")])

        layout = build_table(origin, scale, rows)
        self.add(plan, "pline", "hoan_thien", "hoan_thien/bang/khung", points=layout.frame(), closed=True)
        for k, (p1, p2) in enumerate(layout.horizontal_lines(), start=1):
            self.add(plan, "line", "hoan_thien", f"hoan_thien/bang/ke_ngang/{k}", p1=p1, p2=p2)
        for b, segs in sorted(layout.vertical_lines().items()):
            for s, (p1, p2) in enumerate(segs):
                self.add(plan, "line", "hoan_thien", f"hoan_thien/bang/ke_doc/{b}/{s}", p1=p1, p2=p2)
        for cells in layout.rows:
            for c in cells:
                for j, (line, ins) in enumerate(zip(c.lines, c.inserts)):
                    self.add(plan, "text", "hoan_thien", f"hoan_thien/bang/{c.key}/{j}", insert=ins, text=line,
                             height=c.height, rotation=0.0, align=c.align)
        result.notes.append(f"bảng hoàn thiện: {len(infos)} hàng phòng, góc trên-trái ({origin[0]:.0f}, "
                            f"{origin[1]:.0f}); tổng diện tích {total_txt} m² ({coverage})")
        if unknown_axes:
            result.notes.append("CẢNH BÁO vị trí bảng tính theo trục đã biết lớn nhất — trục "
                                f"{', '.join(unknown_axes)} chưa có toạ độ; bổ sung số liệu thì bảng sẽ dời và có thể "
                                "đang đè hình vẽ")
        if layout.overflow:
            result.notes.append("CẢNH BÁO ô bảng có từ dài hơn bề rộng ô (chữ có thể tràn): "
                                + ", ".join(layout.overflow))

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        infos = self._room_infos(store, result)
        self._labels(store, plan, result, infos)
        basis = self._basis_note(store, infos)
        result.notes.append(basis[len("Ghi chú: "):] if basis.startswith("Ghi chú: ") else basis)
        self._table(store, plan, result, infos, basis)

        no_level = [i.room.id for i in infos if i.room.floor_level is None]
        if no_level:
            result.notes.append("phòng chưa nhập cote sàn (floor_level) — không ghi cote: " + ", ".join(no_level))
        missing_finish = []
        for i in infos:
            miss = [label for label, v in (("sàn", i.room.floor_finish), ("tường", i.room.wall_finish),
                                           ("trần", i.room.ceiling_finish)) if not _clean(v)]
            if miss:
                missing_finish.append(f"{i.room.id} ({', '.join(miss)})")
        if missing_finish:
            result.notes.append("phòng chưa nhập hoàn thiện (bảng ghi \"chưa nhập\"): " + "; ".join(missing_finish))
        doubtful = [f"{i.room.id} ({', '.join(i.area_doubt + [k for k in i.level_doubt if k not in i.area_doubt])})"
                    for i in infos if i.area_doubt or i.level_doubt]
        if doubtful:
            result.notes.append(f"diện tích/cote dựa trên số liệu nội suy CHƯA xác nhận (đánh dấu {DOUBT_MARK}): "
                                + "; ".join(doubtful))
