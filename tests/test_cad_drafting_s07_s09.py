# -*- coding: utf-8 -*-
"""Test Skill 07 (hatch cột, tường, sàn) và Skill 09 (tên phòng, diện tích, cote, bảng hoàn thiện) của agent dựng CAD
mặt bằng (tools/cad_drafting)."""

import unittest
from decimal import Decimal

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from tools.cad_drafting import geom
from tools.cad_drafting.layers import LAYOUT_PAPER_MM, paper_to_model, text_height
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.skills.s07_hatch import HatchSkill
from tools.cad_drafting.skills.s09_hoan_thien import (TABLE_COLUMNS, HoanThienSkill, area_m2, format_area,
                                                      format_level, wrap_text)
from tools.cad_drafting.store import ProjectStore, Provenance

EPS = 1e-3


def run_skill(cls, store, plan=None):
    plan = plan or new_plan(store)
    return plan, cls().run(store, plan)


def ops_by_eid(plan):
    return {o.eid: o for o in plan.ops}


def skipped_map(result):
    return {s["id"]: s["ly_do"] for s in result.skipped}


def hatch_polygon(op):
    loops = op.data["boundaries"]
    return Polygon(loops[0], loops[1:])


def hatch_union(plan, prefix):
    return unary_union([hatch_polygon(o) for o in plan.ops if o.kind == "hatch" and o.eid.startswith(prefix)])


def text_box(op, shrink=1e-6):
    """Khung chữ ước lượng (bề rộng ký tự 0,75 × chiều cao) theo căn lề của Op text."""
    d = op.data
    w = 0.75 * d["height"] * len(d["text"])
    h = d["height"]
    x, y = d["insert"]
    if d["align"] == "MIDDLE_CENTER":
        x0 = x - w / 2
    elif d["align"] == "MIDDLE_LEFT":
        x0 = x
    else:
        raise AssertionError(f"căn lề không dự kiến: {d['align']}")
    return box(x0 + shrink, y - h / 2 + shrink, x0 + w - shrink, y + h / 2 - shrink)


def small_store(**extra):
    """Kho nhỏ: V 1-2-3 (nhịp 3000, 3000), H A-B (nhịp 3000)."""
    d = {"project": {"scale": 100},
         "axes": {"V": {"names": ["1", "2", "3"], "spans": [3000, 3000]},
                  "H": {"names": ["A", "B"], "spans": [3000]}}}
    d.update(extra)
    return ProjectStore.from_dict(d)


# ═════════════════════════════════════════════════════════════════════════════
# SKILL 07 — HATCH
# ═════════════════════════════════════════════════════════════════════════════

class HatchSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load_sample()
        cls.plan, cls.result = run_skill(HatchSkill, cls.store)
        cls.ops = ops_by_eid(cls.plan)

    def test_skill_identity(self):
        self.assertIs(skill_class("07"), HatchSkill)
        self.assertEqual((HatchSkill.code, HatchSkill.name), ("07", "Hatch"))
        self.assertEqual(HatchSkill.reads, ("project", "axes", "columns", "walls", "openings", "rooms", "stairs",
                                            "furniture", "blocks"))
        self.assertEqual(self.result.skipped, [])

    def test_one_solid_hatch_per_column(self):
        col_ops = [o for o in self.plan.ops if o.eid.startswith("07/hatch/cot/")]
        self.assertEqual(sorted(o.eid for o in col_ops), sorted(f"07/hatch/cot/{c.id}" for c in self.store.columns))
        for col in self.store.columns:
            op = self.ops[f"07/hatch/cot/{col.id}"]
            self.assertEqual((op.kind, op.role, op.data["pattern"]), ("hatch", "hatch", "SOLID"))
            self.assertEqual((op.data["pattern_scale"], op.data["angle"]), (1.0, 0.0))
            poly = hatch_polygon(op)
            self.assertAlmostEqual(poly.area, 220 * 220, delta=EPS)
            self.assertLess(poly.symmetric_difference(geom.column_polygon(self.store, col)).area, EPS)

    def test_wall_hatch_ansi31_scaled_to_paper(self):
        wall_ops = [o for o in self.plan.ops if o.eid.startswith("07/hatch/tuong/")]
        self.assertTrue(wall_ops)
        self.assertTrue(all(o.eid.startswith("07/hatch/tuong/xay/") for o in wall_ops))   # đề bài chỉ có tường xây
        for o in wall_ops:
            self.assertEqual(o.data["pattern"], "ANSI31")
            self.assertAlmostEqual(o.data["pattern_scale"], 100 / 3.175, places=9)
            self.assertEqual(o.data["angle"], 0.0)
        hatched = hatch_union(self.plan, "07/hatch/tuong/")
        body = geom.wall_body(self.store)
        self.assertLess(hatched.symmetric_difference(body).area, 1.0)
        self.assertLess(hatched.intersection(geom.openings_union(self.store)).area, EPS)   # ô cửa không bị tô
        self.assertLess(hatched.intersection(geom.columns_union(self.store)).area, EPS)    # cột không tô 2 lần

    def test_wall_hatch_ids_sorted_by_bbox(self):
        ops = [self.ops[f"07/hatch/tuong/xay/{i}"] for i in range(len(
            [o for o in self.plan.ops if o.eid.startswith("07/hatch/tuong/xay/")]))]
        keys = [tuple(round(v, 3) for v in hatch_polygon(o).bounds) for o in ops]
        self.assertEqual(keys, sorted(keys))

    def test_floor_patterns(self):
        expect = {"P1": ("NET", 600 / 3.175), "P2": ("NET", 600 / 3.175), "P3": ("LINE", 150 / 3.175),
                  "P4": ("NET", 600 / 3.175), "P5": ("NET", 300 / 3.175), "P6": ("NET", 600 / 3.175)}
        for rid, (pattern, scale) in expect.items():
            op = self.ops[f"07/hatch/san/{rid}/0"]
            self.assertEqual(op.data["pattern"], pattern, rid)
            self.assertAlmostEqual(op.data["pattern_scale"], scale, places=9, msg=rid)

    def test_floor_hatch_does_not_cover_walls_or_columns(self):
        walls = geom.walls_union(self.store)
        cols = geom.columns_union(self.store)
        floors = [o for o in self.plan.ops if o.eid.startswith("07/hatch/san/")]
        self.assertGreaterEqual(len(floors), 6)
        for o in floors:
            poly = hatch_polygon(o)
            self.assertTrue(poly.is_valid, o.eid)
            self.assertLess(poly.intersection(walls).area, 0.01, o.eid)
            self.assertLess(poly.intersection(cols).area, 0.01, o.eid)

    def test_stair_hall_excludes_flight(self):
        flight = geom.flight_polygon(self.store, self.store.get("stairs", "ST1").flights[0])
        p4 = [o for o in self.plan.ops if o.eid.startswith("07/hatch/san/P4/")]
        self.assertEqual(len(p4), 1)
        self.assertEqual(len(p4[0].data["boundaries"]), 2)            # vế thang nằm giữa sảnh → một lỗ
        region = hatch_polygon(p4[0])
        self.assertLess(region.intersection(flight).area, 0.01)
        room = geom.room_polygon(self.store, self.store.get("rooms", "P4"))
        expected = room.difference(unary_union([geom.walls_union(self.store), geom.columns_union(self.store)]))
        self.assertAlmostEqual(region.area, expected.area - flight.area, delta=1.0)

    def test_ownership_and_rerun_without_duplicates(self):
        self.assertEqual(self.plan.ownership_violations(), [])
        fp, n = self.plan.fingerprint("07"), len(self.plan.ops)
        result = HatchSkill().run(self.store, self.plan)
        self.assertEqual((self.plan.fingerprint("07"), len(self.plan.ops)), (fp, n))
        self.assertEqual(result.ops_added, n)

    def test_hatch_boundaries_ccw_outer_cw_holes(self):
        for o in self.plan.ops:
            loops = o.data["boundaries"]
            self.assertTrue(Polygon(loops[0]).exterior.is_ccw, o.eid)
            for hole in loops[1:]:
                self.assertFalse(Polygon(hole).exterior.is_ccw, o.eid)


class HatchDataCasesTest(unittest.TestCase):
    def test_unknown_floor_key_skipped(self):
        store = load_sample()
        store.get("rooms", "P2").hatch = "da_hoa_cuong"
        plan, result = run_skill(HatchSkill, store)
        skipped = skipped_map(result)
        self.assertIn("hatch:P2", skipped)
        self.assertIn("da_hoa_cuong", skipped["hatch:P2"])
        self.assertFalse([o for o in plan.ops if o.eid.startswith("07/hatch/san/P2/")])
        self.assertTrue([o for o in plan.ops if o.eid.startswith("07/hatch/san/P1/")])

    def test_empty_floor_key_is_not_an_error(self):
        store = load_sample()
        store.get("rooms", "P6").hatch = ""
        plan, result = run_skill(HatchSkill, store)
        self.assertNotIn("hatch:P6", skipped_map(result))
        self.assertFalse([o for o in plan.ops if o.eid.startswith("07/hatch/san/P6/")])
        self.assertTrue(any("P6" in n and "không khai báo" in n for n in result.notes))

    def test_missing_span_skips_with_reason(self):
        store = load_sample(filled=False)
        plan, result = run_skill(HatchSkill, store)
        skipped = skipped_map(result)
        for rid in ("P1", "P2", "P4", "P5", "P6"):
            self.assertIn(f"hatch:{rid}", skipped)
            self.assertIn("axes:V.spans[1]", skipped[f"hatch:{rid}"])
        self.assertNotIn("hatch:P3", skipped)
        self.assertIn("07/hatch/san/P3/0", ops_by_eid(plan))
        for cid in ("C-3A", "C-4C"):
            self.assertIn("axes:V.spans[1]", skipped[f"hatch:cot/{cid}"])
        self.assertIn("07/hatch/cot/C-1A", ops_by_eid(plan))
        for wid in ("W1", "W2", "W3", "W6", "W8", "W9"):
            self.assertIn(f"hatch:tuong/{wid}", skipped)
        self.assertNotIn("hatch:tuong/W4", skipped)
        self.assertEqual(plan.ownership_violations(), [])

    def test_unsubtracted_opening_is_reported(self):
        store = load_sample()
        store.get("openings", "CD2").width = None
        _, result = run_skill(HatchSkill, store)
        self.assertTrue(any("CD2" in n and "W5" in n for n in result.notes))

    def test_tiny_slivers_dropped_with_note(self):
        store = small_store(
            walls=[{"id": "W1", "start": "1/A", "end": "2/A", "thickness": 200}],
            rooms=[{"id": "R1", "name": "R1", "hatch": "gach_600",
                    "boundary": [[500, -100.0002], [2500, -100.0002], [2500, 2000], [500, 2000]]},
                   {"id": "R2", "name": "R2", "hatch": "gach_600",
                    "boundary": [[4000, 1000], [4000.5, 1000], [4000.5, 1000.5], [4000, 1000.5]]}])
        plan, result = run_skill(HatchSkill, store)
        r1 = [o for o in plan.ops if o.eid.startswith("07/hatch/san/R1/")]
        self.assertEqual(len(r1), 1)                                  # mảnh 0,4 mm² dưới tường bị bỏ
        self.assertGreater(hatch_polygon(r1[0]).area, 3.0e6)
        skipped = skipped_map(result)
        self.assertIn("hatch:R2", skipped)                            # phòng 0,25 mm²: không còn gì để tô
        self.assertIn("1 mm²", skipped["hatch:R2"])
        self.assertTrue(any(n.startswith("bỏ 2 vùng hatch") for n in result.notes), result.notes)

    def test_unknown_wall_kind_skipped(self):
        store = small_store(walls=[{"id": "W1", "start": "1/A", "end": "3/A", "thickness": 200, "kind": "go"}])
        plan, result = run_skill(HatchSkill, store)
        self.assertIn("loại tường lạ", skipped_map(result)["hatch:tuong/W1"])
        self.assertFalse(plan.ops_of(skill="07"))

    def test_btct_solid_and_brick_do_not_overlap(self):
        store = small_store(walls=[
            {"id": "W1", "start": "1/A", "end": "3/A", "thickness": 200, "kind": "btct"},
            {"id": "W2", "start": "2/A", "end": "2/B", "thickness": 110, "kind": "xay"}])
        plan, result = run_skill(HatchSkill, store)
        btct = [o for o in plan.ops if o.eid.startswith("07/hatch/tuong/btct/")]
        self.assertEqual([o.data["pattern"] for o in btct], ["SOLID"])
        xay = hatch_union(plan, "07/hatch/tuong/xay/")
        self.assertGreater(xay.area, 0)
        self.assertLess(xay.intersection(hatch_union(plan, "07/hatch/tuong/btct/")).area, EPS)

    def test_scale_changes_paper_patterns_only(self):
        store = load_sample()
        store.project.scale = 50
        plan, _ = run_skill(HatchSkill, store)
        ops = ops_by_eid(plan)
        self.assertAlmostEqual(ops["07/hatch/tuong/xay/0"].data["pattern_scale"], 50 / 3.175, places=9)
        self.assertAlmostEqual(ops["07/hatch/san/P1/0"].data["pattern_scale"], 600 / 3.175, places=9)

    def test_interpolated_dependency_noted(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("tổng 10800 − 3600 − 3600"))
        _, result = run_skill(HatchSkill, store)
        self.assertEqual(result.skipped, [])
        note = [n for n in result.notes if "nội suy CHƯA xác nhận" in n]
        self.assertEqual(len(note), 1)
        self.assertIn("axes:V.spans[1]", note[0])


# ═════════════════════════════════════════════════════════════════════════════
# SKILL 09 — HOÀN THIỆN
# ═════════════════════════════════════════════════════════════════════════════

def table_ops(plan):
    return [o for o in plan.ops if o.eid.startswith("09/hoan_thien/bang/")]


def cell_text(plan, key):
    """Ghép các dòng chữ của một ô bảng (eid 09/hoan_thien/bang/<key>/<dòng>)."""
    ops = ops_by_eid(plan)
    lines, j = [], 0
    while f"09/hoan_thien/bang/{key}/{j}" in ops:
        lines.append(ops[f"09/hoan_thien/bang/{key}/{j}"].data["text"])
        j += 1
    return " ".join(lines)


class FormatTest(unittest.TestCase):
    def test_area_half_up_and_vietnamese_format(self):
        self.assertEqual(area_m2(box(0, 0, 7200, 4200)), Decimal("30.24"))
        self.assertEqual(format_area(area_m2(box(0, 0, 3000, 4115))), "12,35")      # 12,345 → half-up
        self.assertEqual(format_area(Decimal("1234.5")), "1.234,50")
        self.assertEqual(format_area(Decimal("0")), "0,00")

    def test_level_format(self):
        self.assertEqual(format_level(0), "±0.000")
        self.assertEqual(format_level(-0.2), "±0.000")
        self.assertEqual(format_level(450), "+0.450")
        self.assertEqual(format_level(-20), "-0.020")
        self.assertEqual(format_level(1234.5), "+1.235")

    def test_wrap_respects_width_and_keeps_units(self):
        lines = wrap_text("Ốp gạch men cao 1,5 m", 3000, 200)
        self.assertEqual(lines, ["Ốp gạch men cao", "1,5 m"])
        for ln in wrap_text("Lát gạch chống trơn 300×300 rất rất dài", 1200, 200):
            self.assertLessEqual(0.75 * 200 * len(ln), 1200)
        self.assertEqual(wrap_text("ABCDEFGHIJ", 600, 200), ["ABCD", "EFGH", "IJ"])
        self.assertEqual(wrap_text("   ", 600, 200), [])


class HoanThienSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load_sample()
        cls.plan, cls.result = run_skill(HoanThienSkill, cls.store)
        cls.ops = ops_by_eid(cls.plan)

    def test_skill_identity(self):
        self.assertIs(skill_class("09"), HoanThienSkill)
        self.assertEqual((HoanThienSkill.code, HoanThienSkill.name), ("09", "Hoàn thiện"))
        self.assertEqual(HoanThienSkill.reads, ("project", "axes", "rooms", "walls", "columns", "furniture", "blocks",
                                                "stairs", "openings"))
        self.assertEqual(self.result.skipped, [])

    def test_room_labels(self):
        name = self.ops["09/hoan_thien/P1/ten"]
        area = self.ops["09/hoan_thien/P1/dien_tich"]
        cote = self.ops["09/hoan_thien/P1/cote"]
        self.assertEqual(name.data["text"], "PHÒNG KHÁCH")
        self.assertEqual(area.data["text"], "S = 30,24 m²")
        self.assertEqual(cote.data["text"], "±0.000")
        self.assertEqual(name.data["height"], text_height("ten_phong", 100))
        self.assertEqual(area.data["height"], text_height("dien_tich", 100))
        for op in (name, area, cote):
            self.assertEqual((op.kind, op.role, op.data["align"]), ("text", "hoan_thien", "MIDDLE_CENTER"))
        self.assertGreater(name.data["insert"][1], area.data["insert"][1])
        self.assertGreater(area.data["insert"][1], cote.data["insert"][1])
        self.assertEqual(name.data["insert"][0], area.data["insert"][0])
        self.assertEqual(self.ops["09/hoan_thien/P5/cote"].data["text"], "-0.020")
        self.assertEqual(self.ops["09/hoan_thien/P5/dien_tich"].data["text"], "S = 7,20 m²")

    def test_labels_inside_room_clear_of_walls(self):
        walls = geom.walls_union(self.store)
        for room in self.store.rooms:
            free = geom.room_polygon(self.store, room).difference(walls)
            for part in ("ten", "dien_tich", "cote"):
                op = self.ops[f"09/hoan_thien/{room.id}/{part}"]
                self.assertTrue(free.contains(text_box(op)), f"{room.id}/{part}")

    def test_table_position_and_header(self):
        frame = self.ops["09/hoan_thien/bang/khung"].data["points"]
        x0 = 10800 + paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"] + 22, 100)
        y0 = 8400 + paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"], 100)
        self.assertEqual((min(p[0] for p in frame), max(p[1] for p in frame)), (x0, y0))
        width = max(p[0] for p in frame) - x0
        self.assertAlmostEqual(width, paper_to_model(sum(w for _, w, _ in TABLE_COLUMNS), 100))
        self.assertEqual(cell_text(self.plan, "tieu_de"), "BẢNG HOÀN THIỆN")
        headers = [cell_text(self.plan, f"cot/{c}") for c in range(7)]
        self.assertEqual(headers, ["STT", "Phòng", "Diện tích (m²)", "Sàn", "Tường", "Trần", "Cote"])
        self.assertEqual(cell_text(self.plan, "hang/P1/2"), "30,24")
        self.assertEqual(cell_text(self.plan, "hang/P5/6"), "-0.020")
        self.assertEqual(cell_text(self.plan, "hang/P5/3"), "Lát gạch chống trơn 300×300")
        self.assertIn("09/hoan_thien/bang/hang/P5/3/1", self.ops)              # chữ dài đã xuống dòng

    def test_total_and_basis_note(self):
        self.assertEqual(cell_text(self.plan, "tong/0"), "Tổng diện tích")
        self.assertEqual(cell_text(self.plan, "tong/1"), "90,72")
        self.assertEqual(cell_text(self.plan, "tong/2"), "tính 6/6 phòng")
        note = cell_text(self.plan, "ghi_chu/0")
        self.assertIn("theo đường bao nhập", note)
        self.assertIn("KHÔNG phải diện tích thông thủy", note)

    def test_every_table_text_inside_its_cell(self):
        grid = []
        for o in table_ops(self.plan):
            if o.kind == "line":
                grid.append(LineString([o.data["p1"], o.data["p2"]]))
            elif o.kind == "pline":
                pts = o.data["points"]
                grid.append(LineString(pts + [pts[0]]))
        frame = Polygon(self.ops["09/hoan_thien/bang/khung"].data["points"])
        x0 = frame.bounds[0]
        edges = [x0]
        for _, w, _ in TABLE_COLUMNS:
            edges.append(edges[-1] + paper_to_model(w, 100))
        texts = [o for o in table_ops(self.plan) if o.kind == "text"]
        self.assertGreater(len(texts), 50)
        for o in texts:
            tb = text_box(o)
            self.assertTrue(frame.contains(tb), o.eid)
            for ln in grid:
                self.assertFalse(tb.intersects(ln), f"{o.eid} chạm đường kẻ")
            parts = o.eid.split("/")
            if parts[3] in ("cot", "hang"):
                c = int(parts[-2])
                self.assertGreaterEqual(tb.bounds[0], edges[c], o.eid)
                self.assertLessEqual(tb.bounds[2], edges[c + 1], o.eid)

    def test_ownership_and_rerun_without_duplicates(self):
        self.assertEqual(self.plan.ownership_violations(), [])
        fp, n = self.plan.fingerprint("09"), len(self.plan.ops)
        HoanThienSkill().run(self.store, self.plan)
        self.assertEqual((self.plan.fingerprint("09"), len(self.plan.ops)), (fp, n))


class HoanThienDataCasesTest(unittest.TestCase):
    def test_missing_span_rooms_skipped_and_total_counts_pending(self):
        store = load_sample(filled=False)
        plan, result = run_skill(HoanThienSkill, store)
        skipped = skipped_map(result)
        for rid in ("P1", "P2", "P4", "P5", "P6"):
            self.assertIn("axes:V.spans[1]", skipped[f"hoan_thien:{rid}"])
            self.assertNotIn(f"09/hoan_thien/{rid}/ten", ops_by_eid(plan))
            self.assertEqual(cell_text(plan, f"hang/{rid}/2"), "chưa tính")     # vẫn có hàng trong bảng
        self.assertEqual(ops_by_eid(plan)["09/hoan_thien/P3/dien_tich"].data["text"], "S = 15,12 m²")
        self.assertEqual(cell_text(plan, "tong/1"), "15,12")
        coverage = cell_text(plan, "tong/2")
        self.assertIn("tính 1/6 phòng", coverage)
        self.assertIn("chưa tính 5 phòng", coverage)
        frame = ops_by_eid(plan)["09/hoan_thien/bang/khung"].data["points"]
        self.assertEqual(min(p[0] for p in frame), 3600 + paper_to_model(38 + 22, 100))   # theo trục 2 đã biết
        self.assertTrue(any("trục 3, 4 chưa có toạ độ" in n for n in result.notes))

    def test_no_axes_table_skipped_labels_kept(self):
        store = ProjectStore.from_dict({
            "project": {"scale": 100},
            "rooms": [{"id": "R1", "name": "PHÒNG", "floor_level": 450,
                       "boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}]})
        plan, result = run_skill(HoanThienSkill, store)
        self.assertIn("bang_hoan_thien", skipped_map(result))
        self.assertTrue(any("không đặt được bảng" in n for n in result.notes))
        self.assertFalse(table_ops(plan))
        ops = ops_by_eid(plan)
        self.assertEqual(ops["09/hoan_thien/R1/dien_tich"].data["text"], "S = 12,00 m²")
        self.assertEqual(ops["09/hoan_thien/R1/cote"].data["text"], "+0.450")
        self.assertTrue(any("1 phòng (R1) theo đường bao người nhập" in n for n in result.notes))

    def test_interpolated_area_marked_never_confirmed(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("tổng 10800 − 3600 − 3600"))
        plan, result = run_skill(HoanThienSkill, store)
        ops = ops_by_eid(plan)
        self.assertEqual(ops["09/hoan_thien/P1/dien_tich"].data["text"], "S = 30,24 m²*")
        self.assertEqual(ops["09/hoan_thien/P3/dien_tich"].data["text"], "S = 15,12 m²")   # không dựa trục 3, 4
        self.assertEqual(cell_text(plan, "hang/P1/2"), "30,24*")
        self.assertEqual(cell_text(plan, "tong/1"), "90,72*")
        legend = cell_text(plan, "ghi_chu/1")
        self.assertIn("nội suy CHƯA xác nhận", legend)
        self.assertIn("axes:V.spans[1]", legend)
        self.assertTrue(any("nội suy CHƯA xác nhận" in n for n in result.notes))

    def test_empty_name_and_bad_level(self):
        store = load_sample()
        store.get("rooms", "P6").name = ""
        store.get("rooms", "P2").floor_level = "abc"
        store.get("rooms", "P3").floor_level = None
        store.get("rooms", "P3").ceiling_finish = ""
        plan, result = run_skill(HoanThienSkill, store)
        skipped = skipped_map(result)
        ops = ops_by_eid(plan)
        self.assertIn("hoan_thien:P6/ten", skipped)
        self.assertIn("09/hoan_thien/P6/dien_tich", ops)
        self.assertEqual(cell_text(plan, "hang/P6/1"), "chưa nhập")
        self.assertIn("hoan_thien:P2/cote", skipped)
        self.assertNotIn("09/hoan_thien/P2/cote", ops)
        self.assertNotIn("09/hoan_thien/P3/cote", ops)
        self.assertNotIn("hoan_thien:P3/cote", skipped)                   # không nhập cote: không phải lỗi
        self.assertEqual(cell_text(plan, "hang/P3/6"), "chưa nhập")
        self.assertTrue(any("P3" in n and "floor_level" in n for n in result.notes))
        self.assertTrue(any("P3 (trần)" in n for n in result.notes))

    def test_label_that_cannot_fit_stays_inside_room_with_warning(self):
        store = ProjectStore.from_dict({
            "project": {"scale": 100},
            "axes": {"V": {"names": ["1", "2"], "spans": [3000]}, "H": {"names": ["A", "B"], "spans": [3000]}},
            "rooms": [{"id": "HK", "name": "HỘP KỸ THUẬT ĐIỆN", "floor_level": 0,
                       "boundary": [[0, 0], [600, 0], [600, 600], [0, 600]]}]})
        plan, result = run_skill(HoanThienSkill, store)
        name = ops_by_eid(plan)["09/hoan_thien/HK/ten"]
        self.assertTrue(Polygon([(0, 0), (600, 0), (600, 600), (0, 600)]).contains(
            box(*name.data["insert"], *name.data["insert"]).buffer(0.01)))
        self.assertTrue(any(n.startswith("CẢNH BÁO nhãn không vừa") and "HK" in n for n in result.notes))


class S07S09PipelineTest(unittest.TestCase):
    def test_runs_after_skills_01_to_06_without_touching_them(self):
        store = load_sample()
        plan = new_plan(store)
        for code in ("01", "02", "03", "04", "05", "06"):
            skill_class(code)().run(store, plan)
        before = plan.fingerprints()
        for code in ("07", "09"):
            skill_class(code)().run(store, plan)
        after = plan.fingerprints()
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(plan.ownership_violations(), [])
        eids = [o.eid for o in plan.ops]
        self.assertEqual(len(eids), len(set(eids)))
        self.assertEqual({o.role for o in plan.ops_of(skill="07")}, {"hatch"})
        self.assertEqual({o.role for o in plan.ops_of(skill="09")}, {"hoan_thien"})


if __name__ == "__main__":
    unittest.main()
