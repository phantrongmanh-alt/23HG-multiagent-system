# -*- coding: utf-8 -*-
"""
PROJECT DATA STORE — dữ liệu dự án dùng chung cho mọi skill dựng CAD ("phân tích một lần").

Mỗi số liệu mang NGUỒN GỐC (Provenance):
  dxf         đọc từ đối tượng trong file DXF (ref = handle / layer)
  nguoi_nhap  người dùng nhập từ bản vẽ (ref nên ghi "[Trang N] <số hiệu bản vẽ>")
  noi_suy     nội suy từ kích thước rõ gần nhất — LUÔN chưa xác nhận cho tới khi có người xác nhận

Giá trị thiếu để None, không đoán. `missing()` liệt kê mọi kích thước thiếu cần cho việc vẽ;
`status()` TÍNH trạng thái duyệt từ dữ liệu (không có trạng thái gõ tay).

Toạ độ: mm. Trục "V" là đường thẳng đứng (x = offset, đặt tên 1, 2, 3...), trục "H" là đường nằm
ngang (y = offset, đặt tên A, B, C...). Điểm có thể viết theo giao trục: "1/A", hoặc "1/A@dx,dy"
(lệch dx, dy mm so với giao trục), hoặc toạ độ [x, y].

Khoá số liệu (dùng cho file nhập tay, nội suy và xác nhận):
  axes:V.spans[1]   nhịp thứ 2 của nhóm trục V      axes:H.overall   kích thước tổng nhóm trục H
  columns:C5.b      cạnh X của cột C5                walls:W3.thickness
  openings:D2.width / openings:D2.offset            stairs:ST1.flights[0].going
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.cad_drafting.layers import LayerSpec, default_layers
from tools.cad_drafting.plan import BlockDef

STORE_SCHEMA = "23hg-cad-store/1"

SRC_DXF = "dxf"
SRC_USER = "nguoi_nhap"
SRC_INTERP = "noi_suy"
SOURCES = (SRC_DXF, SRC_USER, SRC_INTERP)

SEV_ERROR = "LOI"            # chặn: phải sửa trước khi coi bản vẽ là đạt
SEV_WARN = "CANH_BAO"        # cần kỹ sư xem
SEV_DOUBT = "NGHI_VAN"       # số liệu chưa chắc (nội suy, sai khác nguồn) — chủ dự án soát
SEVERITIES = (SEV_ERROR, SEV_WARN, SEV_DOUBT)

Point = Tuple[float, float]
PointRef = Union[str, List[float], Tuple[float, float]]

_REF_RE = re.compile(r"^\s*([^/@\s]+)\s*/\s*([^/@\s]+)\s*(?:@\s*(-?[\d.]+)\s*,\s*(-?[\d.]+))?\s*$")


class StoreError(ValueError):
    """Dữ liệu dự án sai cấu trúc (không phải thiếu số liệu — thiếu thì để None)."""


# ─────────────────────────────────────────────────────────────────────────────
# NGUỒN GỐC SỐ LIỆU
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Provenance:
    source: str = SRC_USER
    ref: str = ""
    confirmed: bool = True
    confirmed_by: str = ""

    def __post_init__(self):
        if self.source not in SOURCES:
            raise StoreError(f"nguồn số liệu lạ '{self.source}' (hợp lệ: {', '.join(SOURCES)})")
        if self.source == SRC_INTERP and self.confirmed and not self.confirmed_by:
            raise StoreError("số liệu nội suy chỉ được coi là đã xác nhận khi ghi rõ người xác nhận (confirmed_by)")

    @classmethod
    def interpolated(cls, ref: str) -> "Provenance":
        return cls(SRC_INTERP, ref, confirmed=False)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "ref": self.ref, "confirmed": self.confirmed,
                "confirmed_by": self.confirmed_by}

    @classmethod
    def from_any(cls, d: Optional[Dict[str, Any]], default_ref: str = "") -> "Provenance":
        if d is None:
            return cls(SRC_USER, default_ref)
        if isinstance(d, Provenance):
            return d
        source = d.get("source", SRC_USER)
        confirmed = d.get("confirmed", source != SRC_INTERP)
        return cls(source, d.get("ref", default_ref), bool(confirmed), d.get("confirmed_by", ""))


# ─────────────────────────────────────────────────────────────────────────────
# ĐỐI TƯỢNG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class Entity:
    id: str
    prov: Provenance = field(default_factory=Provenance)
    field_prov: Dict[str, Provenance] = field(default_factory=dict)   # nguồn riêng cho từng trường

    def provenance(self, name: str) -> Provenance:
        return self.field_prov.get(name, self.prov)


@dataclass(kw_only=True)
class AxisGroup:
    orientation: str                          # "V" | "H"
    names: List[str]
    spans: List[Optional[float]]              # khoảng cách giữa hai trục liền nhau; len = len(names) - 1
    overall: Optional[float] = None           # kích thước tổng trục đầu → trục cuối (nếu bản vẽ ghi)
    origin: float = 0.0                       # toạ độ trục đầu tiên
    prov: Provenance = field(default_factory=Provenance)
    span_prov: List[Optional[Provenance]] = field(default_factory=list)
    overall_prov: Optional[Provenance] = None

    def __post_init__(self):
        if self.orientation not in ("V", "H"):
            raise StoreError(f"nhóm trục phải là 'V' hoặc 'H', nhận '{self.orientation}'")
        if len(self.spans) != max(len(self.names) - 1, 0):
            raise StoreError(f"nhóm trục {self.orientation}: {len(self.names)} trục cần {len(self.names) - 1} nhịp, "
                             f"nhận {len(self.spans)}")
        if len(set(self.names)) != len(self.names):
            raise StoreError(f"nhóm trục {self.orientation}: tên trục trùng {self.names}")
        while len(self.span_prov) < len(self.spans):
            self.span_prov.append(None)

    def span_provenance(self, i: int) -> Provenance:
        return self.span_prov[i] or self.prov

    def offsets(self) -> List[Optional[float]]:
        """Toạ độ từng trục, cộng dồn nhịp từ trục đầu. Sau một nhịp thiếu, các trục còn lại là None —
        KHÔNG tự suy ngược từ kích thước tổng (việc đó là nội suy, phải qua reader và được đánh dấu)."""
        out: List[Optional[float]] = []
        acc: Optional[float] = self.origin
        for i in range(len(self.names)):
            out.append(acc)
            if i < len(self.spans):
                acc = None if (acc is None or self.spans[i] is None) else acc + float(self.spans[i])
        return out

    def offset_of(self, name: str) -> Optional[float]:
        return self.offsets()[self.names.index(name)]


@dataclass(kw_only=True)
class Column(Entity):
    axis_v: str
    axis_h: str
    b: Optional[float] = None                 # cạnh theo X (mm)
    h: Optional[float] = None                 # cạnh theo Y (mm)
    dx: float = 0.0                           # lệch tâm so với giao trục
    dy: float = 0.0
    mark: str = ""                            # loại cột (C1, C2...)


@dataclass(kw_only=True)
class Wall(Entity):
    start: PointRef                           # điểm đầu tim tường
    end: PointRef                             # điểm cuối tim tường
    thickness: Optional[float] = None
    kind: str = "xay"                         # "xay" (gạch) | "btct"
    height: Optional[float] = None


@dataclass(kw_only=True)
class Opening(Entity):
    wall_id: str
    kind: str                                 # "cua_di" | "cua_so"
    offset: Optional[float] = None            # từ điểm đầu tim tường tới mép gần của ô cửa, đo dọc tường
    width: Optional[float] = None
    height: Optional[float] = None
    sill: float = 0.0                         # cao độ bậu cửa sổ
    hinge: str = "dau"                        # bản lề ở mép phía điểm đầu ("dau") hay điểm cuối ("cuoi") của ô
    opens_to: str = "trai"                    # cánh mở về bên trái / phải khi đi dọc tường từ start → end
    leaves: int = 1                           # số cánh
    mark: str = ""                            # ký hiệu (D1, S1...)

    def __post_init__(self):
        if self.kind not in ("cua_di", "cua_so"):
            raise StoreError(f"cửa {self.id}: kind phải là 'cua_di' hoặc 'cua_so'")
        if self.hinge not in ("dau", "cuoi"):
            raise StoreError(f"cửa {self.id}: hinge phải là 'dau' hoặc 'cuoi'")
        if self.opens_to not in ("trai", "phai"):
            raise StoreError(f"cửa {self.id}: opens_to phải là 'trai' hoặc 'phai'")
        if self.leaves not in (1, 2):
            raise StoreError(f"cửa {self.id}: leaves phải là 1 hoặc 2")


@dataclass(kw_only=True)
class StairFlight:
    """Một vế thang thẳng. origin = góc đầu vế ở mép TRÁI khi đi lên; vế trải theo hướng `angle`
    dài n_treads × going và sang PHẢI một bề rộng `width`."""
    origin: PointRef
    angle: float = 0.0
    width: Optional[float] = None
    going: Optional[float] = None             # bề rộng mặt bậc
    n_treads: Optional[int] = None
    riser: Optional[float] = None             # chiều cao bậc (ghi chú)


@dataclass(kw_only=True)
class Stair(Entity):
    flights: List[StairFlight]
    landings: List[List[PointRef]] = field(default_factory=list)   # chiếu nghỉ (đa giác)
    label: str = "LÊN"


@dataclass(kw_only=True)
class Furniture(Entity):
    block: str                                # tên block (thư viện chuẩn hoặc template)
    insert: PointRef
    rotation: float = 0.0
    room_id: str = ""


@dataclass(kw_only=True)
class Room(Entity):
    name: str
    boundary: List[PointRef]                  # đường bao phòng (theo người nhập: tim trục hoặc thông thủy)
    floor_finish: str = ""
    wall_finish: str = ""
    ceiling_finish: str = ""
    floor_level: Optional[float] = None       # cote sàn hoàn thiện (mm)
    hatch: str = ""                           # khoá trong layers.HATCH_PATTERNS; rỗng = không hatch sàn


@dataclass(kw_only=True)
class MeasuredDim(Entity):
    """Kích thước đọc được từ nguồn (DIMENSION trong DXF / bản vẽ) — để đối chiếu, không để vẽ."""
    p1: List[float]
    p2: List[float]
    angle: float = 0.0
    measurement: Optional[float] = None       # giá trị đo hình học
    text: str = ""                            # chữ ghi đè (text override) nếu có


@dataclass(kw_only=True)
class ProjectInfo:
    name: str = ""
    drawing_title: str = ""
    drawing_no: str = ""
    scale: int = 100
    sheet: str = "A3"
    revision: str = "00"
    level_name: str = ""
    designer: str = ""
    checker: str = ""
    date: str = ""


@dataclass(kw_only=True)
class SourceFile:
    name: str                                 # chỉ tên file (không ghi đường dẫn máy)
    kind: str                                 # "dxf" | "json" | "pdf" | "anh" | "template" | "kich_thuoc_nhap"
    sha256: str = ""
    used_for: str = "du_lieu"                 # "du_lieu" | "anh_nen" | "mau"
    note: str = ""
    underlay: Optional[Dict[str, Any]] = None # {"insert": [x, y], "scale": ..., "page": 1} khi làm ảnh nền


@dataclass(kw_only=True)
class Issue:
    severity: str
    code: str
    message: str
    skill: str = ""                           # "00".."10" hoặc "VAL"
    eids: List[str] = field(default_factory=list)
    where: Optional[List[float]] = None

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise StoreError(f"mức độ lạ '{self.severity}'")


@dataclass(kw_only=True)
class Approval:
    by: str
    at: str
    data_hash: str
    note: str = ""


@dataclass
class MissingItem:
    key: str
    description: str


COLLECTIONS = ("columns", "walls", "openings", "stairs", "furniture", "rooms", "measured_dims")
_ENTITY_CLASS = {"columns": Column, "walls": Wall, "openings": Opening, "stairs": Stair,
                 "furniture": Furniture, "rooms": Room, "measured_dims": MeasuredDim}
DATA_SECTIONS = ("project", "axes") + COLLECTIONS + ("layers", "blocks")


# ─────────────────────────────────────────────────────────────────────────────
# KHO DỮ LIỆU
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectStore:
    project: ProjectInfo = field(default_factory=ProjectInfo)
    axes: Dict[str, AxisGroup] = field(default_factory=dict)          # "V", "H"
    columns: List[Column] = field(default_factory=list)
    walls: List[Wall] = field(default_factory=list)
    openings: List[Opening] = field(default_factory=list)
    stairs: List[Stair] = field(default_factory=list)
    furniture: List[Furniture] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    measured_dims: List[MeasuredDim] = field(default_factory=list)
    layers: Dict[str, LayerSpec] = field(default_factory=default_layers)   # vai trò → layer
    blocks: Dict[str, BlockDef] = field(default_factory=dict)              # block từ template
    sources: List[SourceFile] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)                      # vấn đề phát hiện khi đọc
    approvals: List[Approval] = field(default_factory=list)

    # ── truy vấn ─────────────────────────────────────────────────────────────

    def get(self, collection: str, eid: str):
        for e in getattr(self, collection):
            if e.id == eid:
                return e
        return None

    def axis_group_of(self, name: str) -> Optional[AxisGroup]:
        for g in self.axes.values():
            if name in g.names:
                return g
        return None

    def axis_offset(self, name: str) -> Optional[float]:
        g = self.axis_group_of(name)
        if g is None:
            raise StoreError(f"không có trục tên '{name}'")
        return g.offset_of(name)

    def point_or_reason(self, ref: PointRef) -> Tuple[Optional[Point], str]:
        """(toạ độ, "") hoặc (None, lý do chưa xác định được). StoreError nếu cú pháp sai / trục không tồn tại."""
        if isinstance(ref, (list, tuple)):
            if len(ref) != 2:
                raise StoreError(f"điểm phải có 2 toạ độ: {ref!r}")
            return (float(ref[0]), float(ref[1])), ""
        m = _REF_RE.match(str(ref))
        if not m:
            raise StoreError(f"điểm '{ref}' sai cú pháp (dùng '1/A', '1/A@dx,dy' hoặc [x, y])")
        a, b, dx, dy = m.groups()
        ga, gb = self.axis_group_of(a), self.axis_group_of(b)
        if ga is None or gb is None:
            raise StoreError(f"điểm '{ref}': không có trục '{a if ga is None else b}'")
        if ga.orientation == gb.orientation:
            raise StoreError(f"điểm '{ref}': hai trục cùng phương {ga.orientation}")
        v, h = (a, b) if ga.orientation == "V" else (b, a)
        x, y = self.axis_offset(v), self.axis_offset(h)
        unknown = [n for n, val in ((v, x), (h, y)) if val is None]
        if unknown:
            return None, f"trục {', '.join(unknown)} chưa có toạ độ (thiếu nhịp trục)"
        return (x + float(dx or 0.0), y + float(dy or 0.0)), ""

    def point(self, ref: PointRef) -> Optional[Point]:
        return self.point_or_reason(ref)[0]

    def column_center(self, col: Column) -> Optional[Point]:
        p = self.point(f"{col.axis_v}/{col.axis_h}")
        return None if p is None else (p[0] + col.dx, p[1] + col.dy)

    # ── khoá số liệu: đọc / ghi / xác nhận ───────────────────────────────────

    def _resolve_key(self, key: str):
        """khoá → (đối tượng chứa, tên trường, chỉ số trong list hoặc None)."""
        m = re.match(r"^axes:([VH])\.(spans)\[(\d+)\]$|^axes:([VH])\.(overall)$", key)
        if m:
            if m.group(1):
                g = self.axes.get(m.group(1))
                if g is None or int(m.group(3)) >= len(g.spans):
                    raise StoreError(f"khoá '{key}' không tồn tại")
                return g, "spans", int(m.group(3))
            g = self.axes.get(m.group(4))
            if g is None:
                raise StoreError(f"khoá '{key}' không tồn tại")
            return g, "overall", None
        m = re.match(r"^stairs:([^.]+)\.flights\[(\d+)\]\.(\w+)$", key)
        if m:
            st = self.get("stairs", m.group(1))
            if st is None or int(m.group(2)) >= len(st.flights):
                raise StoreError(f"khoá '{key}' không tồn tại")
            fl = st.flights[int(m.group(2))]
            if not hasattr(fl, m.group(3)):
                raise StoreError(f"khoá '{key}': vế thang không có trường '{m.group(3)}'")
            return st, f"flights[{m.group(2)}].{m.group(3)}", None
        m = re.match(r"^(\w+):([^.]+)\.(\w+)$", key)
        if not m or m.group(1) not in COLLECTIONS:
            raise StoreError(f"khoá '{key}' sai cú pháp")
        ent = self.get(m.group(1), m.group(2))
        if ent is None or m.group(3) not in {f.name for f in fields(ent)}:
            raise StoreError(f"khoá '{key}' không tồn tại")
        return ent, m.group(3), None

    def get_value(self, key: str):
        obj, name, idx = self._resolve_key(key)
        if name.startswith("flights["):
            i, attr = re.match(r"flights\[(\d+)\]\.(\w+)", name).groups()
            return getattr(obj.flights[int(i)], attr)
        val = getattr(obj, name)
        return val[idx] if idx is not None else val

    def get_provenance(self, key: str) -> Provenance:
        obj, name, idx = self._resolve_key(key)
        if isinstance(obj, AxisGroup):
            return obj.span_provenance(idx) if name == "spans" else (obj.overall_prov or obj.prov)
        return obj.provenance(name)

    def set_value(self, key: str, value, prov: Provenance) -> None:
        """Ghi một số liệu kèm nguồn gốc (nhập tay hoặc nội suy)."""
        obj, name, idx = self._resolve_key(key)
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise StoreError(f"{key}: giá trị không hữu hạn")
        if isinstance(obj, AxisGroup):
            if name == "spans":
                obj.spans[idx] = value
                obj.span_prov[idx] = prov
            else:
                obj.overall, obj.overall_prov = value, prov
            return
        if name.startswith("flights["):
            i, attr = re.match(r"flights\[(\d+)\]\.(\w+)", name).groups()
            if attr == "n_treads" and value is not None:
                if value != int(value):
                    raise StoreError(f"{key}: số bậc phải là số nguyên")
                value = int(value)
            setattr(obj.flights[int(i)], attr, value)
        else:
            setattr(obj, name, value)
        obj.field_prov[name] = prov

    def confirm(self, key: str, by: str, note: str = "") -> None:
        """Người dùng xác nhận một số liệu nội suy (ghi rõ người xác nhận)."""
        if not by.strip():
            raise StoreError("xác nhận phải ghi người xác nhận")
        prov = self.get_provenance(key)
        if prov.source != SRC_INTERP:
            raise StoreError(f"{key} không phải số liệu nội suy (nguồn: {prov.source})")
        ref = prov.ref + (f" | xác nhận: {note}" if note else "")
        self.set_value(key, self.get_value(key), Provenance(SRC_INTERP, ref, True, by.strip()))

    # ── thiếu số liệu / chưa xác nhận / trạng thái ───────────────────────────

    def missing(self) -> List[MissingItem]:
        out: List[MissingItem] = []
        for o, g in sorted(self.axes.items()):
            for i, s in enumerate(g.spans):
                if s is None:
                    out.append(MissingItem(f"axes:{o}.spans[{i}]",
                                           f"nhịp trục {g.names[i]}–{g.names[i + 1]}"))
        for c in self.columns:
            for f_ in ("b", "h"):
                if getattr(c, f_) is None:
                    out.append(MissingItem(f"columns:{c.id}.{f_}", f"kích thước {f_} của cột {c.id}"))
        for w in self.walls:
            if w.thickness is None:
                out.append(MissingItem(f"walls:{w.id}.thickness", f"chiều dày tường {w.id}"))
        for op in self.openings:
            for f_ in ("offset", "width"):
                if getattr(op, f_) is None:
                    out.append(MissingItem(f"openings:{op.id}.{f_}",
                                           f"{'vị trí' if f_ == 'offset' else 'bề rộng'} cửa {op.id}"))
        for st in self.stairs:
            for i, fl in enumerate(st.flights):
                for f_ in ("width", "going", "n_treads"):
                    if getattr(fl, f_) is None:
                        out.append(MissingItem(f"stairs:{st.id}.flights[{i}].{f_}",
                                               f"{f_} của vế {i + 1} thang {st.id}"))
        return out

    def unconfirmed(self) -> List[Tuple[str, Provenance]]:
        """Mọi số liệu nội suy chưa có người xác nhận."""
        out: List[Tuple[str, Provenance]] = []
        for o, g in sorted(self.axes.items()):
            for i, p in enumerate(g.span_prov):
                if p is not None and p.source == SRC_INTERP and not p.confirmed:
                    out.append((f"axes:{o}.spans[{i}]", p))
            if g.overall_prov and g.overall_prov.source == SRC_INTERP and not g.overall_prov.confirmed:
                out.append((f"axes:{o}.overall", g.overall_prov))
        for coll in COLLECTIONS:
            for e in getattr(self, coll):
                if e.prov.source == SRC_INTERP and not e.prov.confirmed:
                    out.append((f"{coll}:{e.id}", e.prov))
                for name, p in sorted(e.field_prov.items()):
                    if p.source == SRC_INTERP and not p.confirmed:
                        out.append((f"{coll}:{e.id}.{name}", p))
        return out

    def data_hash(self, section: Optional[str] = None) -> str:
        d = self.to_dict()
        payload = d[section] if section else {k: d[k] for k in DATA_SECTIONS}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def section_hashes(self) -> Dict[str, str]:
        return {s: self.data_hash(s) for s in DATA_SECTIONS}

    def approve(self, by: str, at: str, note: str = "") -> Approval:
        """Ghi phê duyệt dữ liệu. Không cho duyệt khi còn thiếu kích thước hoặc còn số liệu nội suy chưa xác nhận."""
        if not by.strip():
            raise StoreError("phê duyệt phải ghi người duyệt")
        if self.missing():
            raise StoreError(f"chưa duyệt được: còn {len(self.missing())} kích thước thiếu")
        if self.unconfirmed():
            raise StoreError(f"chưa duyệt được: còn {len(self.unconfirmed())} số liệu nội suy chưa xác nhận")
        a = Approval(by=by.strip(), at=at, data_hash=self.data_hash(), note=note)
        self.approvals.append(a)
        return a

    def status(self) -> Dict[str, Any]:
        """Trạng thái duyệt — TÍNH từ dữ liệu, không gõ tay."""
        n_missing, n_unconf = len(self.missing()), len(self.unconfirmed())
        current = self.data_hash()
        approved = [a for a in self.approvals if a.data_hash == current]
        if n_missing:
            state = "THIEU_KICH_THUOC"
        elif n_unconf:
            state = "CHO_XAC_NHAN_NOI_SUY"
        elif approved:
            state = "DA_DUYET"
        else:
            state = "CHO_DUYET"
        return {"trang_thai": state, "so_lieu_thieu": n_missing, "noi_suy_chua_xac_nhan": n_unconf,
                "duyet_boi": approved[-1].by if approved else "", "data_hash": current}

    # ── tuần tự hoá ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        def ent(e) -> Dict[str, Any]:
            d: Dict[str, Any] = {}
            for f_ in fields(e):
                v = getattr(e, f_.name)
                if f_.name == "prov":
                    d["prov"] = v.to_dict()
                elif f_.name == "field_prov":
                    d["field_prov"] = {k: p.to_dict() for k, p in sorted(v.items())}
                elif f_.name == "flights":
                    d["flights"] = [{g.name: getattr(fl, g.name) for g in fields(fl)} for fl in v]
                else:
                    d[f_.name] = copy.deepcopy(list(v) if isinstance(v, tuple) else v)
            return d

        axes = {}
        for o, g in sorted(self.axes.items()):
            axes[o] = {"orientation": g.orientation, "names": list(g.names), "spans": list(g.spans),
                       "overall": g.overall, "origin": g.origin, "prov": g.prov.to_dict(),
                       "span_prov": [p.to_dict() if p else None for p in g.span_prov],
                       "overall_prov": g.overall_prov.to_dict() if g.overall_prov else None}
        return {
            "schema": STORE_SCHEMA,
            "project": {f_.name: getattr(self.project, f_.name) for f_ in fields(self.project)},
            "axes": axes,
            **{c: [ent(e) for e in getattr(self, c)] for c in COLLECTIONS},
            "layers": {r: vars(s).copy() for r, s in sorted(self.layers.items())},
            "blocks": {n: b.to_dict() for n, b in sorted(self.blocks.items())},
            "sources": [{f_.name: getattr(s, f_.name) for f_ in fields(s)} for s in self.sources],
            "issues": [{f_.name: getattr(i, f_.name) for f_ in fields(i)} for i in self.issues],
            "approvals": [{f_.name: getattr(a, f_.name) for f_ in fields(a)} for a in self.approvals],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProjectStore":
        """Đọc kho dữ liệu. Chấp nhận dạng rút gọn để nhập tay:
          - "nguon_mac_dinh": ref mặc định cho mọi số liệu không ghi prov (vd "[Trang 1] KT-01");
          - "column_types": {"C1": {"b": 220, "h": 220, "ref": "..."}} điền b/h cho cột theo loại (mark).
        """
        schema = d.get("schema", STORE_SCHEMA)
        if schema != STORE_SCHEMA:
            raise StoreError(f"schema lạ '{schema}' (cần {STORE_SCHEMA})")
        default_ref = str(d.get("nguon_mac_dinh", ""))

        def prov(x):
            return Provenance.from_any(x, default_ref)

        store = cls()
        store.project = ProjectInfo(**d.get("project", {}))
        if int(store.project.scale) <= 0:
            raise StoreError("tỷ lệ bản vẽ phải > 0")
        for o, g in d.get("axes", {}).items():
            grp = AxisGroup(orientation=g.get("orientation", o), names=[str(n) for n in g["names"]],
                            spans=[None if s is None else float(s) for s in g.get("spans", [])],
                            overall=None if g.get("overall") is None else float(g["overall"]),
                            origin=float(g.get("origin", 0.0)), prov=prov(g.get("prov")),
                            span_prov=[None if p is None else prov(p) for p in g.get("span_prov", [])],
                            overall_prov=None if g.get("overall_prov") is None else prov(g["overall_prov"]))
            if grp.orientation != o:
                raise StoreError(f"nhóm trục khoá '{o}' nhưng orientation = '{grp.orientation}'")
            store.axes[o] = grp
        all_names = [n for g in store.axes.values() for n in g.names]
        if len(set(all_names)) != len(all_names):
            raise StoreError("tên trục trùng giữa hai nhóm V và H")

        col_types = d.get("column_types", {})
        for coll in COLLECTIONS:
            klass = _ENTITY_CLASS[coll]
            for raw in d.get(coll, []):
                raw = dict(raw)
                raw["prov"] = prov(raw.get("prov"))
                raw["field_prov"] = {k: prov(p) for k, p in raw.get("field_prov", {}).items()}
                if coll == "stairs":
                    raw["flights"] = [StairFlight(**fl) for fl in raw.get("flights", [])]
                if coll == "columns" and raw.get("mark") in col_types:
                    t = col_types[raw["mark"]]
                    for f_ in ("b", "h"):
                        if raw.get(f_) is None and t.get(f_) is not None:
                            raw[f_] = float(t[f_])
                            raw["field_prov"].setdefault(
                                f_, Provenance(SRC_USER, t.get("ref", default_ref) or f"bảng loại cột {raw['mark']}"))
                known = {f_.name for f_ in fields(klass)}
                extra = set(raw) - known
                if extra:
                    raise StoreError(f"{coll} '{raw.get('id')}': trường lạ {sorted(extra)}")
                try:
                    store_obj = klass(**raw)
                except TypeError as e:
                    raise StoreError(f"{coll} '{raw.get('id')}': {e}")
                getattr(store, coll).append(store_obj)
            ids = [e.id for e in getattr(store, coll)]
            dup = sorted({i for i in ids if ids.count(i) > 1})
            if dup:
                raise StoreError(f"{coll}: mã trùng {dup}")
        if "layers" in d:
            layers = default_layers()
            for r, s in d["layers"].items():
                layers[r] = LayerSpec(**s)
            store.layers = layers
        store.blocks = {n: BlockDef.from_dict(b) for n, b in d.get("blocks", {}).items()}
        store.sources = [SourceFile(**s) for s in d.get("sources", [])]
        store.issues = [Issue(**i) for i in d.get("issues", [])]
        store.approvals = [Approval(**a) for a in d.get("approvals", [])]
        return store

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "ProjectStore":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
