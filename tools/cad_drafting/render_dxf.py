# -*- coding: utf-8 -*-
"""
BỘ XUẤT DXF — biến DrawingPlan thành file DXF bằng ezdxf (không cần AutoCAD).

Quy ước:
  - Đơn vị mm: $INSUNITS = 4, $MEASUREMENT = 1 (hệ mét).
  - Kiểu đường: bảng kiểu đường chuẩn của ezdxf được ghi lại theo đúng độ dài của acadiso.lin
    (vd CENTER = 31,75 / −6,35 / 6,35 / −6,35 mm) để DXF và AutoLISP (nạp từ acadiso.lin) cho cùng nét.
  - $LTSCALE = tỷ lệ bản vẽ × 0,5 (LTSCALE_FACTOR). Ở 1:100 → 50: nét gạch CENTER in ra giấy
    31,75 × 50 / 100 ≈ 15,9 mm, khe hở ≈ 3,2 mm — đọc rõ trên khổ A3/A1 mà không thành nét liền.
  - Mỗi thực thể trong model space mang XDATA appid "23HG_CAD": [(1000, eid), (1000, skill)] để AutoCAD /
    máy chủ MCP về sau sửa đúng đối tượng ("chỉ sửa phần liên quan").
  - Không bỏ im lặng: Op không vẽ được (block chưa định nghĩa, mẫu hatch lạ, layer sai tên...) ghi vào
    "bo_qua" kèm lý do; thuộc tính phải sửa cho hợp lệ (nét in lạ, màu lạ...) ghi vào "canh_bao".
    Master đối chiếu số thực thể đọc lại (read_back_counts) với plan.count_by_role() nên Op bị bỏ sẽ lộ ra.
  - Ảnh nền (underlays): ghi TÊN FILE tương đối (cùng thư mục với DXF), không ghi đường dẫn máy.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence

from tools.cad_drafting.layers import DEFAULT_ROLES, TEXT_STYLE, LayerSpec
from tools.cad_drafting.plan import DrawingPlan, Op

APPID = "23HG_CAD"
LTSCALE_FACTOR = 0.5                 # $LTSCALE = tỷ lệ bản vẽ × LTSCALE_FACTOR (kiểu đường theo acadiso.lin)
XDATA_MAX_BYTES = 255                # giới hạn chuỗi nhóm 1000 trong XDATA

# Bảng kiểu đường theo acadiso.lin (= acad.lin × 25,4; đơn vị mm; số âm là khe hở, 0 là chấm).
# Ghi đè bảng chuẩn của ezdxf (bảng đó dùng độ dài khác) để DXF và AutoLISP (nạp acadiso.lin) cho cùng nét.
ACADISO_LINETYPES = (
    ("BORDER", "Border __ __ . __ __ . __ __ . __ __ . __ __ .", (12.7, -6.35, 12.7, -6.35, 0.0, -6.35)),
    ("BORDER2", "Border (.5x) __.__.__.__.__.__.__.__.__.__.__.", (6.35, -3.175, 6.35, -3.175, 0.0, -3.175)),
    ("BORDERX2", "Border (2x) ____  ____  .  ____  ____  .  ___", (25.4, -12.7, 25.4, -12.7, 0.0, -12.7)),
    ("CENTER", "Center ____ _ ____ _ ____ _ ____ _ ____ _ ____", (31.75, -6.35, 6.35, -6.35)),
    ("CENTER2", "Center (.5x) ___ _ ___ _ ___ _ ___ _ ___ _ ___", (19.05, -3.175, 3.175, -3.175)),
    ("CENTERX2", "Center (2x) ________  __  ________  __  _____", (63.5, -12.7, 12.7, -12.7)),
    ("DASHDOT", "Dash dot __ . __ . __ . __ . __ . __ . __ . __", (12.7, -6.35, 0.0, -6.35)),
    ("DASHDOT2", "Dash dot (.5x) _._._._._._._._._._._._._._._.", (6.35, -3.175, 0.0, -3.175)),
    ("DASHDOTX2", "Dash dot (2x) ____  .  ____  .  ____  .  ___", (25.4, -12.7, 0.0, -12.7)),
    ("DASHED", "Dashed __ __ __ __ __ __ __ __ __ __ __ __ __ _", (12.7, -6.35)),
    ("DASHED2", "Dashed (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _", (6.35, -3.175)),
    ("DASHEDX2", "Dashed (2x) ____  ____  ____  ____  ____  ___", (25.4, -12.7)),
    ("DIVIDE", "Divide ____ . . ____ . . ____ . . ____ . . ____", (12.7, -6.35, 0.0, -6.35, 0.0, -6.35)),
    ("DIVIDE2", "Divide (.5x) __..__..__..__..__..__..__..__.._", (6.35, -3.175, 0.0, -3.175, 0.0, -3.175)),
    ("DIVIDEX2", "Divide (2x) ________  .  .  ________  .  .  _", (25.4, -12.7, 0.0, -12.7, 0.0, -12.7)),
    ("DOT", "Dot . . . . . . . . . . . . . . . . . . . . . . . .", (0.0, -6.35)),
    ("DOT2", "Dot (.5x) ........................................", (0.0, -3.175)),
    ("DOTX2", "Dot (2x) .  .  .  .  .  .  .  .  .  .  .  .  .  .", (0.0, -12.7)),
    ("HIDDEN", "Hidden __ __ __ __ __ __ __ __ __ __ __ __ __ __", (6.35, -3.175)),
    ("HIDDEN2", "Hidden (.5x) _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _", (3.175, -1.5875)),
    ("HIDDENX2", "Hidden (2x) ____ ____ ____ ____ ____ ____ ____", (12.7, -6.35)),
    ("PHANTOM", "Phantom ______  __  __  ______  __  __  ______", (31.75, -6.35, 6.35, -6.35, 6.35, -6.35)),
    ("PHANTOM2", "Phantom (.5x) ___ _ _ ___ _ _ ___ _ _ ___ _ _", (15.875, -3.175, 3.175, -3.175, 3.175, -3.175)),
    ("PHANTOMX2", "Phantom (2x) ____________    ____    ____   _", (63.5, -12.7, 12.7, -12.7, 12.7, -12.7)),
)

TEXT_ALIGN_MAP = {                   # align của plan → tên TextEntityAlignment của ezdxf
    "LEFT": "LEFT", "CENTER": "CENTER", "RIGHT": "RIGHT", "MIDDLE_CENTER": "MIDDLE_CENTER",
    "MIDDLE_LEFT": "MIDDLE_LEFT", "MIDDLE_RIGHT": "MIDDLE_RIGHT", "TOP_CENTER": "TOP_CENTER",
    "BOTTOM_CENTER": "BOTTOM_CENTER",
}


def _ezdxf():
    import ezdxf  # noqa: WPS433 — nạp lười để module import được cả khi chỉ cần hằng số
    return ezdxf


def ltscale_for(scale: Any) -> float:
    """$LTSCALE theo tỷ lệ bản vẽ (xem docstring module). Tỷ lệ thiếu/sai → 1:100."""
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = 100.0
    if not math.isfinite(s) or s <= 0:
        s = 100.0
    return s * LTSCALE_FACTOR


def _setup_linetypes(doc) -> None:
    """Ghi lại bảng kiểu đường theo acadiso.lin (ACADISO_LINETYPES), thay cho độ dài mặc định của ezdxf."""
    for name, desc, elements in ACADISO_LINETYPES:
        pattern = [round(sum(abs(e) for e in elements), 6)] + [float(e) for e in elements]
        if name in doc.linetypes:
            doc.linetypes.remove(name)
        doc.linetypes.new(name, dxfattribs={"description": desc, "pattern": pattern})


def _find_linetype(doc, name: str) -> Optional[str]:
    """Tên kiểu đường đúng như trong bảng LTYPE (không phân biệt hoa thường), None nếu không có."""
    want = str(name).strip().upper()
    for lt in doc.linetypes:
        if lt.dxf.name.upper() == want:
            return lt.dxf.name
    return None


def _valid_lineweight(value: Any, what: str, warn: List[str]) -> Optional[int]:
    from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
    try:
        lw = int(value)
    except (TypeError, ValueError):
        warn.append(f"{what}: nét in '{value}' không phải số — dùng ByLayer")
        return None
    if lw in (-3, -2, -1) or lw in VALID_DXF_LINEWEIGHTS:
        return lw
    near = min(VALID_DXF_LINEWEIGHTS, key=lambda v: (abs(v - lw), v))
    warn.append(f"{what}: nét in {lw} không thuộc bảng nét DXF — đổi thành {near}")
    return near


def _valid_color(value: Any, what: str, warn: List[str]) -> Optional[int]:
    try:
        c = int(value)
    except (TypeError, ValueError):
        warn.append(f"{what}: màu '{value}' không phải số ACI — dùng ByLayer")
        return None
    if 0 <= c <= 256:
        return c
    warn.append(f"{what}: màu ACI {c} ngoài khoảng 0–256 — dùng ByLayer")
    return None


def _entity_attribs(doc, op_data: Dict[str, Any], layer: str, what: str, warn: List[str]) -> Dict[str, Any]:
    """dxfattribs chung: layer + màu / kiểu đường / nét in tuỳ chọn của Op."""
    attribs: Dict[str, Any] = {"layer": layer}
    if op_data.get("color") is not None:
        c = _valid_color(op_data["color"], what, warn)
        if c is not None:
            attribs["color"] = c
    if op_data.get("lineweight") is not None:
        lw = _valid_lineweight(op_data["lineweight"], what, warn)
        if lw is not None:
            attribs["lineweight"] = lw
    if op_data.get("linetype"):
        lt = _find_linetype(doc, op_data["linetype"])
        if lt is None:
            warn.append(f"{what}: kiểu đường '{op_data['linetype']}' không có trong bảng LTYPE — dùng ByLayer")
        else:
            attribs["linetype"] = lt
    return attribs


def _xdata(entity, eid: str, skill: str, warn: List[str]) -> None:
    for label, value in (("eid", eid), ("skill", skill)):
        if len(str(value).encode("utf-8")) > XDATA_MAX_BYTES:
            warn.append(f"{eid}: {label} dài hơn {XDATA_MAX_BYTES} byte — XDATA bị cắt, AutoCAD/MCP có thể không "
                        f"tìm lại đúng đối tượng")
    entity.set_xdata(APPID, [(1000, str(eid)[:XDATA_MAX_BYTES]), (1000, str(skill)[:XDATA_MAX_BYTES])])


def _single_line(text: str, what: str, warn: List[str]) -> str:
    """TEXT một dòng: ký tự xuống dòng đổi thành khoảng trắng (có cảnh báo)."""
    if "\n" in text or "\r" in text:
        warn.append(f"{what}: TEXT không chứa được xuống dòng — đã nối thành một dòng")
        text = " ".join(part for part in text.replace("\r", "\n").split("\n"))
    return text


def _mtext_content(text: str) -> str:
    """Nội dung MTEXT: xuống dòng '\\n' → mã đoạn '\\P' (mã MTEXT có sẵn trong chuỗi giữ nguyên)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\P")


# ── dựng các bảng ────────────────────────────────────────────────────────────

def _setup_text_style(doc, plan: DrawingPlan) -> str:
    name = (plan.text_style or {}).get("name") or TEXT_STYLE["name"]
    font = (plan.text_style or {}).get("font") or TEXT_STYLE["font"]
    if name in doc.styles:
        doc.styles.get(name).dxf.font = font
    else:
        doc.styles.new(name, dxfattribs={"font": font})
    doc.header["$TEXTSTYLE"] = name
    return name


def _setup_layers(doc, plan: DrawingPlan, warn: List[str]) -> Dict[str, Optional[str]]:
    """Tạo layer theo plan.layers. Trả vai trò → tên layer (None nếu không tạo được)."""
    from ezdxf.lldxf.validator import is_valid_layer_name
    out: Dict[str, Optional[str]] = {}
    for role, spec in plan.layers.items():
        if not is_valid_layer_name(spec.name):
            warn.append(f"layer vai trò '{role}': tên '{spec.name}' không hợp lệ trong DXF — các đối tượng của vai trò "
                        f"này không vẽ được")
            out[role] = None
            continue
        out[role] = _make_layer(doc, spec, f"layer {spec.name}", warn)
    return out


def _make_layer(doc, spec: LayerSpec, what: str, warn: List[str]) -> str:
    attribs: Dict[str, Any] = {}
    c = _valid_color(spec.color, what, warn)
    if c is not None and 1 <= c <= 255:
        attribs["color"] = c
    elif c is not None:
        warn.append(f"{what}: màu layer phải trong 1–255, nhận {c} — dùng 7")
        attribs["color"] = 7
    lt = _find_linetype(doc, spec.linetype or "Continuous")
    if lt is None:
        warn.append(f"{what}: kiểu đường '{spec.linetype}' không có trong bảng kiểu đường chuẩn — dùng Continuous")
        lt = "Continuous"
    attribs["linetype"] = lt
    lw = _valid_lineweight(spec.lineweight, what, warn)
    if lw is not None:
        attribs["lineweight"] = lw
    if spec.name in doc.layers:
        layer = doc.layers.get(spec.name)
        for k, v in attribs.items():
            layer.dxf.set(k, v)
    else:
        layer = doc.layers.add(spec.name, **attribs)
    layer.dxf.plot = 1 if spec.plot else 0
    if spec.description:
        layer.description = spec.description
    return spec.name


def _setup_dimstyles(doc, plan: DrawingPlan, warn: List[str]) -> List[str]:
    """Kiểu kích thước theo plan.dimstyles (biến DIM* chữ thường như layers.dimstyle_tcvn).
    Đầu đo đặt bằng set_arrows(blk=...) để ezdxf tạo block mũi tên (_ARCHTICK)."""
    ezdxf = _ezdxf()
    made: List[str] = []
    for name, dimvars in plan.dimstyles.items():
        ds = doc.dimstyles.get(name) if name in doc.dimstyles else doc.dimstyles.new(name)
        arrow = None
        for key, value in dimvars.items():
            k = str(key).lower()
            if k == "dimblk":
                arrow = value
                continue
            if k == "dimtxsty" and value not in doc.styles:
                warn.append(f"dimstyle {name}: kiểu chữ '{value}' chưa có — tạo với font {TEXT_STYLE['font']}")
                doc.styles.new(str(value), dxfattribs={"font": TEXT_STYLE["font"]})
            if not ds.dxf.is_supported(k):
                warn.append(f"dimstyle {name}: biến '{key}' không được ezdxf hỗ trợ — bỏ qua biến này")
                continue
            ds.dxf.set(k, value)
        if arrow:
            arrow_name = str(arrow)
            if arrow_name.upper() == "ARCHTICK":
                arrow_name = ezdxf.ARROWS.architectural_tick
            if arrow_name not in ezdxf.ARROWS.__acad__ and arrow_name not in doc.blocks:
                warn.append(f"dimstyle {name}: đầu đo '{arrow}' lạ — dùng gạch chéo kiến trúc")
                arrow_name = ezdxf.ARROWS.architectural_tick
            ds.set_arrows(blk=arrow_name)
        made.append(name)
    return made


def _sync_header_dimvars(doc, name: str) -> None:
    """Chép biến DIM* của kiểu hiện hành vào header ($DIM*): AutoCAD coi header là biến DIM hiện hành, lệch nhau thì
    kiểu hiện hành mang "<style overrides>" và kích thước vẽ thêm sau (tay / máy chủ MCP) không theo TCVN."""
    from ezdxf.sections.headervars import HEADER_VAR_MAP
    for key, value in doc.dimstyles.get(name).dxfattribs().items():
        if not key.startswith("dim") or key.endswith("_handle"):
            continue
        var = "$" + key.upper()
        if var not in HEADER_VAR_MAP:
            continue
        if key in ("dimblk", "dimblk1", "dimblk2", "dimldrblk") and value and not str(value).startswith("_"):
            value = "_" + str(value)              # khối đầu đo chuẩn của AutoCAD mang tiền tố "_" (vd _ARCHTICK)
        doc.header[var] = value


def _add_primitive(doc, layout, kind: str, d: Dict[str, Any], attribs: Dict[str, Any], style: str,
                   what: str, warn: List[str]):
    """Thêm một hình cơ bản (line/pline/circle/arc/text/mtext) vào layout. Trả thực thể."""
    from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
    if kind == "line":
        return layout.add_line(d["p1"], d["p2"], dxfattribs=attribs)
    if kind == "pline":
        return layout.add_lwpolyline(d["points"], format="xy", close=bool(d["closed"]), dxfattribs=attribs)
    if kind == "circle":
        return layout.add_circle(d["center"], d["r"], dxfattribs=attribs)
    if kind == "arc":
        return layout.add_arc(d["center"], d["r"], d["start_angle"], d["end_angle"], dxfattribs=attribs)
    if kind == "text":
        a = dict(attribs, style=style, height=d["height"], rotation=d["rotation"])
        ent = layout.add_text(_single_line(d["text"], what, warn), dxfattribs=a)
        ent.set_placement(d["insert"], align=TextEntityAlignment[TEXT_ALIGN_MAP[d["align"]]])
        return ent
    if kind == "mtext":
        a = dict(attribs, style=style, char_height=d["height"], width=d["width"], insert=d["insert"],
                 attachment_point=MTextEntityAlignment[d["attach"]])
        return layout.add_mtext(_mtext_content(d["text"]), dxfattribs=a)
    raise ValueError(f"{what}: loại '{kind}' không phải hình cơ bản")


def _setup_blocks(doc, plan: DrawingPlan, style: str, warn: List[str], skipped: List[Dict[str, str]]) -> List[str]:
    from ezdxf.lldxf.validator import is_valid_block_name
    made: List[str] = []
    for name, bdef in plan.blocks.items():
        if not is_valid_block_name(name) or name.startswith("*"):
            skipped.append({"id": f"block:{name}", "ly_do": "tên block không hợp lệ trong DXF"})
            continue
        if name in doc.blocks:
            warn.append(f"block {name}: trùng tên block có sẵn trong file mới — ghi đè nội dung theo plan")
            doc.blocks.delete_block(name, safe=False)
        blk = doc.blocks.new(name)
        if bdef.description:
            blk.block.dxf.description = bdef.description
        for i, item in enumerate(bdef.ops):
            # hình trong block nằm trên layer "0" → mang thuộc tính layer của INSERT
            attribs = _entity_attribs(doc, item["data"], "0", f"block {name}[{i}]", warn)
            _add_primitive(doc, blk, item["kind"], item["data"], attribs, style, f"block {name}[{i}]", warn)
        made.append(name)
    return made


# ── underlay ─────────────────────────────────────────────────────────────────

def _finite_pos(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _point2(v: Any) -> Optional[List[float]]:
    try:
        x, y = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return [x, y] if math.isfinite(x) and math.isfinite(y) else None


def _image_pixels(ul: Dict[str, Any], path: str) -> Optional[List[int]]:
    px = ul.get("pixels")
    if px is not None:
        try:
            w, h = int(px[0]), int(px[1])
            if w > 0 and h > 0:
                return [w, h]
        except (TypeError, ValueError, IndexError):
            return None
        return None
    if os.path.isfile(path):
        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as im:
                return [int(im.size[0]), int(im.size[1])]
        except Exception:     # noqa: BLE001 — ảnh hỏng/không đọc được: báo ở "bo_qua"
            return None
    return None


def _add_underlays(doc, msp, underlays: Sequence[Dict[str, Any]], layer: str, dxf_dir: str,
                   warn: List[str], skipped: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    placed: List[Dict[str, Any]] = []
    for i, u in enumerate(underlays or ()):
        raw_name = str((u or {}).get("name") or "")
        base = os.path.basename(raw_name.replace("\\", "/"))
        uid = f"anh_nen:{base or i}"
        if not base:
            skipped.append({"id": uid, "ly_do": "ảnh nền không có tên file"})
            continue
        if base != raw_name:
            warn.append(f"{uid}: tên ảnh nền có đường dẫn — chỉ ghi tên file '{base}' (cùng thư mục với DXF)")
        kind = (u or {}).get("kind")
        ul = (u or {}).get("underlay") or {}
        scale = _finite_pos(ul.get("scale"))
        if scale is None:
            skipped.append({"id": uid, "ly_do": "thiếu tỷ lệ (underlay.scale) — không đặt ảnh nền theo kích thước đoán"})
            continue
        insert = _point2(ul.get("insert"))
        if insert is None:
            skipped.append({"id": uid, "ly_do": "thiếu điểm chèn (underlay.insert) — không tự đặt tại gốc toạ độ"})
            continue
        rotation = float(ul.get("rotation", 0.0) or 0.0)
        eid = f"00/anh_nen/{base}"
        if kind == "anh":
            px = _image_pixels(ul, os.path.join(dxf_dir, base))
            if px is None:
                skipped.append({"id": uid, "ly_do": "không biết kích thước ảnh (underlay.pixels) và không đọc được "
                                                     "file ảnh cạnh DXF"})
                continue
            size = (px[0] * scale, px[1] * scale)
            img_def = doc.add_image_def(filename=base, size_in_pixel=(px[0], px[1]))
            ent = msp.add_image(img_def, insert=insert, size_in_units=size, rotation=rotation,
                                dxfattribs={"layer": layer})
            _xdata(ent, eid, "00", warn)
            placed.append({"name": base, "kind": kind, "thuc_the": "IMAGE", "pixels": px,
                           "kich_thuoc_mm": [round(size[0], 3), round(size[1], 3)], "insert": insert})
        elif kind == "pdf":
            try:
                page = int(ul.get("page", 1) or 1)
            except (TypeError, ValueError):
                skipped.append({"id": uid, "ly_do": f"số trang PDF '{ul.get('page')}' không hợp lệ"})
                continue
            udef = doc.add_underlay_def(filename=base, fmt="pdf", name=str(page))
            ent = msp.add_underlay(udef, insert=insert, scale=(scale, scale, 1.0), rotation=rotation,
                                   dxfattribs={"layer": layer})
            _xdata(ent, eid, "00", warn)
            placed.append({"name": base, "kind": kind, "thuc_the": ent.dxftype(), "trang": page,
                           "scale": scale, "insert": insert})
        else:
            skipped.append({"id": uid, "ly_do": f"loại ảnh nền '{kind}' không hỗ trợ (chỉ 'anh' hoặc 'pdf')"})
    return placed


# ── vẽ Op ────────────────────────────────────────────────────────────────────

def _draw_op(doc, msp, op: Op, layer: str, style: str, dimstyles: Iterable[str], blocks: Iterable[str],
             warn: List[str], skipped: List[Dict[str, str]]):
    from ezdxf.lldxf import const
    from ezdxf.tools.pattern import ISO_PATTERN
    d = op.data
    attribs = _entity_attribs(doc, d, layer, op.eid, warn)
    if op.kind in ("line", "pline", "circle", "arc", "text", "mtext"):
        return _add_primitive(doc, msp, op.kind, d, attribs, style, op.eid, warn)
    if op.kind == "insert":
        if d["block"] not in blocks:
            skipped.append({"id": op.eid, "ly_do": f"block '{d['block']}' chưa có định nghĩa trong plan.blocks"})
            return None
        a = dict(attribs, xscale=d["scale"][0], yscale=d["scale"][1], rotation=d["rotation"])
        return msp.add_blockref(d["block"], d["insert"], dxfattribs=a)
    if op.kind == "hatch":
        pattern = str(d["pattern"]).upper()
        color = attribs.pop("color", const.BYLAYER)
        hatch = msp.add_hatch(color=color, dxfattribs=attribs)
        if pattern == "SOLID":
            hatch.set_solid_fill(color=color, style=0)
        elif pattern in ISO_PATTERN:
            hatch.set_pattern_fill(pattern, color=color, angle=d["angle"], scale=d["pattern_scale"], style=0)
        else:
            msp.delete_entity(hatch)
            skipped.append({"id": op.eid, "ly_do": f"mẫu hatch '{d['pattern']}' không có trong bảng mẫu ISO "
                                                   f"(acadiso.pat) của ezdxf"})
            return None
        for i, loop in enumerate(d["boundaries"]):
            flags = (const.BOUNDARY_PATH_EXTERNAL | const.BOUNDARY_PATH_OUTERMOST) if i == 0 \
                else const.BOUNDARY_PATH_DEFAULT
            hatch.paths.add_polyline_path(loop, is_closed=True, flags=flags)
        return hatch
    if op.kind == "dim_linear":
        name = d["dimstyle"]
        if name not in dimstyles:
            # không lặng lẽ vẽ bằng Standard (chữ 2,5 mm model, mũi tên kín): bỏ qua để số đếm đọc lại lệch và báo lỗi
            skipped.append({"id": op.eid, "ly_do": f"dimstyle '{name}' không có trong plan.dimstyles"})
            return None
        text = d.get("text_override")
        dim = msp.add_linear_dim(base=d["base"], p1=d["p1"], p2=d["p2"], angle=d["angle"], dimstyle=name,
                                 text=text if text else "<>", dxfattribs=attribs)
        dim.render()
        return dim.dimension
    skipped.append({"id": op.eid, "ly_do": f"loại Op '{op.kind}' chưa có bộ xuất DXF"})
    return None


def _counts(msp) -> Dict[str, Dict[str, int]]:
    by_type: Counter = Counter()
    by_layer: Counter = Counter()
    for e in msp:
        by_type[e.dxftype()] += 1
        by_layer[e.dxf.layer] += 1
    return {"theo_loai": dict(sorted(by_type.items())), "theo_layer": dict(sorted(by_layer.items()))}


def render_dxf(plan: DrawingPlan, path: str, underlays: Optional[Sequence[Dict[str, Any]]] = None,
               dxfversion: str = "R2018") -> Dict[str, Any]:
    """Ghi plan ra file DXF tại `path`. Trả dict tóm tắt (số đo được, không gõ tay):

      file, dxfversion, insunits, ltscale, so_lenh (số Op trong plan), da_ve (số Op đã thành thực thể),
      so_thuc_the, theo_loai, theo_layer (đếm model space sau audit), layers, blocks, dimstyles,
      underlays (ảnh nền đã đặt), bo_qua [{id, ly_do}], canh_bao [..], audit_errors, audit_fixes, audit_chi_tiet.

    underlays: [{"name": "mat_bang.png", "kind": "anh"|"pdf",
                 "underlay": {"insert": [x, y], "scale": mm/điểm ảnh (ảnh) hoặc hệ số (PDF), "page": 1,
                              "pixels": [w, h] (tuỳ chọn — thiếu thì đọc file ảnh cùng thư mục DXF)}}]
    Ảnh nền thiếu scale/insert hoặc không rõ kích thước → không đặt, ghi vào "bo_qua".
    """
    ezdxf = _ezdxf()
    warn: List[str] = []
    skipped: List[Dict[str, str]] = []
    scale = plan.meta.get("scale", 100)

    # không dùng setup=True: nó thêm các dimstyle mẫu "ez_*" (DIMLFAC ≠ 1) mà Skill 00 sẽ cảnh báo khi đọc lại
    doc = ezdxf.new(dxfversion, setup=["linetypes", "styles"], units=4)
    _setup_linetypes(doc)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LTSCALE"] = ltscale_for(scale)
    doc.header["$CELTSCALE"] = 1.0
    if APPID not in doc.appids:
        doc.appids.new(APPID)

    style = _setup_text_style(doc, plan)
    role_layer = _setup_layers(doc, plan, warn)
    dimstyles = _setup_dimstyles(doc, plan, warn)
    if dimstyles:
        doc.header["$DIMSTYLE"] = dimstyles[0]
        _sync_header_dimvars(doc, dimstyles[0])
    blocks = _setup_blocks(doc, plan, style, warn, skipped)
    msp = doc.modelspace()

    placed: List[Dict[str, Any]] = []
    if underlays:
        spec = plan.layers.get("anh_nen") or LayerSpec(**vars(DEFAULT_ROLES["anh_nen"][1]))
        ul_layer = role_layer.get("anh_nen") or _make_layer(doc, LayerSpec(**dict(vars(spec), plot=False)),
                                                            f"layer {spec.name}", warn)
        placed = _add_underlays(doc, msp, underlays, ul_layer, os.path.dirname(os.path.abspath(path)),
                                warn, skipped)

    drawn = 0
    for op in plan.ops:
        layer = role_layer.get(op.role)
        if layer is None:
            skipped.append({"id": op.eid, "ly_do": f"layer của vai trò '{op.role}' không tạo được"})
            continue
        ent = _draw_op(doc, msp, op, layer, style, dimstyles, blocks, warn, skipped)
        if ent is None:
            continue
        _xdata(ent, op.eid, op.skill, warn)
        drawn += 1

    auditor = doc.audit()
    counts = _counts(msp)
    doc.saveas(path)
    return {
        "file": os.path.basename(path),
        "dxfversion": doc.dxfversion,
        "insunits": int(doc.header["$INSUNITS"]),
        "ltscale": float(doc.header["$LTSCALE"]),
        "so_lenh": len(plan.ops),
        "da_ve": drawn,
        "so_thuc_the": sum(counts["theo_layer"].values()),
        "theo_loai": counts["theo_loai"],
        "theo_layer": counts["theo_layer"],
        "layers": len([r for r, n in role_layer.items() if n]),
        "blocks": blocks,
        "dimstyles": dimstyles,
        "underlays": placed,
        "bo_qua": skipped,
        "canh_bao": warn,
        "audit_errors": len(auditor.errors),
        "audit_fixes": len(auditor.fixes),
        "audit_chi_tiet": [str(e.message) for e in list(auditor.errors)[:20]],
    }


def read_back_counts(path: str) -> Dict[str, int]:
    """Đọc lại file DXF đã ghi, đếm thực thể model space theo tên layer (để Master đối chiếu plan.count_by_role())."""
    doc = _ezdxf().readfile(path)
    counts: Counter = Counter(e.dxf.layer for e in doc.modelspace())
    return dict(sorted(counts.items()))
