# -*- coding: utf-8 -*-
"""
BỘ XUẤT AUTOLISP — biến DrawingPlan thành file .lsp chạy trong AutoCAD (lệnh 23HG_VE).

File sinh ra:
  - THUẦN ASCII: bộ đọc AutoLISP đọc file theo bảng mã ANSI (skills/aec-cad-automation/SKILL.md mục 7A), nên chữ
    tiếng Việt ghi dạng \\U+XXXX của AutoCAD (vd "Ạ" → \\U+1EA0); dấu " và \\ trong chuỗi được escape. Chú thích
    trong file viết không dấu.
  - Bảng: layer (vla-add + màu + kiểu đường nạp từ "acadiso.lin" bằng vl-catch-all-apply + nét in + cờ in),
    kiểu chữ, kiểu kích thước (đặt biến DIM* bằng setvar rồi -DIMSTYLE Save; style đã có thì ghi đè có xác nhận),
    block (entmake BLOCK … ENDBLK; block đã có trong bản vẽ thì GIỮ định nghĩa cũ và in thông báo).
  - Thực thể: LINE / LWPOLYLINE / CIRCLE / ARC / TEXT / MTEXT / INSERT bằng entmake (mã nhóm DXF 8, 10/11, 40,
    50, 72/73, 7...); HATCH bằng ActiveX (vla-AddHatch + AppendOuterLoop / AppendInnerLoop qua polyline tạm, xoá
    polyline tạm sau khi Evaluate); DIMENSION bằng vla-AddDimRotated (góc radian) + vla-put-StyleName
    (+ TextOverride nếu có).
  - Mỗi thực thể mang XDATA "23HG_CAD": (1000 . eid) (1000 . skill) — cùng quy ước với render_dxf.
  - Đối tượng AutoCAD từ chối tạo được ĐẾM và IN RA dòng lệnh (không bỏ im lặng); cuối lệnh in "đã tạo n/N".

GIỚI HẠN: file được sinh tự động và CHƯA chạy thử trên AutoCAD trong CI — chỉ kiểm tra cú pháp tĩnh
(lisp_static_check: ngoặc cân bằng, chuỗi đóng đủ, escape hợp lệ, thuần ASCII).
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional

from tools.cad_drafting.layers import TEXT_STYLE
from tools.cad_drafting.plan import DrawingPlan, Op
from tools.cad_drafting.render_dxf import APPID, ltscale_for

COMMAND = "23HG_VE"
OPS_PER_DEFUN = 150                  # tách phần vẽ thành nhiều defun nhỏ cho bộ đọc AutoLISP
MTEXT_CHUNK = 240                    # MTEXT: chuỗi dài chia đoạn nhóm 3 (≤ 250 ký tự mỗi đoạn)
TEXT_MAX = 256                       # TEXT: giới hạn ký tự nhóm 1

# align của plan → (72, 73) mã căn chữ TEXT
TEXT_ALIGN_CODES = {
    "LEFT": (0, 0), "CENTER": (1, 0), "RIGHT": (2, 0), "MIDDLE_CENTER": (1, 2), "MIDDLE_LEFT": (0, 2),
    "MIDDLE_RIGHT": (2, 2), "TOP_CENTER": (1, 3), "BOTTOM_CENTER": (1, 1),
}
MTEXT_ATTACH_CODES = {
    "TOP_LEFT": 1, "TOP_CENTER": 2, "TOP_RIGHT": 3, "MIDDLE_LEFT": 4, "MIDDLE_CENTER": 5, "MIDDLE_RIGHT": 6,
    "BOTTOM_LEFT": 7, "BOTTOM_CENTER": 8, "BOTTOM_RIGHT": 9,
}


# ─────────────────────────────────────────────────────────────────────────────
# MÃ HOÁ CHUỖI / SỐ
# ─────────────────────────────────────────────────────────────────────────────

def lisp_escape(text: str, warn: Optional[List[str]] = None, what: str = "") -> str:
    """Nội dung chuỗi AutoLISP thuần ASCII (chưa có dấu nháy bao ngoài): \\ → \\\\, " → \\",
    ký tự ngoài ASCII → \\U+XXXX, ký tự điều khiển → khoảng trắng."""
    out: List[str] = []
    for ch in str(text):
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif 32 <= o < 127:
            out.append(ch)
        elif o < 32 or o == 127:
            out.append(" ")
        elif o <= 0xFFFF:
            out.append(f"\\U+{o:04X}")
        else:
            if warn is not None:
                warn.append(f"{what}: ký tự U+{o:X} ngoài dải \\U+XXXX của AutoCAD — thay bằng '?'")
            out.append("?")
    return "".join(out)


def lisp_str(text: str, warn: Optional[List[str]] = None, what: str = "") -> str:
    return '"' + lisp_escape(text, warn, what) + '"'


def ascii_comment(text: str) -> str:
    """Chú thích LISP: bỏ dấu tiếng Việt (Đ → D), ký tự còn lại ngoài ASCII → '?', bỏ xuống dòng."""
    s = str(text).replace("Đ", "D").replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.replace("\r", " ").replace("\n", " ")
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in s)


def _n(v: Any, decimals: int = 6) -> str:
    """Số thực LISP: dạng thập phân cố định (không có dạng mũ), luôn có dấu chấm.
    Toạ độ mm giữ 6 chữ số thập phân; góc radian giữ 12 (xem _rad)."""
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"số không hữu hạn {v!r}")
    s = f"{f:.{int(decimals)}f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    if s in ("-0.0", "-0"):
        s = "0.0"
    return s


def _rad(deg: Any) -> str:
    return _n(math.radians(float(deg)), 12)


def _p3(code: int, p) -> str:
    return f"({code} {_n(p[0])} {_n(p[1])} 0.0)"


def _lisp_value(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _n(v)
    return lisp_str(str(v))


# ─────────────────────────────────────────────────────────────────────────────
# DANH SÁCH MÃ NHÓM CHO entmake
# ─────────────────────────────────────────────────────────────────────────────

def _props_groups(d: Dict[str, Any], warn: List[str], what: str) -> List[str]:
    g: List[str] = []
    if d.get("color") is not None:
        g.append(f"(62 . {int(d['color'])})")
    if d.get("linetype"):
        g.append(f"(6 . {lisp_str(d['linetype'], warn, what)})")
    if d.get("lineweight") is not None:
        g.append(f"(370 . {int(d['lineweight'])})")
    return g


def _text_value(text: str, what: str, warn: List[str]) -> str:
    if "\n" in text or "\r" in text:
        warn.append(f"{what}: TEXT không chứa được xuống dòng — đã nối thành một dòng")
        text = " ".join(text.replace("\r", "\n").split("\n"))
    if len(text) > TEXT_MAX:
        warn.append(f"{what}: TEXT dài {len(text)} ký tự (> {TEXT_MAX}) — AutoCAD có thể cắt bớt")
    return text


def _mtext_groups(text: str, warn: List[str], what: str) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\P")
    chunks = [text[i:i + MTEXT_CHUNK] for i in range(0, len(text), MTEXT_CHUNK)] or [""]
    groups = [f"(3 . {lisp_str(c, warn, what)})" for c in chunks[:-1]]
    groups.append(f"(1 . {lisp_str(chunks[-1], warn, what)})")
    return groups


def _entmake_groups(kind: str, d: Dict[str, Any], layer: str, style: str, warn: List[str], what: str) -> List[str]:
    """Danh sách mã nhóm DXF (dạng chữ LISP) cho entmake một hình cơ bản / INSERT."""
    lay = f"(8 . {lisp_str(layer, warn, what)})"
    props = _props_groups(d, warn, what)
    if kind == "line":
        return ['(0 . "LINE")', lay] + props + [_p3(10, d["p1"]), _p3(11, d["p2"])]
    if kind == "pline":
        pts = [f"(10 {_n(p[0])} {_n(p[1])})" for p in d["points"]]
        return (['(0 . "LWPOLYLINE")', '(100 . "AcDbEntity")', lay] + props
                + ['(100 . "AcDbPolyline")', f"(90 . {len(pts)})", f"(70 . {1 if d['closed'] else 0})"] + pts)
    if kind == "circle":
        return ['(0 . "CIRCLE")', lay] + props + [_p3(10, d["center"]), f"(40 . {_n(d['r'])})"]
    if kind == "arc":
        return (['(0 . "ARC")', lay] + props
                + [_p3(10, d["center"]), f"(40 . {_n(d['r'])})", f"(50 . {_rad(d['start_angle'])})",
                   f"(51 . {_rad(d['end_angle'])})"])
    if kind == "text":
        h72, v73 = TEXT_ALIGN_CODES[d["align"]]
        txt = _text_value(d["text"], what, warn)
        return (['(0 . "TEXT")', lay] + props
                + [f"(7 . {lisp_str(style, warn, what)})", _p3(10, d["insert"]), _p3(11, d["insert"]),
                   f"(40 . {_n(d['height'])})", f"(1 . {lisp_str(txt, warn, what)})",
                   f"(50 . {_rad(d['rotation'])})", f"(72 . {h72})", f"(73 . {v73})"])
    if kind == "mtext":
        return (['(0 . "MTEXT")', '(100 . "AcDbEntity")', lay] + props
                + ['(100 . "AcDbMText")', _p3(10, d["insert"]), f"(40 . {_n(d['height'])})",
                   f"(41 . {_n(d['width'])})", f"(71 . {MTEXT_ATTACH_CODES[d['attach']]})", "(72 . 1)",
                   f"(7 . {lisp_str(style, warn, what)})"] + _mtext_groups(d["text"], warn, what))
    if kind == "insert":
        return (['(0 . "INSERT")', f"(2 . {lisp_str(d['block'], warn, what)})", lay] + props
                + [_p3(10, d["insert"]), f"(41 . {_n(d['scale'][0])})", f"(42 . {_n(d['scale'][1])})",
                   "(43 . 1.0)", f"(50 . {_rad(d['rotation'])})"])
    raise ValueError(f"{what}: loại '{kind}' không tạo bằng entmake")


def _xdata_group(eid: str, skill: str, warn: List[str]) -> str:
    return (f"(-3 ({lisp_str(APPID)} (1000 . {lisp_str(eid, warn, eid)}) "
            f"(1000 . {lisp_str(skill, warn, eid)})))")


def _opt(v: Any, conv) -> str:
    return "nil" if v is None or v == "" else conv(v)


def _op_form(op: Op, layer: str, style: str, warn: List[str], block_names) -> str:
    d = op.data
    eid = lisp_str(op.eid, warn, op.eid)
    if op.kind in ("line", "pline", "circle", "arc", "text", "mtext", "insert"):
        if op.kind == "insert" and d["block"] not in block_names:
            warn.append(f"{op.eid}: block '{d['block']}' không có trong plan.blocks — chỉ tạo được nếu bản vẽ đích "
                        f"đã có block này")
        groups = _entmake_groups(op.kind, d, layer, style, warn, op.eid) + [_xdata_group(op.eid, op.skill, warn)]
        return f"(hg23:em {eid} '({' '.join(groups)}))"
    color = _opt(d.get("color"), lambda v: str(int(v)))
    ltype = _opt(d.get("linetype"), lambda v: lisp_str(v, warn, op.eid))
    lw = _opt(d.get("lineweight"), lambda v: str(int(v)))
    lay = lisp_str(layer, warn, op.eid)
    skill = lisp_str(op.skill, warn, op.eid)
    if op.kind == "hatch":
        loops = " ".join("(" + " ".join(f"({_n(p[0])} {_n(p[1])})" for p in loop) + ")" for loop in d["boundaries"])
        args = (f"{eid} {skill} {lay} {lisp_str(d['pattern'], warn, op.eid)} {_n(d['pattern_scale'])} "
                f"{_rad(d['angle'])} {color} {ltype} {lw} '({loops})")
        return f"(hg23:try {eid} 'hg23:hatch1 (list {args}))"
    if op.kind == "dim_linear":
        txt = d.get("text_override")
        args = (f"{eid} {skill} {lay} {lisp_str(d['dimstyle'], warn, op.eid)} "
                f"'({_n(d['p1'][0])} {_n(d['p1'][1])} 0.0) '({_n(d['p2'][0])} {_n(d['p2'][1])} 0.0) "
                f"'({_n(d['base'][0])} {_n(d['base'][1])} 0.0) {_rad(d['angle'])} "
                f"{lisp_str(txt, warn, op.eid) if txt else 'nil'} {color} {ltype} {lw}")
        return f"(hg23:try {eid} 'hg23:dim1 (list {args}))"
    raise ValueError(f"{op.eid}: loại Op '{op.kind}' chưa có bộ xuất AutoLISP")


# ─────────────────────────────────────────────────────────────────────────────
# PHẦN CỐ ĐỊNH CỦA FILE LISP
# ─────────────────────────────────────────────────────────────────────────────

_HELPERS = r"""
(vl-load-com)

;;; Dem doi tuong da tao / loi, polyline tam cua hatch
(setq hg23:n 0 hg23:nloi 0 hg23:tmp nil)

(defun hg23:em (eid lst / r)
  ;; entmake mot doi tuong; that bai thi dem loi va in ra (khong bo im lang)
  (setq r (entmake lst))
  (if r
    (setq hg23:n (1+ hg23:n))
    (progn
      (setq hg23:nloi (1+ hg23:nloi))
      (princ (strcat "\n23HG: khong tao duoc " eid))))
  r)

(defun hg23:xd (en eid skill)
  ;; gan XDATA 23HG_CAD cho doi tuong tao bang ActiveX
  (if en
    (entmod (append (entget en)
                    (list (list -3 (list "23HG_CAD" (cons 1000 eid) (cons 1000 skill))))))))

(defun hg23:ltype (name)
  ;; nap kieu duong tu acadiso.lin neu ban ve chua co
  (if (and name (/= (strcase name) "CONTINUOUS") (not (tblsearch "LTYPE" name)))
    (vl-catch-all-apply 'vla-load (list (vla-get-Linetypes hg23:doc) name "acadiso.lin")))
  (tblsearch "LTYPE" name))

(defun hg23:layer (name color ltype lw plot desc / lay)
  (setq lay (vla-add (vla-get-Layers hg23:doc) name))
  (vl-catch-all-apply 'vla-put-Color (list lay color))
  (if (hg23:ltype ltype)
    (vla-put-Linetype lay ltype)
    (princ (strcat "\n23HG: khong nap duoc kieu duong " ltype " - layer " name " dung Continuous")))
  (vl-catch-all-apply 'vla-put-Lineweight (list lay lw))
  (vla-put-Plottable lay (if plot :vlax-true :vlax-false))
  ;; layer da co trong ban ve dich co the dang tat / dong bang / khoa: bat lai de doi tuong tao ra nhin thay, sua duoc
  (vl-catch-all-apply 'vla-put-LayerOn (list lay :vlax-true))
  (vl-catch-all-apply 'vla-put-Freeze (list lay :vlax-false))
  (vl-catch-all-apply 'vla-put-Lock (list lay :vlax-false))
  (if (/= desc "") (vl-catch-all-apply 'vla-put-Description (list lay desc)))
  lay)

(defun hg23:style (name font / st)
  (setq st (vla-add (vla-get-TextStyles hg23:doc) name))
  (if (vl-catch-all-error-p (vl-catch-all-apply 'vla-put-FontFile (list st font)))
    (princ (strcat "\n23HG: khong dat duoc font " font " cho kieu chu " name)))
  ;; kieu chu co chieu cao co dinh se lam kich thuoc bo qua DIMTXT: dat chieu cao 0, he so rong 1
  (vl-catch-all-apply 'vla-put-Height (list st 0.0))
  (vl-catch-all-apply 'vla-put-Width (list st 1.0))
  st)

(defun hg23:dimstyle (name vars)
  ;; dat bien DIM* bang setvar roi luu thanh dimstyle (da co thi ghi de)
  (foreach v vars
    (if (vl-catch-all-error-p (vl-catch-all-apply 'setvar (list (car v) (cdr v))))
      (princ (strcat "\n23HG: khong dat duoc bien " (car v) " cho dimstyle " name))))
  (if (tblsearch "DIMSTYLE" name)
    (command "_.-DIMSTYLE" "_Save" name "_Y")
    (command "_.-DIMSTYLE" "_Save" name))
  (princ))

(defun hg23:props (o color ltype lw)
  (if color (vla-put-Color o color))
  (if (and ltype (hg23:ltype ltype)) (vla-put-Linetype o ltype))
  (if lw (vla-put-Lineweight o lw)))

(defun hg23:pl (lay pts / o)
  ;; polyline kin tam lam bien hatch
  (entmake (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbPolyline")
                         (cons 90 (length pts)) '(70 . 1))
                   (mapcar '(lambda (p) (cons 10 p)) pts)))
  (setq o (vlax-ename->vla-object (entlast)))
  (setq hg23:tmp (cons o hg23:tmp))
  o)

(defun hg23:objarr (objs / sa)
  (setq sa (vlax-make-safearray vlax-vbObject (cons 0 (1- (length objs)))))
  (vlax-safearray-fill sa objs))

(defun hg23:xoa-tam ()
  ;; xoa polyline tam (ke ca khi hatch loi giua chung)
  (foreach o hg23:tmp (vl-catch-all-apply 'vla-Delete (list o)))
  (setq hg23:tmp nil))

(defun hg23:hatch1 (eid skill lay pat scl ang color ltype lw loops / h)
  (setq h (vla-AddHatch hg23:ms acHatchPatternTypePreDefined pat :vlax-false))
  (setq hg23:tmp (cons h hg23:tmp))
  (vla-put-Layer h lay)
  (hg23:props h color ltype lw)
  (if (/= (strcase pat) "SOLID")
    (progn (vla-put-PatternScale h scl) (vla-put-PatternAngle h ang)))
  (vla-AppendOuterLoop h (hg23:objarr (list (hg23:pl lay (car loops)))))
  (foreach lp (cdr loops)
    (vla-AppendInnerLoop h (hg23:objarr (list (hg23:pl lay lp)))))
  (vla-Evaluate h)
  (setq hg23:tmp (vl-remove h hg23:tmp))
  (hg23:xd (vlax-vla-object->ename h) eid skill)
  h)

(defun hg23:dim1 (eid skill lay style p1 p2 base ang txt color ltype lw / d)
  (setq d (vla-AddDimRotated hg23:ms (vlax-3d-point p1) (vlax-3d-point p2) (vlax-3d-point base) ang))
  (vla-put-Layer d lay)
  (if (tblsearch "DIMSTYLE" style)
    (vla-put-StyleName d style)
    (princ (strcat "\n23HG: chua co dimstyle " style " - kich thuoc " eid " dung kieu hien hanh")))
  (if txt (vla-put-TextOverride d txt))
  (hg23:props d color ltype lw)
  (hg23:xd (vlax-vla-object->ename d) eid skill)
  d)

(defun hg23:try (eid fn args / r)
  ;; goi ham tao doi tuong ActiveX; loi thi dem, in ra va don polyline tam
  (setq r (vl-catch-all-apply fn args))
  (hg23:xoa-tam)
  (if (or (null r) (vl-catch-all-error-p r))
    (progn
      (setq hg23:nloi (1+ hg23:nloi))
      (princ (strcat "\n23HG: khong tao duoc " eid
                     (if (vl-catch-all-error-p r) (strcat " - " (vl-catch-all-error-message r)) ""))))
    (setq hg23:n (1+ hg23:n)))
  r)
"""


def _header(plan: DrawingPlan) -> List[str]:
    proj = (plan.meta or {}).get("project") or {}
    lines = [
        ";;; =====================================================================",
        ";;; 23HG CAD - AutoLISP SINH TU DONG tu DrawingPlan (tools/cad_drafting/render_lisp.py)",
        f";;; Du an: {ascii_comment(proj.get('name', ''))}",
        f";;; Ban ve: {ascii_comment(proj.get('drawing_title', ''))} {ascii_comment(proj.get('drawing_no', ''))}",
        f";;; Ty le 1:{ascii_comment(plan.meta.get('scale', ''))} - don vi mm - so lenh ve: {len(plan.ops)}",
        ";;; CHUA chay thu tren AutoCAD trong CI - chi kiem tra cu phap tinh",
        ";;; (ngoac can bang, chuoi dong du, escape hop le, thuan ASCII).",
        ";;; Chu tieng Viet ghi dang \\U+XXXX vi AutoLISP doc file theo bang ma ANSI.",
        f";;; Cach dung: APPLOAD file nay roi go lenh {COMMAND}. Moi doi tuong mang XDATA {APPID} (eid, skill).",
        ";;; =====================================================================",
    ]
    return lines


def _dimvars(dimvars: Dict[str, Any], warn: List[str], name: str) -> str:
    pairs = []
    for key, value in dimvars.items():
        var = str(key).upper()
        if not var.startswith("DIM"):
            warn.append(f"dimstyle {name}: '{key}' không phải biến DIM* — bỏ qua biến này")
            continue
        if var == "DIMBLK" and str(value).upper().lstrip("_") == "ARCHTICK":
            value = "_ARCHTICK"
        pairs.append(f"({lisp_str(var)} . {_lisp_value(value)})")
    return "'(" + " ".join(pairs) + ")"


def _tables(plan: DrawingPlan, style: str, font: str, warn: List[str]) -> List[str]:
    out = ["(defun hg23:bang ()", "  ;; layer, kieu chu, kieu kich thuoc, block"]
    for role, spec in plan.layers.items():
        out.append(f"  (hg23:layer {lisp_str(spec.name, warn, 'layer')} {int(spec.color)} "
                   f"{lisp_str(spec.linetype or 'Continuous', warn, 'layer')} {int(spec.lineweight)} "
                   f"{'T' if spec.plot else 'nil'} {lisp_str(spec.description or '', warn, 'layer')})"
                   f" ; {ascii_comment(role)}")
    out.append(f"  (hg23:style {lisp_str(style, warn, 'style')} {lisp_str(font, warn, 'style')})")
    for name, dimvars in plan.dimstyles.items():
        out.append(f"  (hg23:dimstyle {lisp_str(name, warn, 'dimstyle')} {_dimvars(dimvars, warn, name)})")
    for name, bdef in plan.blocks.items():
        bname = lisp_str(name, warn, f"block {name}")
        out.append(f"  (if (not (tblsearch \"BLOCK\" {bname}))")
        out.append("    (progn")
        out.append(f"      (entmake '((0 . \"BLOCK\") (2 . {bname}) (70 . 0) (10 0.0 0.0 0.0)))")
        for i, item in enumerate(bdef.ops):
            groups = _entmake_groups(item["kind"], item["data"], "0", style, warn, f"block {name}[{i}]")
            out.append(f"      (entmake '({' '.join(groups)}))")
        out.append("      (entmake '((0 . \"ENDBLK\"))))")
        out.append(f"    (princ (strcat \"\\n23HG: block \" {bname} \" da co trong ban ve - giu dinh nghia cu\")))")
    out.append("  (princ))")
    return out


def render_lisp(plan: DrawingPlan, path: str) -> Dict[str, Any]:
    """Ghi file AutoLISP (thuần ASCII, xuống dòng CRLF) tại `path`. Trả dict tóm tắt (số đo được):

      file, lenh, so_lenh, theo_loai, layers, blocks, dimstyles, ltscale, bytes, thuan_ascii,
      loi_cu_phap_tinh (kết quả lisp_static_check), canh_bao, bo_qua, chay_tren_autocad.
    """
    warn: List[str] = []
    skipped: List[Dict[str, str]] = []
    style = (plan.text_style or {}).get("name") or TEXT_STYLE["name"]
    font = (plan.text_style or {}).get("font") or TEXT_STYLE["font"]
    block_names = set(plan.blocks)
    ltypes = sorted({str(o.data["linetype"]) for o in plan.ops if o.data.get("linetype")})

    lines = _header(plan) + _HELPERS.strip("\n").split("\n") + [""] + _tables(plan, style, font, warn) + [""]

    forms: List[str] = []
    for op in plan.ops:
        spec = plan.layers.get(op.role)
        if spec is None:
            skipped.append({"id": op.eid, "ly_do": f"vai trò layer '{op.role}' không có trong plan.layers"})
            continue
        forms.append(f"  {_op_form(op, spec.name, style, warn, block_names)}")
    chunks = [forms[i:i + OPS_PER_DEFUN] for i in range(0, len(forms), OPS_PER_DEFUN)]
    for k, chunk in enumerate(chunks, start=1):
        lines.append(f"(defun hg23:ve-{k} ()")
        lines.extend(chunk)
        lines.append("  (princ))")
        lines.append("")

    total = len(forms)
    lines += [
        f"(defun C:{COMMAND} (/ *error* cmde)",
        "  (defun *error* (msg)",
        "    (if cmde (setvar \"CMDECHO\" cmde))",
        "    (hg23:xoa-tam)",
        "    (if hg23:doc (vla-EndUndoMark hg23:doc))",
        "    (if (and msg (not (wcmatch (strcase msg) \"*CANCEL*,*QUIT*,*EXIT*\")))",
        "      (princ (strcat \"\\n23HG: dung giua chung - \" msg)))",
        "    (princ))",
        "  (setq hg23:doc (vla-get-ActiveDocument (vlax-get-acad-object))",
        "        hg23:ms (vla-get-ModelSpace hg23:doc)",
        "        hg23:n 0 hg23:nloi 0 hg23:tmp nil)",
        "  (vla-StartUndoMark hg23:doc)",
        "  (setq cmde (getvar \"CMDECHO\"))",
        "  (setvar \"CMDECHO\" 0)",
        f"  (regapp {lisp_str(APPID)})",
        "  (setvar \"INSUNITS\" 4)",
        "  (setvar \"MEASUREMENT\" 1)",
        f"  (setvar \"LTSCALE\" {_n(ltscale_for(plan.meta.get('scale', 100)))})",
        "  (hg23:bang)",
    ]
    lines += [f"  (hg23:ltype {lisp_str(lt, warn, 'linetype')})" for lt in ltypes]
    lines += [f"  (hg23:ve-{k})" for k in range(1, len(chunks) + 1)]
    lines += [
        "  (setvar \"CMDECHO\" cmde)",
        "  (vla-EndUndoMark hg23:doc)",
        f"  (princ (strcat \"\\n23HG: da tao \" (itoa hg23:n) \"/{total} doi tuong, loi \" (itoa hg23:nloi) \".\"))",
        "  (princ))",
        "",
        f"(princ \"\\n23HG: da nap - go lenh {COMMAND} de ve.\")",
        "(princ)",
        "",
    ]
    text = "\n".join(lines)
    is_ascii = all(ord(c) < 128 for c in text)
    problems = lisp_static_check(text)
    with open(path, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write(text)
    return {
        "file": os.path.basename(path),
        "lenh": COMMAND,
        "so_lenh": total,
        "theo_loai": dict(sorted(Counter(o.kind for o in plan.ops).items())),
        "layers": len(plan.layers),
        "blocks": sorted(plan.blocks),
        "dimstyles": sorted(plan.dimstyles),
        "ltscale": ltscale_for(plan.meta.get("scale", 100)),
        "bytes": os.path.getsize(path),
        "thuan_ascii": is_ascii,
        "loi_cu_phap_tinh": problems,
        "canh_bao": warn,
        "bo_qua": skipped,
        "chay_tren_autocad": "CHƯA chạy thử — chỉ kiểm tra cú pháp tĩnh",
    }


# ─────────────────────────────────────────────────────────────────────────────
# KIỂM TRA CÚ PHÁP TĨNH
# ─────────────────────────────────────────────────────────────────────────────

_HEX4 = re.compile(r"[0-9A-Fa-f]{4}")
_SIMPLE_ESCAPES = set('\\"enrt')


def lisp_static_check(text: str) -> List[str]:
    """Kiểm tra cú pháp tĩnh một file AutoLISP. Trả danh sách lỗi (rỗng = không phát hiện lỗi):
      - ký tự ngoài ASCII (AutoLISP đọc ANSI);
      - ngoặc cân bằng (bỏ qua ngoặc trong chuỗi, chú thích ';' và ';| ... |;');
      - chuỗi đóng đủ, không chứa xuống dòng thật;
      - escape trong chuỗi hợp lệ: \\\\ \\" \\e \\n \\r \\t \\nnn (bát phân) \\U+XXXX \\M+NXXXX.
    Không thay cho việc chạy thử trên AutoCAD."""
    problems: List[str] = []
    non_ascii = [i for i, c in enumerate(text) if ord(c) > 127]
    if non_ascii:
        lines_bad = sorted({text.count("\n", 0, i) + 1 for i in non_ascii})
        problems.append(f"có {len(non_ascii)} ký tự ngoài ASCII (dòng {', '.join(map(str, lines_bad[:10]))}"
                        f"{'…' if len(lines_bad) > 10 else ''})")
    depth = 0
    line = 1
    i = 0
    n = len(text)
    in_str = False
    str_line = 0
    max_reports = 20
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                nxt = text[i + 1] if i + 1 < n else ""
                if nxt in _SIMPLE_ESCAPES:
                    i += 2
                    continue
                if nxt.isdigit() and nxt in "01234567":
                    i += 2
                    continue
                if nxt in ("U", "u") and text[i + 2:i + 3] == "+" and _HEX4.fullmatch(text[i + 3:i + 7] or ""):
                    i += 7
                    continue
                if nxt in ("M", "m") and text[i + 2:i + 3] == "+" and re.fullmatch(r"[0-9A-Fa-f]{5}", text[i + 3:i + 8]):
                    i += 8
                    continue
                if len(problems) < max_reports:
                    problems.append(f"dòng {line}: escape lạ '\\{nxt}' trong chuỗi (cần \\\\ nếu là dấu \\ thật)")
                if nxt == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                if len(problems) < max_reports:
                    problems.append(f"dòng {line}: chuỗi mở ở dòng {str_line} chứa xuống dòng thật")
                line += 1
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == "\n":
            line += 1
        elif ch == ";":
            if text.startswith(";|", i):
                end = text.find("|;", i + 2)
                if end < 0:
                    problems.append(f"dòng {line}: chú thích khối ';|' chưa đóng '|;'")
                    break
                line += text.count("\n", i, end)
                i = end + 2
                continue
            end = text.find("\n", i)
            if end < 0:
                break
            i = end
            continue
        elif ch == '"':
            in_str = True
            str_line = line
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                if len(problems) < max_reports:
                    problems.append(f"dòng {line}: thừa dấu ')'")
                depth = 0
        i += 1
    if in_str:
        problems.append(f"chuỗi mở ở dòng {str_line} chưa đóng dấu \"")
    if depth > 0:
        problems.append(f"thiếu {depth} dấu ')' tới cuối file")
    return problems
