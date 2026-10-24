# -*- coding: utf-8 -*-
"""
SKILL 10 — KIỂM TRA & XUẤT: khung bản vẽ, khung tên (vai trò "khung_ten") và đánh dấu kiểm tra (vai trò "kiem_tra",
layer không in).

Khung giấy:
  - Bao nội dung = bao hình mọi điểm (plan.iter_points) của các Op KHÔNG thuộc skill 10, nới thêm
    CONTENT_PAD_PAPER_MM mm giấy (iter_points chỉ lấy điểm chèn của chữ, chữ thật còn chiếm chỗ quanh điểm đó).
    Dưới bao nội dung là dải tên bản vẽ ("<drawing_title>" cao text_height("tieu_de") và "TỶ LỆ 1:<scale>" ngay
    dưới, căn giữa theo bao nội dung).
  - Khổ giấy store.project.sheet (layers.SHEET_SIZES_MM, khổ ngang) ở tỷ lệ 1:scale → khung giấy (model mm) =
    khổ × scale. Vùng vẽ = trong lề (LAYOUT_PAPER_MM sheet_margin_left bên trái, sheet_margin ba cạnh còn lại) trừ
    khung tên góc dưới-phải. Khối (bao nội dung + dải tên bản vẽ) được căn giữa trong dải phía TRÊN khung tên; không
    vừa thì thử dải bên TRÁI khung tên; gốc khung giấy làm tròn tới bội số của tỷ lệ (1 mm giấy) khi vẫn vừa.
  - Không vừa cả hai → vẫn vẽ khung (căn giữa theo khối), ghi note + result.skip("khung_ban_ve", "nội dung vượt khổ
    <khổ> ở tỷ lệ 1:<scale> ...") để Validator/Master báo. Khổ giấy lạ (không có trong SHEET_SIZES_MM) → skip, không vẽ
    khung, không có plan.meta["sheet_frame"].
  - plan.meta["sheet_frame"] = [xmin, ymin, xmax, ymax] (mép giấy, model mm);
    plan.meta["sheet"] = {"size": ..., "scale": ..., "paper_mm": [w, h]}.

Vẽ (eid đã có tiền tố "10/" do DraftSkill.add gắn):
  khung_ten/vien_giay         pline kín mép giấy, nét mảnh (lineweight 13)
  khung_ten/khung_ve          pline kín khung bản vẽ trong lề, nét đậm (lineweight 50)
  khung_ten/o/vien            cạnh trái + cạnh trên khung tên 180 × 40 mm giấy, góc dưới-phải khung bản vẽ (cạnh dưới/phải
                              là khung bản vẽ — không vẽ lại để khỏi trùng nét) (lineweight 50)
  khung_ten/o/ke/<i>          line kẻ ô khung tên (lineweight 18)
  khung_ten/nhan/<ô>[/<i>]    chữ nhãn ô (DỰ ÁN, BẢN VẼ, THIẾT KẾ, KIỂM TRA, SỐ HIỆU, TỶ LỆ, LẦN SỬA, NGÀY, TRẠNG THÁI SỐ LIỆU)
  khung_ten/gia_tri/<ô>       giá trị ô lấy từ ProjectInfo — ô trống khi ProjectInfo không có (KHÔNG bịa tên); riêng
                              ô "trang_thai" TÍNH từ store.status() (status_text): "THIẾU 2 KÍCH THƯỚC", "CHỜ XÁC NHẬN
                              2 SỐ LIỆU NỘI SUY", "CHỜ DUYỆT", "ĐÃ DUYỆT (<người>)"
  khung_ten/ten_ban_ve        tên bản vẽ dưới hình (bỏ qua kèm note nếu ProjectInfo.drawing_title rỗng)
  khung_ten/ty_le             "TỶ LỆ 1:<scale>" dưới tên bản vẽ
  Chữ dài hơn ô được hạ chiều cao cho vừa (ước lượng bề rộng chữ ≈ CHAR_WIDTH_RATIO × chiều cao × số ký tự), không
  nhỏ hơn MIN_TEXT_PAPER_MM; vẫn không vừa → CẢNH BÁO trong notes.

Đánh dấu kiểm tra (vai trò "kiem_tra", không in) — mỗi mục: circle bán kính MARKER_R_PAPER_MM mm giấy × scale
(eid "kiem_tra/<khoá>/vong") + chữ bên phải vòng tròn (eid "kiem_tra/<khoá>/chu"):
  - store.missing():     "THIẾU: <khoá>" tại vị trí xác định được: nhịp trục thiếu → trên đường kích thước cấp 2 phía
                         dưới (trục V) / trái (trục H), ngay sau trục đầu nhịp nếu trục đó có toạ độ; ô cửa → trung điểm
                         ô cửa / mép đầu ô cửa / trung điểm tim tường; cột → tâm cột; tường → trung điểm tim; vế thang →
                         gốc vế. Không xác định được → liệt kê trong một mtext ở góc trên-trái khung bản vẽ
                         (eid "kiem_tra/thieu_chua_dinh_vi").
  - store.unconfirmed(): "NỘI SUY – CHƯA XÁC NHẬN: <khoá>": nhịp trục → trung điểm hai trục trên đường kích thước cấp 2
                         phía dưới (trục V) / trái (trục H); cửa → trung điểm ô cửa; cột → tâm cột; tường → trung điểm
                         tim; còn lại → góc dưới-trái bao nội dung (xếp chồng lên trên nếu nhiều mục).
                         Khoá vừa thiếu vừa nội suy (giá trị None) chỉ đánh dấu một lần với chữ "THIẾU".
  - plan.meta["validator_issues"] (Master đặt trước khi chạy skill 10; mỗi mục có "where") → "<mức độ>: <mã>"
    tại "where" (eid "kiem_tra/val/<i>/vong|chu").
  Hai dấu gần nhau (tâm cách < 2 bán kính) → chữ dấu sau được hạ xuống một dòng để không đè.

Skill không sửa store; chạy lại không nhân đôi (DraftSkill.run xoá Op cũ của skill, meta được ghi đè).
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from tools.cad_drafting import geom
from tools.cad_drafting.layers import (LAYOUT_PAPER_MM, SHEET_SIZES_MM, TEXT_PAPER_MM, paper_to_model,
                                       text_height)
from tools.cad_drafting.plan import DrawingPlan, iter_points
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s08_dimension import axis_frames, dim_line_position
from tools.cad_drafting.store import (DATA_SECTIONS, SEV_DOUBT, SEV_ERROR, SEV_WARN, ProjectStore, StoreError)

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

# ── kích thước trên giấy (mm) ────────────────────────────────────────────────
CONTENT_PAD_PAPER_MM = 5.0        # nới bao nội dung (chữ chiếm chỗ quanh điểm chèn)
TITLE_GAP_PAPER_MM = 4.0          # bao nội dung → tên bản vẽ
SCALE_GAP_PAPER_MM = 2.0          # tên bản vẽ → dòng tỷ lệ
SCALE_LABEL_PAPER_MM = 3.0        # chiều cao chữ "TỶ LỆ 1:<scale>" dưới tên bản vẽ
TB_W_PAPER_MM = 180.0             # khung tên
TB_H_PAPER_MM = 40.0
TB_GAP_PAPER_MM = 2.0             # khoảng trống giữa khung tên và vùng đặt hình
TB_COLS = (24.0, 110.0, 134.0)    # vạch đứng: hết cột nhãn | hết giá trị 1 | hết nhãn 2
TB_ROWS = (6.0, 12.0, 18.0, 24.0, 32.0)   # vạch ngang tính từ đáy khung tên
TB_LABEL_PAPER_MM = 2.0           # chữ nhãn ô
TB_EMPH_PAPER_MM = 3.5            # chữ tên dự án, tên bản vẽ trong khung tên
TB_PAD_PAPER_MM = 1.5             # lề chữ trong ô
MIN_TEXT_PAPER_MM = 1.8
CHAR_WIDTH_RATIO = 0.7            # bề rộng trung bình một ký tự ≈ 0,7 × chiều cao (ước lượng, font VN_ARIAL)
LW_THIN, LW_GRID, LW_BOLD = 13, 18, 50
MARKER_R_PAPER_MM = 4.0
MARKER_TEXT_GAP_PAPER_MM = 1.5
MISSING_LIST_WIDTH_PAPER_MM = 150.0

SEV_LABEL = {SEV_ERROR: "LỖI", SEV_DOUBT: "NGHI VẤN", SEV_WARN: "CẢNH BÁO"}

_AXIS_SPAN_KEY = re.compile(r"^axes:([VH])\.spans\[(\d+)\]$")
_ENTITY_KEY = re.compile(r"^(\w+):([^.]+?)(?:\.(.+))?$")
_FLIGHT_FIELD = re.compile(r"^flights\[(\d+)\]\.\w+$")


# ── trợ giúp dùng chung (kiểm thử cũng dùng) ────────────────────────────────

def status_text(status: Dict[str, Any]) -> str:
    """Dòng trạng thái số liệu cho khung tên — TÍNH từ store.status(), không gõ tay."""
    state = status.get("trang_thai")
    n_miss = int(status.get("so_lieu_thieu") or 0)
    n_unc = int(status.get("noi_suy_chua_xac_nhan") or 0)
    if state == "THIEU_KICH_THUOC":
        text = f"THIẾU {n_miss} KÍCH THƯỚC"
        if n_unc:
            text += f" + {n_unc} SỐ LIỆU NỘI SUY CHƯA XÁC NHẬN"
        return text
    if state == "CHO_XAC_NHAN_NOI_SUY":
        return f"CHỜ XÁC NHẬN {n_unc} SỐ LIỆU NỘI SUY"
    if state == "CHO_DUYET":
        return "CHỜ DUYỆT"
    if state == "DA_DUYET":
        by = str(status.get("duyet_boi") or "").strip()
        return f"ĐÃ DUYỆT ({by})" if by else "ĐÃ DUYỆT"
    return f"TRẠNG THÁI CHƯA RÕ: {state}"


def content_bbox(plan: DrawingPlan, exclude_skill: str = "10") -> Optional[Box]:
    """Bao hình (xmin, ymin, xmax, ymax) mọi điểm của các Op không thuộc `exclude_skill`; None nếu không có Op nào."""
    xs: List[float] = []
    ys: List[float] = []
    for op in plan.ops:
        if op.skill == exclude_skill:
            continue
        for x, y in iter_points(op):
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def box_inside(inner: Box, outer: Box, tol: float = 1e-6) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def sheet_layout(paper: Tuple[float, float], scale: int) -> Dict[str, Box]:
    """Các vùng TƯƠNG ĐỐI so với góc dưới-trái tờ giấy (model mm): mép giấy, khung bản vẽ, khung tên và hai vùng đặt
    hình (trên khung tên / trái khung tên)."""
    w, h = paper
    ml, m = LAYOUT_PAPER_MM["sheet_margin_left"], LAYOUT_PAPER_MM["sheet_margin"]
    inner = (ml, m, w - m, h - m)
    tb = (inner[2] - TB_W_PAPER_MM, inner[1], inner[2], inner[1] + TB_H_PAPER_MM)
    above = (inner[0], tb[3] + TB_GAP_PAPER_MM, inner[2], inner[3])
    left = (inner[0], inner[1], tb[0] - TB_GAP_PAPER_MM, inner[3])
    k = float(scale)
    return {name: tuple(v * k for v in box) for name, box in
            (("paper", (0.0, 0.0, w, h)), ("inner", inner), ("title_block", tb), ("above", above), ("left", left))}


def place_sheet(block: Box, paper: Tuple[float, float], scale: int) -> Dict[str, Any]:
    """Đặt tờ giấy quanh khối nội dung. Trả {"origin": (x0, y0), "fits": bool, "region": "above" | "left" | "",
    "frame", "inner", "title_block": Box tuyệt đối (model mm)}."""
    rel = sheet_layout(paper, scale)
    bw, bh = block[2] - block[0], block[3] - block[1]
    bcx, bcy = (block[0] + block[2]) / 2.0, (block[1] + block[3]) / 2.0
    k = float(scale)

    def shifted(box: Box, x0: float, y0: float) -> Box:
        return (box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0)

    chosen: Optional[Tuple[float, float, str]] = None
    for name in ("above", "left"):
        r = rel[name]
        if bw <= (r[2] - r[0]) + 1e-6 and bh <= (r[3] - r[1]) + 1e-6:
            x0 = bcx - (r[0] + r[2]) / 2.0
            y0 = bcy - (r[1] + r[3]) / 2.0
            xr, yr = round(x0 / k) * k, round(y0 / k) * k
            if box_inside(block, shifted(r, xr, yr)):
                x0, y0 = xr, yr
            chosen = (x0, y0, name)
            break
    if chosen is None:
        x0 = bcx - rel["paper"][2] / 2.0
        y0 = bcy - rel["paper"][3] / 2.0
        chosen = (x0, y0, "")
    x0, y0, region = chosen
    return {"origin": (x0, y0), "fits": bool(region), "region": region,
            "frame": shifted(rel["paper"], x0, y0), "inner": shifted(rel["inner"], x0, y0),
            "title_block": shifted(rel["title_block"], x0, y0)}


def fitting_sheets(block: Box, scale: int) -> List[str]:
    """Các khổ trong SHEET_SIZES_MM chứa vừa khối nội dung ở tỷ lệ đã cho (nhỏ → lớn)."""
    out = []
    for name, paper in sorted(SHEET_SIZES_MM.items(), key=lambda kv: kv[1][0] * kv[1][1]):
        if place_sheet(block, paper, scale)["fits"]:
            out.append(name)
    return out


def fit_text_height(text: str, height: float, max_width: float, min_height: float) -> Tuple[float, bool]:
    """(chiều cao, vừa?) — hạ chiều cao chữ cho vừa bề rộng ô (ước lượng), không nhỏ hơn min_height."""
    n = max(len(text), 1)
    if n * CHAR_WIDTH_RATIO * height <= max_width:
        return height, True
    h = max(min_height, max_width / (n * CHAR_WIDTH_RATIO))
    return h, n * CHAR_WIDTH_RATIO * h <= max_width + 1e-9


def _safe_point(store: ProjectStore, ref) -> Optional[Point]:
    try:
        return store.point(ref)
    except StoreError:
        return None


def _wall_mid(store: ProjectStore, wall_id: str) -> Optional[Point]:
    wall = store.get("walls", wall_id)
    if wall is None:
        return None
    a, b = _safe_point(store, wall.start), _safe_point(store, wall.end)
    if a is None or b is None:
        return None
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def marker_position(store: ProjectStore, key: str, frames=None) -> Optional[Point]:
    """Vị trí đánh dấu một khoá số liệu trên hình (model mm); None nếu chưa xác định được."""
    frames = frames if frames is not None else axis_frames(store)
    m = _AXIS_SPAN_KEY.match(key)
    if m:
        o, i = m.group(1), int(m.group(2))
        g = store.axes.get(o)
        if g is None or i >= len(g.spans):
            return None
        offs = g.offsets()
        side = "duoi" if o == "V" else "trai"
        line = dim_line_position(store, side, 2, frames)
        if line is None or offs[i] is None:
            return None
        if offs[i + 1] is not None:
            s = (float(offs[i]) + float(offs[i + 1])) / 2.0
        else:
            s = float(offs[i]) + 2.0 * paper_to_model(MARKER_R_PAPER_MM, int(store.project.scale))
        return (s, line) if o == "V" else (line, s)
    m = _ENTITY_KEY.match(key)
    if not m:
        return None
    coll, eid, fld = m.group(1), m.group(2), m.group(3)
    if coll == "openings":
        op = store.get("openings", eid)
        if op is None:
            return None
        f = geom.opening_frame(store, op)
        if f is not None:
            return ((f["a"][0] + f["b"][0]) / 2.0, (f["a"][1] + f["b"][1]) / 2.0)
        wall = store.get("walls", op.wall_id)
        if wall is not None and op.offset is not None:
            a, b = _safe_point(store, wall.start), _safe_point(store, wall.end)
            if a is not None and b is not None and geom.length(geom.sub(b, a)) >= geom.TOL:
                u = geom.unit(geom.sub(b, a))
                return geom.add(a, geom.mul(u, float(op.offset)))
        return _wall_mid(store, op.wall_id)
    if coll == "columns":
        col = store.get("columns", eid)
        if col is None:
            return None
        try:
            return store.column_center(col)
        except StoreError:
            return None
    if coll == "walls":
        return _wall_mid(store, eid)
    if coll == "stairs" and fld:
        st = store.get("stairs", eid)
        fm = _FLIGHT_FIELD.match(fld)
        if st is None or not fm or int(fm.group(1)) >= len(st.flights):
            return None
        return _safe_point(store, st.flights[int(fm.group(1))].origin)
    return None


# ── skill ────────────────────────────────────────────────────────────────────

class KiemTraXuatSkill(DraftSkill):
    code = "10"
    name = "Kiểm tra & xuất"
    reads = DATA_SECTIONS

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        scale = int(store.project.scale)
        k = float(scale)
        info = store.project
        bbox = content_bbox(plan, self.code)
        if bbox is None:
            result.skip("khung_ban_ve", "chưa có nội dung bản vẽ (các skill 01–09 chưa vẽ Op nào) — khung đặt quanh "
                                        "gốc toạ độ")
            bbox = (0.0, 0.0, 0.0, 0.0)
        pad = CONTENT_PAD_PAPER_MM * k
        padded = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)

        # dải tên bản vẽ dưới hình
        title = (info.drawing_title or "").strip()
        h_title = text_height("tieu_de", scale)
        h_scale = paper_to_model(SCALE_LABEL_PAPER_MM, scale)
        cx = (bbox[0] + bbox[2]) / 2.0
        y = padded[1] - TITLE_GAP_PAPER_MM * k
        title_y = None
        if title:
            title_y = y - h_title / 2.0
            y -= h_title + SCALE_GAP_PAPER_MM * k
        scale_y = y - h_scale / 2.0
        band_bottom = y - h_scale
        title_w = max(len(title) * CHAR_WIDTH_RATIO * h_title, len(f"TỶ LỆ 1:{scale}") * CHAR_WIDTH_RATIO * h_scale)
        block = (min(padded[0], cx - title_w / 2.0), band_bottom, max(padded[2], cx + title_w / 2.0), padded[3])

        sheet = (info.sheet or "").strip()
        placement = None
        if sheet not in SHEET_SIZES_MM:
            result.skip("khung_ban_ve", f"khổ giấy '{sheet}' chưa có trong layers.SHEET_SIZES_MM "
                                        f"({', '.join(SHEET_SIZES_MM)}) — chưa vẽ khung bản vẽ và khung tên")
            plan.meta.pop("sheet_frame", None)
            plan.meta.pop("sheet", None)
        else:
            paper = SHEET_SIZES_MM[sheet]
            placement = place_sheet(block, paper, scale)
            plan.meta["sheet_frame"] = [float(v) for v in placement["frame"]]
            plan.meta["sheet"] = {"size": sheet, "scale": scale, "paper_mm": [float(paper[0]), float(paper[1])]}
            bw, bh = (block[2] - block[0]) / k, (block[3] - block[1]) / k
            if placement["fits"]:
                where = "trên khung tên" if placement["region"] == "above" else "bên trái khung tên"
                result.notes.append(f"khổ {sheet} 1:{scale}: khung giấy {paper[0] * k:g} × {paper[1] * k:g} mm (model); "
                                    f"khối nội dung + tên bản vẽ {bw:.0f} × {bh:.0f} mm giấy đặt {where}")
            else:
                why = (f"nội dung vượt khổ {sheet} ở tỷ lệ 1:{scale} (khối nội dung + tên bản vẽ {bw:.0f} × {bh:.0f} "
                       f"mm giấy)")
                alt = [s for s in fitting_sheets(block, scale) if s != sheet]
                why += (f"; khổ vừa ở tỷ lệ này: {', '.join(alt)}" if alt
                        else "; không khổ nào trong SHEET_SIZES_MM vừa ở tỷ lệ này")
                result.notes.append(why)
                result.skip("khung_ban_ve", why)
            self._frame(plan, placement, k)
            self._title_block(store, plan, result, placement["title_block"], scale)

        # tên bản vẽ dưới hình
        if title:
            self.add(plan, "text", "khung_ten", "khung_ten/ten_ban_ve", insert=(cx, title_y), text=title,
                     height=h_title, rotation=0.0, align="MIDDLE_CENTER")
        else:
            result.notes.append("chưa có tên bản vẽ (project.drawing_title) — không ghi tên dưới hình")
        self.add(plan, "text", "khung_ten", "khung_ten/ty_le", insert=(cx, scale_y), text=f"TỶ LỆ 1:{scale}",
                 height=h_scale, rotation=0.0, align="MIDDLE_CENTER")

        self._markers(store, plan, result, bbox, placement["inner"] if placement else None, scale)

    # ── khung giấy, khung bản vẽ ─────────────────────────────────────────────

    def _frame(self, plan: DrawingPlan, placement: Dict[str, Any], k: float) -> None:
        for eid, box, lw in (("khung_ten/vien_giay", placement["frame"], LW_THIN),
                             ("khung_ten/khung_ve", placement["inner"], LW_BOLD)):
            x0, y0, x1, y1 = box
            self.add(plan, "pline", "khung_ten", eid, points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True,
                     lineweight=lw)

    # ── khung tên ────────────────────────────────────────────────────────────

    def _title_block(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult, tb: Box, scale: int) -> None:
        k = float(scale)
        x0, y0, x1, y1 = tb
        c1, c2, c3 = (x0 + c * k for c in TB_COLS)
        r = [y0 + v * k for v in TB_ROWS]          # r[0]=6, r[1]=12, r[2]=18, r[3]=24, r[4]=32
        # khung tên đặt sát góc dưới-phải khung bản vẽ: cạnh dưới và cạnh phải đã có trong khung bản vẽ, chỉ vẽ cạnh
        # trái và cạnh trên để không trùng nét
        self.add(plan, "pline", "khung_ten", "khung_ten/o/vien", points=[(x0, y0), (x0, y1), (x1, y1)],
                 closed=False, lineweight=LW_BOLD)
        grid = [((x0, r[4]), (x1, r[4])), ((x0, r[3]), (x1, r[3])), ((x0, r[2]), (x1, r[2])),
                ((x0, r[1]), (x1, r[1])), ((c2, r[0]), (x1, r[0])),
                ((c1, y0), (c1, y1)), ((c2, y0), (c2, r[3])), ((c3, y0), (c3, r[3]))]
        for i, (p1, p2) in enumerate(grid):
            self.add(plan, "line", "khung_ten", f"khung_ten/o/ke/{i}", p1=p1, p2=p2, lineweight=LW_GRID)

        info = store.project
        st = store.status()
        # (ô, nhãn, ô nhãn, ô giá trị, giá trị, cỡ chữ giấy)
        h_val = TEXT_PAPER_MM["khung_ten"]
        cells = [
            ("du_an", ["DỰ ÁN"], (x0, r[4], c1, y1), (c1, r[4], x1, y1), info.name, TB_EMPH_PAPER_MM),
            ("ban_ve", ["BẢN VẼ"], (x0, r[3], c1, r[4]), (c1, r[3], x1, r[4]), info.drawing_title, TB_EMPH_PAPER_MM),
            ("thiet_ke", ["THIẾT KẾ"], (x0, r[2], c1, r[3]), (c1, r[2], c2, r[3]), info.designer, h_val),
            ("so_hieu", ["SỐ HIỆU"], (c2, r[2], c3, r[3]), (c3, r[2], x1, r[3]), info.drawing_no, h_val),
            ("kiem_tra", ["KIỂM TRA"], (x0, r[1], c1, r[2]), (c1, r[1], c2, r[2]), info.checker, h_val),
            ("ty_le", ["TỶ LỆ"], (c2, r[1], c3, r[2]), (c3, r[1], x1, r[2]), f"1:{scale}", h_val),
            ("trang_thai", ["TRẠNG THÁI", "SỐ LIỆU"], (x0, y0, c1, r[1]), (c1, y0, c2, r[1]), status_text(st), h_val),
            ("lan_sua", ["LẦN SỬA"], (c2, r[0], c3, r[1]), (c3, r[0], x1, r[1]), info.revision, h_val),
            ("ngay", ["NGÀY"], (c2, y0, c3, r[0]), (c3, y0, x1, r[0]), info.date, h_val),
        ]
        pad = TB_PAD_PAPER_MM * k
        h_label = TB_LABEL_PAPER_MM * k
        empty: List[str] = []
        overflow: List[str] = []
        for cell, labels, lbox, vbox, value, h_paper in cells:
            n = len(labels)
            for i, lab in enumerate(labels):
                ly = lbox[3] - (lbox[3] - lbox[1]) * (i + 1) / (n + 1)
                eid = f"khung_ten/nhan/{cell}" + (f"/{i}" if n > 1 else "")
                h, ok = fit_text_height(lab, h_label, (lbox[2] - lbox[0]) - 2 * pad, MIN_TEXT_PAPER_MM * k)
                self.add(plan, "text", "khung_ten", eid, insert=(lbox[0] + pad, ly), text=lab, height=h,
                         rotation=0.0, align="MIDDLE_LEFT")
                if not ok:
                    overflow.append(lab)
            text = str(value or "").strip()
            if not text:
                empty.append(labels[0] if n == 1 else " ".join(labels))
                continue
            h, ok = fit_text_height(text, h_paper * k, (vbox[2] - vbox[0]) - 2 * pad, MIN_TEXT_PAPER_MM * k)
            self.add(plan, "text", "khung_ten", f"khung_ten/gia_tri/{cell}",
                     insert=(vbox[0] + pad, (vbox[1] + vbox[3]) / 2.0), text=text, height=h, rotation=0.0,
                     align="MIDDLE_LEFT")
            if not ok:
                overflow.append(text)
        result.notes.append(f"khung tên: trạng thái số liệu TÍNH từ store.status() = {st['trang_thai']} → "
                            f"\"{status_text(st)}\"")
        if empty:
            result.notes.append("khung tên: để trống ô " + ", ".join(empty)
                                + " vì ProjectInfo chưa có số liệu (không tự điền)")
        for text in overflow:
            result.notes.append(f"CẢNH BÁO chữ \"{text}\" có thể tràn ô khung tên (đã hạ tới cỡ tối thiểu "
                                f"{MIN_TEXT_PAPER_MM:g} mm giấy)")

    # ── đánh dấu kiểm tra ────────────────────────────────────────────────────

    def _markers(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult, bbox: Box,
                 inner: Optional[Box], scale: int) -> None:
        k = float(scale)
        r = MARKER_R_PAPER_MM * k
        h = text_height("ghi_chu", scale)
        frames = axis_frames(store)
        placed: List[Point] = []

        def mark(eid_base: str, p: Point, text: str) -> None:
            near = sum(1 for q in placed if math.hypot(p[0] - q[0], p[1] - q[1]) < 2.0 * r)
            placed.append(p)
            self.add(plan, "circle", "kiem_tra", f"{eid_base}/vong", center=p, r=r)
            self.add(plan, "text", "kiem_tra", f"{eid_base}/chu",
                     insert=(p[0] + r + MARKER_TEXT_GAP_PAPER_MM * k, p[1] - near * 1.6 * h), text=text, height=h,
                     rotation=0.0, align="MIDDLE_LEFT")

        missing = store.missing()
        missing_keys = {m.key for m in missing}
        unplaced: List[str] = []
        n_missing_marked = 0
        for item in missing:
            p = marker_position(store, item.key, frames)
            if p is None:
                unplaced.append(f"THIẾU: {item.key} ({item.description})")
                continue
            mark(f"kiem_tra/{item.key}", p, f"THIẾU: {item.key}")
            n_missing_marked += 1
        if unplaced:
            if inner is not None:
                at = (inner[0] + 3.0 * k, inner[3] - 3.0 * k)
            else:
                at = (bbox[0], bbox[3] + CONTENT_PAD_PAPER_MM * k)
            self.add(plan, "mtext", "kiem_tra", "kiem_tra/thieu_chua_dinh_vi", insert=at,
                     text="\\P".join(["THIẾU — chưa định vị được trên hình:"] + unplaced), height=h,
                     width=MISSING_LIST_WIDTH_PAPER_MM * k, attach="TOP_LEFT")

        fallback = 0
        n_unconf = 0
        unconf_corner: List[str] = []
        for key, _prov in store.unconfirmed():
            if key in missing_keys:
                continue
            p = marker_position(store, key, frames)
            if p is None:
                p = (bbox[0], bbox[1] + fallback * 2.5 * r)
                fallback += 1
                unconf_corner.append(key)
            mark(f"kiem_tra/{key}", p, f"NỘI SUY – CHƯA XÁC NHẬN: {key}")
            n_unconf += 1

        seen = set()
        n_val = 0
        for i, it in enumerate(plan.meta.get("validator_issues") or []):
            where = it.get("where") if isinstance(it, dict) else None
            try:
                p = (float(where[0]), float(where[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if not (math.isfinite(p[0]) and math.isfinite(p[1])):
                continue
            sig = (it.get("code"), round(p[0], 3), round(p[1], 3))
            if sig in seen:
                continue
            seen.add(sig)
            sev = str(it.get("severity", ""))
            mark(f"kiem_tra/val/{i}", p, f"{SEV_LABEL.get(sev, sev)}: {it.get('code', '')}")
            n_val += 1

        result.notes.append(f"đánh dấu kiểm tra (layer không in): {n_missing_marked} số liệu thiếu định vị được, "
                            f"{len(unplaced)} thiếu chưa định vị (liệt kê ở góc khung), {n_unconf} số liệu nội suy "
                            f"chưa xác nhận, {n_val} phát hiện của Validator")
        if unconf_corner:
            result.notes.append("số liệu nội suy chưa định vị được trên hình, đánh dấu ở góc dưới-trái bao nội dung: "
                                + ", ".join(unconf_corner))
