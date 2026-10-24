# -*- coding: utf-8 -*-
"""
DANH SÁCH LỆNH VẼ (DrawingPlan) — đầu ra chuẩn duy nhất của 10 skill.

Skill không gọi thẳng ezdxf/AutoCAD: skill thêm Op vào DrawingPlan, rồi bộ xuất biến plan thành
DXF (ezdxf), AutoLISP (chạy trong AutoCAD) hoặc JSON (giao cho máy chủ MCP). Nhờ vậy:
  - Validator kiểm tra cùng một dữ liệu bất kể xuất ra đâu;
  - "chỉ sửa phần liên quan": chạy lại một skill = xoá đúng Op của skill đó rồi vẽ lại,
    dấu vân tay (fingerprint) Op của các skill khác phải giữ nguyên.

Mọi toạ độ là mm trong model space, góc tính bằng độ (ngược chiều kim đồng hồ, 0° = trục +X).

Dữ liệu (`data`) theo từng loại Op:
  line       p1, p2
  pline      points (≥2 điểm), closed (bool)
  circle     center, r
  arc        center, r, start_angle, end_angle            (vẽ ngược chiều kim đồng hồ từ start → end)
  text       insert, text, height, rotation, align         (align: LEFT | CENTER | RIGHT | MIDDLE_CENTER |
                                                            MIDDLE_LEFT | MIDDLE_RIGHT | TOP_CENTER | BOTTOM_CENTER)
  mtext      insert, text, height, width, attach           (attach: TOP_LEFT | TOP_CENTER | MIDDLE_CENTER ...)
  insert     block, insert, rotation, scale ([sx, sy])
  hatch      boundaries (list vòng kín; vòng đầu là biên ngoài, các vòng sau là lỗ), pattern,
             pattern_scale, angle
  dim_linear p1, p2 (điểm đo), base (một điểm trên đường kích thước), angle (0 = đo theo X, 90 = theo Y),
             dimstyle; tuỳ chọn text_override (chỉ dùng khi có lý do, Validator sẽ đánh dấu NGHI_VAN)
Khoá tuỳ chọn cho mọi Op: color (ACI, mặc định ByLayer), linetype, lineweight.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from tools.cad_drafting.layers import LayerSpec, ROLE_OWNER

PLAN_SCHEMA = "23hg-cad-plan/1"

REQUIRED_KEYS: Dict[str, tuple] = {
    "line": ("p1", "p2"),
    "pline": ("points", "closed"),
    "circle": ("center", "r"),
    "arc": ("center", "r", "start_angle", "end_angle"),
    "text": ("insert", "text", "height", "rotation", "align"),
    "mtext": ("insert", "text", "height", "width", "attach"),
    "insert": ("block", "insert", "rotation", "scale"),
    "hatch": ("boundaries", "pattern", "pattern_scale", "angle"),
    "dim_linear": ("p1", "p2", "base", "angle", "dimstyle"),
}
OP_KINDS = tuple(REQUIRED_KEYS)
TEXT_ALIGNS = ("LEFT", "CENTER", "RIGHT", "MIDDLE_CENTER", "MIDDLE_LEFT", "MIDDLE_RIGHT",
               "TOP_CENTER", "BOTTOM_CENTER")
MTEXT_ATTACH = ("TOP_LEFT", "TOP_CENTER", "TOP_RIGHT", "MIDDLE_LEFT", "MIDDLE_CENTER", "MIDDLE_RIGHT",
                "BOTTOM_LEFT", "BOTTOM_CENTER", "BOTTOM_RIGHT")
# Op trong định nghĩa block chỉ được dùng các loại hình học đơn giản này
BLOCK_PRIMITIVES = ("line", "pline", "circle", "arc", "text")


class PlanError(ValueError):
    """Op sai dạng — lỗi lập trình của skill, không phải lỗi dữ liệu dự án."""


def _pt(value, what: str) -> List[float]:
    try:
        x, y = value
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        raise PlanError(f"{what}: cần điểm [x, y], nhận {value!r}")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise PlanError(f"{what}: toạ độ không hữu hạn {value!r}")
    return [x, y]


def _num(value, what: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise PlanError(f"{what}: cần số, nhận {value!r}")
    if not math.isfinite(v):
        raise PlanError(f"{what}: số không hữu hạn {value!r}")
    return v


def normalize_op_data(kind: str, data: Dict[str, Any], where: str = "") -> Dict[str, Any]:
    """Kiểm tra và chuẩn hoá dữ liệu một Op (điểm → [float, float], số → float). PlanError nếu sai."""
    if kind not in REQUIRED_KEYS:
        raise PlanError(f"{where}: loại Op lạ '{kind}' (hợp lệ: {', '.join(OP_KINDS)})")
    missing = [k for k in REQUIRED_KEYS[kind] if k not in data]
    if missing:
        raise PlanError(f"{where}: Op '{kind}' thiếu khoá {missing}")
    d = dict(data)
    w = f"{where} {kind}"
    if kind == "line":
        d["p1"], d["p2"] = _pt(d["p1"], w + ".p1"), _pt(d["p2"], w + ".p2")
    elif kind == "pline":
        pts = [_pt(p, w + ".points") for p in d["points"]]
        if len(pts) < 2:
            raise PlanError(f"{w}: pline cần ít nhất 2 điểm")
        d["points"], d["closed"] = pts, bool(d["closed"])
    elif kind == "circle":
        d["center"], d["r"] = _pt(d["center"], w + ".center"), _num(d["r"], w + ".r")
        if d["r"] <= 0:
            raise PlanError(f"{w}: bán kính phải > 0")
    elif kind == "arc":
        d["center"], d["r"] = _pt(d["center"], w + ".center"), _num(d["r"], w + ".r")
        d["start_angle"], d["end_angle"] = _num(d["start_angle"], w), _num(d["end_angle"], w)
        if d["r"] <= 0:
            raise PlanError(f"{w}: bán kính phải > 0")
    elif kind == "text":
        d["insert"], d["height"] = _pt(d["insert"], w + ".insert"), _num(d["height"], w + ".height")
        d["rotation"], d["text"] = _num(d["rotation"], w + ".rotation"), str(d["text"])
        if d["align"] not in TEXT_ALIGNS:
            raise PlanError(f"{w}: align lạ '{d['align']}'")
        if d["height"] <= 0 or not d["text"]:
            raise PlanError(f"{w}: chữ rỗng hoặc chiều cao ≤ 0")
    elif kind == "mtext":
        d["insert"], d["height"] = _pt(d["insert"], w + ".insert"), _num(d["height"], w + ".height")
        d["width"], d["text"] = _num(d["width"], w + ".width"), str(d["text"])
        if d["attach"] not in MTEXT_ATTACH:
            raise PlanError(f"{w}: attach lạ '{d['attach']}'")
        if d["height"] <= 0 or not d["text"]:
            raise PlanError(f"{w}: chữ rỗng hoặc chiều cao ≤ 0")
    elif kind == "insert":
        d["insert"], d["rotation"] = _pt(d["insert"], w + ".insert"), _num(d["rotation"], w + ".rotation")
        d["scale"] = _pt(d["scale"], w + ".scale")
        d["block"] = str(d["block"])
    elif kind == "hatch":
        loops = []
        for loop in d["boundaries"]:
            pts = [_pt(p, w + ".boundaries") for p in loop]
            if len(pts) < 3:
                raise PlanError(f"{w}: vòng biên hatch cần ≥ 3 điểm")
            loops.append(pts)
        if not loops:
            raise PlanError(f"{w}: hatch không có biên")
        d["boundaries"] = loops
        d["pattern"] = str(d["pattern"])
        d["pattern_scale"], d["angle"] = _num(d["pattern_scale"], w), _num(d["angle"], w)
        if d["pattern_scale"] <= 0:
            raise PlanError(f"{w}: pattern_scale phải > 0")
    elif kind == "dim_linear":
        d["p1"], d["p2"], d["base"] = _pt(d["p1"], w), _pt(d["p2"], w), _pt(d["base"], w)
        d["angle"] = _num(d["angle"], w + ".angle")
        d["dimstyle"] = str(d["dimstyle"])
        if "text_override" in d and d["text_override"] is not None:
            d["text_override"] = str(d["text_override"])
    for opt in ("color", "lineweight"):
        if opt in d and d[opt] is not None:
            d[opt] = int(d[opt])
    return d


def dim_measurement(data: Dict[str, Any]) -> float:
    """Giá trị đo của dim_linear = hình chiếu p1→p2 lên phương của đường kích thước."""
    a = math.radians(float(data["angle"]))
    dx = data["p2"][0] - data["p1"][0]
    dy = data["p2"][1] - data["p1"][1]
    return abs(dx * math.cos(a) + dy * math.sin(a))


@dataclass
class Op:
    kind: str
    role: str                         # vai trò layer (xem layers.DEFAULT_ROLES)
    skill: str                        # "01".."10" — skill đã tạo Op
    eid: str                          # mã ổn định, duy nhất trong plan, vd "03/W1/outline/0"
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "role": self.role, "skill": self.skill, "eid": self.eid, "data": self.data}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Op":
        return cls(kind=d["kind"], role=d["role"], skill=d["skill"], eid=d["eid"],
                   data=normalize_op_data(d["kind"], d["data"], d.get("eid", "")))


@dataclass
class BlockDef:
    """Định nghĩa block: hình học trong hệ toạ độ riêng của block, điểm chèn tại (0, 0)."""
    name: str
    ops: List[Dict[str, Any]]                  # [{"kind": "line", "data": {...}}, ...] — chỉ BLOCK_PRIMITIVES
    size: List[float] = field(default_factory=lambda: [0.0, 0.0])   # [rộng X, sâu Y] mm, để kiểm tra va chạm
    description: str = ""
    source: str = "thu_vien"                   # "thu_vien" (thư viện chuẩn) | "mau" (từ template người dùng)

    def __post_init__(self):
        norm = []
        for i, o in enumerate(self.ops):
            if o.get("kind") not in BLOCK_PRIMITIVES:
                raise PlanError(f"block {self.name}: loại '{o.get('kind')}' không dùng được trong block")
            norm.append({"kind": o["kind"], "data": normalize_op_data(o["kind"], o["data"], f"block {self.name}[{i}]")})
        self.ops = norm
        self.size = [float(self.size[0]), float(self.size[1])]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ops": self.ops, "size": self.size,
                "description": self.description, "source": self.source}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BlockDef":
        return cls(name=d["name"], ops=d.get("ops", []), size=d.get("size", [0.0, 0.0]),
                   description=d.get("description", ""), source=d.get("source", "thu_vien"))


@dataclass
class DrawingPlan:
    layers: Dict[str, LayerSpec] = field(default_factory=dict)       # vai trò → layer thật
    blocks: Dict[str, BlockDef] = field(default_factory=dict)
    dimstyles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    text_style: Dict[str, str] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)               # dự án, tỷ lệ, khung bản vẽ (sheet_frame)...
    ops: List[Op] = field(default_factory=list)

    # ── thêm / xoá ───────────────────────────────────────────────────────────

    def add(self, kind: str, role: str, skill: str, eid: str, **data) -> Op:
        if role not in self.layers:
            raise PlanError(f"{eid}: vai trò layer '{role}' chưa khai báo trong plan")
        if any(o.eid == eid for o in self.ops):
            raise PlanError(f"eid trùng: {eid}")
        op = Op(kind=kind, role=role, skill=skill, eid=eid, data=normalize_op_data(kind, data, eid))
        self.ops.append(op)
        return op

    def add_block(self, block: BlockDef) -> None:
        """Thêm định nghĩa block (trùng tên mà khác nội dung → lỗi, không ghi đè ngầm)."""
        old = self.blocks.get(block.name)
        if old is not None and old.to_dict() != block.to_dict():
            raise PlanError(f"block '{block.name}' đã có với nội dung khác")
        self.blocks[block.name] = block

    def remove_skill(self, skill: str) -> int:
        """Xoá mọi Op của một skill (trước khi skill vẽ lại). Trả số Op đã xoá."""
        before = len(self.ops)
        self.ops = [o for o in self.ops if o.skill != skill]
        return before - len(self.ops)

    # ── truy vấn ─────────────────────────────────────────────────────────────

    def ops_of(self, skill: Optional[str] = None, role: Optional[str] = None,
               kind: Optional[str] = None) -> List[Op]:
        return [o for o in self.ops
                if (skill is None or o.skill == skill) and (role is None or o.role == role)
                and (kind is None or o.kind == kind)]

    def layer_name(self, role: str) -> str:
        return self.layers[role].name

    def fingerprint(self, skill: str) -> str:
        """Dấu vân tay các Op của một skill (sha256 của JSON chuẩn hoá)."""
        payload = json.dumps([o.to_dict() for o in self.ops if o.skill == skill],
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def fingerprints(self) -> Dict[str, str]:
        return {s: self.fingerprint(s) for s in sorted({o.skill for o in self.ops})}

    def count_by_role(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for o in self.ops:
            out[o.role] = out.get(o.role, 0) + 1
        return out

    def ownership_violations(self) -> List[Op]:
        """Op nằm trên vai trò không thuộc skill tạo ra nó."""
        return [o for o in self.ops if ROLE_OWNER.get(o.role) != o.skill]

    # ── tuần tự hoá (đây cũng là giao thức gửi máy chủ MCP) ──────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "units": "mm",
            "meta": copy.deepcopy(self.meta),
            "text_style": dict(self.text_style),
            "layers": {r: vars(s).copy() for r, s in self.layers.items()},
            "dimstyles": copy.deepcopy(self.dimstyles),
            "blocks": {n: b.to_dict() for n, b in self.blocks.items()},
            "ops": [o.to_dict() for o in self.ops],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DrawingPlan":
        if d.get("schema") != PLAN_SCHEMA:
            raise PlanError(f"schema plan lạ: {d.get('schema')!r} (cần {PLAN_SCHEMA})")
        return cls(
            layers={r: LayerSpec(**s) for r, s in d.get("layers", {}).items()},
            blocks={n: BlockDef.from_dict(b) for n, b in d.get("blocks", {}).items()},
            dimstyles=copy.deepcopy(d.get("dimstyles", {})),
            text_style=dict(d.get("text_style", {})),
            meta=copy.deepcopy(d.get("meta", {})),
            ops=[Op.from_dict(o) for o in d.get("ops", [])],
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "DrawingPlan":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def iter_points(op_or_block_item: Dict[str, Any] | Op) -> Iterable[List[float]]:
    """Mọi điểm định nghĩa của một Op (dùng cho bao hình, kiểm tra nằm trong khung)."""
    if isinstance(op_or_block_item, Op):
        kind, d = op_or_block_item.kind, op_or_block_item.data
    else:
        kind, d = op_or_block_item["kind"], op_or_block_item["data"]
    if kind == "line":
        yield d["p1"]
        yield d["p2"]
    elif kind == "pline":
        yield from d["points"]
    elif kind in ("circle", "arc"):
        cx, cy = d["center"]
        r = d["r"]
        yield from ([cx - r, cy - r], [cx + r, cy + r])
    elif kind in ("text", "mtext", "insert"):
        yield d["insert"]
    elif kind == "hatch":
        for loop in d["boundaries"]:
            yield from loop
    elif kind == "dim_linear":
        yield d["p1"]
        yield d["p2"]
        yield d["base"]
