# -*- coding: utf-8 -*-
"""
SKILL 04 — CỬA: cánh cửa, cung mở, khung cửa sổ (vai trò "cua") và ký hiệu cửa (vai trò "cua_kh").

Chỉ vẽ ô cửa có geom.opening_frame; thiếu số liệu → result.skip("cua:<id>", lý do) — lý do bắt đầu bằng
geom.opening_reason và kể thêm mọi số liệu riêng của ô cửa còn thiếu kèm khoá (xem s03_tuong.opening_skip_reason).

Cửa đi (cua_di) — theo geom.door_leaves (1 hoặc 2 cánh):
  - mỗi cánh: line từ bản lề (hinge) tới đầu cánh khi mở 90° (open)      eid "cua/<id>/leaf/<k>"
  - mỗi cánh: arc tâm bản lề, bán kính r, start_angle → end_angle          eid "cua/<id>/arc/<k>"
  (không vẽ ngưỡng cửa).
Cửa sổ (cua_so) — trong hệ (u dọc tường, n pháp tuyến trái) của geom.opening_frame:
  - 4 line song song tường từ mép a tới mép b ở khoảng lệch n = −t/2, −25, +25, +t/2   eid "cua/<id>/line/0..3"
  - 2 line đóng hai đầu ngang qua chiều dày tại a và tại b                               eid "cua/<id>/line/4..5"
  (tường mỏng t ≤ 50 mm: hai đường giữa ±25 nằm ngoài mặt tường nên KHÔNG vẽ line/1, line/2 — ghi CẢNH BÁO).
Ký hiệu (mark; mark rỗng thì dùng id) — text cao text_height("cua_kh", tỷ lệ), MIDDLE_CENTER, eid "cua_kh/<id>":
  đặt tại trung điểm ô cửa, lệch ra phía KHÔNG có cánh mở (cửa đi) / phía PHẢI hướng tường (cửa sổ) một khoảng
  t/2 + 2,5 mm giấy × tỷ lệ; xoay theo hướng tường nhưng luôn đọc được (góc trong (−90°, 90°]).

Ghi chú kết quả: số ô cửa đã vẽ / tổng, ô cửa vượt ra ngoài tim tường, ô cửa chồng nhau trên cùng tường, ô cửa
dựa trên số liệu nội suy CHƯA xác nhận. Skill không sửa store.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from tools.cad_drafting import geom
from tools.cad_drafting.layers import paper_to_model, text_height
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills.base import DraftSkill, SkillResult
from tools.cad_drafting.skills.s03_tuong import opening_skip_reason, opening_unconfirmed_keys
from tools.cad_drafting.store import Opening, ProjectStore

Point = Tuple[float, float]

WINDOW_GLASS_OFFSET = 25.0      # mm model — hai đường giữa của cửa sổ (lớp kính) cách tim tường ±25
MARK_GAP_PAPER_MM = 2.5         # mm trên giấy — ký hiệu cửa cách mặt tường
OVERLAP_TOL = geom.TOL          # mm — dung sai coi hai ô cửa chồng nhau / vượt ra ngoài tim tường

_KIND_NAME = {"cua_di": "cửa đi", "cua_so": "cửa sổ"}


# ── trợ giúp dùng chung (kiểm thử cũng dùng) ────────────────────────────────

def readable_angle(u: Point) -> float:
    """Góc xoay chữ theo hướng vectơ u nhưng luôn đọc được: đưa về khoảng (−90°, 90°]."""
    a = geom.angle_deg(u)                 # [0, 360)
    if a > 180.0:
        a -= 360.0                        # (−180, 180]
    if a > 90.0:
        a -= 180.0
    elif a <= -90.0:
        a += 180.0
    return round(a, 9) + 0.0              # + 0.0 bỏ −0.0


def window_lines(frame: Dict[str, object]) -> List[Tuple[int, Point, Point]]:
    """Các line của cửa sổ [(k, p1, p2)]: k = 0..3 song song tường (lệch −t/2, −25, +25, +t/2), k = 4, 5 đóng
    hai đầu tại a và b. Tường mỏng (t/2 ≤ 25) bỏ k = 1, 2."""
    a, b, n, t = frame["a"], frame["b"], frame["n"], float(frame["t"])
    half = t / 2.0
    out: List[Tuple[int, Point, Point]] = []
    for k, d in enumerate((-half, -WINDOW_GLASS_OFFSET, WINDOW_GLASS_OFFSET, half)):
        if k in (1, 2) and half <= WINDOW_GLASS_OFFSET:
            continue
        out.append((k, geom.add(a, geom.mul(n, d)), geom.add(b, geom.mul(n, d))))
    for k, p in ((4, a), (5, b)):
        out.append((k, geom.add(p, geom.mul(n, -half)), geom.add(p, geom.mul(n, half))))
    return out


def mark_side(store: ProjectStore, op: Opening, frame: Dict[str, object]) -> Point:
    """Vectơ đơn vị phía đặt ký hiệu: cửa đi → phía KHÔNG có cánh mở; cửa sổ → phía phải hướng tường (−n)."""
    n = frame["n"]
    if op.kind == "cua_di":
        leaves = geom.door_leaves(store, op) or []
        if leaves:
            swing = geom.unit(geom.sub(leaves[0]["open"], leaves[0]["hinge"]))
            return geom.mul(swing, -1.0)
    return geom.mul(n, -1.0)


def mark_placement(store: ProjectStore, op: Opening, frame: Dict[str, object]) -> Dict[str, object]:
    """Vị trí, góc xoay, chiều cao và nội dung ký hiệu cửa."""
    scale = int(store.project.scale)
    mid = geom.mul(geom.add(frame["a"], frame["b"]), 0.5)
    dist = float(frame["t"]) / 2.0 + paper_to_model(MARK_GAP_PAPER_MM, scale)
    side = mark_side(store, op, frame)
    text = (op.mark or "").strip() or op.id
    return {"insert": geom.add(mid, geom.mul(side, dist)), "rotation": readable_angle(frame["u"]),
            "height": text_height("cua_kh", scale), "text": text}


def _range_warnings(store: ProjectStore, frames: Dict[str, Dict[str, object]]) -> List[str]:
    """CẢNH BÁO ô cửa vượt ra ngoài tim tường và ô cửa chồng nhau trên cùng một tường."""
    notes: List[str] = []
    by_wall: Dict[str, List[Opening]] = {}
    for op in store.openings:
        f = frames.get(op.id)
        if f is None:
            continue
        lo, hi, L = float(op.offset), float(op.offset) + float(op.width), float(f["wall_length"])
        if lo < -OVERLAP_TOL or hi > L + OVERLAP_TOL:
            notes.append(f"CẢNH BÁO ô cửa {op.id} vượt ra ngoài tim tường {op.wall_id}: đoạn [{lo:g}, {hi:g}] mm "
                         f"so với chiều dài tim tường {L:g} mm")
        by_wall.setdefault(op.wall_id, []).append(op)
    for wall_id in sorted(by_wall):
        ops = sorted(by_wall[wall_id], key=lambda o: (float(o.offset), o.id))
        for i, p in enumerate(ops):
            for q in ops[i + 1:]:
                if float(q.offset) < float(p.offset) + float(p.width) - OVERLAP_TOL:
                    notes.append(f"CẢNH BÁO ô cửa {p.id} và {q.id} chồng nhau trên tường {wall_id}")
    return notes


# ── skill ────────────────────────────────────────────────────────────────────

class CuaSkill(DraftSkill):
    code = "04"
    name = "Cửa"
    reads = ("project", "axes", "walls", "openings")

    def draw(self, store: ProjectStore, plan: DrawingPlan, result: SkillResult) -> None:
        frames: Dict[str, Dict[str, object]] = {}
        drawn = {"cua_di": 0, "cua_so": 0}
        thin = []
        doubtful = []
        for op in store.openings:
            why = opening_skip_reason(store, op)
            frame: Optional[Dict[str, object]] = None if why else geom.opening_frame(store, op)
            if frame is None:
                result.skip(f"cua:{op.id}", why or "không dựng được khung ô cửa từ số liệu hiện có")
                continue
            frames[op.id] = frame
            base = f"cua/{op.id}"
            if op.kind == "cua_di":
                leaves = geom.door_leaves(store, op) or []
                for k, lf in enumerate(leaves):
                    self.add(plan, "line", "cua", f"{base}/leaf/{k}", p1=lf["hinge"], p2=lf["open"])
                    self.add(plan, "arc", "cua", f"{base}/arc/{k}", center=lf["hinge"], r=lf["r"],
                             start_angle=lf["start_angle"], end_angle=lf["end_angle"])
            else:
                lines = window_lines(frame)
                for k, p1, p2 in lines:
                    self.add(plan, "line", "cua", f"{base}/line/{k}", p1=p1, p2=p2)
                if len(lines) < 6:
                    thin.append(f"{op.id} (tường {op.wall_id} dày {float(frame['t']):g} mm)")
            m = mark_placement(store, op, frame)
            self.add(plan, "text", "cua_kh", f"cua_kh/{op.id}", insert=m["insert"], text=m["text"],
                     height=m["height"], rotation=m["rotation"], align="MIDDLE_CENTER")
            drawn[op.kind] += 1
            keys = opening_unconfirmed_keys(store, op)
            if keys:
                doubtful.append(f"{op.id} ({', '.join(keys)})")

        total = {k: sum(1 for o in store.openings if o.kind == k) for k in drawn}
        result.notes.append(f"đã vẽ {sum(drawn.values())}/{len(store.openings)} ô cửa ("
                            + ", ".join(f"{_KIND_NAME[k]}: {drawn[k]}/{total[k]}" for k in drawn) + ")")
        if thin:
            result.notes.append(f"CẢNH BÁO tường mỏng (t ≤ {2 * WINDOW_GLASS_OFFSET:g} mm), cửa sổ chỉ vẽ hai "
                                f"đường mặt tường, không vẽ hai đường giữa ±{WINDOW_GLASS_OFFSET:g} mm: "
                                + "; ".join(thin))
        result.notes.extend(_range_warnings(store, frames))
        if doubtful:
            result.notes.append("ô cửa dựa trên số liệu nội suy CHƯA xác nhận: " + "; ".join(doubtful))
