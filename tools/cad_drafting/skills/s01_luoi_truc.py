# -*- coding: utf-8 -*-
"""
SKILL 01 — LƯỚI TRỤC: đường trục định vị (vai trò "truc") và vòng tròn + tên trục (vai trò "truc_kh").

Quy ước:
  - Chỉ vẽ trục ĐÃ CÓ toạ độ (AxisGroup.offsets() khác None). Trục chưa có toạ độ → result.skip("truc:<tên>")
    kèm khoá số liệu còn thiếu; KHÔNG tự suy ngược từ kích thước tổng (việc đó là nội suy của Skill 00).
  - Khung trục của mỗi nhóm = [min, max] toạ độ các trục đã biết của nhóm đó. Trục V (đứng) trải theo khung
    của nhóm H và ngược lại; nếu nhóm kia không có trục nào có toạ độ thì không xác định được chiều dài đường
    trục → bỏ qua mọi trục của nhóm này kèm lý do.
  - Tâm vòng tròn đặt ra ngoài khung trục một khoảng LAYOUT_PAPER_MM["axis_bubble_center"] × tỷ lệ, ở CẢ HAI đầu
    (trục V: dưới và trên; trục H: trái và phải). Bán kính = AXIS_BUBBLE_DIAMETER_PAPER_MM / 2 × tỷ lệ.
  - Đường trục chạy từ mép vòng tròn đầu này tới mép vòng tròn đầu kia (không chui vào trong vòng tròn).
  - Tên trục: text MIDDLE_CENTER tại tâm vòng tròn, cao text_height("truc", tỷ lệ).

eid (đã có tiền tố "01/" do DraftSkill.add gắn):
  truc/<V|H>/<tên>/line, truc/<V|H>/<tên>/bubble/<0|1>, truc/<V|H>/<tên>/name/<0|1>
  (0 = đầu dưới (trục V) / trái (trục H); 1 = đầu trên / phải).

Skill không sửa store. Toạ độ phụ thuộc số liệu nội suy chưa xác nhận được ghi vào result.notes để người
dùng biết (Validator đánh dấu NGHI_VAN theo store.unconfirmed()).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from tools.cad_drafting.layers import (AXIS_BUBBLE_DIAMETER_PAPER_MM, LAYOUT_PAPER_MM, paper_to_model,
                                       text_height)
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.store import SRC_INTERP, AxisGroup, ProjectStore

ORIENTATIONS = ("V", "H")
_OTHER = {"V": "H", "H": "V"}
_KIND_NAME = {"V": "trục đứng (V)", "H": "trục ngang (H)"}


# ── trợ giúp dùng chung (Skill 02 và kiểm thử cũng dùng) ────────────────────

def missing_span_key(group: AxisGroup, name: str) -> Optional[Tuple[str, str]]:
    """(khoá số liệu, mô tả) của nhịp thiếu ĐẦU TIÊN làm trục `name` chưa có toạ độ; None nếu trục đã có toạ độ."""
    idx = group.names.index(name)
    for j in range(idx):
        if group.spans[j] is None:
            return (f"axes:{group.orientation}.spans[{j}]",
                    f"nhịp trục {group.names[j]}–{group.names[j + 1]}")
    return None


def axis_unconfirmed_keys(store: ProjectStore, name: str) -> List[str]:
    """Khoá các nhịp NỘI SUY CHƯA XÁC NHẬN mà toạ độ trục `name` phụ thuộc (cộng dồn từ trục đầu)."""
    group = store.axis_group_of(name)
    if group is None:
        return []
    out = []
    for j in range(group.names.index(name)):
        p = group.span_prov[j] if j < len(group.span_prov) else None
        if p is not None and p.source == SRC_INTERP and not p.confirmed:
            out.append(f"axes:{group.orientation}.spans[{j}]")
    return out


def axis_skip_reason(store: ProjectStore, orientation: str, name: str) -> str:
    """Lý do trục chưa vẽ được ("" nếu vẽ được)."""
    group = store.axes.get(orientation)
    if group is None or name not in group.names:
        return f"không có trục '{name}' trong nhóm {orientation}"
    if not str(name).strip():
        return "tên trục rỗng"
    if group.offset_of(name) is None:
        key, desc = missing_span_key(group, name)
        why = f"trục {name} chưa có toạ độ: thiếu {desc} (khoá {key})"
        if group.overall is not None:
            why += ("; kích thước tổng có ghi nhưng không tự suy ngược — cần nhập nhịp hoặc nội suy qua Skill 00 "
                    "và xác nhận")
        return why
    other = store.axes.get(_OTHER[orientation])
    if other is None or not _known(other):
        return (f"nhóm trục {_OTHER[orientation]} không có trục nào có toạ độ — không xác định được chiều dài "
                f"đường trục {orientation}")
    return ""


def _known(group: AxisGroup) -> List[Tuple[str, float]]:
    """(tên, toạ độ) các trục đã có toạ độ, theo thứ tự trong nhóm."""
    return [(n, float(o)) for n, o in zip(group.names, group.offsets()) if o is not None]


def axis_layout(store: ProjectStore) -> Dict[str, Any]:
    """Bố cục lưới trục TÍNH từ store (không vẽ): khung trục, bán kính, khoảng đặt tâm vòng tròn và hình học
    từng trục vẽ được. Trục không vẽ được nằm trong "skipped" kèm lý do.

    Trả về:
      {"scale", "bubble_r", "bubble_dist", "text_h",
       "frames": {"V": (xmin, xmax) | None, "H": (ymin, ymax) | None},
       "axes": [{"orientation", "name", "offset", "centers": [c0, c1], "line": (p1, p2)}, ...],
       "skipped": [(orientation, name, lý do), ...]}
    """
    scale = int(store.project.scale)
    r = paper_to_model(AXIS_BUBBLE_DIAMETER_PAPER_MM, scale) / 2.0
    d = paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"], scale)
    frames: Dict[str, Optional[Tuple[float, float]]] = {}
    for o in ORIENTATIONS:
        g = store.axes.get(o)
        known = _known(g) if g is not None else []
        frames[o] = (min(v for _, v in known), max(v for _, v in known)) if known else None

    axes: List[Dict[str, Any]] = []
    skipped: List[Tuple[str, str, str]] = []
    for o in ORIENTATIONS:
        g = store.axes.get(o)
        if g is None:
            continue
        for name in g.names:
            why = axis_skip_reason(store, o, name)
            if why:
                skipped.append((o, name, why))
                continue
            pos = float(g.offset_of(name))
            lo, hi = frames[_OTHER[o]]
            c0, c1 = lo - d, hi + d
            if o == "V":
                centers = [(pos, c0), (pos, c1)]
                line = ((pos, c0 + r), (pos, c1 - r))
            else:
                centers = [(c0, pos), (c1, pos)]
                line = ((c0 + r, pos), (c1 - r, pos))
            axes.append({"orientation": o, "name": name, "offset": pos, "centers": centers, "line": line})
    return {"scale": scale, "bubble_r": r, "bubble_dist": d, "text_h": text_height("truc", scale),
            "frames": frames, "axes": axes, "skipped": skipped}


# ── skill ────────────────────────────────────────────────────────────────────

class LuoiTrucSkill(DraftSkill):
    code = "01"
    name = "Lưới trục"
    reads = ("project", "axes")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        lay = axis_layout(store)
        r, th = lay["bubble_r"], lay["text_h"]

        for ax in lay["axes"]:
            base = f"truc/{ax['orientation']}/{ax['name']}"
            p1, p2 = ax["line"]
            self.add(plan, "line", "truc", f"{base}/line", p1=p1, p2=p2)
            for i, c in enumerate(ax["centers"]):
                self.add(plan, "circle", "truc_kh", f"{base}/bubble/{i}", center=c, r=r)
                self.add(plan, "text", "truc_kh", f"{base}/name/{i}", insert=c, text=str(ax["name"]),
                         height=th, rotation=0.0, align="MIDDLE_CENTER")

        for o, name, why in lay["skipped"]:
            result.skip(f"truc:{name}", why)

        # ── ghi chú: số trục đã vẽ / tổng, khung chưa đủ, số liệu chưa chắc ──
        for o in ORIENTATIONS:
            g = store.axes.get(o)
            if g is None:
                result.notes.append(f"không có nhóm {_KIND_NAME[o]} trong dữ liệu")
                continue
            n_drawn = sum(1 for a in lay["axes"] if a["orientation"] == o)
            result.notes.append(f"{_KIND_NAME[o]}: đã vẽ {n_drawn}/{len(g.names)} trục")
            n_unknown = sum(1 for v in g.offsets() if v is None)
            if n_unknown and lay["frames"][o] is not None and any(a["orientation"] == _OTHER[o] for a in lay["axes"]):
                lo, hi = lay["frames"][o]
                result.notes.append(
                    f"khung nhóm {o} chỉ tính trên trục đã có toạ độ [{lo:g}, {hi:g}] — còn {n_unknown} trục {o} "
                    f"chưa có toạ độ nên chiều dài đường trục {_OTHER[o]} sẽ thay đổi khi đủ số liệu")
            for i, s in enumerate(g.spans):
                if s is not None and s <= 0:
                    result.notes.append(f"CẢNH BÁO nhịp trục {g.names[i]}–{g.names[i + 1]} = {s:g} mm ≤ 0 "
                                        f"(khoá axes:{o}.spans[{i}]) — hai trục trùng hoặc đảo thứ tự")
            drawn = sorted((a["offset"], a["name"]) for a in lay["axes"] if a["orientation"] == o)
            for (p, n1), (q, n2) in zip(drawn, drawn[1:]):
                if q - p < 2.0 * r:
                    result.notes.append(f"CẢNH BÁO vòng tròn tên trục {n1} và {n2} chồng nhau: hai trục cách "
                                        f"{q - p:g} mm < đường kính vòng tròn {2.0 * r:g} mm")
        for ax in lay["axes"]:
            keys = axis_unconfirmed_keys(store, ax["name"])
            if keys:
                result.notes.append(f"trục {ax['name']}: toạ độ dựa trên số liệu nội suy CHƯA xác nhận "
                                    f"({', '.join(keys)})")
