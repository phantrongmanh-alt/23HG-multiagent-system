# -*- coding: utf-8 -*-
"""
SKILL 00 — "AutoCAD ĐỌC BẢN VẼ": đưa mọi đầu vào về Project Data Store (store.py) đúng MỘT lần.

Nguồn vào (load_inputs điều phối theo đuôi file):
  .json            đề bài nhập tay theo mẫu examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json → read_spec
  .dxf             bản vẽ CAD: trục, cột, tường, cửa, DIMENSION nhận diện theo TÊN LAYER       → read_dxf
  .pdf .png .jpg   ảnh nền tham chiếu — KHÔNG tự nhận dạng số (repo cấm đoán số OCR mờ)       → attach_reference
  template .dxf    layer + block của đơn vị                                                     → read_template
  .dwg             từ chối: cần AutoCAD (máy chủ cad-mcp) hoặc chuyển sang DXF trước

Kích thước thiếu (store.missing()):
  A. "Tôi nhập" — apply_user_values: file JSON {"nguon", "gia_tri", "xac_nhan"}; nguồn "nguoi_nhap".
  B. "Nội suy"  — interpolate_missing: tất định, chỉ từ kích thước rõ (kích thước tổng trục, đối tượng cùng
                  ký hiệu); nguồn "noi_suy", confirmed=False — KHÔNG BAO GIỜ tự coi là đã xác nhận.

Không bỏ dữ liệu im lặng: mỗi thực thể trong model space của DXF hoặc được đọc thành dữ liệu, hoặc hiện trong
store.issues (skill "00") kèm handle và lý do. Đơn vị mm; toạ độ model space đọc nguyên giá trị, không quy đổi.

Đọc DXF — quy tắc nhận diện (mẫu regex theo tên layer ở DEFAULT_ROLE_PATTERNS, không phân biệt hoa thường,
tên layer được bỏ dấu tiếng Việt trước khi so; một layer khớp nhiều mẫu thì lấy theo DXF_ROLE_PRIORITY):
  trục   LINE gần đứng → nhóm V (x), gần ngang → nhóm H (y); gộp đường cùng toạ độ (≤ tol). Tên trục là chữ
         (TEXT/MTEXT, hoặc ATTRIB của INSERT) trong/ngay cạnh vòng tròn ở đầu đường trục; không có → "?1", "?2"...
  cột    đa tuyến kín hình chữ nhật thẳng trục X/Y → b, h, tâm; gán giao trục gần nhất, dx/dy = độ lệch.
  tường  cặp đường song song cách nhau WALL_MIN_THICKNESS–WALL_MAX_THICKNESS mm, có đoạn chồng nhau → tim = đường
         giữa, dày = khoảng cách. Đoạn tường thẳng hàng cùng chiều dày được nối qua ô cửa (có INSERT cửa) và qua
         chỗ giao tường (có đầu tường khác); đầu tường chạm (hoặc ăn vào) tường khác được đưa về giao tim (góc, ngã ba khép kín).
  cửa    INSERT trên layer cửa đi / cửa sổ → tường gần nhất (tim cách điểm chèn ≤ nửa dày + tol); offset, width đo
         bao hình block dọc tim tường; cửa đi: số cánh, bản lề, chiều mở đọc từ cung mở trong block.
  DIMENSION (mọi layer) → MeasuredDim; chữ ghi đè khác số đo → NGHI_VAN "DIM_GHI_DE".
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import ezdxf
from ezdxf import disassemble, recover
from ezdxf import units as dxf_units
from ezdxf.render.arrows import ARROWS
from ezdxf.tools.text import plain_mtext

from tools.cad_drafting.geom import dist_point_segment
from tools.cad_drafting.layers import DEFAULT_ROLES, LayerSpec
from tools.cad_drafting.plan import BlockDef, PlanError, normalize_op_data
from tools.cad_drafting.store import (SEV_DOUBT, SEV_ERROR, SEV_WARN, SRC_DXF, SRC_INTERP, SRC_USER, AxisGroup,
                                      Column, Issue, MeasuredDim, Opening, ProjectStore, Provenance, SourceFile,
                                      StoreError, Wall)

SKILL_CODE = "00"
Pt = Tuple[float, float]

# ── mẫu nhận diện layer ──────────────────────────────────────────────────────

DEFAULT_ROLE_PATTERNS: Dict[str, str] = {
    "truc": r"truc|axis|grid",
    "tuong": r"tuong|wall",
    "cot": r"cot|col|column",
    "cua_di": r"cua.?di|door",
    "cua_so": r"cua.?so|window|glaz",
    "dim": r"dim",
}
# layer khớp nhiều mẫu → lấy vai trò đứng trước (vd "TUONG-DIM" là kích thước, không phải tường)
DXF_ROLE_PRIORITY: Tuple[str, ...] = ("dim", "cua_di", "cua_so", "truc", "cot", "tuong")

# mẫu khớp layer template với các vai trò trong layers.DEFAULT_ROLES (cùng cách so như trên)
TEMPLATE_ROLE_PATTERNS: Dict[str, str] = {
    "anh_nen": r"anh.?nen|underlay|raster|image",
    "truc": r"truc|axis|axes|grid",
    "truc_kh": r"(truc|axis|axes|grid).*(kh|ky.?hieu|bubble|tag|iden|text|ten)"
               r"|(ky.?hieu|bubble|tag|iden).*(truc|axis|grid)",
    "cot": r"cot|col|column",
    "tuong": r"tuong|wall",
    "cua": r"cua|door|window|glaz",
    "cua_kh": r"(cua|door|window|glaz).*(kh|ky.?hieu|tag|iden|mark)|(ky.?hieu|tag|iden|mark).*(cua|door|window)",
    "thang": r"thang|stair|strs",
    "noi_that": r"noi.?that|furn|equip|fixt|thiet.?bi",
    "hatch": r"hatch|patt",
    "dim": r"dim|kich.?thuoc",
    "hoan_thien": r"hoan.?thien|finish|ten.?phong|room|anno|cote|cao.?do",
    "khung_ten": r"khung|title|frame|border|tblk",
    "kiem_tra": r"kiem.?tra|check|review|redline",
}
TEMPLATE_ROLE_PRIORITY: Tuple[str, ...] = (
    "kiem_tra", "anh_nen", "khung_ten", "truc_kh", "cua_kh", "dim", "hatch", "thang", "noi_that",
    "hoan_thien", "cua", "cot", "tuong", "truc")
NON_PLOT_ROLES = ("anh_nen", "kiem_tra")     # vai trò không in theo thiết kế, giữ plot=False dù template ghi khác

# ── ngưỡng hình học ──────────────────────────────────────────────────────────

WALL_MIN_THICKNESS = 50.0      # mm — khoảng cách hai mặt tường nhỏ nhất được ghép cặp
WALL_MAX_THICKNESS = 500.0     # mm — lớn nhất
AXIS_ANGLE_TOL_DEG = 0.5       # đường trục lệch phương đứng/ngang tới mức này vẫn coi là trục V/H
MAX_EIDS = 200                 # số handle tối đa ghi vào một Issue gộp (số đếm trong thông điệp luôn đủ)

REFERENCE_EXT: Dict[str, str] = {".pdf": "pdf", ".png": "anh", ".jpg": "anh", ".jpeg": "anh"}
DATA_EXT = (".json", ".dxf")
SPEC_TEMPLATE_HINT = "examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json"
DWG_MESSAGE = "DWG cần AutoCAD (máy chủ cad-mcp) hoặc chuyển sang DXF trước"

USER_VALUES_KEYS = ("nguon", "gia_tri", "xac_nhan", "ghi_chu", "schema")
CONFIRM_KEYS = ("key", "by", "ghi_chu")
POSITIVE_FIELDS = ("spans", "overall", "b", "h", "thickness", "width", "height", "going", "n_treads", "riser")
NON_NEGATIVE_FIELDS = ("offset", "sill")


class ReaderError(ValueError):
    """Đầu vào không đọc được / không hợp lệ — thông điệp nói rõ cần làm gì."""


# ─────────────────────────────────────────────────────────────────────────────
# TIỆN ÍCH CHUNG
# ─────────────────────────────────────────────────────────────────────────────

def _r(v: float, nd: int = 3) -> float:
    """Làm tròn toạ độ/kích thước tới 0,001 mm (bỏ nhiễu dấu phẩy động, không có -0.0)."""
    v = round(float(v), nd)
    return 0.0 if v == 0 else v


def _fmt(v: float) -> str:
    s = f"{_r(v):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_file(path: Any, what: str) -> str:
    if not isinstance(path, (str, os.PathLike)):
        raise ReaderError(f"{what}: cần đường dẫn file, nhận {path!r}")
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise ReaderError(f"{what}: không thấy file '{os.path.basename(path)}'")
    return path


def _load_json(path: str, fname: str) -> Any:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ReaderError(f"{fname}: JSON sai cú pháp ở dòng {e.lineno}, cột {e.colno}: {e.msg}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ReaderError(f"{fname}: không đọc được file JSON ({e.__class__.__name__})") from e


def _add_issue(store: ProjectStore, severity: str, code: str, message: str,
               eids: Iterable[str] = (), where: Optional[Pt] = None) -> Issue:
    """Thêm Issue của Skill 00 (bỏ qua nếu đã có Issue giống hệt — gọi lại không nhân đôi)."""
    eids = [str(e) for e in eids]
    for old in store.issues:
        if (old.skill, old.severity, old.code, old.message, old.eids) == (SKILL_CODE, severity, code, message, eids):
            return old
    iss = Issue(severity=severity, code=code, message=message, skill=SKILL_CODE, eids=eids,
                where=None if where is None else [_r(where[0]), _r(where[1])])
    store.issues.append(iss)
    return iss


def _capped(handles: Sequence[str]) -> Tuple[List[str], str]:
    """(danh sách handle ≤ MAX_EIDS, ghi chú nếu bị cắt bớt)."""
    uniq = list(dict.fromkeys(handles))
    if len(uniq) <= MAX_EIDS:
        return uniq, ""
    return uniq[:MAX_EIDS], f" (eids liệt kê {MAX_EIDS}/{len(uniq)} handle đầu)"


def _fold(name: str) -> str:
    """Bỏ dấu tiếng Việt, chữ thường — để mẫu "tuong" khớp layer "TƯỜNG"."""
    s = str(name).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


def _compile_patterns(patterns: Optional[Dict[str, Any]], defaults: Dict[str, str],
                      what: str) -> Dict[str, "re.Pattern[str]"]:
    """Mẫu mặc định + mẫu người dùng (cùng khoá vai trò). Chuỗi → regex không phân biệt hoa thường;
    re.Pattern dùng nguyên; None hoặc "" tắt vai trò đó."""
    merged: Dict[str, Any] = dict(defaults)
    if patterns is not None:
        if not isinstance(patterns, dict):
            raise ReaderError(f"{what}: role_patterns phải là dict {{vai_trò: regex}}")
        for role, pat in patterns.items():
            if role not in defaults:
                raise ReaderError(f"{what}: vai trò lạ '{role}' (hợp lệ: {', '.join(defaults)})")
            merged[role] = pat
    out: Dict[str, re.Pattern] = {}
    for role, pat in merged.items():
        if pat is None or pat == "":
            continue
        if isinstance(pat, re.Pattern):
            out[role] = pat
            continue
        try:
            out[role] = re.compile(str(pat), re.IGNORECASE)
        except re.error as e:
            raise ReaderError(f"{what}: mẫu regex của vai trò '{role}' sai: {e}") from e
    return out


def _match_role(layer: str, compiled: Dict[str, "re.Pattern[str]"],
                priority: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    folded = _fold(layer)
    hits = [r for r in priority if r in compiled and (compiled[r].search(folded) or compiled[r].search(layer))]
    return (hits[0] if hits else None), hits


def _dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _xy(v: Any) -> Pt:
    return (float(v[0]), float(v[1]))


def _wcs(entity: Any, p: Any) -> Pt:
    """Điểm trong hệ OCS của thực thể → (x, y) WCS."""
    return _xy(entity.ocs().to_wcs(p))


def _canon_dir(dx: float, dy: float) -> Pt:
    """Vectơ đơn vị có góc trong [0°, 180°): tường/trục ngang hướng +X, đứng hướng +Y."""
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    if uy < -1e-12 or (abs(uy) <= 1e-12 and ux < 0):
        ux, uy = -ux, -uy
    return (ux, uy)


class _Unsupported(Exception):
    """Thực thể không đọc được hình học (vd POLYLINE 3D) — người gọi phải báo, không bỏ im lặng."""


def _poly_vertices(e: Any, tol: float) -> Tuple[List[Pt], List[float], bool]:
    """(đỉnh WCS, bulge từng đỉnh, kín?) của LWPOLYLINE / POLYLINE 2D. Đỉnh cuối trùng đỉnh đầu → coi là kín."""
    t = e.dxftype()
    if t == "LWPOLYLINE":
        pts = [_xy(v) for v in e.vertices_in_wcs()]
        bulges = [float(p[2]) for p in e.get_points("xyb")]
        closed = bool(e.closed)
    elif t == "POLYLINE":
        if not e.is_2d_polyline:
            raise _Unsupported("POLYLINE 3D / lưới")
        pts = [_xy(v) for v in e.points_in_wcs()]
        bulges = [float(v.dxf.get("bulge", 0.0)) for v in e.vertices]
        closed = bool(e.is_closed)
    else:
        raise _Unsupported(t)
    if len(pts) > 2 and math.hypot(*_sub(pts[0], pts[-1])) <= tol:
        pts.pop()
        bulges.pop()
        closed = True
    return pts, bulges, closed


def _axis_rect(pts: List[Pt], tol: float) -> Optional[Tuple[float, float, float, float]]:
    """(xmin, ymin, xmax, ymax) nếu vòng điểm là hình chữ nhật cạnh song song X/Y, ngược lại None."""
    if len(pts) < 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    if xmax - xmin <= tol or ymax - ymin <= tol:
        return None
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol:
            return None                                    # cạnh xiên
        on_x = abs(a[0] - xmin) <= tol or abs(a[0] - xmax) <= tol
        on_y = abs(a[1] - ymin) <= tol or abs(a[1] - ymax) <= tol
        if not (on_x or on_y):
            return None                                    # đỉnh lõm vào trong (chữ L, chữ T...)
    for cx in (xmin, xmax):
        for cy in (ymin, ymax):
            if not any(abs(p[0] - cx) <= tol and abs(p[1] - cy) <= tol for p in pts):
                return None
    return xmin, ymin, xmax, ymax


def _text_center(e: Any) -> Optional[Tuple[Pt, str]]:
    """(tâm ước lượng, nội dung) của TEXT / ATTRIB / MTEXT. Chiều rộng chữ ước lượng 0,6 × cao × số ký tự —
    chỉ dùng để tìm chữ nằm trong vòng tròn tên trục."""
    t = e.dxftype()
    if t in ("TEXT", "ATTRIB"):
        txt = e.plain_text().strip()
        h = float(e.dxf.get("height", 0.0) or 0.0)
        rot = math.radians(float(e.dxf.get("rotation", 0.0)))
        halign, valign = int(e.dxf.get("halign", 0)), int(e.dxf.get("valign", 0))
        ins = _wcs(e, e.dxf.insert)
        ap = _wcs(e, e.dxf.align_point) if e.dxf.hasattr("align_point") else ins
        w = 0.6 * h * max(len(txt), 1) * float(e.dxf.get("width", 1.0) or 1.0)
        if halign in (3, 5):                                 # ALIGNED / FIT: chữ trải giữa insert và align_point
            ref, dx, dy = ((ins[0] + ap[0]) / 2, (ins[1] + ap[1]) / 2), 0.0, h / 2
        else:
            ref = ins if (halign == 0 and valign == 0) else ap
            dx = {0: w / 2, 1: 0.0, 2: -w / 2, 4: 0.0}.get(halign, 0.0)
            dy = 0.0 if halign == 4 else {0: h / 2, 1: h / 2, 2: 0.0, 3: -h / 2}.get(valign, 0.0)
    elif t == "MTEXT":
        txt = e.plain_text().strip()
        h = float(e.dxf.get("char_height", 0.0) or 0.0)
        rot = math.radians(float(e.get_rotation()))
        lines = txt.split("\n") or [""]
        w = float(e.dxf.get("width", 0.0) or 0.0) or 0.6 * h * max(max(len(s) for s in lines), 1)
        total_h = h * (len(lines) + 0.67 * (len(lines) - 1))
        ap_code = int(e.dxf.get("attachment_point", 1))
        col, row = (ap_code - 1) % 3, (ap_code - 1) // 3
        ref = _xy(e.dxf.insert)
        dx = {0: w / 2, 1: 0.0, 2: -w / 2}[col]
        dy = {0: -total_h / 2, 1: 0.0, 2: total_h / 2}[row]
    else:
        return None
    c, s = math.cos(rot), math.sin(rot)
    return (ref[0] + dx * c - dy * s, ref[1] + dx * s + dy * c), txt


def _open_dxf(path: str, store: ProjectStore, fname: str) -> Any:
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        pass
    except (OSError, UnicodeDecodeError) as e:
        raise ReaderError(f"{fname}: không đọc được file DXF ({e.__class__.__name__}: {e})") from e
    try:
        doc, auditor = recover.readfile(path)
    except (OSError, ezdxf.DXFError) as e:
        raise ReaderError(f"{fname}: file DXF hỏng, không khôi phục được ({e})") from e
    if auditor.has_errors:
        raise ReaderError(f"{fname}: file DXF còn {len(auditor.errors)} lỗi sau khi khôi phục — mở bằng AutoCAD, "
                          f"chạy AUDIT rồi lưu lại DXF")
    _add_issue(store, SEV_WARN, "DXF_DA_KHOI_PHUC",
               f"{fname}: cấu trúc DXF lỗi, đã đọc ở chế độ khôi phục ({len(auditor.fixes)} chỗ sửa) — "
               f"kiểm tra lại bằng AutoCAD (AUDIT).")
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# ĐỀ BÀI JSON
# ─────────────────────────────────────────────────────────────────────────────

def read_spec(path: str) -> ProjectStore:
    """Đọc đề bài JSON nhập tay (ProjectStore.from_dict) và ghi nguồn SourceFile kind="json"."""
    path = _require_file(path, "read_spec")
    fname = os.path.basename(path)
    data = _load_json(path, fname)
    if not isinstance(data, dict):
        raise ReaderError(f"{fname}: đề bài phải là một đối tượng JSON (theo mẫu {SPEC_TEMPLATE_HINT})")
    try:
        store = ProjectStore.from_dict(data)
    except (StoreError, TypeError, KeyError, ValueError) as e:
        raise ReaderError(f"{fname}: đề bài sai cấu trúc — {e}") from e
    store.sources.append(SourceFile(name=fname, kind="json", sha256=_sha256(path), used_for="du_lieu",
                                    note=str(data.get("nguon_mac_dinh", ""))[:300]))
    return store


# ─────────────────────────────────────────────────────────────────────────────
# ĐỌC DXF
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _Seg:
    """Một đoạn thẳng trên layer tường (LINE hoặc cạnh đa tuyến)."""
    idx: int
    handle: str
    label: str
    layer: str
    p1: Pt
    p2: Pt
    fam: int = -1                  # họ phương song song
    s0: float = 0.0                # khoảng chiếu dọc phương họ
    s1: float = 0.0
    o: float = 0.0                 # toạ độ theo pháp tuyến họ
    paired: float = 0.0            # chiều dài đã ghép cặp
    cap: bool = False              # nét bịt đầu tường


@dataclass
class _Piece:
    """Một đoạn tường: tim song song họ `fam`, toạ độ pháp tuyến o, dày t, trải dọc phương từ a tới b."""
    fam: int
    o: float
    t: float
    a: float
    b: float
    segs: Set[int]
    notes: List[str] = field(default_factory=list)
    start: Pt = (0.0, 0.0)
    end: Pt = (0.0, 0.0)


class _DxfReader:
    def __init__(self, doc: Any, store: ProjectStore, compiled: Dict[str, "re.Pattern[str]"], tol: float,
                 fname: str):
        self.doc, self.store, self.compiled, self.tol, self.fname = doc, store, compiled, tol, fname
        self.entities = list(doc.modelspace())
        self.used: Set[str] = set()
        self.layer_roles: Dict[str, Optional[str]] = {}
        self.by_role: Dict[str, List[Any]] = {r: [] for r in DXF_ROLE_PRIORITY}
        self.fams: List[Tuple[Pt, Pt]] = []      # (u, n) của từng họ phương tường

    # ── chung ────────────────────────────────────────────────────────────────

    @staticmethod
    def h(e: Any) -> str:
        return str(e.dxf.handle)

    def use(self, e: Any) -> None:
        self.used.add(self.h(e))

    def issue(self, severity: str, code: str, message: str, eids: Iterable[str] = (),
              where: Optional[Pt] = None) -> None:
        _add_issue(self.store, severity, code, message, eids, where)

    def run(self) -> None:
        self._classify()
        self._check_units()
        dims = self._read_dimensions()
        self._read_axes(dims)
        self._read_columns()
        inserts = self._opening_inserts()
        self._read_walls([p for _, _, p in inserts])
        self._read_openings(inserts)
        self._report_leftovers()

    def _classify(self) -> None:
        for e in self.entities:
            layer = str(e.dxf.get("layer", "0"))
            if layer not in self.layer_roles:
                role, hits = _match_role(layer, self.compiled, DXF_ROLE_PRIORITY)
                self.layer_roles[layer] = role
                if len(hits) > 1:
                    self.issue(SEV_WARN, "LAYER_NHIEU_VAI_TRO",
                               f"Layer '{layer}' khớp nhiều mẫu vai trò ({', '.join(hits)}) — đọc theo vai trò "
                               f"'{role}' (thứ tự ưu tiên {', '.join(DXF_ROLE_PRIORITY)}); nếu sai, truyền role_patterns.")
            role = self.layer_roles[layer]
            if role:
                self.by_role[role].append(e)

    def _check_units(self) -> None:
        code = int(self.doc.header.get("$INSUNITS", 0) or 0)
        if code == 4:
            return
        if code == 0:
            self.issue(SEV_WARN, "DON_VI_KHONG_KHAI_BAO",
                       f"{self.fname}: $INSUNITS = 0 (không khai báo đơn vị) — giả định mm; kiểm tra lại một kích "
                       f"thước đã biết trước khi dùng số liệu.")
            return
        try:
            name = dxf_units.unit_name(code)
        except (KeyError, ValueError, IndexError):
            name = "không rõ"
        self.issue(SEV_WARN, "DON_VI_KHAC_MM",
                   f"{self.fname}: $INSUNITS = {code} ({name}), không phải mm — toạ độ đọc nguyên giá trị, KHÔNG quy "
                   f"đổi; chiều dày tường {_fmt(WALL_MIN_THICKNESS)}–{_fmt(WALL_MAX_THICKNESS)} mm và mọi kích thước "
                   f"sẽ hiểu sai. Chuyển bản vẽ sang mm trước khi đọc.")

    # ── DIMENSION ────────────────────────────────────────────────────────────

    def _style_dimlfac(self, name: str) -> float:
        if self.doc.dimstyles.has_entry(name):
            return float(self.doc.dimstyles.get(name).dxf.get("dimlfac", 1.0) or 1.0)
        return 1.0

    def _read_dimensions(self) -> List[Tuple[Any, MeasuredDim, int]]:
        out: List[Tuple[Any, MeasuredDim, int]] = []
        lfac: Dict[Tuple[str, float, str], List[str]] = {}
        for e in self.entities:
            if e.dxftype() != "DIMENSION":
                continue
            self.use(e)
            h, layer = self.h(e), e.dxf.get("layer", "0")
            p1, p2 = _xy(e.dxf.defpoint2), _xy(e.dxf.defpoint3)
            dimtype = int(e.dimtype)
            if dimtype == 0:
                angle = float(e.dxf.get("angle", 0.0))
            elif dimtype == 1:
                angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
            else:
                angle = 0.0
            try:
                raw_m = e.get_measurement()
                m = float(raw_m) if isinstance(raw_m, (int, float)) else None
            except (TypeError, ValueError, ZeroDivisionError, AttributeError):
                m = None
            raw = str(e.dxf.get("text", "") or "")
            text = "" if raw in ("", "<>") else raw
            md = MeasuredDim(id=f"DIM-{h}", p1=[_r(p1[0]), _r(p1[1])], p2=[_r(p2[0]), _r(p2[1])],
                             angle=_r(angle % 360.0), measurement=None if m is None else _r(m), text=text,
                             prov=Provenance(SRC_DXF, f"{self.fname}: DIMENSION #{h} layer {layer}"))
            self.store.measured_dims.append(md)
            out.append((e, md, dimtype))
            if text:
                differs, shown = _override_differs(text, m)
                if differs:
                    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                    self.issue(SEV_DOUBT, "DIM_GHI_DE",
                               f"Kích thước #{h}: chữ ghi đè '{shown}' khác số đo hình học "
                               f"{'không đo được' if m is None else _fmt(m)} — số hiển thị sửa tay là cờ đỏ "
                               f"(TextOverride ≠ Measurement); đối chiếu bản vẽ đã duyệt.", [md.id], mid)
            style = str(e.dxf.get("dimstyle", "Standard"))
            style_val = self._style_dimlfac(style)
            try:
                eff = float(e.override().get("dimlfac", style_val))
            except (TypeError, ValueError, AttributeError, ezdxf.DXFError):
                eff = style_val
            if abs(eff - 1.0) > 1e-9:
                src = "ghi đè riêng từng kích thước" if abs(eff - style_val) > 1e-9 else f"dimstyle '{style}'"
                lfac.setdefault((style, eff, src), []).append(h)
        for (style, eff, src), handles in lfac.items():
            eids, extra = _capped(handles)
            self.issue(SEV_WARN, "DIMLFAC_KHAC_1",
                       f"{len(handles)} kích thước dùng DIMLFAC = {_fmt(eff)} ({src}) — số hiển thị bị co giãn so "
                       f"với hình học (lỗi co giãn kích thước); đặt DIMLFAC = 1.{extra}", eids)
        used_styles = {str(e.dxf.get("dimstyle", "Standard")).lower() for e, _, _ in out}
        idle = [f"{ds.dxf.name} ({_fmt(float(ds.dxf.get('dimlfac', 1.0) or 1.0))})" for ds in self.doc.dimstyles
                if str(ds.dxf.name).lower() not in used_styles
                and abs(float(ds.dxf.get("dimlfac", 1.0) or 1.0) - 1.0) > 1e-9]
        if idle:
            self.issue(SEV_WARN, "DIMLFAC_KHAC_1",
                       f"{len(idle)} kiểu kích thước có DIMLFAC ≠ 1 nhưng chưa kích thước nào trong model space dùng: "
                       f"{', '.join(idle)} — kích thước vẽ thêm bằng kiểu này sẽ bị co giãn.")
        return out

    # ── TRỤC ─────────────────────────────────────────────────────────────────

    def _read_axes(self, dims: List[Tuple[Any, MeasuredDim, int]]) -> None:
        tol = self.tol
        lines: Dict[str, List[Dict[str, Any]]] = {"V": [], "H": []}
        bad: List[str] = []
        skewed: List[str] = []
        layers: Set[str] = set()
        for e in self.by_role["truc"]:
            if e.dxftype() != "LINE":
                continue
            self.use(e)
            h = self.h(e)
            p1, p2 = _xy(e.dxf.start), _xy(e.dxf.end)
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            L = math.hypot(dx, dy)
            if L <= tol:
                bad.append(f"#{h} (dài 0)")
                continue
            dev_v = math.degrees(math.asin(min(1.0, abs(dx) / L)))
            dev_h = math.degrees(math.asin(min(1.0, abs(dy) / L)))
            if dev_v <= AXIS_ANGLE_TOL_DEG:
                o, coord, lo, hi, skew = "V", (p1[0] + p2[0]) / 2, min(p1[1], p2[1]), max(p1[1], p2[1]), abs(dx)
            elif dev_h <= AXIS_ANGLE_TOL_DEG:
                o, coord, lo, hi, skew = "H", (p1[1] + p2[1]) / 2, min(p1[0], p2[0]), max(p1[0], p2[0]), abs(dy)
            else:
                bad.append(f"#{h} (xiên {math.degrees(math.atan2(dy, dx)) % 180.0:.2f}°)")
                continue
            if skew > tol:
                skewed.append(f"#{h} (hai đầu lệch {_fmt(skew)} mm)")
            layers.add(str(e.dxf.get("layer", "0")))
            lines[o].append({"h": h, "coord": coord, "lo": lo, "hi": hi})
        if bad:
            self.issue(SEV_DOUBT, "TRUC_KHONG_DUNG_DUOC",
                       f"{len(bad)} đường trên layer trục không thẳng đứng / nằm ngang (trục xiên chưa hỗ trợ) — "
                       f"không đọc thành trục: {', '.join(bad)}", [b.split()[0][1:] for b in bad])
        if skewed:
            self.issue(SEV_DOUBT, "TRUC_LECH_GOC",
                       f"{len(skewed)} đường trục hơi lệch phương (≤ {AXIS_ANGLE_TOL_DEG}°), toạ độ lấy trung bình hai "
                       f"đầu: {', '.join(skewed)}", [s.split()[0][1:] for s in skewed])

        axes: Dict[str, List[Dict[str, Any]]] = {}
        for o in ("V", "H"):
            clusters: List[List[Dict[str, Any]]] = []
            for d in sorted(lines[o], key=lambda d: (d["coord"], d["h"])):
                if clusters and d["coord"] - clusters[-1][0]["coord"] <= tol:
                    clusters[-1].append(d)
                else:
                    clusters.append([d])
            axes[o] = [{"o": o, "coord": sum(d["coord"] for d in c) / len(c), "lo": min(d["lo"] for d in c),
                        "hi": max(d["hi"] for d in c), "handles": [d["h"] for d in c]} for c in clusters]

        bubbles = self._axis_bubbles()
        texts = []
        for e in self.entities:
            if e.dxftype() in ("TEXT", "MTEXT"):
                info = _text_center(e)
                if info and info[1]:
                    texts.append({"c": info[0], "text": info[1], "h": self.h(e), "e": e})

        # tên trục
        seen: Set[str] = set()
        for o in ("V", "H"):
            for ax in axes[o]:
                names = []
                ends = ([((ax["coord"], ax["lo"]), (0.0, -1.0)), ((ax["coord"], ax["hi"]), (0.0, 1.0))] if o == "V"
                        else [((ax["lo"], ax["coord"]), (-1.0, 0.0)), ((ax["hi"], ax["coord"]), (1.0, 0.0))])
                for end, d in ends:
                    b = self._bubble_at(bubbles, end, d)
                    if b is None:
                        continue
                    self.used.add(b["h"])                     # vòng tròn đầu trục đã dùng (có tên hay không)
                    name = self._bubble_name(b, texts)
                    if name:
                        if b.get("text_h"):
                            self.used.add(b["text_h"])
                        names.append((name, b))
                name = None
                distinct = list(dict.fromkeys(n for n, _ in names))
                where = ((ax["coord"], (ax["lo"] + ax["hi"]) / 2) if o == "V" else ((ax["lo"] + ax["hi"]) / 2, ax["coord"]))
                if distinct:
                    name = distinct[0]
                    if len(distinct) > 1:
                        self.issue(SEV_DOUBT, "TRUC_HAI_TEN",
                                   f"Trục {o} (LINE #{', #'.join(ax['handles'])}) có hai tên khác nhau ở hai đầu "
                                   f"({', '.join(distinct)}) — dùng '{name}' (đầu dưới/trái); kiểm tra bản vẽ.",
                                   ax["handles"], where)
                if name is not None and not re.fullmatch(r"[^/@\s]+", name):
                    self.issue(SEV_DOUBT, "TRUC_TEN_KHONG_HOP_LE",
                               f"Tên trục '{name}' (LINE #{', #'.join(ax['handles'])}) có khoảng trắng hoặc ký tự '/', "
                               f"'@' — không dùng được trong toạ độ giao trục; coi như chưa có tên.", ax["handles"], where)
                    name = None
                if name is not None and name in seen:
                    self.issue(SEV_DOUBT, "TRUC_TRUNG_TEN",
                               f"Tên trục '{name}' lặp lại (LINE #{', #'.join(ax['handles'])}) — trục này coi như chưa "
                               f"có tên.", ax["handles"], where)
                    name = None
                if name is not None:
                    seen.add(name)
                ax["name"], ax["where"] = name, where
        k = 1
        for o in ("V", "H"):
            for ax in axes[o]:
                if ax["name"] is not None:
                    continue
                while f"?{k}" in seen:
                    k += 1
                ax["name"] = f"?{k}"
                seen.add(ax["name"])
                coord_name = "x" if o == "V" else "y"
                self.issue(SEV_DOUBT, "TRUC_CHUA_CO_TEN",
                           f"Trục {o} tại {coord_name} = {_fmt(ax['coord'])} (LINE #{', #'.join(ax['handles'])}) không "
                           f"đọc được tên trong vòng tròn đầu trục — đặt tên tạm '{ax['name']}'; cần nhập tên đúng "
                           f"theo bản vẽ.", ax["handles"], ax["where"])

        for o in ("V", "H"):
            lst = axes[o]
            if not lst:
                self.store.axes[o] = AxisGroup(orientation=o, names=[], spans=[],
                                               prov=Provenance(SRC_DXF, f"{self.fname}: không có trục {o}"))
                pat = self.compiled["truc"].pattern if "truc" in self.compiled else "(tắt)"
                self.issue(SEV_WARN, "KHONG_CO_TRUC",
                           f"{self.fname}: không tìm thấy trục {'đứng (V)' if o == 'V' else 'ngang (H)'} trên layer khớp "
                           f"mẫu '{pat}' — nhóm trục {o} rỗng; cột không gán được giao trục.")
                continue
            coords = [_r(a["coord"]) for a in lst]
            spans: List[Optional[float]] = [_r(coords[i + 1] - coords[i]) for i in range(len(coords) - 1)]
            span_prov: List[Optional[Provenance]] = [
                Provenance(SRC_DXF, f"{self.fname}: khoảng cách LINE #{lst[i]['handles'][0]} → "
                                    f"LINE #{lst[i + 1]['handles'][0]} (đo hình học)") for i in range(len(spans))]
            grp = AxisGroup(orientation=o, names=[a["name"] for a in lst], spans=spans, origin=coords[0],
                            prov=Provenance(SRC_DXF, f"{self.fname}: {len(lst)} đường trục {o} trên layer "
                                                     f"{', '.join(sorted(layers))}"),
                            span_prov=span_prov)
            if len(lst) >= 2:
                self._match_overall(grp, coords[0], coords[-1], dims)
            self.store.axes[o] = grp

    def _axis_bubbles(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for e in self.by_role["truc"]:
            t = e.dxftype()
            if t == "CIRCLE":
                out.append({"c": _wcs(e, e.dxf.center), "r": float(e.dxf.radius), "name": None, "h": self.h(e)})
            elif t == "INSERT":
                name = None
                heights = []
                for a in e.attribs:
                    heights.append(float(a.dxf.get("height", 0.0) or 0.0))
                    txt = a.plain_text().strip()
                    if txt and name is None:
                        name = txt
                center, radius = _wcs(e, e.dxf.insert), max(heights + [self.tol])
                try:
                    virtual = list(e.virtual_entities())
                except (ezdxf.DXFError, ValueError, TypeError, ZeroDivisionError):
                    virtual = []
                for v in virtual:
                    if v.dxftype() == "CIRCLE":
                        center, radius = _wcs(v, v.dxf.center), float(v.dxf.radius)
                        break
                if name is None:
                    for v in virtual:
                        info = _text_center(v) if v.dxftype() in ("TEXT", "MTEXT") else None
                        if info and info[1]:
                            name = info[1]
                            break
                out.append({"c": center, "r": radius, "name": name, "h": self.h(e)})
        return out

    def _bubble_at(self, bubbles: List[Dict[str, Any]], end: Pt, d: Pt) -> Optional[Dict[str, Any]]:
        """Vòng tròn tên trục ở đầu `end` (d = hướng ra ngoài): tâm nằm trên phương trục, chồng lên đầu trục hoặc
        cách đầu trục không quá một bán kính."""
        n = (-d[1], d[0])
        best = None
        for b in bubbles:
            v = _sub(b["c"], end)
            s, perp, r = _dot(v, d), abs(_dot(v, n)), b["r"]
            if perp <= max(self.tol, 0.1 * r) and -r - self.tol <= s <= 2 * r + self.tol:
                key = (math.hypot(*v), b["h"])
                if best is None or key < best[0]:
                    best = (key, b)
        return None if best is None else best[1]

    def _bubble_name(self, b: Dict[str, Any], texts: List[Dict[str, Any]]) -> Optional[str]:
        if b.get("name"):
            return b["name"]
        r = b["r"]
        best = None
        for t in texts:
            dist = math.hypot(*_sub(t["c"], b["c"]))
            if dist <= 1.5 * r + self.tol:                  # trong vòng tròn hoặc ngay cạnh
                key = (0 if dist <= r + self.tol else 1, dist, t["h"])
                if best is None or key < best[0]:
                    best = (key, t)
        if best is None:
            return None
        b["text_h"] = best[1]["h"]
        return best[1]["text"]

    def _match_overall(self, grp: AxisGroup, first: float, last: float,
                       dims: List[Tuple[Any, MeasuredDim, int]]) -> None:
        """DIMENSION đo đúng từ trục đầu tới trục cuối → kích thước tổng của nhóm trục."""
        i = 0 if grp.orientation == "V" else 1
        want = last - first
        cos_tol = math.cos(math.radians(AXIS_ANGLE_TOL_DEG))
        for e, md, dimtype in dims:
            if dimtype not in (0, 1) or md.measurement is None:
                continue
            a = math.radians(md.angle)
            along = abs(math.cos(a)) if grp.orientation == "V" else abs(math.sin(a))
            if along < cos_tol:
                continue
            ends = sorted((md.p1[i], md.p2[i]))
            if (abs(ends[0] - first) <= self.tol and abs(ends[1] - last) <= self.tol
                    and abs(md.measurement - want) <= self.tol):
                grp.overall = _r(md.measurement)
                grp.overall_prov = Provenance(SRC_DXF, f"{self.fname}: DIMENSION #{self.h(e)} đo từ trục "
                                                       f"{grp.names[0]} tới {grp.names[-1]}")
                return

    # ── CỘT ──────────────────────────────────────────────────────────────────

    def _read_columns(self) -> None:
        tol = self.tol
        gv, gh = self.store.axes["V"], self.store.axes["H"]
        xs = list(zip(gv.names, gv.offsets()))
        ys = list(zip(gh.names, gh.offsets()))
        ids: Set[str] = set()
        for e in self.by_role["cot"]:
            t = e.dxftype()
            if t not in ("LWPOLYLINE", "POLYLINE"):
                continue
            self.use(e)
            h, layer = self.h(e), e.dxf.get("layer", "0")
            try:
                pts, bulges, closed = _poly_vertices(e, tol)
            except _Unsupported as why:
                self.issue(SEV_DOUBT, "COT_KHONG_DOC_DUOC",
                           f"{t} #{h} trên layer cột: {why} — không đọc được thành cột.", [h])
                continue
            center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None
            if not closed:
                self.issue(SEV_DOUBT, "COT_KHONG_KHEP_KIN",
                           f"Đường bao #{h} trên layer cột không khép kín — chưa đọc thành cột; kiểm tra bản vẽ.",
                           [h], center)
                continue
            bulged = any(abs(b) > 1e-9 for b in bulges)
            rect = None if bulged else _axis_rect(pts, tol)
            if rect is None:
                self.issue(SEV_DOUBT, "COT_KHONG_PHAI_CHU_NHAT",
                           f"Đường bao #{h} trên layer cột không phải hình chữ nhật thẳng trục X/Y ({len(pts)} đỉnh"
                           f"{', có cung' if bulged else ''}) — chưa đọc thành cột; kiểm tra hoặc nhập tay.",
                           [h], center)
                continue
            xmin, ymin, xmax, ymax = rect
            b, hh = xmax - xmin, ymax - ymin
            cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
            if not xs or not ys:
                self.issue(SEV_DOUBT, "COT_CHUA_GAN_TRUC",
                           f"Cột #{h} {_fmt(b)}×{_fmt(hh)} tâm ({_fmt(cx)}, {_fmt(cy)}): bản vẽ thiếu nhóm trục "
                           f"{'V' if not xs else 'H'} nên chưa gán được giao trục — chưa đưa vào dữ liệu.",
                           [h], (cx, cy))
                continue
            v, x = min(xs, key=lambda it: abs(cx - it[1]))
            hn, y = min(ys, key=lambda it: abs(cy - it[1]))
            dx, dy = _r(cx - x), _r(cy - y)
            cid = base = f"C-{v}{hn}"
            k = 2
            while cid in ids:
                cid, k = f"{base}-{k}", k + 1
            ids.add(cid)
            self.store.columns.append(Column(
                id=cid, axis_v=v, axis_h=hn, b=_r(b), h=_r(hh), dx=dx, dy=dy, mark="",
                prov=Provenance(SRC_DXF, f"{self.fname}: {t} #{h} layer {layer} — {_fmt(b)}×{_fmt(hh)}, tâm "
                                         f"({_fmt(cx)}, {_fmt(cy)}), lệch giao trục {v}/{hn} ({_fmt(dx)}, {_fmt(dy)})")))
            if abs(dx) > b / 2 + tol or abs(dy) > hh / 2 + tol:
                self.issue(SEV_DOUBT, "COT_XA_GIAO_TRUC",
                           f"Cột {cid} (#{h}) không chứa giao trục gần nhất {v}/{hn} (lệch {_fmt(dx)}, {_fmt(dy)} mm) "
                           f"— kiểm tra vị trí cột hoặc lưới trục.", [h], (cx, cy))

    # ── CỬA (điểm chèn) ──────────────────────────────────────────────────────

    def _opening_inserts(self) -> List[Tuple[Any, str, Pt]]:
        out = []
        for e in self.entities:
            if e.dxftype() != "INSERT":
                continue
            role = self.layer_roles.get(str(e.dxf.get("layer", "0")))
            if role in ("cua_di", "cua_so"):
                out.append((e, role, _wcs(e, e.dxf.insert)))
        return out

    # ── TƯỜNG ────────────────────────────────────────────────────────────────

    def _read_walls(self, opening_points: List[Pt]) -> None:
        tol = self.tol
        segs: List[_Seg] = []
        degenerate: List[Tuple[str, str]] = []
        curved: List[Tuple[str, str]] = []
        layers: Set[str] = set()
        for e in self.by_role["tuong"]:
            t, h, layer = e.dxftype(), self.h(e), str(e.dxf.get("layer", "0"))
            if t == "LINE":
                self.use(e)
                p1, p2 = _xy(e.dxf.start), _xy(e.dxf.end)
                if math.hypot(*_sub(p2, p1)) <= tol:
                    degenerate.append((h, f"LINE #{h} (dài 0)"))
                    continue
                segs.append(_Seg(len(segs), h, f"LINE #{h}", layer, p1, p2))
                layers.add(layer)
            elif t in ("LWPOLYLINE", "POLYLINE"):
                try:
                    pts, bulges, closed = _poly_vertices(e, tol)
                except _Unsupported:
                    continue                                  # để lại cho báo cáo thực thể chưa xử lý
                self.use(e)
                n = len(pts)
                for i in range(n if closed else n - 1):
                    a, b = pts[i], pts[(i + 1) % n]
                    if math.hypot(*_sub(b, a)) <= tol:
                        continue                              # đỉnh trùng nhau, không phải một cạnh
                    if abs(bulges[i]) > 1e-9:
                        curved.append((h, f"{t} #{h} cạnh {i + 1}"))
                        continue
                    segs.append(_Seg(len(segs), h, f"{t} #{h} cạnh {i + 1}", layer, a, b))
                    layers.add(layer)
        pieces = self._pair_faces(segs)
        self._mark_caps(segs, pieces)
        pieces = self._merge_collinear(pieces, opening_points)
        self._snap_ends(pieces)

        pieces.sort(key=lambda p: (round(math.degrees(math.atan2(self.fams[p.fam][0][1], self.fams[p.fam][0][0])), 3),
                                   round(p.o, 3), round(p.a, 3)))
        for i, p in enumerate(pieces, start=1):
            labels = [segs[k].label for k in sorted(p.segs)]
            ref = (f"{self.fname}: layer {', '.join(sorted({segs[k].layer for k in p.segs}))}; nét tường "
                   f"{', '.join(labels)}; tim = đường giữa hai mặt, dày = khoảng cách")
            if p.notes:
                ref += "; " + "; ".join(dict.fromkeys(p.notes))
            self.store.walls.append(Wall(id=f"W{i}", start=[_r(p.start[0]), _r(p.start[1])],
                                         end=[_r(p.end[0]), _r(p.end[1])], thickness=_r(p.t), kind="xay",
                                         prov=Provenance(SRC_DXF, ref)))
        if pieces:
            self.issue(SEV_WARN, "TUONG_CHUA_RO_VAT_LIEU",
                       f"{len(pieces)} tường đọc từ DXF gán loại 'xay' (gạch) mặc định vì DXF không ghi vật liệu — "
                       f"sửa kind = 'btct' cho tường bê tông trước khi hatch.", [f"W{i}" for i in range(1, len(pieces) + 1)])
        unpaired = [(s.handle, s.label) for s in segs if s.paired <= 0 and not s.cap] + degenerate
        if unpaired:
            eids, extra = _capped([h for h, _ in unpaired])
            self.issue(SEV_DOUBT, "TUONG_CHUA_GHEP_CAP",
                       f"{len(unpaired)} đường trên layer tường không ghép được cặp song song (cách nhau "
                       f"{_fmt(WALL_MIN_THICKNESS)}–{_fmt(WALL_MAX_THICKNESS)} mm, có đoạn chồng nhau) — chưa đọc "
                       f"thành tường: {', '.join(lb for _, lb in unpaired)}.{extra}", eids)
        if curved:
            eids, extra = _capped([h for h, _ in curved])
            self.issue(SEV_DOUBT, "TUONG_CONG_CHUA_HO_TRO",
                       f"{len(curved)} cạnh cong trên layer tường — tường cong chưa hỗ trợ, không đọc: "
                       f"{', '.join(lb for _, lb in curved)}.{extra}", eids)

    def _pair_faces(self, segs: List[_Seg]) -> List[_Piece]:
        """Ghép mặt tường theo từng khoảng cơ sở dọc mỗi họ phương: trong khoảng đó, các đường phủ kín được xếp theo
        toạ độ pháp tuyến rồi chọn các cặp LIỀN KỀ (không xen nhau) cho nhiều cặp nhất, hoà thì ưu tiên hai đường
        chồng nhau dài nhất rồi tổng khoảng cách nhỏ nhất."""
        tol = self.tol
        for s in segs:
            d = _sub(s.p2, s.p1)
            for k, (u, _n) in enumerate(self.fams):
                if abs(_cross(u, d)) <= tol:
                    s.fam = k
                    break
            else:
                u = _canon_dir(d[0], d[1])
                self.fams.append((u, (-u[1], u[0])))
                s.fam = len(self.fams) - 1
            u, n = self.fams[s.fam]
            a, b = _dot(s.p1, u), _dot(s.p2, u)
            s.s0, s.s1 = min(a, b), max(a, b)
            s.o = (_dot(s.p1, n) + _dot(s.p2, n)) / 2

        pair_iv: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
        members: Dict[Tuple[int, int], Set[int]] = {}
        for k in range(len(self.fams)):
            fs = sorted((s for s in segs if s.fam == k), key=lambda s: (s.s0, s.idx))
            bps: List[float] = []
            for v in sorted(x for s in fs for x in (s.s0, s.s1)):
                if not bps or v - bps[-1] > tol:
                    bps.append(v)
            nxt, active = 0, []                               # quét dọc phương: các đường đang phủ khoảng [a, b]
            for a, b in zip(bps, bps[1:]):
                while nxt < len(fs) and fs[nxt].s0 <= a + tol:
                    active.append(fs[nxt])
                    nxt += 1
                active = [s for s in active if s.s1 > a + tol]
                # các đường trùng toạ độ pháp tuyến (nét vẽ chồng, nét bịt trùng mặt tường) gộp thành một "mặt"
                slots: List[List[_Seg]] = []
                for s in sorted((s for s in active if s.s1 >= b - tol), key=lambda s: (s.o, s.idx)):
                    if slots and s.o - slots[-1][0].o <= tol:
                        slots[-1].append(s)
                    else:
                        slots.append([s])
                for A, B in self._best_pairing(slots):
                    key = (A[0].idx, B[0].idx)
                    pair_iv.setdefault(key, []).append((a, b))
                    members.setdefault(key, set()).update(s.idx for s in A + B)
                    for s in A + B:
                        s.paired += b - a

        pieces: List[_Piece] = []
        for (ia, ib), ivs in sorted(pair_iv.items()):
            A, B = segs[ia], segs[ib]
            ivs.sort()
            cur = list(ivs[0])
            for a, b in ivs[1:] + [(math.inf, math.inf)]:
                if a - cur[1] <= tol:
                    cur[1] = max(cur[1], b)
                    continue
                used = {i for i in members[(ia, ib)] if segs[i].s0 <= cur[1] + tol and segs[i].s1 >= cur[0] - tol}
                pieces.append(_Piece(fam=A.fam, o=(A.o + B.o) / 2, t=abs(B.o - A.o), a=cur[0], b=cur[1],
                                     segs=used | {ia, ib}))
                cur = [a, b]
        return pieces

    def _best_pairing(self, slots: List[List[_Seg]]) -> Tuple[Tuple[List[_Seg], List[_Seg]], ...]:
        """Chọn các cặp mặt liền kề (quy hoạch động trên dãy mặt đã sắp theo toạ độ pháp tuyến)."""
        tol = self.tol
        empty: Tuple[int, float, float, Tuple] = (0, 0.0, 0.0, ())
        best = [empty, empty]
        for i in range(2, len(slots) + 1):
            cand = best[i - 1]
            A, B = slots[i - 2], slots[i - 1]
            d = B[0].o - A[0].o
            if WALL_MIN_THICKNESS - tol <= d <= WALL_MAX_THICKNESS + tol:
                overlap = max(max(0.0, min(x.s1, y.s1) - max(x.s0, y.s0)) for x in A for y in B)
                prev = best[i - 2]
                c2 = (prev[0] + 1, prev[1] + overlap, prev[2] - d, prev[3] + ((A, B),))
                if c2[:3] > cand[:3]:
                    cand = c2
            best.append(cand)
        return best[len(slots)][3] if len(slots) >= 2 else ()

    def _mark_caps(self, segs: List[_Seg], pieces: List[_Piece]) -> None:
        """Nét bịt đầu tường: đoạn vuông góc, dài bằng chiều dày, trung điểm nằm ở đầu tim một đoạn tường."""
        tol = self.tol
        for s in segs:
            if s.paired > 0:
                continue
            d = _sub(s.p2, s.p1)
            L = math.hypot(*d)
            mid = ((s.p1[0] + s.p2[0]) / 2, (s.p1[1] + s.p2[1]) / 2)
            for p in pieces:
                u, n = self.fams[p.fam]
                if abs(_dot(d, u)) > tol or abs(L - p.t) > tol:
                    continue
                sm, om = _dot(mid, u), _dot(mid, n)
                if abs(om - p.o) <= tol and (abs(sm - p.a) <= tol or abs(sm - p.b) <= tol):
                    s.cap = True
                    p.segs.add(s.idx)
                    break

    def _merge_collinear(self, pieces: List[_Piece], opening_points: List[Pt]) -> List[_Piece]:
        """Nối các đoạn tường thẳng hàng, cùng chiều dày khi khe giữa chúng ≤ tol, có điểm chèn cửa, hoặc có đầu
        một tường khác (chỗ giao chữ T / chữ thập — mặt tường bị ngắt ở đó)."""
        tol = self.tol
        groups: List[List[_Piece]] = []
        for p in sorted(pieces, key=lambda p: (p.fam, p.o, p.t, p.a)):
            for g in groups:
                q = g[0]
                if q.fam == p.fam and abs(q.o - p.o) <= tol and abs(q.t - p.t) <= tol:
                    g.append(p)
                    break
            else:
                groups.append([p])
        ends: List[Tuple[Pt, int]] = []
        for p in pieces:
            u, n = self.fams[p.fam]
            for s in (p.a, p.b):
                ends.append(((s * u[0] + p.o * n[0], s * u[1] + p.o * n[1]), p.fam))

        def gap_hit(cur: _Piece, nxt: _Piece) -> Optional[str]:
            u, n = self.fams[cur.fam]
            lo, hi = cur.b - tol, nxt.a + tol
            half = max(cur.t, nxt.t) / 2 + tol
            for pt, fam in ends:
                if fam != cur.fam and lo <= _dot(pt, u) <= hi and abs(_dot(pt, n) - cur.o) <= half:
                    return "nối qua chỗ giao tường"
            for pt in opening_points:
                if lo <= _dot(pt, u) <= hi and abs(_dot(pt, n) - cur.o) <= half:
                    return "nối qua ô cửa"
            return None

        merged: List[_Piece] = []
        for g in groups:
            g.sort(key=lambda p: (p.a, p.b))
            cur = g[0]
            for nxt in g[1:]:
                why = "" if nxt.a - cur.b <= tol else gap_hit(cur, nxt)
                if why is None:
                    merged.append(cur)
                    cur = nxt
                    continue
                cur.b = max(cur.b, nxt.b)
                cur.segs |= nxt.segs
                cur.notes += nxt.notes + ([why] if why else [])
            merged.append(cur)
        for p in merged:
            u, n = self.fams[p.fam]
            p.start = (p.a * u[0] + p.o * n[0], p.a * u[1] + p.o * n[1])
            p.end = (p.b * u[0] + p.o * n[0], p.b * u[1] + p.o * n[1])
        return merged

    def _snap_ends(self, pieces: List[_Piece]) -> None:
        """Đầu tường chạm mặt một tường khác (khe ≤ tol) hoặc ăn vào thân tường đó (vẽ chồng ở góc, lấn ≤ nửa chiều
        dày tường kia) → đưa về giao điểm hai tim, để góc / ngã ba khép kín khi vẽ (geom kéo dài đầu tường)."""
        tol = self.tol
        snaps: Dict[Tuple[int, str], Pt] = {}
        for i, p in enumerate(pieces):
            u = self.fams[p.fam][0]
            for which, P, sign in (("start", p.start, -1.0), ("end", p.end, 1.0)):
                best = None
                for j, q in enumerate(pieces):
                    if j == i or q.fam == p.fam:
                        continue
                    uq = self.fams[q.fam][0]
                    den = _cross(u, uq)
                    if abs(den) < 1e-9:
                        continue
                    t = _cross(_sub(q.start, P), uq) / den
                    X = (P[0] + t * u[0], P[1] + t * u[1])
                    s = t * sign                               # > 0: giao điểm nằm ngoài đầu tường
                    if not (-(q.t / 2 + tol) <= s <= q.t / 2 + tol):
                        continue                               # < 0: đầu tường ăn vào thân tường kia (vẽ chồng ở góc)
                    w = _dot(_sub(X, q.start), uq)
                    ext = p.t / 2 + tol
                    if not (-ext <= w <= (q.b - q.a) + ext):
                        continue
                    key = (abs(s), j)
                    if best is None or key < best[0]:
                        best = (key, X)
                if best is not None:
                    snaps[(i, which)] = best[1]
        for i, p in enumerate(pieces):
            new_start, new_end = snaps.get((i, "start"), p.start), snaps.get((i, "end"), p.end)
            if math.hypot(*_sub(new_end, new_start)) <= tol:
                p.notes.append("không đưa đầu tường về giao tim vì tường sẽ dài 0 (nằm gọn trong tường khác)")
                continue
            for which, old, X in (("start", p.start, new_start), ("end", p.end, new_end)):
                if math.hypot(*_sub(X, old)) <= 1e-9:
                    continue
                p.notes.append(f"điểm {'đầu' if which == 'start' else 'cuối'} đưa về giao tim tường "
                               f"({_fmt(X[0])}, {_fmt(X[1])})")
            p.start, p.end = new_start, new_end

    # ── CỬA ──────────────────────────────────────────────────────────────────

    def _read_openings(self, inserts: List[Tuple[Any, str, Pt]]) -> None:
        tol = self.tol
        counters = {"cua_di": 0, "cua_so": 0}
        used_ids = {o.id for o in self.store.openings}
        for e, kind, P in inserts:
            self.use(e)
            h, layer, bname = self.h(e), e.dxf.get("layer", "0"), e.dxf.get("name", "")
            label = "Cửa đi" if kind == "cua_di" else "Cửa sổ"
            cands = []
            for k, w in enumerate(self.store.walls):
                d = dist_point_segment(P, tuple(w.start), tuple(w.end))
                if d <= float(w.thickness) / 2 + tol:
                    cands.append((d, k, w))
            if not cands:
                self.issue(SEV_DOUBT, "CUA_CHUA_GAN_TUONG",
                           f"{label} block '{bname}' #{h} tại ({_fmt(P[0])}, {_fmt(P[1])}): không có tường nào có tim "
                           f"cách điểm chèn ≤ nửa chiều dày + {_fmt(tol)} mm — chưa đọc thành ô cửa.", [h], P)
                continue
            _d, _k, wall = min(cands, key=lambda c: (c[0], c[1]))
            a, b = tuple(wall.start), tuple(wall.end)
            L = math.hypot(*_sub(b, a))
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
            n = (-u[1], u[0])
            geo = _insert_geometry(e)
            proj = [_dot(_sub(p, a), u) for p in geo["points"]]
            offset = width = None
            if proj:
                smin, smax = min(proj), max(proj)
                if smax - smin > tol:
                    offset, width = _r(smin), _r(smax - smin)
            if width is None:
                self.issue(SEV_DOUBT, "CUA_KHONG_DO_DUOC_BE_RONG",
                           f"{label} block '{bname}' #{h}: block không có hình học đo được dọc tường {wall.id} — "
                           f"thiếu vị trí và bề rộng, cần nhập tay.", [h], P)
            leaves, hinge, opens_to = 1, "dau", "trai"
            swing = ""
            if kind == "cua_di" and width is not None:
                arcs = [(c, m) for c, r, m in geo["arcs"] if r >= 0.25 * width]
                if arcs:
                    hinges, sides = [], []
                    for c, m in arcs:
                        sc = _dot(_sub(c, a), u)
                        hinges.append("dau" if sc - offset <= offset + width - sc else "cuoi")
                        sides.append("trai" if _dot(_sub(m, c), n) > 0 else "phai")
                    leaves = 2 if len(arcs) == 2 else 1
                    hinge = hinges[0] if leaves == 1 else "dau"
                    opens_to = sides[0]
                    swing = f"bản lề/chiều mở đọc từ {len(arcs)} cung mở"
                    if len(arcs) > 2 or len(set(sides)) > 1:
                        self.issue(SEV_DOUBT, "CUA_CHIEU_MO_CHUA_RO",
                                   f"{label} #{h} (block '{bname}'): {len(arcs)} cung mở"
                                   f"{', hai phía khác nhau' if len(set(sides)) > 1 else ''} — lấy {leaves} cánh, mở về "
                                   f"{opens_to}; kiểm tra bản vẽ.", [h], P)
                else:
                    swing = "block không có cung mở — bản lề 'dau', mở về 'trai' theo mặc định"
                    self.issue(SEV_DOUBT, "CUA_CHIEU_MO_CHUA_RO",
                               f"{label} #{h} (block '{bname}'): không có cung mở trong block — số cánh, bản lề, chiều "
                               f"mở để mặc định (1 cánh, 'dau', 'trai'); kiểm tra bản vẽ.", [h], P)
            counters[kind] += 1
            oid = f"{'CD' if kind == 'cua_di' else 'CS'}{counters[kind]}"
            while oid in used_ids:
                counters[kind] += 1
                oid = f"{'CD' if kind == 'cua_di' else 'CS'}{counters[kind]}"
            used_ids.add(oid)
            mark = next((a_.plain_text().strip() for a_ in e.attribs if a_.plain_text().strip()), "")
            ref = (f"{self.fname}: INSERT #{h} block '{bname}' layer {layer}; tường {wall.id}; vị trí, bề rộng đo bao "
                   f"hình block dọc tim tường; chiều cao/bậu không có trong mặt bằng DXF")
            if swing:
                ref += f"; {swing}"
            self.store.openings.append(Opening(id=oid, wall_id=wall.id, kind=kind, offset=offset, width=width,
                                               hinge=hinge, opens_to=opens_to, leaves=leaves, mark=mark,
                                               prov=Provenance(SRC_DXF, ref)))

    # ── thực thể chưa xử lý ──────────────────────────────────────────────────

    def _report_leftovers(self) -> None:
        by_role: Dict[str, Dict[str, Any]] = {}
        unknown: Dict[str, Counter] = {}
        unknown_handles: List[str] = []
        for e in self.entities:
            h = self.h(e)
            if h in self.used:
                continue
            layer = str(e.dxf.get("layer", "0"))
            role = self.layer_roles.get(layer)
            if role:
                slot = by_role.setdefault(role, {"count": Counter(), "handles": [], "layers": set()})
                slot["count"][e.dxftype()] += 1
                slot["handles"].append(h)
                slot["layers"].add(layer)
            else:
                unknown.setdefault(layer, Counter())[e.dxftype()] += 1
                unknown_handles.append(h)
        for role in DXF_ROLE_PRIORITY:
            slot = by_role.get(role)
            if not slot:
                continue
            eids, extra = _capped(slot["handles"])
            counts = ", ".join(f"{t} {n}" for t, n in sorted(slot["count"].items()))
            self.issue(SEV_WARN, "THUC_THE_CHUA_XU_LY",
                       f"Layer vai trò '{role}' ({', '.join(sorted(slot['layers']))}) có {len(slot['handles'])} thực thể "
                       f"chưa đọc thành dữ liệu: {counts}{_LEFTOVER_HINTS.get(role, '')}.{extra}", eids)
        if unknown:
            eids, extra = _capped(unknown_handles)
            detail = "; ".join(f"{layer} ({', '.join(f'{t} {n}' for t, n in sorted(c.items()))})"
                               for layer, c in sorted(unknown.items()))
            self.issue(SEV_WARN, "LAYER_KHONG_NHAN_DIEN",
                       f"{len(unknown_handles)} thực thể trên {len(unknown)} layer không khớp mẫu vai trò "
                       f"(DEFAULT_ROLE_PATTERNS) — không đọc: {detail}. Nếu là trục/tường/cột/cửa, truyền "
                       f"role_patterns.{extra}", eids)


_LEFTOVER_HINTS = {
    "truc": " (chỉ đọc LINE làm trục; CIRCLE/TEXT/INSERT chỉ dùng khi là vòng tròn tên ở đầu trục)",
    "tuong": " (chỉ đọc LINE / cạnh thẳng của đa tuyến; tường cong, HATCH không đọc)",
    "cot": " (chỉ đọc đa tuyến kín hình chữ nhật; cột tròn, HATCH không đọc)",
    "cua_di": " (cửa phải là block INSERT mới đọc được vị trí, bề rộng)",
    "cua_so": " (cửa phải là block INSERT mới đọc được vị trí, bề rộng)",
    "dim": " (kích thước đã phá khối không còn số đo để đối chiếu)",
}


def _override_differs(text: str, measurement: Optional[float]) -> Tuple[bool, str]:
    """(chữ ghi đè khác số đo?, chữ đã bỏ mã định dạng). Chữ chứa "<>" vẫn hiện số đo → không khác.
    Mỗi số trong chữ được hiểu theo cả dấu thập phân "," / "." và dấu phân nhóm nghìn kiểu Việt Nam ("3.600")."""
    shown = plain_mtext(text).strip()
    if "<>" in text:
        return False, shown
    if measurement is None:
        return True, shown
    for tok in re.findall(r"\d[\d.,]*", shown):
        tok = tok.rstrip(".,")
        cands = []
        try:
            cands.append(float(tok.replace(",", ".")) if tok.count(",") + tok.count(".") <= 1 else math.nan)
        except ValueError:
            pass
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
            cands.append(float(re.sub(r"[.,]", "", tok)))
        if any(abs(c - measurement) <= 0.5 for c in cands if math.isfinite(c)):
            return False, shown
    return True, shown


def _insert_geometry(e: Any) -> Dict[str, Any]:
    """Điểm hình học (WCS) của một INSERT (kể cả block lồng, bỏ chữ) và các cung (tâm, bán kính, trung điểm cung)."""
    points: List[Pt] = []
    arcs: List[Tuple[Pt, float, Pt]] = []
    try:
        flat = [v for v in disassemble.recursive_decompose([e])
                if v.dxftype() not in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF", "POINT")]
    except (ezdxf.DXFError, ValueError, TypeError, ZeroDivisionError):
        flat = []
    for prim in disassemble.to_primitives(flat):
        points.extend(_xy(v) for v in prim.vertices())
    for v in flat:
        if v.dxftype() == "ARC":
            r = float(v.dxf.radius)
            pts = [_xy(p) for p in v.flattening(max(r / 200.0, 0.01))]
            if len(pts) >= 2:
                arcs.append((_wcs(v, v.dxf.center), r, pts[len(pts) // 2]))
    return {"points": points, "arcs": arcs}


def read_dxf(path: str, role_patterns: Optional[Dict[str, Any]] = None, tol: float = 1.0) -> ProjectStore:
    """Đọc bản vẽ DXF (model space) thành ProjectStore. Nhận diện theo tên layer: DEFAULT_ROLE_PATTERNS, có thể
    thay từng vai trò bằng `role_patterns` ({vai_trò: regex | re.Pattern | None để tắt}). `tol` (mm): dung sai coi
    hai toạ độ trùng nhau. Mọi vấn đề phát hiện ghi vào store.issues (skill "00")."""
    path = _require_file(path, "read_dxf")
    try:
        tol = float(tol)
    except (TypeError, ValueError):
        raise ReaderError(f"read_dxf: tol phải là số, nhận {tol!r}")
    if not (math.isfinite(tol) and tol > 0):
        raise ReaderError(f"read_dxf: tol phải > 0, nhận {tol!r}")
    compiled = _compile_patterns(role_patterns, DEFAULT_ROLE_PATTERNS, "read_dxf")
    fname = os.path.basename(path)
    store = ProjectStore()
    doc = _open_dxf(path, store, fname)
    _DxfReader(doc, store, compiled, tol, fname).run()
    n_axes = sum(len(g.names) for g in store.axes.values())
    store.sources.append(SourceFile(
        name=fname, kind="dxf", sha256=_sha256(path), used_for="du_lieu",
        note=(f"{n_axes} trục, {len(store.columns)} cột, {len(store.walls)} tường, {len(store.openings)} cửa, "
              f"{len(store.measured_dims)} kích thước")))
    return store


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE DXF (layer, block)
# ─────────────────────────────────────────────────────────────────────────────

def _block_op(kind: str, where: str, **data) -> Dict[str, Any]:
    return {"kind": kind, "data": normalize_op_data(kind, data, where)}


_TEXT_ALIGN = {(0, 0): "LEFT", (1, 0): "CENTER", (2, 0): "RIGHT", (4, 0): "MIDDLE_CENTER",
               (0, 2): "MIDDLE_LEFT", (1, 2): "MIDDLE_CENTER", (2, 2): "MIDDLE_RIGHT",
               (1, 3): "TOP_CENTER", (1, 1): "BOTTOM_CENTER"}


def _extrusion_z(e: Any) -> float:
    ex = e.dxf.get("extrusion", (0.0, 0.0, 1.0))
    if abs(ex[0]) > 1e-9 or abs(ex[1]) > 1e-9:
        return 0.0
    return 1.0 if ex[2] > 0 else -1.0


def _block_ops(entities: Iterable[Any], base: Pt, skipped: Counter, where: str, depth: int = 0) -> List[Dict[str, Any]]:
    """Hình học block → Op (line/pline/circle/arc/text) trong hệ toạ độ block, điểm chèn tại (0, 0).
    Thực thể không chuyển được → đếm vào `skipped` theo loại."""
    ops: List[Dict[str, Any]] = []
    bx, by = base

    def rel(p: Pt) -> List[float]:
        return [_r(p[0] - bx), _r(p[1] - by)]

    for e in entities:
        t = e.dxftype()
        try:
            if t == "LINE":
                ops.append(_block_op("line", where, p1=rel(_xy(e.dxf.start)), p2=rel(_xy(e.dxf.end))))
            elif t in ("LWPOLYLINE", "POLYLINE"):
                try:
                    pts, bulges, closed = _poly_vertices(e, 1e-6)
                except _Unsupported:
                    skipped[f"{t} 3D/lưới"] += 1
                    continue
                if any(abs(b) > 1e-9 for b in bulges):
                    ops += _block_ops(e.virtual_entities(), base, skipped, where, depth + 1)
                else:
                    ops.append(_block_op("pline", where, points=[rel(p) for p in pts], closed=closed))
            elif t == "CIRCLE":
                if _extrusion_z(e) == 0.0:
                    skipped["CIRCLE (mặt phẳng nghiêng)"] += 1
                    continue
                ops.append(_block_op("circle", where, center=rel(_wcs(e, e.dxf.center)), r=float(e.dxf.radius)))
            elif t == "ARC":
                z = _extrusion_z(e)
                if z == 0.0:
                    skipped["ARC (mặt phẳng nghiêng)"] += 1
                    continue
                s, en = float(e.dxf.start_angle), float(e.dxf.end_angle)
                if z < 0:                                     # OCS lật: (x, y) → (-x, y)
                    s, en = (180.0 - en) % 360.0, (180.0 - s) % 360.0
                ops.append(_block_op("arc", where, center=rel(_wcs(e, e.dxf.center)), r=float(e.dxf.radius),
                                     start_angle=_r(s, 6), end_angle=_r(en, 6)))
            elif t == "TEXT":
                key = (int(e.dxf.get("halign", 0)), int(e.dxf.get("valign", 0)))
                if _extrusion_z(e) != 1.0 or key not in _TEXT_ALIGN:
                    skipped[f"TEXT (căn lề {key[0]},{key[1]} / mặt phẳng khác)"] += 1
                    continue
                align = _TEXT_ALIGN[key]
                p = _xy(e.dxf.insert) if align == "LEFT" or not e.dxf.hasattr("align_point") else _xy(e.dxf.align_point)
                ops.append(_block_op("text", where, insert=rel(p), text=e.plain_text(),
                                     height=float(e.dxf.get("height", 0.0)), rotation=float(e.dxf.get("rotation", 0.0)),
                                     align=align))
            elif t == "INSERT":
                if depth >= 8:
                    skipped["INSERT (lồng quá 8 cấp)"] += 1
                    continue
                if e.attribs:
                    skipped["ATTRIB"] += len(e.attribs)
                ops += _block_ops(e.virtual_entities(), base, skipped, where, depth + 1)
            else:
                skipped[t] += 1
        except (PlanError, ValueError, TypeError, ZeroDivisionError, ezdxf.DXFError):
            skipped[f"{t} (dữ liệu lỗi)"] += 1
    return ops


def _ops_extents(ops: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for o in ops:
        d = o["data"]
        k = o["kind"]
        if k == "line":
            pts = [d["p1"], d["p2"]]
        elif k == "pline":
            pts = d["points"]
        elif k == "circle":
            cx, cy = d["center"]
            pts = [[cx - d["r"], cy - d["r"]], [cx + d["r"], cy + d["r"]]]
        elif k == "arc":
            cx, cy = d["center"]
            s, e_ = d["start_angle"] % 360.0, d["end_angle"] % 360.0
            sweep = (e_ - s) % 360.0 or 360.0
            angles = [s, s + sweep] + [q for q in (0.0, 90.0, 180.0, 270.0, 360.0, 450.0, 540.0, 630.0)
                                       if s < q < s + sweep]
            pts = [[cx + d["r"] * math.cos(math.radians(a)), cy + d["r"] * math.sin(math.radians(a))] for a in angles]
        else:
            pts = [d["insert"]]
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def read_template(store: ProjectStore, path: str, role_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Đọc template DXF: layer → store.layers[vai_trò], block → store.blocks (source="mau").

    role_map {vai_trò: tên_layer} chỉ định thẳng; không truyền thì khớp tên layer với TEMPLATE_ROLE_PATTERNS
    (vai trò không khớp giữ layer mặc định). Trả dict:
      layers           {vai_trò: tên layer template đã dùng}
      unmatched_roles  vai trò giữ layer mặc định
      multi_layer_roles {vai_trò: [các layer cùng khớp]} (dùng layer đầu theo thứ tự tên)
      blocks           tên block đã nạp;  replaced_blocks  tên block ghi đè block cũ trong store
      skipped          {block: {loại thực thể: số lượng bỏ qua}};  empty_blocks  block không còn hình học nào
      notes            ghi chú (lineweight mặc định, plot...)
    """
    ext = os.path.splitext(os.fspath(path))[1].lower() if isinstance(path, (str, os.PathLike)) else ""
    if ext in (".dwg", ".dwt"):
        raise ReaderError(f"template {ext.upper()[1:]}: {DWG_MESSAGE} — lưu template dạng DXF")
    path = _require_file(path, "read_template")
    fname = os.path.basename(path)
    doc = _open_dxf(path, store, fname)
    by_name = {str(layer.dxf.name).lower(): layer for layer in doc.layers}
    mapping: Dict[str, Any] = {}
    multi: Dict[str, List[str]] = {}
    if role_map is not None:
        if not isinstance(role_map, dict):
            raise ReaderError("read_template: role_map phải là dict {vai_trò: tên_layer}")
        for role, lname in role_map.items():
            if role not in DEFAULT_ROLES:
                raise ReaderError(f"read_template: vai trò lạ '{role}' (hợp lệ: {', '.join(DEFAULT_ROLES)})")
            layer = by_name.get(str(lname).lower())
            if layer is None:
                raise ReaderError(f"{fname}: không có layer '{lname}' cho vai trò '{role}'")
            mapping[role] = layer
    else:
        compiled = _compile_patterns(None, TEMPLATE_ROLE_PATTERNS, "read_template")
        cands: Dict[str, List[Any]] = {}
        for layer in sorted(doc.layers, key=lambda la: str(la.dxf.name).lower()):
            role, _hits = _match_role(str(layer.dxf.name), compiled, TEMPLATE_ROLE_PRIORITY)
            if role:
                cands.setdefault(role, []).append(layer)
        for role in DEFAULT_ROLES:
            if role in cands:
                mapping[role] = cands[role][0]
                if len(cands[role]) > 1:
                    multi[role] = [str(la.dxf.name) for la in cands[role]]

    new_layers = {r: LayerSpec(**vars(s)) for r, s in store.layers.items()}
    notes: List[str] = []
    no_plot: List[str] = []
    for role in DEFAULT_ROLES:
        if role not in mapping:
            continue
        layer, default = mapping[role], DEFAULT_ROLES[role][1]
        name = str(layer.dxf.name)
        lw = int(layer.dxf.get("lineweight", -3))
        if lw < 0:
            notes.append(f"{role}: layer '{name}' có lineweight mặc định/ByBlock ({lw}) → dùng {default.lineweight}")
            lw = default.lineweight
        color = abs(int(layer.dxf.get("color", 7))) or 7
        plot = bool(layer.dxf.get("plot", 1))
        if role in NON_PLOT_ROLES:
            if plot:
                notes.append(f"{role}: layer '{name}' được đặt KHÔNG in (vai trò không in theo thiết kế)")
            plot = False
        elif not plot:
            no_plot.append(f"{role} → {name}")
        new_layers[role] = LayerSpec(name=name, color=color, linetype=str(layer.dxf.get("linetype", "Continuous")),
                                     lineweight=lw, plot=plot, description=default.description)
    owners: Dict[str, str] = {}
    for role, spec in new_layers.items():
        other = owners.get(spec.name.lower())
        if other is not None:
            raise ReaderError(f"{fname}: vai trò '{other}' và '{role}' cùng layer '{spec.name}' — mỗi vai trò cần layer "
                              f"riêng (Validator dựa vào đó để bắt skill vẽ lấn phần nhau); truyền role_map.")
        owners[spec.name.lower()] = role
    store.layers = new_layers
    if multi:
        _add_issue(store, SEV_WARN, "TEMPLATE_NHIEU_LAYER",
                   f"{fname}: nhiều layer cùng khớp một vai trò — dùng layer đầu theo thứ tự tên: "
                   + "; ".join(f"{r}: {', '.join(ls)}" for r, ls in multi.items()) + ". Nếu sai, truyền role_map.")
    if no_plot:
        _add_issue(store, SEV_WARN, "TEMPLATE_LAYER_KHONG_IN",
                   f"{fname}: layer template đặt không in cho vai trò cần in: {', '.join(no_plot)} — bản in sẽ thiếu nét.")

    blocks_added: List[str] = []
    replaced: List[str] = []
    skipped: Dict[str, Dict[str, int]] = {}
    empty: List[str] = []
    off_origin: List[str] = []
    for blk in doc.blocks:
        name = str(blk.name)
        if name.startswith("*") or blk.is_any_layout:
            continue                                          # block ẩn danh (kích thước, bảng) / layout
        if name.startswith("_") and ARROWS.is_acad_arrow(ARROWS.arrow_name(name)):
            continue                                          # đầu mũi tên kích thước chuẩn của AutoCAD
        if blk.block.is_xref:
            skipped[name] = {"XREF (block tham chiếu ngoài)": 1}
            continue
        cnt: Counter = Counter()
        ops = _block_ops(blk, _xy(blk.block.dxf.base_point), cnt, f"block {name}")
        if cnt:
            skipped[name] = dict(sorted(cnt.items()))
        if not ops:
            empty.append(name)
            continue
        xmin, ymin, xmax, ymax = _ops_extents(ops)
        desc = (f"Block từ template {fname}; bao hình x[{_fmt(xmin)}..{_fmt(xmax)}] y[{_fmt(ymin)}..{_fmt(ymax)}] "
                f"so với điểm chèn")
        if name in store.blocks:
            replaced.append(name)
        store.blocks[name] = BlockDef(name=name, ops=ops, size=[_r(xmax - xmin), _r(ymax - ymin)],
                                      description=desc, source="mau")
        blocks_added.append(name)
        if abs(xmin) > 1.0 or abs(ymin) > 1.0:
            off_origin.append(f"{name} (góc dưới-trái tại {_fmt(xmin)}, {_fmt(ymin)})")
    if skipped:
        _add_issue(store, SEV_WARN, "TEMPLATE_BO_QUA_THUC_THE",
                   f"{fname}: thực thể trong block không chuyển được sang hình học block (chỉ line/pline/circle/arc/text) "
                   f"— bỏ qua: " + "; ".join(f"{b}: {', '.join(f'{t} {n}' for t, n in c.items())}"
                                              for b, c in skipped.items()) + ".")
    if empty:
        _add_issue(store, SEV_WARN, "TEMPLATE_BLOCK_RONG",
                   f"{fname}: block không còn hình học nào sau khi chuyển — không nạp: {', '.join(empty)}.")
    if off_origin:
        _add_issue(store, SEV_WARN, "TEMPLATE_BLOCK_GOC_LECH",
                   f"{fname}: block có bao hình không bắt đầu tại điểm chèn — vết chiếm chỗ (geom.footprint giả định "
                   f"góc dưới-trái tại điểm chèn) sẽ lệch: {', '.join(off_origin)}.")
    if replaced:
        notes.append(f"block ghi đè block cùng tên đã có trong dữ liệu: {', '.join(replaced)}")
    store.sources.append(SourceFile(name=fname, kind="template", sha256=_sha256(path), used_for="mau",
                                    note=f"{len(mapping)} vai trò layer, {len(blocks_added)} block"))
    return {"file": fname,
            "layers": {r: new_layers[r].name for r in DEFAULT_ROLES if r in mapping},
            "unmatched_roles": [r for r in DEFAULT_ROLES if r not in mapping],
            "multi_layer_roles": multi, "blocks": blocks_added, "replaced_blocks": replaced,
            "skipped": skipped, "empty_blocks": empty, "notes": notes}


# ─────────────────────────────────────────────────────────────────────────────
# ẢNH / PDF NỀN THAM CHIẾU
# ─────────────────────────────────────────────────────────────────────────────

def attach_reference(store: ProjectStore, path: str, insert: Sequence[float] = (0.0, 0.0),
                     scale: Optional[float] = None, page: int = 1) -> SourceFile:
    """Gắn PDF/JPG/PNG làm ẢNH NỀN tham chiếu (layer vai trò "anh_nen", không in). KHÔNG nhận dạng số liệu từ
    ảnh — số liệu phải nhập tay theo mẫu đề bài JSON. scale = mm bản vẽ trên 1 pixel ảnh / 1 đơn vị PDF."""
    ext = os.path.splitext(os.fspath(path))[1].lower() if isinstance(path, (str, os.PathLike)) else ""
    if ext == ".dwg":
        raise ReaderError(DWG_MESSAGE)
    if ext not in REFERENCE_EXT:
        raise ReaderError(f"attach_reference: chỉ nhận {', '.join(REFERENCE_EXT)} (nhận '{ext or path!r}')")
    path = _require_file(path, "attach_reference")
    fname = os.path.basename(path)
    try:
        ix, iy = insert
        ix, iy = float(ix), float(iy)
    except (TypeError, ValueError):
        raise ReaderError(f"attach_reference: insert phải là [x, y], nhận {insert!r}")
    if not (math.isfinite(ix) and math.isfinite(iy)):
        raise ReaderError(f"attach_reference: insert không hữu hạn {insert!r}")
    if scale is not None:
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            raise ReaderError(f"attach_reference: scale phải là số, nhận {scale!r}")
        if not (math.isfinite(scale) and scale > 0):
            raise ReaderError(f"attach_reference: scale phải > 0, nhận {scale!r}")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ReaderError(f"attach_reference: page phải là số nguyên ≥ 1, nhận {page!r}")
    kind = REFERENCE_EXT[ext]
    underlay: Dict[str, Any] = {"insert": [ix, iy], "scale": scale, "page": page}
    if kind == "anh":
        if page != 1:
            raise ReaderError(f"{fname}: ảnh chỉ có 1 trang (nhận page={page})")
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(path) as im:
                w, h = im.size
        except (OSError, UnidentifiedImageError) as e:
            raise ReaderError(f"{fname}: không đọc được ảnh ({e.__class__.__name__})") from e
        underlay["pixels"] = [int(w), int(h)]
    else:
        with open(path, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise ReaderError(f"{fname}: không phải file PDF")
    sf = SourceFile(name=fname, kind=kind, sha256=_sha256(path), used_for="anh_nen",
                    note="ảnh nền tham chiếu (layer vai trò 'anh_nen', không in) — không nhận dạng số liệu",
                    underlay=underlay)
    store.sources.append(sf)
    _add_issue(store, SEV_WARN, "ANH_CHUA_NHAN_DANG",
               f"{fname}: chỉ dùng làm ảnh nền tham chiếu — KHÔNG tự nhận dạng số liệu từ ảnh/PDF (không đoán số OCR "
               f"mờ). Kích thước, trục, tường, cửa phải nhập tay theo mẫu đề bài JSON ({SPEC_TEMPLATE_HINT}), ghi "
               f"[Trang N] và số hiệu bản vẽ.", [fname])
    if scale is None:
        _add_issue(store, SEV_WARN, "ANH_CHUA_CO_TY_LE",
                   f"{fname}: chưa có tỷ lệ ảnh nền (scale = mm bản vẽ trên 1 pixel ảnh / 1 đơn vị PDF) — ảnh nền "
                   f"chưa đặt đúng kích thước; truyền scale khi đính kèm hoặc gọi set_reference_scale.", [fname])
    return sf


def set_reference_scale(store: ProjectStore, scale: float, name: Optional[str] = None) -> List[SourceFile]:
    """Đặt tỷ lệ cho ảnh nền đã gắn (mọi ảnh nền, hoặc chỉ file tên `name`) và bỏ cảnh báo "ANH_CHUA_CO_TY_LE" của
    đúng các file đó (điều kiện cảnh báo không còn). Trả các SourceFile đã sửa."""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        raise ReaderError(f"set_reference_scale: scale phải là số, nhận {scale!r}")
    if not (math.isfinite(scale) and scale > 0):
        raise ReaderError(f"set_reference_scale: scale phải > 0, nhận {scale!r}")
    targets = [s for s in store.sources if s.used_for == "anh_nen" and (name is None or s.name == name)]
    if not targets:
        raise ReaderError(f"set_reference_scale: không có ảnh nền {'nào' if name is None else repr(name)} trong dữ liệu")
    names = {s.name for s in targets}
    for s in targets:
        s.underlay = dict(s.underlay or {}, scale=scale)
    store.issues = [i for i in store.issues
                    if not (i.skill == SKILL_CODE and i.code == "ANH_CHUA_CO_TY_LE" and set(i.eids) <= names)]
    return targets


# ─────────────────────────────────────────────────────────────────────────────
# A. NGƯỜI DÙNG NHẬP  /  B. NỘI SUY
# ─────────────────────────────────────────────────────────────────────────────

def _field_name(key: str) -> str:
    return re.sub(r"\[\d+\]$", "", key.rsplit(".", 1)[-1])


def apply_user_values(store: ProjectStore, path: str) -> List[str]:
    """Phương án A "Tôi nhập". File JSON:
        {"nguon": "[Trang 2] KT-01", "gia_tri": {khoá: số},
         "xac_nhan": [{"key": khoá_nội_suy, "by": "tên người", "ghi_chu": "..."}]}
    gia_tri → store.set_value(khoá, số, Provenance("nguoi_nhap", nguon)); xac_nhan → store.confirm(...).
    Kiểm tra toàn bộ file trước rồi mới ghi (sai một mục → ReaderError, không ghi mục nào).
    Trả danh sách khoá đã ghi (giá trị nhập trước, khoá xác nhận sau)."""
    path = _require_file(path, "apply_user_values")
    fname = os.path.basename(path)
    data = _load_json(path, fname)
    if not isinstance(data, dict):
        raise ReaderError(f"{fname}: file kích thước nhập phải là đối tượng JSON {{\"nguon\", \"gia_tri\", \"xac_nhan\"}}")
    extra = sorted(set(data) - set(USER_VALUES_KEYS))
    if extra:
        raise ReaderError(f"{fname}: khoá lạ {extra} (hợp lệ: {', '.join(USER_VALUES_KEYS)})")
    nguon = str(data.get("nguon", "") or "").strip()
    if not nguon:
        raise ReaderError(f"{fname}: phải ghi 'nguon' — trang và số hiệu bản vẽ, vd \"[Trang 2] KT-01\"")
    gia_tri = data.get("gia_tri") or {}
    xac_nhan = data.get("xac_nhan") or []
    if not isinstance(gia_tri, dict):
        raise ReaderError(f"{fname}: 'gia_tri' phải là {{khoá: số}}")
    if not isinstance(xac_nhan, list):
        raise ReaderError(f"{fname}: 'xac_nhan' phải là danh sách [{{key, by, ghi_chu}}]")
    if not gia_tri and not xac_nhan:
        raise ReaderError(f"{fname}: không có giá trị nào để ghi ('gia_tri' và 'xac_nhan' đều rỗng)")

    errors: List[str] = []
    values: List[Tuple[str, float]] = []
    for key, val in gia_tri.items():
        try:
            cur = store.get_value(key)
        except StoreError as e:
            errors.append(f"khoá sai '{key}': {e}")
            continue
        if cur is not None and (isinstance(cur, bool) or not isinstance(cur, (int, float))):
            errors.append(f"'{key}' không phải số liệu kích thước (giá trị hiện tại {cur!r})")
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            errors.append(f"'{key}': giá trị phải là số hữu hạn, nhận {val!r}")
            continue
        fld = _field_name(key)
        if fld in POSITIVE_FIELDS and val <= 0:
            errors.append(f"'{key}': {fld} phải > 0, nhận {val!r}")
            continue
        if fld in NON_NEGATIVE_FIELDS and val < 0:
            errors.append(f"'{key}': {fld} phải ≥ 0, nhận {val!r}")
            continue
        if fld == "n_treads" and float(val) != int(val):
            errors.append(f"'{key}': số bậc phải là số nguyên, nhận {val!r}")
            continue
        values.append((key, float(val)))
    confirms: List[Tuple[str, str, str]] = []
    seen: Set[str] = set()
    for i, item in enumerate(xac_nhan):
        if not isinstance(item, dict):
            errors.append(f"xac_nhan[{i}] phải là {{key, by, ghi_chu}}")
            continue
        bad = sorted(set(item) - set(CONFIRM_KEYS))
        if bad:
            errors.append(f"xac_nhan[{i}]: khoá lạ {bad}")
            continue
        key = str(item.get("key", "") or "")
        by = str(item.get("by", "") or "").strip()
        note = str(item.get("ghi_chu", "") or "").strip()
        if not by:
            errors.append(f"xac_nhan[{i}] ('{key}'): phải ghi người xác nhận 'by'")
            continue
        if key in gia_tri:
            errors.append(f"'{key}' vừa có trong gia_tri vừa xác nhận nội suy — chọn một")
            continue
        if key in seen:
            errors.append(f"'{key}' xác nhận hai lần")
            continue
        try:
            prov = store.get_provenance(key)
            cur = store.get_value(key)
        except StoreError as e:
            errors.append(f"xac_nhan[{i}]: khoá sai '{key}': {e}")
            continue
        if prov.source != SRC_INTERP:
            errors.append(f"'{key}' không phải số liệu nội suy (nguồn: {prov.source}) — chỉ xác nhận được số liệu nội suy")
            continue
        if cur is None:
            errors.append(f"'{key}' chưa có giá trị để xác nhận")
            continue
        seen.add(key)
        confirms.append((key, by, note))
    if errors:
        raise ReaderError(f"{fname}: " + "; ".join(errors))

    for key, val in values:
        store.set_value(key, val, Provenance(SRC_USER, nguon))
    for key, by, note in confirms:
        store.confirm(key, by, note)
    if not re.search(r"\[\s*trang\s+\d+\s*\]", nguon, re.IGNORECASE):
        _add_issue(store, SEV_WARN, "NGUON_NHAP_THIEU_TRANG",
                   f"{fname}: nguồn nhập tay '{nguon}' chưa ghi trang dạng [Trang N] kèm số hiệu bản vẽ (quy ước repo "
                   f"cho số liệu trích từ bản vẽ).")
    store.sources.append(SourceFile(name=fname, kind="kich_thuoc_nhap", sha256=_sha256(path), used_for="du_lieu",
                                    note=f"{nguon}; {len(values)} giá trị nhập, {len(confirms)} xác nhận nội suy"))
    return [k for k, _ in values] + [k for k, _, _ in confirms]


def _not_interpolated(key: str, reason: str) -> Dict[str, Any]:
    return {"key": key, "value": None, "method": "khong_noi_suy", "reason": reason}


def _interp_span(store: ProjectStore, o: str, i: int, key: str) -> Dict[str, Any]:
    g = store.axes[o]
    label = f"{g.names[i]}–{g.names[i + 1]}"
    miss = [j for j, s in enumerate(g.spans) if s is None]
    if g.overall is None:
        return _not_interpolated(key, f"nhóm trục {o} không có kích thước tổng — không suy được nhịp {label}; cần nhập tay")
    if len(miss) >= 2:
        labels = ", ".join(f"{g.names[j]}–{g.names[j + 1]}" for j in miss)
        return _not_interpolated(key, f"nhóm trục {o} thiếu {len(miss)} nhịp ({labels}) — kích thước tổng chỉ suy được "
                                      f"khi thiếu đúng 1 nhịp; cần nhập tay")
    deps = [g.overall_prov or g.prov] + [g.span_provenance(j) for j, s in enumerate(g.spans) if s is not None]
    if any(p.source == SRC_INTERP and not p.confirmed for p in deps):
        return _not_interpolated(key, f"nhịp {label} sẽ phụ thuộc số liệu nội suy chưa xác nhận — xác nhận hoặc nhập "
                                      f"tay số liệu đó trước")
    known = [float(s) for s in g.spans if s is not None]
    value = float(g.overall) - sum(known)
    span_names = f"{g.names[0]}–{g.names[-1]}"
    if known:
        formula = (f"{_fmt(g.overall)} − ({' + '.join(_fmt(s) for s in known)}) từ kích thước tổng trục {o} "
                   f"({span_names})")
    else:
        formula = f"{_fmt(g.overall)} = kích thước tổng trục {o} ({span_names}), nhóm chỉ có một nhịp"
    if value <= 0:
        _add_issue(store, SEV_ERROR, "NOI_SUY_NHIP_KHONG_DUONG",
                   f"Nội suy nhịp {label} nhóm trục {o}: {formula} = {_fmt(value)} ≤ 0 — kích thước tổng mâu thuẫn với "
                   f"các nhịp đã biết; không nội suy, cần kiểm tra bản vẽ.")
        return _not_interpolated(key, f"{formula} = {_fmt(value)} ≤ 0 — kích thước tổng mâu thuẫn với các nhịp đã biết")
    store.set_value(key, _r(value), Provenance.interpolated(formula))
    return {"key": key, "value": _r(value), "method": "tong_tru_nhip", "reason": formula}


def _interp_same_mark(store: ProjectStore, coll: str, eid: str, fld: str, key: str) -> Dict[str, Any]:
    ent = store.get(coll, eid)
    thing = "cột" if coll == "columns" else "cửa"
    if not ent.mark:
        return _not_interpolated(key, f"{thing} {eid} không có ký hiệu (mark) để lấy kích thước từ {thing} cùng loại; "
                                      f"cần nhập tay")
    peers = [e for e in getattr(store, coll)
             if e.id != eid and e.mark == ent.mark and (coll != "openings" or e.kind == ent.kind)]
    known = [(e.id, float(getattr(e, fld))) for e in peers
             if getattr(e, fld) is not None and e.provenance(fld).source != SRC_INTERP]
    values = sorted({_r(v) for _, v in known})
    if not values:
        return _not_interpolated(key, f"không có {thing} cùng ký hiệu {ent.mark} có {fld} đã biết (không tính số liệu "
                                      f"nội suy); cần nhập tay")
    if len(values) > 1:
        detail = ", ".join(f"{i} = {_fmt(v)}" for i, v in known)
        _add_issue(store, SEV_DOUBT, "NOI_SUY_MAU_THUAN",
                   f"{thing.capitalize()} cùng ký hiệu {ent.mark} có {fld} khác nhau ({detail}) — không nội suy {key}; "
                   f"kiểm tra bảng ký hiệu.", [eid] + [i for i, _ in known])
        return _not_interpolated(key, f"mâu thuẫn: {thing} cùng ký hiệu {ent.mark} có {fld} khác nhau ({detail})")
    value = values[0]
    formula = f"{fld} = {_fmt(value)} lấy từ {thing} cùng ký hiệu {ent.mark}: {', '.join(i for i, _ in known)}"
    store.set_value(key, value, Provenance.interpolated(formula))
    return {"key": key, "value": value, "method": "cung_ky_hieu", "reason": formula}


def interpolate_missing(store: ProjectStore) -> List[Dict[str, Any]]:
    """Phương án B "nội suy" (tất định) cho MỌI mục trong store.missing():
      - nhịp trục: nhóm có kích thước tổng và thiếu đúng 1 nhịp → tổng − các nhịp đã biết (phải > 0, ≤ 0 → LOI);
      - b/h cột, bề rộng cửa: lấy từ đối tượng KHÁC cùng ký hiệu (mark) có giá trị không phải nội suy; nhiều giá trị
        khác nhau → không nội suy (mâu thuẫn);
      - còn lại (vị trí cửa, chiều dày tường, thang...) → không nội suy.
    Ghi bằng Provenance.interpolated (confirmed=False — chỉ người xác nhận qua apply_user_values / store.confirm).
    Trả [{"key", "value" (None nếu không nội suy), "method", "reason"}] cho mọi mục thiếu."""
    results: List[Dict[str, Any]] = []
    for item in store.missing():
        key = item.key
        m_span = re.match(r"^axes:([VH])\.spans\[(\d+)\]$", key)
        m_col = re.match(r"^columns:([^.]+)\.(b|h)$", key)
        m_op = re.match(r"^openings:([^.]+)\.(width)$", key)
        if m_span:
            results.append(_interp_span(store, m_span.group(1), int(m_span.group(2)), key))
        elif m_col:
            results.append(_interp_same_mark(store, "columns", m_col.group(1), m_col.group(2), key))
        elif m_op:
            results.append(_interp_same_mark(store, "openings", m_op.group(1), m_op.group(2), key))
        else:
            results.append(_not_interpolated(key, f"{item.description}: không có kích thước rõ gần nhất để nội suy — "
                                                  f"cần nhập tay (phương án A)"))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# ĐIỀU PHỐI
# ─────────────────────────────────────────────────────────────────────────────

def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, (str, os.PathLike, dict)):
        return [x]
    return list(x)


def load_inputs(paths: Any, template: Any = None, user_values: Any = None, interpolate: bool = False,
                references: Any = None) -> ProjectStore:
    """Đọc đầu vào theo đuôi file: .json → read_spec; .dxf → read_dxf; .pdf/.jpg/.jpeg/.png → attach_reference
    (ảnh nền, cần thêm đúng MỘT nguồn dữ liệu JSON hoặc DXF); .dwg → ReaderError.
    Sau đó lần lượt: references (ảnh nền thêm, mỗi mục là đường dẫn hoặc {"path", "insert", "scale", "page"}),
    template (đường dẫn hoặc {"path", "role_map"}), user_values (một hoặc nhiều file kích thước nhập), interpolate.
    Lưu ý: nội suy chạy SAU file nhập tay, nên xác nhận nội suy phải nằm trong một file nhập ở lần gọi sau."""
    data_src: List[str] = []
    refs: List[Dict[str, Any]] = []
    for p in _as_list(paths):
        if not isinstance(p, (str, os.PathLike)):
            raise ReaderError(f"load_inputs: cần đường dẫn file, nhận {p!r}")
        p = os.fspath(p)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".dwg":
            raise ReaderError(f"{os.path.basename(p)}: {DWG_MESSAGE}")
        if ext in DATA_EXT:
            data_src.append(p)
        elif ext in REFERENCE_EXT:
            refs.append({"path": p})
        else:
            raise ReaderError(f"{os.path.basename(p)}: định dạng '{ext or '(không đuôi)'}' chưa hỗ trợ "
                              f"(dùng .json, .dxf, .pdf, .png, .jpg)")
    for r in _as_list(references):
        if isinstance(r, dict):
            if "path" not in r:
                raise ReaderError(f"load_inputs: mục references thiếu 'path': {r!r}")
            bad = sorted(set(r) - {"path", "insert", "scale", "page"})
            if bad:
                raise ReaderError(f"load_inputs: mục references có khoá lạ {bad}")
            refs.append(dict(r))
        else:
            refs.append({"path": r})
    if not data_src:
        if refs:
            raise ReaderError("chỉ có ảnh/PDF: ảnh chỉ dùng làm nền tham chiếu, không tự nhận dạng số liệu — cần đề bài "
                              f"JSON nhập tay theo mẫu {SPEC_TEMPLATE_HINT} (hoặc bản vẽ DXF) làm nguồn dữ liệu")
        raise ReaderError("không có nguồn dữ liệu: cần đề bài JSON hoặc bản vẽ DXF")
    if len(data_src) > 1:
        raise ReaderError(f"chưa hỗ trợ gộp nhiều nguồn dữ liệu ({', '.join(os.path.basename(p) for p in data_src)}) — "
                          f"chọn MỘT đề bài JSON hoặc MỘT bản vẽ DXF; số liệu bổ sung đưa qua file kích thước nhập tay")
    src = data_src[0]
    store = read_spec(src) if src.lower().endswith(".json") else read_dxf(src)
    for r in refs:
        attach_reference(store, r["path"], insert=r.get("insert", (0.0, 0.0)), scale=r.get("scale"),
                         page=r.get("page", 1))
    if template is not None:
        if isinstance(template, dict):
            if "path" not in template:
                raise ReaderError(f"load_inputs: template thiếu 'path': {template!r}")
            read_template(store, template["path"], template.get("role_map"))
        else:
            read_template(store, template)
    for uv in _as_list(user_values):
        apply_user_values(store, uv)
    if interpolate:
        interpolate_missing(store)
    return store


__all__ = ["ReaderError", "DEFAULT_ROLE_PATTERNS", "DXF_ROLE_PRIORITY", "TEMPLATE_ROLE_PATTERNS",
           "WALL_MIN_THICKNESS", "WALL_MAX_THICKNESS", "read_spec", "read_dxf", "read_template",
           "attach_reference", "set_reference_scale", "apply_user_values", "interpolate_missing", "load_inputs"]
