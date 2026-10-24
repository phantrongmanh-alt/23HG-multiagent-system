# -*- coding: utf-8 -*-
"""
CAD VALIDATOR — kiểm tra dữ liệu và danh sách lệnh vẽ của agent dựng CAD mặt bằng (tất định, không LLM).

Ba thời điểm kiểm tra (Master gọi) và một hàm tổng hợp:
  precheck(store)                              trước khi vẽ: trục, tham chiếu điểm, tường, ô cửa, phòng, kích thước
                                               nguồn (MeasuredDim), thiếu kích thước, nội suy chưa xác nhận
  check_step(store, plan, code, before_fp)     sau MỖI skill: lấn layer, sửa phần skill khác (so dấu vân tay), trùng
                                               nét trong vai trò của skill vừa chạy, rồi kiểm tra riêng của skill đó
  check_final(store, plan, results)            cuối: đối tượng skill bỏ qua chưa vẽ; còn thiếu / còn nội suy chưa xác nhận
  summarize(issues)                            đếm theo mức độ và theo mã; "dat" TÍNH = không LOI và không NGHI_VAN

Mọi phát hiện là store.Issue: severity LOI | CANH_BAO | NGHI_VAN, code (bảng dưới), message tiếng Việt nêu mã đối
tượng / toạ độ, skill = "VAL" (kiểm tra dữ liệu, kiểm tra cuối) hoặc mã bước ("01".."10"), eids (mã đối tượng trong
store, khoá số liệu hoặc eid lệnh vẽ), where = [x, y] (tâm vùng giao / vị trí đối tượng) khi xác định được.

Bảng mã:
  precheck      LOI  NHIP_TRUC_KHONG_DUONG, TONG_NHIP_LECH, THAM_CHIEU_SAI, TUONG_DAI_0, KICH_THUOC_KHONG_DUONG,
                     SO_LIEU_KHONG_PHAI_SO, CUA_KHONG_CO_TUONG, CUA_VUOT_TUONG, CUA_CHONG_NHAU, PHONG_BIEN_HONG,
                     PHONG_CHONG_NHAU, THIEU_KICH_THUOC
                NGHI_VAN DIM_GHI_DE, DIM_LECH_TRUC, NOI_SUY_CHUA_XAC_NHAN
  chung mỗi bước LOI SKILL_LAN_PHAN (Op của skill vừa chạy, và Op mang mã skill lạ ngoài 01–10),
                 SKILL_SUA_PHAN_KHAC; CANH_BAO TRUNG_NET, CHUA_CO_DAU_VAN_TAY,
                 CHUA_KIEM_TRA_HINH_HOC (geom.* ném lỗi vì dữ liệu sai kiểu)
  01  LOI TRUC_TRUNG_VI_TRI
  02  LOI COT_CHONG_NHAU; CANH_BAO COT_LECH_TRUC (thông tin)
  03  LOI TUONG_TRUNG; CANH_BAO TUONG_LECH_TRUC, TUONG_CAT_NHAU
  04  LOI CUA_DAM_COT; CANH_BAO CANH_CUA_VUONG, CANH_CUA_CHONG
  05  LOI THANG_DAM_TUONG; CANH_BAO THANG_NGOAI_PHONG, THANG_CHUA_KIEM_TRA, CUA_VUONG_THANG
  06  LOI NOI_THAT_XUNG_DOT; CANH_BAO NOI_THAT_CHAN_CUA, NOI_THAT_NGOAI_PHONG, NOI_THAT_CHONG_NHAU, NOI_THAT_CHUA_KIEM_TRA
  07  LOI HATCH_BIEN_HONG
  08  LOI DIM_BANG_0; NGHI_VAN DIM_GHI_DE
  09  CANH_BAO NHAN_NGOAI_PHONG
  10  LOI NOI_DUNG_NGOAI_KHUNG; CANH_BAO CHU_DE_CHU, KHUNG_CHUA_CO, KHUNG_KHONG_DOC_DUOC
  cuối CANH_BAO DOI_TUONG_CHUA_VE (+ lặp lại THIEU_KICH_THUOC / NOI_SUY_CHUA_XAC_NHAN nếu còn, cùng nguyên văn
       với precheck để Master gộp trùng)

Dung sai và ngưỡng: geom.TOL (1 mm) cho điểm trùng, điểm nằm trên đường, đoạn chồng, lệch tổng nhịp, lệch kích thước
theo trục; 1 mm² cho cột chồng / cửa đè cột; 100 mm² cho va chạm cánh cửa, thang, nội thất; 0,01 m² cho phòng chồng;
chữ: hộp ước lượng cao = chiều cao chữ, rộng = 0,75 × chiều cao × số ký tự, giao > 25 % hộp nhỏ hơn.

Nguyên tắc:
  - Không đoán: kiểm tra cần toạ độ mà đối tượng còn thiếu số liệu (nhịp trục thiếu, bề rộng cửa thiếu...) thì kiểm tra
    đó không chạy cho đối tượng ấy — nguyên nhân đã được báo bằng THIEU_KICH_THUOC; tham chiếu sai đã báo THAM_CHIEU_SAI.
    Riêng nội thất không kiểm tra được (thiếu block / size / điểm chèn, phòng chưa dựng được) → CANH_BAO
    NOI_THAT_CHUA_KIEM_TRA; vế thang chưa đối chiếu được với phòng chưa dựng được → CANH_BAO THANG_CHUA_KIEM_TRA.
  - Hình học dùng chung geom.* (shapely), gọi qua _CachedStore (nhớ kết quả giải điểm trong một lần kiểm tra);
    không sửa store, không sửa plan.
  - Cặp đôi O(n²) có lọc bao hình (quét theo xmin). Đo trên lưới trục giả lập (cả 10 bước check_step): 220 tường /
    121 cột / 110 cửa / 100 phòng / 100 nội thất ≈ 1,2 s; 480 tường ≈ 4,7 s — phần lớn nằm trong geom.wall_polygon
    (dò mọi tường cho mỗi đầu tường).
"""

from __future__ import annotations

import math
import re
from functools import cached_property
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from shapely import affinity
from shapely.errors import GEOSException
from shapely.geometry import Point as ShPoint, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import explain_validity

from tools.cad_drafting import geom
from tools.cad_drafting.layers import ROLE_OWNER
from tools.cad_drafting.plan import DrawingPlan, Op, dim_measurement, iter_points
from tools.cad_drafting.store import (COLLECTIONS, SEV_DOUBT, SEV_ERROR, SEV_WARN, SEVERITIES, Issue, ProjectStore,
                                      StoreError)

Point = Tuple[float, float]
Bounds = Tuple[float, float, float, float]

VAL = "VAL"
TOL = geom.TOL
AREA_COLUMN_MM2 = 1.0            # cột chồng cột, ô cửa đè cột
AREA_CLASH_MM2 = 100.0           # cánh cửa / thang / nội thất va chạm
AREA_ROOM_MM2 = 10_000.0         # 0,01 m² — hai phòng chồng nhau
AREA_ZERO_MM2 = 1e-6             # diện tích coi như bằng 0 (nhiễu số học)
ROOM_ZERO_MM2 = 1.0              # phòng có diện tích < 1 mm² coi như diện tích 0
OVERRIDE_TOL = 0.5               # chữ ghi đè so với số đo (số đo hiển thị làm tròn tới mm)
AXIS_DIM_ANGLE_TOL_DEG = 0.5     # kích thước nguồn được coi là đo vuông góc với nhóm trục
TEXT_CHAR_WIDTH = 0.75           # bề rộng một ký tự ≈ 0,75 × chiều cao chữ
TEXT_OVERLAP_RATIO = 0.25        # hai hộp chữ giao > 25 % hộp nhỏ hơn → chữ đè chữ
MTEXT_LINE_SPACING = 1.667       # bước dòng MTEXT mặc định của AutoCAD (× chiều cao chữ)
FRAME_FREE_ROLES = ("kiem_tra", "anh_nen")   # vai trò không in — không bắt nằm trong khung, không xét chữ đè
MAX_LISTED = 10                  # số mã liệt kê trong message trước khi ghi "và N mục khác"

_EMPTY_FP = DrawingPlan().fingerprint("")    # dấu vân tay của một skill không có lệnh vẽ nào

# vị trí điểm chèn trong hộp chữ: (phần bề rộng nằm bên trái điểm chèn, phần chiều cao nằm dưới điểm chèn)
_ALIGN_FRAC: Dict[str, Tuple[float, float]] = {
    "LEFT": (0.0, 0.0), "CENTER": (0.5, 0.0), "RIGHT": (1.0, 0.0),
    "MIDDLE_LEFT": (0.0, 0.5), "MIDDLE_CENTER": (0.5, 0.5), "MIDDLE_RIGHT": (1.0, 0.5),
    "TOP_CENTER": (0.5, 1.0), "BOTTOM_CENTER": (0.5, 0.0),
}
_ATTACH_FRAC: Dict[str, Tuple[float, float]] = {
    "TOP_LEFT": (0.0, 1.0), "TOP_CENTER": (0.5, 1.0), "TOP_RIGHT": (1.0, 1.0),
    "MIDDLE_LEFT": (0.0, 0.5), "MIDDLE_CENTER": (0.5, 0.5), "MIDDLE_RIGHT": (1.0, 0.5),
    "BOTTOM_LEFT": (0.0, 0.0), "BOTTOM_CENTER": (0.5, 0.0), "BOTTOM_RIGHT": (1.0, 0.0),
}
_MTEXT_CODE = re.compile(r"\\[ACcFfHhQqTtWw][^;\\{}]*;|\\[LlOoKkNn]|[{}]")


# ─────────────────────────────────────────────────────────────────────────────
# TIỆN ÍCH CHUNG
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(v: Any) -> str:
    """Số mm: số nguyên khi gần nguyên, ngược lại 1 chữ số thập phân với dấu phẩy kiểu Việt Nam."""
    v = float(v)
    r = round(v)
    if abs(v - r) < 0.05:
        return str(int(r))
    return f"{v:.1f}".replace(".", ",")


def _fmt_pt(p: Sequence[float]) -> str:
    return f"({_fmt(p[0])}; {_fmt(p[1])})"


def _fmt_m2(area_mm2: float) -> str:
    return f"{area_mm2 / 1e6:.2f}".replace(".", ",") + " m²"


def _cap(s: str) -> str:
    """Viết hoa chữ cái đầu, giữ nguyên phần còn lại (str.capitalize làm hỏng mã như "C-1A")."""
    return s[:1].upper() + s[1:]


def _listed(items: Sequence[str]) -> str:
    items = list(items)
    s = ", ".join(items[:MAX_LISTED])
    if len(items) > MAX_LISTED:
        s += f" và {len(items) - MAX_LISTED} mục khác"
    return s


def _where_of(obj: Any) -> Optional[List[float]]:
    """[x, y] làm tròn 0,1 mm: tâm hình shapely, hoặc điểm (x, y). None nếu không xác định."""
    if obj is None:
        return None
    if isinstance(obj, BaseGeometry):
        if obj.is_empty:
            return None
        c = obj.centroid
        if c.is_empty:
            c = obj.representative_point()
        return [round(float(c.x), 1), round(float(c.y), 1)]
    try:
        x, y = float(obj[0]), float(obj[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return [round(x, 1), round(y, 1)]


def _issue(severity: str, code: str, message: str, skill: str, eids: Iterable[Any] = (),
           where: Any = None) -> Issue:
    return Issue(severity=severity, code=code, message=message, skill=skill,
                 eids=[str(e) for e in eids], where=_where_of(where))


def _num(v: Any) -> Optional[float]:
    """Số hữu hạn hoặc None (None / không phải số — chữ không phải số được precheck báo riêng)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _try_point(store: ProjectStore, ref: Any) -> Optional[Point]:
    """Toạ độ điểm hoặc None (thiếu số liệu hoặc tham chiếu sai — precheck đã báo nguyên nhân)."""
    try:
        return store.point(ref)
    except (StoreError, TypeError, ValueError):
        return None


def _wall_axis(store: ProjectStore, wall) -> Optional[Tuple[Point, Point]]:
    a, b = _try_point(store, wall.start), _try_point(store, wall.end)
    if a is None or b is None or geom.length(geom.sub(b, a)) < TOL:
        return None
    return a, b


def _seg_bounds(a: Point, b: Point) -> Bounds:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _bbox_hit(p: Bounds, q: Bounds, tol: float = 0.0) -> bool:
    return p[0] <= q[2] + tol and q[0] <= p[2] + tol and p[1] <= q[3] + tol and q[1] <= p[3] + tol


def _bbox_pairs(bounds: Sequence[Bounds], tol: float = 0.0) -> List[Tuple[int, int]]:
    """Mọi cặp (i, j), i < j, có bao hình (nới tol) giao nhau — quét theo xmin. Kết quả đã sắp xếp (tất định)."""
    order = sorted(range(len(bounds)), key=lambda k: (bounds[k][0], k))
    out = []
    for pos, i in enumerate(order):
        bi = bounds[i]
        for j in order[pos + 1:]:
            bj = bounds[j]
            if bj[0] > bi[2] + tol:
                break
            if bj[1] <= bi[3] + tol and bi[1] <= bj[3] + tol:
                out.append((i, j) if i < j else (j, i))
    return sorted(out)


def _intersection(a: BaseGeometry, b: BaseGeometry) -> BaseGeometry:
    try:
        return a.intersection(b)
    except GEOSException:
        return a.buffer(0).intersection(b.buffer(0))


def _clashes(subject: BaseGeometry, obstacles: Sequence[Tuple[str, str, BaseGeometry]],
             min_area: float) -> List[Tuple[str, str, BaseGeometry, float]]:
    """Các vật cản giao `subject` diện tích > min_area: [(nhãn, mã, vùng giao, diện tích)]."""
    out = []
    sb = subject.bounds
    for label, oid, g in obstacles:
        if g.is_empty or not _bbox_hit(sb, g.bounds):
            continue
        inter = _intersection(subject, g)
        if inter.area > min_area:
            out.append((label, oid, inter, inter.area))
    return out


def _covers(container: BaseGeometry, g: BaseGeometry) -> bool:
    """container (nới TOL, giữ góc vuông) chứa trọn g."""
    try:
        return container.buffer(TOL, join_style=2).covers(g)
    except GEOSException:
        return False


def _collinear_overlap(a: Point, b: Point, c: Point, d: Point, tol: float = TOL) -> Optional[Tuple[float, Point]]:
    """Hai đoạn thẳng gần thẳng hàng (hai đầu đoạn ngắn hơn cách đường chứa đoạn dài hơn ≤ tol): (chiều dài phần
    chồng, trung điểm phần chồng). None nếu không thẳng hàng hoặc không chồng."""
    la, lc = geom.length(geom.sub(b, a)), geom.length(geom.sub(d, c))
    if la < 1e-9 or lc < 1e-9:
        return None
    if lc > la:
        a, b, c, d, la, lc = c, d, a, b, lc, la
    ux, uy = (b[0] - a[0]) / la, (b[1] - a[1]) / la
    for p in (c, d):
        if abs((p[0] - a[0]) * uy - (p[1] - a[1]) * ux) > tol:
            return None
    tc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
    td = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
    lo, hi = max(0.0, min(tc, td)), min(la, max(tc, td))
    if hi <= lo:
        return None
    m = (lo + hi) / 2.0
    return hi - lo, (a[0] + ux * m, a[1] + uy * m)


def _proper_crossing(a: Point, b: Point, c: Point, d: Point) -> Optional[Point]:
    """Giao điểm của hai đoạn cắt nhau ở GIỮA cả hai (cách mọi đầu mút > TOL). None nếu song song / không cắt /
    gặp nhau ở đầu đoạn (góc, chữ T)."""
    r = geom.sub(b, a)
    s = geom.sub(d, c)
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    ca = geom.sub(c, a)
    t = (ca[0] * s[1] - ca[1] * s[0]) / den
    u = (ca[0] * r[1] - ca[1] * r[0]) / den
    if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
        return None
    p = (a[0] + t * r[0], a[1] + t * r[1])
    if min(geom.length(geom.sub(p, q)) for q in (a, b, c, d)) <= TOL:
        return None
    return p


def _plain_text(text: Any) -> str:
    """Bỏ mã định dạng MTEXT (\\P, \\A1;, {\\f...;}) và mã %%c/%%d/%%p để đếm ký tự / đọc số."""
    s = str(text).replace("\\P", " ").replace("\\~", " ")
    s = _MTEXT_CODE.sub("", s)
    for code, ch in (("%%c", "Ø"), ("%%C", "Ø"), ("%%d", "°"), ("%%D", "°"), ("%%p", "±"), ("%%P", "±")):
        s = s.replace(code, ch)
    return s.strip()


def _override_differs(text: str, value: Optional[float]) -> Tuple[bool, str]:
    """(chữ ghi đè khác số đo?, chữ đã bỏ mã định dạng). Chữ chứa "<>" vẫn hiện số đo → không khác. Mỗi số trong chữ
    được hiểu theo cả dấu thập phân "," / "." và dấu phân nhóm nghìn ("3.600" = 3600). Không số nào khớp số đo
    (± OVERRIDE_TOL) → khác (kể cả chữ không có số: số đo bị che)."""
    shown = _plain_text(text)
    if "<>" in str(text):
        return False, shown
    if value is None:
        return True, shown
    for tok in re.findall(r"\d[\d.,]*", shown):
        tok = tok.rstrip(".,")
        cands = []
        if tok.count(",") + tok.count(".") <= 1:
            cands.append(float(tok.replace(",", ".")))
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
            cands.append(float(re.sub(r"[.,]", "", tok)))
        if any(abs(c - value) <= OVERRIDE_TOL for c in cands):
            return False, shown
    return True, shown


def _other_axis_coord(store: ProjectStore, orientation: str) -> float:
    """Toạ độ trục đầu tiên đã biết của nhóm trục kia (để đặt điểm đánh dấu cho một nhịp trục); 0 nếu không có."""
    g = store.axes.get("H" if orientation == "V" else "V")
    if g is not None:
        for off in g.offsets():
            if off is not None:
                return float(off)
    return 0.0


def _span_point(store: ProjectStore, orientation: str, i: int) -> Optional[Point]:
    g = store.axes.get(orientation)
    if g is None or i >= len(g.spans):
        return None
    offs = g.offsets()
    a, b = offs[i], offs[i + 1]
    if a is None:
        return None
    mid = a if b is None else (a + b) / 2.0
    c = _other_axis_coord(store, orientation)
    return (mid, c) if orientation == "V" else (c, mid)


def _entity_point(store: ProjectStore, coll: str, ent: Any, fld: Optional[str] = None) -> Optional[Point]:
    """Vị trí đại diện của một đối tượng store (để đặt where); None nếu chưa xác định được."""
    if ent is None:
        return None
    if coll == "columns":
        p = _try_point(store, f"{ent.axis_v}/{ent.axis_h}")
        if p is None:
            return None
        return (p[0] + (_num(ent.dx) or 0.0), p[1] + (_num(ent.dy) or 0.0))
    if coll == "walls":
        ab = _wall_axis(store, ent)
        return None if ab is None else ((ab[0][0] + ab[1][0]) / 2.0, (ab[0][1] + ab[1][1]) / 2.0)
    if coll == "openings":
        wall = store.get("walls", ent.wall_id)
        ab = None if wall is None else _wall_axis(store, wall)
        if ab is None:
            return None
        a, b = ab
        u = geom.unit(geom.sub(b, a))
        off, width = _num(ent.offset), _num(ent.width)
        if off is None:
            return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        t = off + (width / 2.0 if width is not None else 0.0)
        return geom.add(a, geom.mul(u, t))
    if coll == "stairs":
        i = 0
        m = re.match(r"flights\[(\d+)\]", fld or "")
        if m:
            i = int(m.group(1))
        if i < len(ent.flights):
            return _try_point(store, ent.flights[i].origin)
        return None
    if coll == "furniture":
        return _try_point(store, ent.insert)
    if coll == "rooms":
        poly = geom.room_polygon(store, ent)
        if poly is not None:
            c = poly.centroid
            return (c.x, c.y)
        for ref in ent.boundary:
            p = _try_point(store, ref)
            if p is not None:
                return p
        return None
    if coll == "measured_dims":
        try:
            return ((float(ent.p1[0]) + float(ent.p2[0])) / 2.0, (float(ent.p1[1]) + float(ent.p2[1])) / 2.0)
        except (TypeError, ValueError, IndexError):
            return None
    return None


def _key_where(store: ProjectStore, key: str) -> Optional[Point]:
    """Vị trí đại diện cho một khoá số liệu ("axes:V.spans[1]", "openings:CD4.width"...)."""
    try:
        m = re.match(r"^axes:([VH])\.spans\[(\d+)\]$", key)
        if m:
            return _span_point(store, m.group(1), int(m.group(2)))
        m = re.match(r"^(\w+):([^.]+)(?:\.(.+))?$", key)
        if not m or m.group(1) not in COLLECTIONS:
            return None
        coll, eid, fld = m.groups()
        return _entity_point(store, coll, store.get(coll, eid), fld)
    except (StoreError, ValueError, TypeError, IndexError, AttributeError, ZeroDivisionError):
        return None


def _locate_id(store: ProjectStore, item_id: str) -> Optional[Point]:
    """Vị trí của một mã bỏ qua kiểu "noi_that:F1", "hoan_thien:P1/ten", "W3" — dò từng phần trong các bộ đối tượng."""
    for token in re.split(r"[:/]", str(item_id)):
        if not token:
            continue
        for coll in COLLECTIONS:
            ent = store.get(coll, token)
            if ent is not None:
                try:
                    return _entity_point(store, coll, ent)
                except (StoreError, ValueError, TypeError, IndexError, AttributeError, ZeroDivisionError):
                    return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# KIỂM TRA DỮ LIỆU TRƯỚC KHI VẼ
# ─────────────────────────────────────────────────────────────────────────────

def precheck(store: ProjectStore) -> List[Issue]:
    """Kiểm tra dữ liệu dự án trước khi vẽ. Không sửa store."""
    out: List[Issue] = []
    out += _check_axes(store)
    out += _check_refs(store)
    out += _check_numbers(store)
    out += _check_walls(store)
    out += _check_openings(store)
    out += _check_rooms(store)
    out += _check_measured_dims(store)
    out += _missing_issues(store)
    out += _unconfirmed_issues(store)
    return out


def _check_axes(store: ProjectStore) -> List[Issue]:
    out = []
    for o, g in sorted(store.axes.items()):
        for i, s in enumerate(g.spans):
            v = _num(s)
            if v is not None and v <= 0:
                key = f"axes:{o}.spans[{i}]"
                out.append(_issue(SEV_ERROR, "NHIP_TRUC_KHONG_DUONG",
                                  f"Nhịp trục {g.names[i]}–{g.names[i + 1]} (khoá {key}) = {_fmt(v)} mm ≤ 0 — "
                                  f"nhịp trục phải dương.", VAL, [key], _span_point(store, o, i)))
        overall = _num(g.overall)
        if overall is not None and overall <= 0:
            out.append(_issue(SEV_ERROR, "KICH_THUOC_KHONG_DUONG",
                              f"Kích thước tổng nhóm trục {o} (khoá axes:{o}.overall) = {_fmt(overall)} mm ≤ 0.",
                              VAL, [f"axes:{o}.overall"]))
        spans = [_num(s) for s in g.spans]
        if overall is not None and spans and all(s is not None for s in spans):
            total = sum(spans)
            if abs(total - overall) > TOL:
                out.append(_issue(SEV_ERROR, "TONG_NHIP_LECH",
                                  f"Nhóm trục {o} ({g.names[0]}–{g.names[-1]}): tổng nhịp "
                                  f"{' + '.join(_fmt(s) for s in spans)} = {_fmt(total)} mm khác kích thước tổng "
                                  f"{_fmt(overall)} mm (khoá axes:{o}.overall), lệch {_fmt(total - overall)} mm "
                                  f"> {_fmt(TOL)} mm.", VAL, [f"axes:{o}.overall"]))
    return out


def _ref_items(store: ProjectStore):
    """(nhãn đối tượng, mã, trường, tham chiếu điểm) cho mọi điểm cần giải từ trục."""
    for c in store.columns:
        yield "cột", c.id, "axis_v/axis_h", f"{c.axis_v}/{c.axis_h}"
    for w in store.walls:
        yield "tường", w.id, "start", w.start
        yield "tường", w.id, "end", w.end
    for r in store.rooms:
        for i, ref in enumerate(r.boundary):
            yield "phòng", r.id, f"boundary[{i}]", ref
    for st in store.stairs:
        for i, fl in enumerate(st.flights):
            yield "thang", st.id, f"flights[{i}].origin", fl.origin
        for j, loop in enumerate(st.landings):
            for k, ref in enumerate(loop):
                yield "thang", st.id, f"landings[{j}][{k}]", ref
    for f in store.furniture:
        yield "nội thất", f.id, "insert", f.insert


def _check_refs(store: ProjectStore) -> List[Issue]:
    out = []
    for label, eid, fld, ref in _ref_items(store):
        try:
            store.point_or_reason(ref)
        except (StoreError, TypeError, ValueError) as e:
            out.append(_issue(SEV_ERROR, "THAM_CHIEU_SAI",
                              f"Tham chiếu điểm sai ở {label} {eid} ({fld} = {ref!r}): {e}.", VAL, [eid]))
    return out


def _check_numbers(store: ProjectStore) -> List[Issue]:
    """Kích thước ≤ 0 hoặc không phải số (cột, tường, ô cửa, vế thang). Giá trị None là thiếu — báo ở THIEU_KICH_THUOC."""
    items: List[Tuple[str, str, Any, bool, Optional[Point]]] = []   # (khoá, mô tả, giá trị, phải dương, where)
    for c in store.columns:
        for f_ in ("b", "h"):
            items.append((f"columns:{c.id}.{f_}", f"cạnh {f_} của cột {c.id}", getattr(c, f_), True,
                          _entity_point(store, "columns", c)))
        for f_ in ("dx", "dy"):
            items.append((f"columns:{c.id}.{f_}", f"độ lệch {f_} của cột {c.id}", getattr(c, f_), False, None))
    for w in store.walls:
        items.append((f"walls:{w.id}.thickness", f"chiều dày tường {w.id}", w.thickness, True,
                      _entity_point(store, "walls", w)))
    for op in store.openings:
        items.append((f"openings:{op.id}.width", f"bề rộng cửa {op.id}", op.width, True,
                      _entity_point(store, "openings", op)))
        items.append((f"openings:{op.id}.offset", f"vị trí cửa {op.id}", op.offset, False, None))
    for st in store.stairs:
        for i, fl in enumerate(st.flights):
            where = _try_point(store, fl.origin)
            for f_ in ("width", "going"):
                items.append((f"stairs:{st.id}.flights[{i}].{f_}", f"{f_} của vế {i + 1} thang {st.id}",
                              getattr(fl, f_), True, where))
            items.append((f"stairs:{st.id}.flights[{i}].angle", f"góc vế {i + 1} thang {st.id}", fl.angle, False,
                          where))
    out = []
    for key, desc, val, positive, where in items:
        if val is None:
            continue
        v = _num(val)
        if v is None:
            out.append(_issue(SEV_ERROR, "SO_LIEU_KHONG_PHAI_SO",
                              f"{_cap(desc)} (khoá {key}) = {val!r} không phải số hữu hạn.", VAL, [key], where))
        elif positive and v <= 0:
            out.append(_issue(SEV_ERROR, "KICH_THUOC_KHONG_DUONG",
                              f"{_cap(desc)} (khoá {key}) = {_fmt(v)} mm ≤ 0.", VAL, [key], where))
    for st in store.stairs:
        for i, fl in enumerate(st.flights):
            if fl.n_treads is None:
                continue
            key = f"stairs:{st.id}.flights[{i}].n_treads"
            v = _num(fl.n_treads)
            if v is None or v != int(v) or v < 1:
                out.append(_issue(SEV_ERROR, "KICH_THUOC_KHONG_DUONG",
                                  f"Số bậc vế {i + 1} thang {st.id} (khoá {key}) = {fl.n_treads!r} — phải là số "
                                  f"nguyên ≥ 1.", VAL, [key], _try_point(store, fl.origin)))
    return out


def _check_walls(store: ProjectStore) -> List[Issue]:
    out = []
    for w in store.walls:
        a, b = _try_point(store, w.start), _try_point(store, w.end)
        if a is None or b is None:
            continue
        if geom.length(geom.sub(b, a)) < TOL:
            out.append(_issue(SEV_ERROR, "TUONG_DAI_0",
                              f"Tường {w.id} dài 0: điểm đầu {w.start!r} và điểm cuối {w.end!r} cùng ở {_fmt_pt(a)}.",
                              VAL, [w.id], a))
    return out


def _check_openings(store: ProjectStore) -> List[Issue]:
    out = []
    by_wall: Dict[str, List[Tuple[Any, float, float]]] = {}
    for op in store.openings:
        wall = store.get("walls", op.wall_id)
        if wall is None:
            out.append(_issue(SEV_ERROR, "CUA_KHONG_CO_TUONG",
                              f"Ô cửa {op.id} ({op.mark or op.kind}) gắn vào tường '{op.wall_id}' không có trong dữ liệu.",
                              VAL, [op.id]))
            continue
        off, width = _num(op.offset), _num(op.width)
        ab = _wall_axis(store, wall)
        reasons = []
        if off is not None and off < -TOL:
            reasons.append(f"offset = {_fmt(off)} mm < 0")
        if ab is not None and off is not None and width is not None:
            wall_len = geom.length(geom.sub(ab[1], ab[0]))
            if off + width > wall_len + TOL:
                reasons.append(f"offset + bề rộng = {_fmt(off)} + {_fmt(width)} = {_fmt(off + width)} mm > chiều dài "
                               f"tim tường {_fmt(wall_len)} mm")
        if reasons:
            out.append(_issue(SEV_ERROR, "CUA_VUOT_TUONG",
                              f"Ô cửa {op.id} vượt ra ngoài tường {wall.id}: {'; '.join(reasons)}.",
                              VAL, [op.id, wall.id], _entity_point(store, "openings", op)))
        if off is not None and width is not None and width > 0:
            by_wall.setdefault(wall.id, []).append((op, off, off + width))
    for wall_id, items in by_wall.items():
        wall = store.get("walls", wall_id)
        ab = _wall_axis(store, wall)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (o1, s1, e1), (o2, s2, e2) = items[i], items[j]
                lo, hi = max(s1, s2), min(e1, e2)
                if hi - lo > TOL:
                    where = None
                    if ab is not None:
                        where = geom.add(ab[0], geom.mul(geom.unit(geom.sub(ab[1], ab[0])), (lo + hi) / 2.0))
                    out.append(_issue(SEV_ERROR, "CUA_CHONG_NHAU",
                                      f"Hai ô cửa {o1.id} [{_fmt(s1)}–{_fmt(e1)}] và {o2.id} [{_fmt(s2)}–{_fmt(e2)}] "
                                      f"trên tường {wall_id} chồng nhau {_fmt(hi - lo)} mm (đo dọc tim tường từ điểm "
                                      f"đầu).", VAL, [o1.id, o2.id, wall_id], where))
    return out


def _room_poly_checked(store: ProjectStore, room) -> Tuple[Optional[Polygon], Optional[Issue]]:
    """(đa giác phòng đúng hình học, None) | (None, Issue PHONG_BIEN_HONG) | (None, None) khi chưa đủ toạ độ."""
    if len(room.boundary) < 3:
        return None, _issue(SEV_ERROR, "PHONG_BIEN_HONG",
                            f"Phòng {room.id} ({room.name}): đường bao chỉ có {len(room.boundary)} điểm (cần ≥ 3).",
                            VAL, [room.id])
    pts = []
    for ref in room.boundary:
        p = _try_point(store, ref)
        if p is None:
            return None, None
        pts.append(p)
    poly = Polygon(pts)
    if not poly.is_valid:
        why = explain_validity(poly)
        m = re.search(r"\[(-?[\d.eE+-]+) (-?[\d.eE+-]+)\]", why)
        where = (float(m.group(1)), float(m.group(2))) if m else pts[0]
        return None, _issue(SEV_ERROR, "PHONG_BIEN_HONG",
                            f"Phòng {room.id} ({room.name}): đường bao tự cắt / sai hình học ({why}) — "
                            f"điểm bao: {', '.join(_fmt_pt(p) for p in pts)}.", VAL, [room.id], where)
    if poly.area < ROOM_ZERO_MM2:
        return None, _issue(SEV_ERROR, "PHONG_BIEN_HONG",
                            f"Phòng {room.id} ({room.name}): đường bao có diện tích 0 — "
                            f"điểm bao: {', '.join(_fmt_pt(p) for p in pts)}.", VAL, [room.id], pts[0])
    return poly, None


def _check_rooms(store: ProjectStore) -> List[Issue]:
    out = []
    polys: List[Tuple[Any, Polygon]] = []
    for room in store.rooms:
        poly, iss = _room_poly_checked(store, room)
        if iss is not None:
            out.append(iss)
        if poly is not None:
            polys.append((room, poly))
    for i, j in _bbox_pairs([p.bounds for _, p in polys]):
        (r1, p1), (r2, p2) = polys[i], polys[j]
        inter = _intersection(p1, p2)
        if inter.area > AREA_ROOM_MM2:
            out.append(_issue(SEV_ERROR, "PHONG_CHONG_NHAU",
                              f"Phòng {r1.id} ({r1.name}) và {r2.id} ({r2.name}) chồng nhau {_fmt_m2(inter.area)} "
                              f"quanh {_fmt_pt(_where_of(inter))}.", VAL, [r1.id, r2.id], inter))
    return out


def _axis_at(names: Sequence[str], offs: Sequence[Optional[float]], coord: float) -> Optional[str]:
    for name, off in zip(names, offs):
        if off is not None and abs(coord - off) <= TOL:
            return name
    return None


def _check_measured_dims(store: ProjectStore) -> List[Issue]:
    out = []
    cos_tol = math.cos(math.radians(AXIS_DIM_ANGLE_TOL_DEG))
    for md in store.measured_dims:
        try:
            p1 = (float(md.p1[0]), float(md.p1[1]))
            p2 = (float(md.p2[0]), float(md.p2[1]))
            angle = float(md.angle)
        except (TypeError, ValueError, IndexError):
            out.append(_issue(SEV_ERROR, "SO_LIEU_KHONG_PHAI_SO",
                              f"Kích thước nguồn {md.id}: điểm đo / góc không phải số (p1 = {md.p1!r}, p2 = {md.p2!r}, "
                              f"angle = {md.angle!r}).", VAL, [md.id]))
            continue
        meas = _num(md.measurement)
        value = meas if meas is not None else dim_measurement({"p1": p1, "p2": p2, "angle": angle})
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        text = str(md.text or "").strip()
        if text and text != "<>":
            differs, shown = _override_differs(text, value)
            if differs:
                out.append(_issue(SEV_DOUBT, "DIM_GHI_DE",
                                  f"Kích thước nguồn {md.id}: chữ ghi đè '{shown}' khác số đo {_fmt(value)} mm "
                                  f"(đo từ {_fmt_pt(p1)} tới {_fmt_pt(p2)}) — số hiển thị bị sửa tay, đối chiếu bản vẽ "
                                  f"đã duyệt.", VAL, [md.id], mid))
        a = math.radians(angle)
        for o, g in sorted(store.axes.items()):
            idx = 0 if o == "V" else 1
            across = abs(math.cos(a)) if o == "V" else abs(math.sin(a))
            if across < cos_tol:
                continue
            offs = g.offsets()
            n1, n2 = _axis_at(g.names, offs, p1[idx]), _axis_at(g.names, offs, p2[idx])
            if n1 is None or n2 is None or n1 == n2:
                continue
            dist = abs(g.offset_of(n2) - g.offset_of(n1))
            if abs(value - dist) > TOL:
                out.append(_issue(SEV_DOUBT, "DIM_LECH_TRUC",
                                  f"Kích thước nguồn {md.id} đo giữa trục {n1} và {n2}: {_fmt(value)} mm, nhưng khoảng "
                                  f"cách hai trục trong dữ liệu là {_fmt(dist)} mm (lệch {_fmt(value - dist)} mm "
                                  f"> {_fmt(TOL)} mm) — đối chiếu nhịp trục với bản vẽ.", VAL, [md.id], mid))
    return out


def _missing_issues(store: ProjectStore) -> List[Issue]:
    return [_issue(SEV_ERROR, "THIEU_KICH_THUOC",
                   f"Thiếu kích thước: {m.description} (khoá {m.key}) — người dùng nhập từ bản vẽ, hoặc nội suy có "
                   f"đánh dấu và phải được xác nhận.", VAL, [m.key], _key_where(store, m.key))
            for m in store.missing()]


def _unconfirmed_issues(store: ProjectStore) -> List[Issue]:
    out = []
    for key, prov in store.unconfirmed():
        try:
            val = store.get_value(key)
            shown = f" = {_fmt(val)}" if _num(val) is not None else ""
        except StoreError:
            shown = ""
        out.append(_issue(SEV_DOUBT, "NOI_SUY_CHUA_XAC_NHAN",
                          f"Số liệu nội suy CHƯA xác nhận: {key}{shown} (nguồn: {prov.ref or 'không ghi'}) — cần người "
                          f"có thẩm quyền xác nhận hoặc nhập giá trị đo từ bản vẽ.", VAL, [key],
                          _key_where(store, key)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# KIỂM TRA SAU MỖI SKILL
# ─────────────────────────────────────────────────────────────────────────────

class _CachedStore:
    """Bọc ProjectStore, nhớ kết quả giải điểm (point_or_reason / point) trong MỘT lần kiểm tra — store không đổi
    trong lúc kiểm tra. geom.wall_polygon dò mọi tường đi qua hai đầu của từng tường nên giải lại cùng một điểm rất
    nhiều lần (480 tường: 16,8 s không đệm → 1,9 s có đệm, đo trên lưới 16 × 16 trục). Mọi thuộc tính khác chuyển
    thẳng tới store thật; không sửa store."""

    def __init__(self, store: ProjectStore):
        self._store = store
        self._cache: Dict[Tuple[str, str], Tuple[bool, Any]] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def point_or_reason(self, ref: Any):
        key = (type(ref).__name__, repr(ref))
        hit = self._cache.get(key)
        if hit is None:
            try:
                hit = (True, self._store.point_or_reason(ref))
            except (StoreError, TypeError, ValueError) as e:
                hit = (False, e)
            self._cache[key] = hit
        if not hit[0]:
            raise hit[1]
        return hit[1]

    def point(self, ref: Any) -> Optional[Point]:
        return self.point_or_reason(ref)[0]


class _Ctx:
    """Hình học dùng chung trong một lần kiểm tra (tính lười, một lần). Lời gọi geom.* đi qua _CachedStore.

    Mỗi lời gọi geom.* được bọc riêng từng đối tượng: dữ liệu sai kiểu (vd bề rộng cửa là chữ) làm geom ném
    TypeError / ValueError thì đối tượng đó không dựng được hình — ghi vào geom_errors để check_step báo
    CANH_BAO CHUA_KIEM_TRA_HINH_HOC, không lờ đi."""

    def __init__(self, store: ProjectStore, plan: DrawingPlan):
        self.store, self.plan = store, plan
        self.cstore = _CachedStore(store)
        # lỗi → [(nhãn, mã)] các đối tượng không dựng được hình vì lỗi đó
        self.geom_errors: Dict[str, List[Tuple[str, str]]] = {}

    def safe(self, label: str, oid: str, fn, *args):
        """fn(*args) hoặc None khi geom ném lỗi vì dữ liệu sai kiểu (ghi lại để báo)."""
        try:
            return fn(*args)
        except (TypeError, ValueError, ZeroDivisionError, StoreError, GEOSException) as e:
            items = self.geom_errors.setdefault(f"{type(e).__name__}: {e}", [])
            if (label, oid) not in items:
                items.append((label, oid))
            return None

    @cached_property
    def wall_axes(self) -> List[Tuple[Any, Point, Point]]:
        out = []
        for w in self.store.walls:
            ab = _wall_axis(self.cstore, w)
            if ab is not None:
                out.append((w, ab[0], ab[1]))
        return out

    @cached_property
    def holes(self) -> BaseGeometry:
        polys = [f["poly"] for _, f in self.opening_frames] + [p for _, _, p in self.columns]
        return unary_union(polys) if polys else Polygon()

    @cached_property
    def wall_bodies(self) -> List[Tuple[str, str, BaseGeometry]]:
        """Thân từng tường (đã trừ ô cửa và cột) — để nêu đúng tường bị va chạm."""
        out = []
        for w in self.store.walls:
            poly = self.safe(f"tường {w.id}", w.id, geom.wall_polygon, self.cstore, w)
            if poly is None:
                continue
            body = poly.difference(self.holes)
            if not body.is_empty:
                out.append(("tường", w.id, body))
        return out

    @cached_property
    def columns(self) -> List[Tuple[str, str, Polygon]]:
        out = []
        for c in self.store.columns:
            poly = self.safe(f"cột {c.id}", c.id, geom.column_polygon, self.cstore, c)
            if poly is not None:
                out.append(("cột", c.id, poly))
        return out

    @cached_property
    def opening_frames(self) -> List[Tuple[Any, Dict[str, Any]]]:
        out = []
        for op in self.store.openings:
            f = self.safe(f"ô cửa {op.id}", op.id, geom.opening_frame, self.cstore, op)
            if f is not None:
                out.append((op, f))
        return out

    @cached_property
    def door_swings(self) -> List[Tuple[str, str, BaseGeometry]]:
        out = []
        for op in self.store.openings:
            sw = self.safe(f"cánh cửa {op.id}", op.id, geom.door_swing_polygon, self.cstore, op)
            if sw is not None and not sw.is_empty:
                out.append(("vùng quét cửa", op.id, sw))
        return out

    @cached_property
    def flights(self) -> List[Tuple[str, str, Polygon]]:
        out = []
        for st in self.store.stairs:
            for i, fl in enumerate(st.flights):
                fid = f"{st.id}.flights[{i}]"
                poly = self.safe(_flight_label(fid), fid, geom.flight_polygon, self.cstore, fl)
                if poly is not None:
                    out.append(("vế thang", fid, poly))
        return out

    @cached_property
    def rooms(self) -> Dict[str, Polygon]:
        out = {}
        for r in self.store.rooms:
            poly = self.safe(f"phòng {r.id}", r.id, geom.room_polygon, self.cstore, r)
            if poly is not None:
                out[r.id] = poly
        return out

    @cached_property
    def unbuilt_rooms(self) -> List[str]:
        """Phòng chưa dựng được đường bao (thiếu toạ độ / tham chiếu sai / bao hỏng — precheck đã báo nguyên nhân)."""
        return [r.id for r in self.store.rooms if r.id not in self.rooms]

    def geom_issues(self, code: str) -> List[Issue]:
        return [_issue(SEV_WARN, "CHUA_KIEM_TRA_HINH_HOC",
                       f"Chưa dựng được hình để kiểm tra xung đột ở bước {code} cho {_listed([lb for lb, _ in items])} — "
                       f"dữ liệu sai kiểu ({err}); sửa số liệu theo SO_LIEU_KHONG_PHAI_SO / KICH_THUOC_KHONG_DUONG của "
                       f"bước kiểm tra dữ liệu rồi chạy lại.", code, sorted({oid for _, oid in items}))
                for err, items in self.geom_errors.items()]


def _flight_label(fid: str) -> str:
    m = re.match(r"^(.*)\.flights\[(\d+)\]$", fid)
    return f"vế {int(m.group(2)) + 1} thang {m.group(1)}" if m else fid


def _obj_label(label: str, oid: str) -> str:
    return _flight_label(oid) if label == "vế thang" else f"{label} {oid}"


def check_step(store: ProjectStore, plan: DrawingPlan, code: str,
               before_fingerprints: Optional[Dict[str, str]]) -> List[Issue]:
    """Kiểm tra sau khi skill `code` chạy. before_fingerprints = plan.fingerprints() chụp ngay trước khi skill chạy."""
    code = f"{int(code):02d}" if str(code).isdigit() else str(code)
    ctx = _Ctx(store, plan)
    out: List[Issue] = []
    out += _ownership(plan, code)
    out += _foreign_changes(plan, code, before_fingerprints)
    out += _duplicate_strokes(plan, code)
    step = _STEP_CHECKS.get(code)
    if step is not None:
        out += step(ctx, code)
    out += ctx.geom_issues(code)
    return out


def _first_point(op: Op) -> Optional[List[float]]:
    for p in iter_points(op):
        return p
    return None


def _ownership(plan: DrawingPlan, code: str) -> List[Issue]:
    """Op nằm trên vai trò không thuộc skill tạo ra nó (plan.ownership_violations), gom theo (skill, vai trò).
    Chỉ xét Op của skill vừa chạy — mỗi skill đều qua check_step nên không lọt, và không báo lặp ở các bước sau —
    cộng Op mang mã skill lạ (ngoài "01".."10"), vì không bước nào khác xét tới chúng."""
    groups: Dict[Tuple[str, str], List[Op]] = {}
    for o in plan.ownership_violations():
        if o.skill == code or o.skill not in _STEP_CHECKS:
            groups.setdefault((o.skill, o.role), []).append(o)
    out = []
    for (skill, role), ops in groups.items():
        owner = ROLE_OWNER.get(role)
        layer = plan.layers[role].name if role in plan.layers else role
        whose = f"của skill {owner}" if owner else "không có trong bảng vai trò (ROLE_OWNER)"
        out.append(_issue(SEV_ERROR, "SKILL_LAN_PHAN",
                          f"Skill {skill} ghi {len(ops)} lệnh vẽ vào vai trò '{role}' (layer {layer}) {whose} — mỗi "
                          f"skill chỉ được ghi vào vai trò của mình: {_listed([o.eid for o in ops])}.",
                          skill, [o.eid for o in ops], _first_point(ops[0])))
    return out


def _foreign_changes(plan: DrawingPlan, code: str, before: Optional[Dict[str, str]]) -> List[Issue]:
    """Dấu vân tay Op của skill khác `code` phải giữ nguyên ("chỉ sửa phần liên quan")."""
    if before is None:
        return [_issue(SEV_WARN, "CHUA_CO_DAU_VAN_TAY",
                       f"Không có dấu vân tay chụp trước skill {code} — chưa kiểm tra được skill {code} có sửa phần "
                       f"của skill khác hay không.", code)]
    now = plan.fingerprints()
    out = []
    for s in sorted((set(before) | set(now)) - {code}):
        fb, fn = before.get(s, _EMPTY_FP), now.get(s, _EMPTY_FP)
        if fb == fn:
            continue
        n_now = len(plan.ops_of(skill=s))
        if fn == _EMPTY_FP:
            detail = f"toàn bộ lệnh vẽ của skill {s} đã bị xoá"
        elif fb == _EMPTY_FP:
            detail = f"skill {s} trước đó không có lệnh vẽ nào, nay có {n_now}"
        else:
            detail = f"nội dung lệnh vẽ của skill {s} đã đổi (hiện có {n_now} lệnh)"
        out.append(_issue(SEV_ERROR, "SKILL_SUA_PHAN_KHAC",
                          f"Sau skill {code}: dấu vân tay của skill {s} thay đổi — {detail}; mỗi skill chỉ được sửa "
                          f"phần của mình (trước {fb[:12]}…, sau {fn[:12]}…).", code,
                          [o.eid for o in plan.ops_of(skill=s)][:MAX_LISTED]))
    return out


def _op_segments(op: Op) -> List[Tuple[Point, Point]]:
    if op.kind == "line":
        pts = [op.data["p1"], op.data["p2"]]
        closed = False
    elif op.kind == "pline":
        pts = op.data["points"]
        closed = bool(op.data["closed"])
    else:
        return []
    pts = [(float(p[0]), float(p[1])) for p in pts]
    segs = list(zip(pts[:-1], pts[1:]))
    if closed and len(pts) > 2:
        segs.append((pts[-1], pts[0]))
    return [(a, b) for a, b in segs if geom.length(geom.sub(b, a)) > 1e-9]


def _duplicate_strokes(plan: DrawingPlan, code: str) -> List[Issue]:
    """line/pline của skill vừa chạy chồng nét lên nhau (cùng vai trò), phần chồng dài > TOL."""
    by_role: Dict[str, List[Op]] = {}
    for op in plan.ops_of(skill=code):
        if op.kind in ("line", "pline"):
            by_role.setdefault(op.role, []).append(op)
    out = []
    for role in sorted(by_role):
        ops = by_role[role]
        segs = [(oi, a, b) for oi, op in enumerate(ops) for a, b in _op_segments(op)]
        found: Dict[Tuple[int, int], Tuple[float, Point]] = {}
        for i, j in _bbox_pairs([_seg_bounds(a, b) for _, a, b in segs], TOL):
            (oi, a1, b1), (oj, a2, b2) = segs[i], segs[j]
            r = _collinear_overlap(a1, b1, a2, b2)
            if r is None or r[0] <= TOL:
                continue
            key = (min(oi, oj), max(oi, oj))
            if key not in found or r[0] > found[key][0]:
                found[key] = r
        for (oi, oj), (length, mid) in sorted(found.items()):
            if oi == oj:
                what = f"{ops[oi].eid} có hai đoạn chồng lên nhau"
                eids = [ops[oi].eid]
            else:
                what = f"{ops[oi].eid} và {ops[oj].eid} chồng lên nhau"
                eids = [ops[oi].eid, ops[oj].eid]
            out.append(_issue(SEV_WARN, "TRUNG_NET",
                              f"Trùng nét trong vai trò '{role}' (skill {code}): {what} dài {_fmt(length)} mm quanh "
                              f"{_fmt_pt(mid)}.", code, eids, mid))
    return out


# ── 01: lưới trục ────────────────────────────────────────────────────────────

def _step_01(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    for o, g in sorted(ctx.store.axes.items()):
        offs = g.offsets()
        other = _other_axis_coord(ctx.store, o)
        for i in range(len(g.names)):
            for j in range(i + 1, len(g.names)):
                if offs[i] is None or offs[j] is None or abs(offs[i] - offs[j]) > TOL:
                    continue
                coord = "x" if o == "V" else "y"
                where = (offs[i], other) if o == "V" else (other, offs[i])
                out.append(_issue(SEV_ERROR, "TRUC_TRUNG_VI_TRI",
                                  f"Trục {g.names[i]} và {g.names[j]} (nhóm {o}) cùng toạ độ {coord} = "
                                  f"{_fmt(offs[i])} mm — hai đường trục trùng nhau.", code, [g.names[i], g.names[j]],
                                  where))
    return out


# ── 02: cột ──────────────────────────────────────────────────────────────────

def _step_02(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    cols = ctx.columns
    for i, j in _bbox_pairs([p.bounds for _, _, p in cols]):
        (_, c1, p1), (_, c2, p2) = cols[i], cols[j]
        inter = _intersection(p1, p2)
        if inter.area > AREA_COLUMN_MM2:
            out.append(_issue(SEV_ERROR, "COT_CHONG_NHAU",
                              f"Cột {c1} và cột {c2} chồng nhau {_fmt(inter.area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [c1, c2], inter))
    for c in ctx.store.columns:
        dx, dy = _num(c.dx) or 0.0, _num(c.dy) or 0.0
        if dx != 0.0 or dy != 0.0:
            out.append(_issue(SEV_WARN, "COT_LECH_TRUC",
                              f"Cột {c.id} lệch tâm so với giao trục {c.axis_v}/{c.axis_h}: dx = {_fmt(dx)} mm, "
                              f"dy = {_fmt(dy)} mm (thông tin — kiểm tra đúng ý đồ thiết kế).", code, [c.id],
                              _entity_point(ctx.store, "columns", c)))
    return out


# ── 03: tường ────────────────────────────────────────────────────────────────

def _on_axis_line(store: ProjectStore, a: Point, b: Point) -> bool:
    for o, g in store.axes.items():
        idx = 0 if o == "V" else 1
        for off in g.offsets():
            if off is not None and abs(a[idx] - off) <= TOL and abs(b[idx] - off) <= TOL:
                return True
    return False


def _step_03(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    walls = ctx.wall_axes
    for i, j in _bbox_pairs([_seg_bounds(a, b) for _, a, b in walls], TOL):
        (w1, a1, b1), (w2, a2, b2) = walls[i], walls[j]
        ov = _collinear_overlap(a1, b1, a2, b2)
        if ov is not None and ov[0] > TOL:
            out.append(_issue(SEV_ERROR, "TUONG_TRUNG",
                              f"Tường {w1.id} và tường {w2.id} thẳng hàng, tim chồng nhau {_fmt(ov[0])} mm quanh "
                              f"{_fmt_pt(ov[1])} — tường bị nhập trùng.", code, [w1.id, w2.id], ov[1]))
            continue
        p = _proper_crossing(a1, b1, a2, b2)
        if p is not None:
            out.append(_issue(SEV_WARN, "TUONG_CAT_NHAU",
                              f"Tường {w1.id} và tường {w2.id} cắt nhau tại {_fmt_pt(p)} ở giữa cả hai tường (không phải "
                              f"đầu tường) — kiểm tra định vị, nên tách tường tại giao điểm.", code, [w1.id, w2.id], p))
    for w, a, b in walls:
        numeric = [n for n, ref in (("đầu", w.start), ("cuối", w.end)) if isinstance(ref, (list, tuple))]
        if numeric and not _on_axis_line(ctx.store, a, b):
            out.append(_issue(SEV_WARN, "TUONG_LECH_TRUC",
                              f"Tường {w.id} cho điểm {' và '.join(numeric)} bằng toạ độ số ({_fmt_pt(a)} → "
                              f"{_fmt_pt(b)}), tim không nằm trên đường trục nào — kiểm tra định vị (nên tham chiếu "
                              f"trục, vd '1/A@dx,dy').", code, [w.id], ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)))
    return out


# ── 04: cửa ──────────────────────────────────────────────────────────────────

def _step_04(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    for op, fr in ctx.opening_frames:
        for _, cid, inter, area in _clashes(fr["poly"], ctx.columns, AREA_COLUMN_MM2):
            out.append(_issue(SEV_ERROR, "CUA_DAM_COT",
                              f"Ô cửa {op.id} (tường {op.wall_id}) đè cột {cid}: giao {_fmt(area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [op.id, cid], inter))
    obstacles = ctx.wall_bodies + ctx.columns
    swings = ctx.door_swings
    for _, oid, sw in swings:
        for label, xid, inter, area in _clashes(sw, obstacles, AREA_CLASH_MM2):
            out.append(_issue(SEV_WARN, "CANH_CUA_VUONG",
                              f"Cánh cửa {oid} khi mở quét vào {label} {xid}: giao {_fmt(area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [oid, xid], inter))
    for i, j in _bbox_pairs([sw.bounds for _, _, sw in swings]):
        (_, o1, s1), (_, o2, s2) = swings[i], swings[j]
        inter = _intersection(s1, s2)
        if inter.area > AREA_CLASH_MM2:
            out.append(_issue(SEV_WARN, "CANH_CUA_CHONG",
                              f"Vùng quét cánh cửa {o1} và {o2} chồng nhau {_fmt(inter.area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))} — hai cánh mở va nhau.", code, [o1, o2], inter))
    return out


# ── 05: cầu thang ────────────────────────────────────────────────────────────

def _room_overlap_note(rooms: Dict[str, Polygon], g: BaseGeometry) -> str:
    parts = []
    total = g.area or 1.0
    for rid, poly in rooms.items():
        if not _bbox_hit(poly.bounds, g.bounds):
            continue
        a = _intersection(poly, g).area
        if a > AREA_ZERO_MM2:
            parts.append(f"{rid} {a / total * 100:.0f} %")
    return ("giao " + ", ".join(parts)) if parts else "không giao phòng nào"


def _step_05(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    obstacles = ctx.wall_bodies + ctx.columns
    rooms = ctx.rooms
    for _, fid, poly in ctx.flights:
        name = _flight_label(fid)
        for label, xid, inter, area in _clashes(poly, obstacles, AREA_CLASH_MM2):
            out.append(_issue(SEV_ERROR, "THANG_DAM_TUONG",
                              f"{_cap(name)} đè {label} {xid}: giao {_fmt(area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [fid, xid], inter))
        if not any(_covers(rp, poly) for rp in rooms.values()):
            unbuilt = ctx.unbuilt_rooms
            if unbuilt:
                out.append(_issue(SEV_WARN, "THANG_CHUA_KIEM_TRA",
                                  f"Chưa kiểm tra được {name} nằm trong phòng: không nằm trọn trong phòng nào đã dựng "
                                  f"được ({_room_overlap_note(rooms, poly)}), còn phòng chưa dựng được đường bao: "
                                  f"{_listed(unbuilt)}.", code, [fid], poly))
            else:
                note = _room_overlap_note(rooms, poly) if rooms else "dữ liệu không có phòng nào"
                out.append(_issue(SEV_WARN, "THANG_NGOAI_PHONG",
                                  f"{_cap(name)} không nằm trọn trong phòng nào ({note}).", code, [fid], poly))
        for _, oid, inter, area in _clashes(poly, ctx.door_swings, AREA_CLASH_MM2):
            out.append(_issue(SEV_WARN, "CUA_VUONG_THANG",
                              f"Cánh cửa {oid} khi mở quét vào {name}: giao {_fmt(area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [oid, fid], inter))
    return out


# ── 06: nội thất ─────────────────────────────────────────────────────────────

def _furniture_footprints(ctx: _Ctx, code: str, out: List[Issue]) -> List[Tuple[Any, Polygon]]:
    fps = []
    for f in ctx.store.furniture:
        blk = ctx.plan.blocks.get(f.block)
        why = ""
        p = None
        if blk is None:
            why = f"block '{f.block}' chưa có trong plan.blocks (skill 06 chưa chèn?)"
        elif not (blk.size[0] > 0 and blk.size[1] > 0):
            why = f"block '{f.block}' chưa khai báo kích thước (size = {blk.size})"
        else:
            try:
                p, reason = ctx.store.point_or_reason(f.insert)
                if p is None:
                    why = f"điểm chèn chưa xác định: {reason}"
            except (StoreError, TypeError, ValueError) as e:
                why = f"điểm chèn sai: {e}"
        rot = _num(f.rotation) if f.rotation is not None else 0.0
        if not why and rot is None:
            why = f"góc xoay {f.rotation!r} không phải số"
        if why:
            out.append(_issue(SEV_WARN, "NOI_THAT_CHUA_KIEM_TRA",
                              f"Chưa kiểm tra va chạm nội thất {f.id} ({f.block}): {why}.", code, [f.id],
                              p if p is not None else None))
            continue
        fps.append((f, geom.footprint(p, (blk.size[0], blk.size[1]), rot)))
    return fps


def _step_06(ctx: _Ctx, code: str) -> List[Issue]:
    out: List[Issue] = []
    fps = _furniture_footprints(ctx, code, out)
    obstacles = ctx.wall_bodies + ctx.columns + ctx.flights
    rooms = ctx.rooms
    for f, fp in fps:
        for label, xid, inter, area in _clashes(fp, obstacles, AREA_CLASH_MM2):
            out.append(_issue(SEV_ERROR, "NOI_THAT_XUNG_DOT",
                              f"Nội thất {f.id} ({f.block}) đè {_obj_label(label, xid)}: giao {_fmt(area)} mm² quanh "
                              f"{_fmt_pt(_where_of(inter))}.", code, [f.id, xid], inter))
        for _, oid, inter, area in _clashes(fp, ctx.door_swings, AREA_CLASH_MM2):
            out.append(_issue(SEV_WARN, "NOI_THAT_CHAN_CUA",
                              f"Nội thất {f.id} ({f.block}) nằm trong vùng quét cánh cửa {oid}: giao {_fmt(area)} mm² "
                              f"quanh {_fmt_pt(_where_of(inter))}.", code, [f.id, oid], inter))
        if f.room_id:
            if ctx.store.get("rooms", f.room_id) is None:
                out.append(_issue(SEV_WARN, "NOI_THAT_NGOAI_PHONG",
                                  f"Nội thất {f.id} ({f.block}) ghi phòng '{f.room_id}' không có trong dữ liệu.",
                                  code, [f.id], fp))
            elif f.room_id not in rooms:
                out.append(_issue(SEV_WARN, "NOI_THAT_CHUA_KIEM_TRA",
                                  f"Chưa kiểm tra được nội thất {f.id} nằm trong phòng {f.room_id}: đường bao phòng "
                                  f"chưa dựng được.", code, [f.id, f.room_id], fp))
            elif not _covers(rooms[f.room_id], fp):
                outside = fp.area - _intersection(rooms[f.room_id], fp).area
                out.append(_issue(SEV_WARN, "NOI_THAT_NGOAI_PHONG",
                                  f"Nội thất {f.id} ({f.block}) không nằm trọn trong phòng {f.room_id}: "
                                  f"{_fmt(outside)} mm² ({outside / fp.area * 100:.0f} %) ở ngoài.", code,
                                  [f.id, f.room_id], fp.difference(rooms[f.room_id])))
        elif not any(_covers(rp, fp) for rp in rooms.values()):
            if ctx.unbuilt_rooms:
                out.append(_issue(SEV_WARN, "NOI_THAT_CHUA_KIEM_TRA",
                                  f"Chưa kiểm tra được nội thất {f.id} ({f.block}) nằm trong phòng: chưa ghi phòng, không "
                                  f"nằm trọn trong phòng nào đã dựng được, còn phòng chưa dựng được đường bao: "
                                  f"{_listed(ctx.unbuilt_rooms)}.", code, [f.id], fp))
            else:
                out.append(_issue(SEV_WARN, "NOI_THAT_NGOAI_PHONG",
                                  f"Nội thất {f.id} ({f.block}) chưa ghi phòng và không nằm trọn trong phòng nào "
                                  f"({_room_overlap_note(rooms, fp)}).", code, [f.id], fp))
    for i, j in _bbox_pairs([fp.bounds for _, fp in fps]):
        (f1, p1), (f2, p2) = fps[i], fps[j]
        inter = _intersection(p1, p2)
        if inter.area > AREA_CLASH_MM2:
            out.append(_issue(SEV_WARN, "NOI_THAT_CHONG_NHAU",
                              f"Nội thất {f1.id} ({f1.block}) và {f2.id} ({f2.block}) chồng nhau {_fmt(inter.area)} mm² "
                              f"quanh {_fmt_pt(_where_of(inter))}.", code, [f1.id, f2.id], inter))
    return out


# ── 07: hatch ────────────────────────────────────────────────────────────────

def _step_07(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    for op in ctx.plan.ops_of(skill=code, kind="hatch"):
        loops = op.data["boundaries"]
        where = loops[0][0] if loops and loops[0] else None
        try:
            poly = Polygon(loops[0], loops[1:])
            why = "" if poly.is_valid else explain_validity(poly)
            if not why and poly.area <= AREA_ZERO_MM2:
                why = "diện tích 0"
            if not why:
                continue
            if not poly.is_empty:
                m = re.search(r"\[(-?[\d.eE+-]+) (-?[\d.eE+-]+)\]", why)
                where = (float(m.group(1)), float(m.group(2))) if m else where
        except (ValueError, TypeError, GEOSException) as e:
            why = f"không dựng được đa giác: {e}"
        out.append(_issue(SEV_ERROR, "HATCH_BIEN_HONG",
                          f"Hatch {op.eid} ({op.data['pattern']}): biên không tạo được miền kín đúng hình học "
                          f"({why}); {len(loops)} vòng biên, vòng ngoài {len(loops[0])} điểm.", code, [op.eid], where))
    return out


# ── 08: kích thước ───────────────────────────────────────────────────────────

def _step_08(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    for op in ctx.plan.ops_of(skill=code, kind="dim_linear"):
        d = op.data
        p1, p2 = d["p1"], d["p2"]
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        value = dim_measurement(d)
        if value <= TOL:
            out.append(_issue(SEV_ERROR, "DIM_BANG_0",
                              f"Kích thước {op.eid} đo {_fmt(value)} mm ≤ {_fmt(TOL)} mm (từ {_fmt_pt(p1)} tới "
                              f"{_fmt_pt(p2)}, góc {_fmt(d['angle'])}°).", code, [op.eid], mid))
        override = d.get("text_override")
        if override not in (None, "", "<>"):
            out.append(_issue(SEV_DOUBT, "DIM_GHI_DE",
                              f"Kích thước {op.eid} ghi đè chữ '{override}' thay cho số đo {_fmt(value)} mm — "
                              f"chủ dự án soát lý do.", code, [op.eid], mid))
    return out


# ── 09: hoàn thiện ───────────────────────────────────────────────────────────

def _step_09(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    rooms = ctx.rooms
    for op in ctx.plan.ops_of(skill=code, kind="text"):
        if not op.eid.endswith("/ten"):
            continue
        parts = op.eid.split("/")
        rid = parts[-2] if len(parts) >= 2 else ""
        pt = ShPoint(op.data["insert"])
        if rid in rooms:
            if _covers(rooms[rid], pt):
                continue
            msg = f"nằm ngoài phòng {rid}"
        elif any(_covers(rp, pt) for rp in rooms.values()):
            continue
        else:
            msg = f"không nằm trong phòng nào (mã phòng '{rid}' chưa dựng được đường bao)"
        out.append(_issue(SEV_WARN, "NHAN_NGOAI_PHONG",
                          f"Nhãn tên phòng {op.eid} ('{op.data['text']}') tại {_fmt_pt(op.data['insert'])} {msg}.",
                          code, [op.eid], op.data["insert"]))
    return out


# ── 10: khung bản vẽ, chữ đè chữ ─────────────────────────────────────────────

def _frame_bounds(frame: Any) -> Optional[Bounds]:
    """plan.meta["sheet_frame"] → (xmin, ymin, xmax, ymax). Nhận [xmin, ymin, xmax, ymax] (dạng skill 10 ghi),
    [[x0, y0], [x1, y1]] hoặc {"xmin", "ymin", "xmax", "ymax"}. None nếu không đọc được."""
    try:
        if isinstance(frame, dict):
            vals = [float(frame[k]) for k in ("xmin", "ymin", "xmax", "ymax")]
        elif len(frame) == 4:
            vals = [float(v) for v in frame]
        elif len(frame) == 2:
            (x0, y0), (x1, y1) = frame
            vals = [float(x0), float(y0), float(x1), float(y1)]
        else:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    if not all(math.isfinite(v) for v in vals):
        return None
    x0, y0, x1, y1 = vals
    b = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if b[2] - b[0] <= 0 or b[3] - b[1] <= 0:
        return None
    return b


def _extent_points(op: Op, plan: DrawingPlan) -> List[Point]:
    """Điểm định nghĩa của Op (plan.iter_points); block chèn có size thì thêm 4 góc hộp block đã biến đổi."""
    pts = [(float(p[0]), float(p[1])) for p in iter_points(op)]
    if op.kind == "insert":
        blk = plan.blocks.get(op.data["block"])
        if blk is not None and blk.size[0] > 0 and blk.size[1] > 0:
            x, y = op.data["insert"]
            sx, sy = op.data["scale"]
            r = math.radians(op.data["rotation"])
            c, s = math.cos(r), math.sin(r)
            for bx, by in ((0.0, 0.0), (blk.size[0], 0.0), (blk.size[0], blk.size[1]), (0.0, blk.size[1])):
                px, py = bx * sx, by * sy
                pts.append((x + px * c - py * s, y + px * s + py * c))
    return pts


def _text_box(op: Op) -> Optional[Polygon]:
    """Hộp bao ước lượng của text / mtext: cao = chiều cao chữ (mtext: theo số dòng), rộng = 0,75 × cao × số ký tự,
    đặt theo align / attach rồi xoay quanh điểm chèn."""
    d = op.data
    h = float(d["height"])
    if op.kind == "text":
        w = TEXT_CHAR_WIDTH * h * max(len(_plain_text(d["text"])), 1)
        bh = h
        fx, fy = _ALIGN_FRAC.get(d["align"], (0.0, 0.0))
        rot = float(d.get("rotation", 0.0) or 0.0)
    elif op.kind == "mtext":
        lines = re.split(r"\\P|\n", str(d["text"]))
        est = [TEXT_CHAR_WIDTH * h * max(len(_plain_text(ln)), 1) for ln in lines]
        width = _num(d.get("width")) or 0.0
        if width > 0:
            n_lines = sum(max(1, math.ceil(e / width - 1e-9)) for e in est)
            w = min(width, max(est))
        else:
            n_lines, w = len(lines), max(est)
        bh = h * (1.0 + (n_lines - 1) * MTEXT_LINE_SPACING)
        fx, fy = _ATTACH_FRAC.get(d["attach"], (0.0, 1.0))
        rot = _num(d.get("rotation")) or 0.0
    else:
        return None
    if w <= 0 or bh <= 0:
        return None
    x, y = d["insert"]
    x0, y0 = x - fx * w, y - fy * bh
    rect = box(x0, y0, x0 + w, y0 + bh)
    return affinity.rotate(rect, rot, origin=(x, y)) if rot else rect


def _eid_root(eid: str) -> str:
    """Eid gốc: bỏ MỘT đoạn chỉ số dòng cuối ("…/hang/P1/2/0" → "…/hang/P1/2") — các dòng của cùng một ô chữ."""
    head, _, tail = eid.rpartition("/")
    return head if head and tail.isdigit() else eid


def _step_10(ctx: _Ctx, code: str) -> List[Issue]:
    out = []
    plan = ctx.plan
    frame = plan.meta.get("sheet_frame")
    if frame is None:
        out.append(_issue(SEV_WARN, "KHUNG_CHUA_CO",
                          "plan.meta chưa có 'sheet_frame' (khung bản vẽ chưa đặt được) — chưa kiểm tra được nội dung "
                          "nằm trong khung.", code))
    else:
        fb = _frame_bounds(frame)
        if fb is None:
            out.append(_issue(SEV_WARN, "KHUNG_KHONG_DOC_DUOC",
                              f"plan.meta['sheet_frame'] = {frame!r} không đọc được (cần [xmin, ymin, xmax, ymax]) — "
                              f"chưa kiểm tra được nội dung nằm trong khung.", code))
        else:
            bad: Dict[str, List[Tuple[str, Point]]] = {}
            for op in plan.ops:
                if op.role in FRAME_FREE_ROLES:
                    continue
                for p in _extent_points(op, plan):
                    if not (fb[0] - TOL <= p[0] <= fb[2] + TOL and fb[1] - TOL <= p[1] <= fb[3] + TOL):
                        bad.setdefault(op.skill, []).append((op.eid, p))
                        break
            for s in sorted(bad):
                items = bad[s]
                out.append(_issue(SEV_ERROR, "NOI_DUNG_NGOAI_KHUNG",
                                  f"{len(items)} lệnh vẽ của skill {s} có điểm nằm ngoài khung bản vẽ "
                                  f"{_fmt_pt(fb[:2])} – {_fmt_pt(fb[2:])}: {_listed([e for e, _ in items])} (điểm đầu "
                                  f"tiên ngoài khung {_fmt_pt(items[0][1])}).", code, [e for e, _ in items],
                                  items[0][1]))
    texts = []
    for op in plan.ops:
        if op.kind in ("text", "mtext") and op.role not in FRAME_FREE_ROLES:
            bx = _text_box(op)
            if bx is not None and bx.area > 0:
                texts.append((op, bx))
    for i, j in _bbox_pairs([bx.bounds for _, bx in texts]):
        (o1, b1), (o2, b2) = texts[i], texts[j]
        if _eid_root(o1.eid) == _eid_root(o2.eid):
            continue
        inter = _intersection(b1, b2)
        small = min(b1.area, b2.area)
        if inter.area > TEXT_OVERLAP_RATIO * small:
            out.append(_issue(SEV_WARN, "CHU_DE_CHU",
                              f"Chữ '{_plain_text(o1.data['text'])}' ({o1.eid}) và '{_plain_text(o2.data['text'])}' "
                              f"({o2.eid}) đè nhau {inter.area / small * 100:.0f} % hộp chữ nhỏ hơn quanh "
                              f"{_fmt_pt(_where_of(inter))} (hộp ước lượng 0,75 × chiều cao × số ký tự).",
                              code, [o1.eid, o2.eid], inter))
    return out


_STEP_CHECKS = {"01": _step_01, "02": _step_02, "03": _step_03, "04": _step_04, "05": _step_05,
                "06": _step_06, "07": _step_07, "08": _step_08, "09": _step_09, "10": _step_10}


# ─────────────────────────────────────────────────────────────────────────────
# KIỂM TRA CUỐI VÀ TỔNG HỢP
# ─────────────────────────────────────────────────────────────────────────────

def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def check_final(store: ProjectStore, plan: DrawingPlan, results: Iterable[Any]) -> List[Issue]:
    """results: SkillResult (hoặc vật có code / name / skipped, hoặc dict SkillResult.to_dict()).
    Mỗi mục bỏ qua → CANH_BAO DOI_TUONG_CHUA_VE; còn thiếu / còn nội suy chưa xác nhận → lặp lại như precheck."""
    out: List[Issue] = []
    for r in results or []:
        code, name = str(_field(r, "code", "")), str(_field(r, "name", ""))
        for item in _field(r, "skipped", None) or []:
            iid = str(_field(item, "id", ""))
            reason = str(_field(item, "ly_do", "") or "không ghi lý do")
            out.append(_issue(SEV_WARN, "DOI_TUONG_CHUA_VE",
                              f"Skill {code} ({name}) chưa vẽ '{iid}': {reason}.", code, [iid],
                              _locate_id(store, iid)))
    out += _missing_issues(store)
    out += _unconfirmed_issues(store)
    return out


def summarize(issues: Iterable[Issue]) -> Dict[str, Any]:
    """Đếm theo mức độ, theo mã (và mã × mức độ). "dat" TÍNH = không có LOI và không có NGHI_VAN."""
    issues = list(issues)
    by_sev = {s: 0 for s in SEVERITIES}
    by_code: Dict[str, int] = {}
    by_code_sev: Dict[str, Dict[str, int]] = {}
    for i in issues:
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
        by_code[i.code] = by_code.get(i.code, 0) + 1
        by_code_sev.setdefault(i.code, {})
        by_code_sev[i.code][i.severity] = by_code_sev[i.code].get(i.severity, 0) + 1
    return {
        "tong": len(issues),
        "theo_muc_do": by_sev,
        "theo_ma": dict(sorted(by_code.items())),
        "theo_ma_muc_do": {k: dict(sorted(v.items())) for k, v in sorted(by_code_sev.items())},
        "dat": by_sev[SEV_ERROR] == 0 and by_sev[SEV_DOUBT] == 0,
    }


__all__ = ["precheck", "check_step", "check_final", "summarize", "VAL",
           "AREA_COLUMN_MM2", "AREA_CLASH_MM2", "AREA_ROOM_MM2", "TEXT_CHAR_WIDTH", "TEXT_OVERLAP_RATIO"]
