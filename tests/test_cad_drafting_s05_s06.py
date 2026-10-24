# -*- coding: utf-8 -*-
"""Test Skill 05 (cầu thang), thư viện block và Skill 06 (nội thất) của agent dựng CAD mặt bằng (tools/cad_drafting)."""

import math
import unittest

from shapely import affinity
from shapely.geometry import MultiPoint, Point as ShPoint

from tools.cad_drafting import geom
from tools.cad_drafting.block_library import LIBRARY, block_origin, get_block, library_names
from tools.cad_drafting.layers import paper_to_model, roles_of, text_height
from tools.cad_drafting.plan import BlockDef, DrawingPlan, PlanError, iter_points
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.skills.s05_cau_thang import ARROW_PAPER_MM, CUT_AT, CauThangSkill
from tools.cad_drafting.skills.s06_noi_that import NoiThatSkill
from tools.cad_drafting.store import Furniture, ProjectStore, Provenance, StairFlight

TOL = 1e-6

EXPECTED_SIZES = {
    "GIUONG_DOI": [1600.0, 2000.0], "TU_AO": [1200.0, 600.0], "SOFA_3": [2100.0, 850.0],
    "BAN_TRA": [1000.0, 600.0], "BAN_AN_4": [1200.0, 1600.0], "TU_BEP": [2400.0, 600.0],
    "BON_CAU": [400.0, 700.0], "LAVABO": [500.0, 400.0],
}


def ops_by_eid(plan):
    return {o.eid: o for o in plan.ops}


def skipped_map(result):
    return {s["id"]: s["ly_do"] for s in result.skipped}


def run_skill(cls, store, plan=None):
    plan = plan or new_plan(store)
    return plan, cls().run(store, plan)


def bounds(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def stair_store(stairs, scale=100):
    """Kho nhỏ 3 × 3 trục (V: 1-2-3, nhịp thứ 2 THIẾU; H: A-B-C) chỉ có thang."""
    return ProjectStore.from_dict({
        "project": {"scale": scale},
        "axes": {"V": {"names": ["1", "2", "3"], "spans": [4000, None]},
                 "H": {"names": ["A", "B", "C"], "spans": [3000, 3000]}},
        "stairs": list(stairs)})


def transformed_block_points(blk, insert, rotation):
    """Mọi điểm định nghĩa của block sau khi chèn (xoay quanh điểm chèn, rồi tịnh tiến)."""
    a = math.radians(rotation)
    c, s = math.cos(a), math.sin(a)
    out = []
    for item in blk.ops:
        for x, y in iter_points(item):
            out.append((insert[0] + x * c - y * s, insert[1] + x * s + y * c))
    return out


# ─────────────────────────────────────────────────────────────────────────────

class RegistryTest(unittest.TestCase):
    def test_skill_classes_and_metadata(self):
        self.assertIs(skill_class("05"), CauThangSkill)
        self.assertIs(skill_class("06"), NoiThatSkill)
        s5, s6 = CauThangSkill(), NoiThatSkill()
        self.assertEqual((s5.code, s5.name, s5.reads), ("05", "Cầu thang", ("project", "axes", "stairs")))
        self.assertEqual((s6.code, s6.name, s6.reads),
                         ("06", "Nội thất", ("project", "axes", "furniture", "blocks")))
        self.assertEqual(s5.roles, ("thang",))
        self.assertEqual(s6.roles, ("noi_that",))
        self.assertEqual(s6.roles, roles_of("06"))

    def test_add_refuses_foreign_role(self):
        plan = new_plan(load_sample())
        with self.assertRaises(PlanError):
            CauThangSkill().add(plan, "line", "noi_that", "x", p1=[0, 0], p2=[1, 0])
        with self.assertRaises(PlanError):
            NoiThatSkill().add(plan, "line", "thang", "x", p1=[0, 0], p2=[1, 0])


# ─────────────────────────────────────────────────────────────────────────────

class CauThangSampleTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan, self.result = run_skill(CauThangSkill, self.store)
        self.ops = ops_by_eid(self.plan)
        self.poly = geom.flight_polygon(self.store, self.store.stairs[0].flights[0])

    def test_nothing_skipped_and_only_own_role(self):
        self.assertEqual(self.result.skipped, [])
        self.assertTrue(self.plan.ops)
        self.assertTrue(all(o.skill == "05" and o.role == "thang" for o in self.plan.ops))
        self.assertTrue(all(o.eid.startswith("05/thang/ST1/") for o in self.plan.ops))
        self.assertEqual(self.result.ops_added, len(self.plan.ops))
        self.assertEqual(self.plan.ownership_violations(), [])

    def test_flight_outline(self):
        op = self.ops["05/thang/ST1/0/bao"]
        self.assertEqual(op.kind, "pline")
        self.assertTrue(op.data["closed"])
        self.assertEqual(len(op.data["points"]), 4)
        for got, exp in zip(bounds(op.data["points"]), (3900.0, 4900.0, 4900.0, 7760.0)):
            self.assertAlmostEqual(got, exp, delta=TOL)
        expected = [tuple(p) for p in list(self.poly.exterior.coords)[:-1]]
        for got, exp in zip(op.data["points"], expected):
            self.assertAlmostEqual(got[0], exp[0], delta=TOL)
            self.assertAlmostEqual(got[1], exp[1], delta=TOL)

    def test_ten_nosing_lines_across_full_width(self):
        lines = [o for o in self.plan.ops if o.kind == "line" and "/bac/" in o.eid]
        self.assertEqual(len(lines), 10)
        ys = sorted(o.data["p1"][1] for o in lines)
        for k, y in enumerate(ys, start=1):
            self.assertAlmostEqual(y, 4900.0 + 260.0 * k, delta=TOL)
        for o in lines:
            self.assertAlmostEqual(o.data["p1"][1], o.data["p2"][1], delta=TOL)
            self.assertAlmostEqual(min(o.data["p1"][0], o.data["p2"][0]), 3900.0, delta=TOL)
            self.assertAlmostEqual(max(o.data["p1"][0], o.data["p2"][0]), 4900.0, delta=TOL)

    def test_walk_line_and_arrow(self):
        walk = self.ops["05/thang/ST1/0/duong_di"]
        self.assertFalse(walk.data["closed"])
        (x0, y0), (x1, y1) = walk.data["points"][0], walk.data["points"][-1]
        self.assertAlmostEqual(x0, 4400.0, delta=TOL)
        self.assertAlmostEqual(y0, 4900.0 + 130.0, delta=TOL)        # giữa bậc đầu
        self.assertAlmostEqual(x1, 4400.0, delta=TOL)
        self.assertAlmostEqual(y1, 7760.0 - 130.0, delta=TOL)        # giữa bậc cuối
        arrow = self.ops["05/thang/ST1/0/mui_ten"]
        self.assertTrue(arrow.data["closed"])
        tip, b1, b2 = arrow.data["points"]
        self.assertAlmostEqual(tip[0], x1, delta=TOL)
        self.assertAlmostEqual(tip[1], y1, delta=TOL)
        base_mid = ((b1[0] + b2[0]) / 2.0, (b1[1] + b2[1]) / 2.0)
        self.assertAlmostEqual(math.dist(tip, base_mid), paper_to_model(ARROW_PAPER_MM, 100), delta=TOL)
        self.assertLess(base_mid[1], tip[1])                         # mũi tên chỉ theo hướng đi lên
        for p in arrow.data["points"]:
            self.assertTrue(self.poly.buffer(TOL).contains(ShPoint(p)))

    def test_label_near_flight_start(self):
        label = self.ops["05/thang/ST1/chu"]
        self.assertEqual(label.kind, "text")
        self.assertEqual(label.data["text"], "LÊN")
        self.assertAlmostEqual(label.data["height"], text_height("thang", 100), delta=TOL)
        self.assertEqual(label.data["align"], "MIDDLE_CENTER")
        x, y = label.data["insert"]
        self.assertAlmostEqual(x, 4400.0, delta=TOL)
        self.assertLess(y, 4900.0)                                   # ngoài mép đầu vế
        self.assertLess(4900.0 - y, 2 * text_height("thang", 100))   # nhưng sát mép đầu
        self.assertEqual(sum(1 for o in self.plan.ops if o.kind == "text"), 1)

    def test_cut_line_crosses_flight_at_60_percent(self):
        cut = self.ops["05/thang/ST1/cat"]
        self.assertEqual(cut.kind, "pline")
        self.assertFalse(cut.data["closed"])
        pts = cut.data["points"]
        self.assertGreaterEqual(len(pts), 4)
        for p in pts:
            self.assertTrue(self.poly.buffer(TOL).contains(ShPoint(p)))
        self.assertAlmostEqual(pts[0][0], 3900.0, delta=TOL)          # từ mép trái
        self.assertAlmostEqual(pts[-1][0], 4900.0, delta=TOL)         # tới mép phải
        self.assertNotAlmostEqual(pts[0][1], pts[-1][1], delta=10.0)  # xiên
        mid_y = (pts[0][1] + pts[-1][1]) / 2.0
        self.assertAlmostEqual(mid_y, 4900.0 + CUT_AT * 2860.0, delta=TOL)
        # có nét gấp: một số điểm nằm ngoài đường thẳng nối hai đầu
        (ax, ay), (bx, by) = pts[0], pts[-1]
        off = [abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / math.hypot(bx - ax, by - ay) for px, py in pts]
        self.assertGreater(max(off), 20.0)

    def test_tread_note(self):
        self.assertIn("ST1 vế 1: bậc: 11 × 260, cao bậc 170", self.result.notes)
        self.assertTrue(any("1/1 vế thang" in n for n in self.result.notes))

    def test_rerun_does_not_duplicate(self):
        n, fp = len(self.plan.ops), self.plan.fingerprint("05")
        r2 = CauThangSkill().run(self.store, self.plan)
        self.assertEqual(len(self.plan.ops), n)
        self.assertEqual(self.plan.fingerprint("05"), fp)
        self.assertEqual(r2.ops_added, n)

    def test_unfilled_sample_still_draws_stair(self):
        store = load_sample(filled=False)
        self.assertTrue(store.missing())
        plan, result = run_skill(CauThangSkill, store)
        self.assertEqual(result.skipped, [])
        self.assertEqual(plan.fingerprint("05"), self.plan.fingerprint("05"))

    def test_scale_changes_paper_sized_symbols(self):
        store = load_sample()
        store.project.scale = 50
        plan, _ = run_skill(CauThangSkill, store)
        ops = ops_by_eid(plan)
        self.assertAlmostEqual(ops["05/thang/ST1/chu"].data["height"], 2.5 * 50, delta=TOL)
        tip, b1, b2 = ops["05/thang/ST1/0/mui_ten"].data["points"]
        self.assertAlmostEqual(math.dist(tip, ((b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2)), 2.5 * 50, delta=TOL)


class CauThangMissingDataTest(unittest.TestCase):
    def test_missing_width_and_going_skipped_with_keys(self):
        store = load_sample()
        fl = store.stairs[0].flights[0]
        fl.width, fl.going = None, None
        plan, result = run_skill(CauThangSkill, store)
        why = skipped_map(result)["thang:ST1/0"]
        self.assertIn("width", why)
        self.assertIn("going", why)
        self.assertIn("stairs:ST1.flights[0].going", why)
        self.assertIn("stairs:ST1.flights[0].width", why)
        self.assertEqual(plan.ops, [])
        self.assertTrue(any("chưa vẽ đường cắt" in n for n in result.notes))
        self.assertTrue(any("0/1 vế thang" in n for n in result.notes))

    def test_missing_n_treads(self):
        store = load_sample()
        store.stairs[0].flights[0].n_treads = None
        _, result = run_skill(CauThangSkill, store)
        self.assertIn("n_treads", skipped_map(result)["thang:ST1/0"])

    def test_origin_on_axis_without_coordinate(self):
        store = load_sample(filled=False)
        store.stairs[0].flights[0].origin = "3/B@100,100"
        plan, result = run_skill(CauThangSkill, store)
        why = skipped_map(result)["thang:ST1/0"]
        self.assertIn("chưa có toạ độ", why)
        self.assertIn("axes:V.spans[1]", why)
        self.assertEqual(plan.ops, [])

    def test_bad_axis_reference_is_skipped_not_raised(self):
        store = load_sample()
        store.stairs[0].flights[0].origin = "9/B"
        _, result = run_skill(CauThangSkill, store)
        self.assertIn("sai cấu trúc", skipped_map(result)["thang:ST1/0"])

    def test_invalid_values(self):
        cases = [("width", 0, "width"), ("going", -260, "going"), ("n_treads", 2.5, "số nguyên"),
                 ("n_treads", 0, "số nguyên"), ("angle", None, "angle")]
        for attr, value, expect in cases:
            with self.subTest(attr=attr, value=value):
                store = load_sample()
                setattr(store.stairs[0].flights[0], attr, value)
                plan, result = run_skill(CauThangSkill, store)
                self.assertIn(expect, skipped_map(result)["thang:ST1/0"])
                self.assertEqual(plan.ops, [])

    def test_missing_riser_is_noted(self):
        store = load_sample()
        store.stairs[0].flights[0].riser = None
        _, result = run_skill(CauThangSkill, store)
        self.assertIn("ST1 vế 1: bậc: 11 × 260 (chưa có cao bậc riser)", result.notes)

    def test_empty_label_skipped(self):
        store = load_sample()
        store.stairs[0].label = "  "
        plan, result = run_skill(CauThangSkill, store)
        self.assertIn("thang:ST1/chu", skipped_map(result))
        self.assertNotIn("05/thang/ST1/chu", ops_by_eid(plan))
        self.assertIn("05/thang/ST1/0/bao", ops_by_eid(plan))

    def test_interpolated_values_are_flagged(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("nội suy từ kích thước tổng"))
        store.set_value("stairs:ST1.flights[0].going", 260, Provenance.interpolated("nội suy thử"))
        store.stairs[0].flights[0].origin = "3/B@-1300,700"
        _, result = run_skill(CauThangSkill, store)
        self.assertEqual(result.skipped, [])
        note = next(n for n in result.notes if "nội suy CHƯA xác nhận" in n)
        self.assertIn("stairs:ST1.flights[0].going", note)
        self.assertIn("axes:V.spans[1]", note)

    def test_short_flight_arrow_shrunk_with_warning(self):
        store = load_sample()
        fl = store.stairs[0].flights[0]
        fl.n_treads, fl.going = 1, 200
        plan, result = run_skill(CauThangSkill, store)
        self.assertEqual(result.skipped, [])
        self.assertEqual([o for o in plan.ops if "/bac/" in o.eid], [])
        self.assertTrue(any(n.startswith("CẢNH BÁO ST1 vế 1") for n in result.notes))
        poly = geom.flight_polygon(store, fl)
        for o in plan.ops_of(kind="pline"):
            for p in o.data["points"]:
                self.assertTrue(poly.buffer(TOL).contains(ShPoint(p)), o.eid)


class CauThangMultiFlightTest(unittest.TestCase):
    def setUp(self):
        self.store = stair_store([{
            "id": "ST2", "label": "LÊN",
            "flights": [
                {"origin": "1/A@200,300", "angle": 90, "width": 1000, "going": 250, "n_treads": 8, "riser": 165},
                {"origin": "1/A@2200,2300", "angle": 270, "width": 1000, "going": 250, "n_treads": 8},
                {"origin": "3/A@0,0", "angle": 0, "width": 1000, "going": 250, "n_treads": 4},
            ],
            "landings": [
                ["1/A@200,2300", "1/A@2200,2300", "1/A@2200,3300", "1/A@200,3300"],
                ["1/A@0,0", "3/A@0,0", "3/B@0,0"],
                [[0, 0], [100, 0]],
                [[0, 0], [100, 0], [200, 0]],
            ]}])
        self.plan, self.result = run_skill(CauThangSkill, self.store)
        self.ops = ops_by_eid(self.plan)
        self.skipped = skipped_map(self.result)

    def test_each_drawable_flight_drawn(self):
        for i in (0, 1):
            self.assertIn(f"05/thang/ST2/{i}/bao", self.ops)
            self.assertEqual(sum(1 for e in self.ops if e.startswith(f"05/thang/ST2/{i}/bac/")), 7)
            self.assertIn(f"05/thang/ST2/{i}/duong_di", self.ops)
            self.assertIn(f"05/thang/ST2/{i}/mui_ten", self.ops)
        self.assertIn("chưa có toạ độ", self.skipped["thang:ST2/2"])
        self.assertIn("axes:V.spans[1]", self.skipped["thang:ST2/2"])
        self.assertTrue(any("2/3 vế thang" in n for n in self.result.notes))

    def test_second_flight_goes_down_the_page(self):
        poly = geom.flight_polygon(self.store, self.store.stairs[0].flights[1])
        self.assertEqual(tuple(round(v, 6) for v in poly.bounds), (1200.0, 300.0, 2200.0, 2300.0))
        tip = self.ops["05/thang/ST2/1/mui_ten"].data["points"][0]
        self.assertAlmostEqual(tip[1], 300.0 + 125.0, delta=TOL)

    def test_cut_line_and_label_only_once(self):
        cuts = [e for e in self.ops if e.endswith("/cat")]
        labels = [o for o in self.plan.ops if o.kind == "text"]
        self.assertEqual(cuts, ["05/thang/ST2/cat"])
        self.assertEqual(len(labels), 1)
        poly0 = geom.flight_polygon(self.store, self.store.stairs[0].flights[0])
        for p in self.ops["05/thang/ST2/cat"].data["points"]:
            self.assertTrue(poly0.buffer(TOL).contains(ShPoint(p)))
        self.assertTrue(poly0.buffer(1000).contains(ShPoint(labels[0].data["insert"])))

    def test_landings(self):
        landing = self.ops["05/thang/ST2/chieu_nghi/0"]
        self.assertTrue(landing.data["closed"])
        self.assertEqual(bounds(landing.data["points"]), (200.0, 2300.0, 2200.0, 3300.0))
        self.assertIn("chưa có toạ độ", self.skipped["thang:ST2/chieu_nghi/1"])
        self.assertIn("ít nhất 3 điểm", self.skipped["thang:ST2/chieu_nghi/2"])
        self.assertIn("suy biến", self.skipped["thang:ST2/chieu_nghi/3"])
        self.assertTrue(any("1/4 chiếu nghỉ" in n for n in self.result.notes))

    def test_cut_line_not_drawn_when_first_flight_missing(self):
        self.store.stairs[0].flights[0].going = None
        plan, result = run_skill(CauThangSkill, self.store)
        self.assertFalse(any(o.eid.endswith("/cat") for o in plan.ops))
        self.assertTrue(any("chưa vẽ đường cắt" in n for n in result.notes))
        self.assertIn("thang:ST2/0", skipped_map(result))
        self.assertEqual(sum(1 for o in plan.ops if o.kind == "text"), 1)   # nhãn chuyển sang vế vẽ được


# ─────────────────────────────────────────────────────────────────────────────

class BlockLibraryTest(unittest.TestCase):
    def test_exact_names_and_sizes(self):
        self.assertEqual(set(LIBRARY), set(EXPECTED_SIZES))
        self.assertEqual(library_names(), list(LIBRARY))
        for name, size in EXPECTED_SIZES.items():
            blk = LIBRARY[name]
            self.assertIsInstance(blk, BlockDef)
            self.assertEqual(blk.name, name)
            self.assertEqual(blk.size, size)
            self.assertEqual(blk.source, "thu_vien")
            self.assertTrue(blk.description)
            self.assertTrue(blk.ops)

    def test_geometry_inside_box_and_simple_primitives(self):
        for name, blk in LIBRARY.items():
            X, Y = blk.size
            for item in blk.ops:
                self.assertIn(item["kind"], ("line", "pline", "circle", "arc"), name)
                for x, y in iter_points(item):
                    self.assertTrue(-1.0 <= x <= X + 1.0 and -1.0 <= y <= Y + 1.0, f"{name}: ({x}, {y})")
            # hình học chạm đủ bốn cạnh hộp → size đúng là vết chiếm chỗ
            pts = [p for item in blk.ops for p in iter_points(item)]
            for got, exp in zip(bounds(pts), (0.0, 0.0, X, Y)):
                self.assertAlmostEqual(got, exp, delta=1.0, msg=name)

    def test_recognisable_features(self):
        def closed_plines(name):
            return [bounds(i["data"]["points"]) for i in LIBRARY[name].ops
                    if i["kind"] == "pline" and i["data"]["closed"]]

        def circles(name):
            return [i["data"] for i in LIBRARY[name].ops if i["kind"] == "circle"]

        pillows = [b for b in closed_plines("GIUONG_DOI") if b[1] > 1000.0]
        self.assertEqual(len(pillows), 2)                           # 2 gối ở cạnh y lớn
        backrest = [i for i in LIBRARY["SOFA_3"].ops if i["kind"] == "line"
                    and i["data"]["p1"][1] == i["data"]["p2"][1] and i["data"]["p1"][1] > 425.0]
        self.assertTrue(backrest)                                   # tựa lưng ở cạnh y lớn
        table = [b for b in closed_plines("BAN_AN_4") if b == (0.0, 400.0, 1200.0, 1200.0)]
        self.assertEqual(len(table), 1)                             # bàn 1200×800 ở giữa
        seats = [b for b in closed_plines("BAN_AN_4") if abs((b[2] - b[0]) - 450.0) < TOL and b[3] - b[1] > 300]
        self.assertEqual(len(seats), 4)
        self.assertEqual(sum(1 for b in seats if b[3] <= 400.0), 2)  # 2 ghế dưới
        self.assertEqual(sum(1 for b in seats if b[1] >= 1200.0), 2)  # 2 ghế trên
        burners = [c for c in circles("TU_BEP") if c["r"] >= 100.0]
        self.assertEqual(len(burners), 2)                           # bếp 2 vùng nấu
        self.assertTrue(any(b[2] - b[0] >= 600 and b[2] <= 1200 for b in closed_plines("TU_BEP")))   # chậu rửa
        tank = closed_plines("BON_CAU")[0]
        self.assertLessEqual(tank[3], 200.0)                        # két nước ở cạnh y nhỏ
        arcs = [i["data"] for i in LIBRARY["BON_CAU"].ops if i["kind"] == "arc"]
        self.assertTrue(arcs and all(a["center"][1] > 350.0 for a in arcs))   # mép trước bồn phía y lớn
        self.assertTrue(any(c["r"] >= 100.0 for c in circles("LAVABO")))       # lòng chậu

    def test_get_block_library_template_and_unknown(self):
        store = load_sample()
        blk = get_block("SOFA_3", store)
        self.assertEqual(blk.to_dict(), LIBRARY["SOFA_3"].to_dict())
        self.assertIsNot(blk, LIBRARY["SOFA_3"])
        blk.ops.clear()
        self.assertTrue(LIBRARY["SOFA_3"].ops)                      # bản sao, thư viện không đổi
        self.assertIsNone(get_block("KHONG_CO", store))
        self.assertIsNone(get_block("KHONG_CO"))
        self.assertEqual(get_block("LAVABO").name, "LAVABO")
        self.assertEqual(block_origin("LAVABO", store), "thu_vien")
        self.assertEqual(block_origin("KHONG_CO", store), "")
        store.blocks["SOFA_3"] = BlockDef("SOFA_3", [{"kind": "line", "data": {"p1": [0, 0], "p2": [10, 0]}}],
                                          size=[2000, 900], source="mau")
        tpl = get_block("SOFA_3", store)
        self.assertEqual(tpl.source, "mau")
        self.assertEqual(tpl.size, [2000.0, 900.0])
        self.assertEqual(block_origin("SOFA_3", store), "mau")


# ─────────────────────────────────────────────────────────────────────────────

class NoiThatTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan, self.result = run_skill(NoiThatSkill, self.store)

    def test_eight_inserts_and_blocks(self):
        self.assertEqual(self.result.skipped, [])
        inserts = self.plan.ops_of(skill="06", kind="insert")
        self.assertEqual(len(inserts), 8)
        self.assertEqual(len(self.plan.ops), 8)
        ops = ops_by_eid(self.plan)
        for f in self.store.furniture:
            op = ops[f"06/noi_that/{f.id}"]
            self.assertEqual(op.role, "noi_that")
            self.assertEqual(op.data["block"], f.block)
            self.assertEqual(op.data["insert"], [float(v) for v in f.insert])
            self.assertEqual(op.data["rotation"], float(f.rotation))
            self.assertEqual(op.data["scale"], [1.0, 1.0])
        self.assertEqual({n: b.size for n, b in self.plan.blocks.items()}, EXPECTED_SIZES)
        self.assertTrue(any("8/8" in n for n in self.result.notes))
        self.assertEqual(self.plan.ownership_violations(), [])

    def test_inserted_geometry_matches_footprint(self):
        for op in self.plan.ops_of(kind="insert"):
            blk = self.plan.blocks[op.data["block"]]
            fp = geom.footprint(tuple(op.data["insert"]), tuple(blk.size), op.data["rotation"])
            pts = transformed_block_points(blk, op.data["insert"], op.data["rotation"])
            self.assertTrue(fp.buffer(1.0).contains(MultiPoint(pts)), op.eid)

    def test_wall_mounted_fixtures_back_on_wall_in_sample(self):
        # tủ bếp, bồn cầu: lưng (y = 0 của block) nằm trên mặt trong tường trục 4 (x = 10800 − 110)
        for fid in ("F6", "F7"):
            op = ops_by_eid(self.plan)[f"06/noi_that/{fid}"]
            back = affinity.rotate(MultiPoint([(0, 0), (self.plan.blocks[op.data["block"]].size[0], 0)]),
                                   op.data["rotation"], origin=(0, 0))
            for p in back.geoms:
                self.assertAlmostEqual(p.x + op.data["insert"][0], 10690.0, delta=TOL)

    def test_unknown_block_skipped_with_reason(self):
        self.store.furniture.append(Furniture(id="F9", block="BE_CA", insert=[500, 500]))
        plan, result = run_skill(NoiThatSkill, self.store)
        self.assertEqual(skipped_map(result),
                         {"noi_that:F9": "không có block 'BE_CA' trong template lẫn thư viện"})
        self.assertEqual(len(plan.ops_of(kind="insert")), 8)
        self.assertNotIn("BE_CA", plan.blocks)

    def test_insert_point_without_coordinate_skipped(self):
        store = load_sample(filled=False)
        store.furniture.append(Furniture(id="F9", block="BAN_TRA", insert="3/B@-1500,-1500"))
        plan, result = run_skill(NoiThatSkill, store)
        why = skipped_map(result)["noi_that:F9"]
        self.assertIn("chưa có toạ độ", why)
        self.assertIn("axes:V.spans[1]", why)
        self.assertEqual(len(plan.ops_of(kind="insert")), 8)

    def test_bad_reference_and_rotation_skipped(self):
        self.store.furniture.append(Furniture(id="F9", block="BAN_TRA", insert="9/Z"))
        self.store.furniture.append(Furniture(id="F10", block="BAN_TRA", insert=[0, 0], rotation=None))
        _, result = run_skill(NoiThatSkill, self.store)
        skipped = skipped_map(result)
        self.assertIn("sai cấu trúc", skipped["noi_that:F9"])
        self.assertIn("góc xoay", skipped["noi_that:F10"])

    def test_unfilled_sample_draws_all_furniture(self):
        plan, result = run_skill(NoiThatSkill, load_sample(filled=False))
        self.assertEqual(result.skipped, [])
        self.assertEqual(plan.fingerprint("06"), self.plan.fingerprint("06"))

    def test_axis_based_insert_and_interpolation_flag(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("nội suy từ kích thước tổng"))
        store.furniture[3].insert = "3/A@-6050,2200"          # F4 bàn trà, cùng vị trí [1150, 2200]
        plan, result = run_skill(NoiThatSkill, store)
        self.assertEqual(ops_by_eid(plan)["06/noi_that/F4"].data["insert"], [1150.0, 2200.0])
        note = next(n for n in result.notes if "nội suy CHƯA xác nhận" in n)
        self.assertIn("F4", note)
        self.assertIn("axes:V.spans[1]", note)

    def test_template_block_has_priority(self):
        store = load_sample()
        store.blocks["SOFA_3"] = BlockDef("SOFA_3", [{"kind": "pline", "data": {
            "points": [[0, 0], [2000, 0], [2000, 900], [0, 900]], "closed": True}}], size=[2000, 900], source="mau")
        plan, result = run_skill(NoiThatSkill, store)
        self.assertEqual(plan.blocks["SOFA_3"].source, "mau")
        self.assertEqual(plan.blocks["SOFA_3"].size, [2000.0, 900.0])
        self.assertEqual(plan.blocks["TU_AO"].source, "thu_vien")
        self.assertTrue(any("template" in n and "SOFA_3" in n for n in result.notes))

    def test_template_without_size_warned(self):
        self.store.blocks["LAVABO"] = BlockDef("LAVABO", [{"kind": "circle", "data": {"center": [0, 0], "r": 200}}],
                                               source="mau")
        _, result = run_skill(NoiThatSkill, self.store)
        self.assertTrue(any(n.startswith("CẢNH BÁO") and "LAVABO" in n for n in result.notes))

    def test_rerun_does_not_duplicate(self):
        fp = self.plan.fingerprint("06")
        blocks = {n: b.to_dict() for n, b in self.plan.blocks.items()}
        r2 = NoiThatSkill().run(self.store, self.plan)
        self.assertEqual(len(self.plan.ops), 8)
        self.assertEqual(r2.ops_added, 8)
        self.assertEqual(self.plan.fingerprint("06"), fp)
        self.assertEqual({n: b.to_dict() for n, b in self.plan.blocks.items()}, blocks)

    def test_rerun_after_template_change_replaces_block(self):
        self.store.blocks["SOFA_3"] = BlockDef("SOFA_3", [{"kind": "line", "data": {"p1": [0, 0], "p2": [2100, 0]}}],
                                               size=[2100, 850], source="mau")
        result = NoiThatSkill().run(self.store, self.plan)       # không được ném PlanError
        self.assertEqual(result.skipped, [])
        self.assertEqual(self.plan.blocks["SOFA_3"].source, "mau")
        self.assertTrue(any("cập nhật định nghĩa block 'SOFA_3'" in n for n in result.notes))

    def test_rerun_removes_unused_block_definition(self):
        self.store.furniture = [f for f in self.store.furniture if f.id != "F8"]
        result = NoiThatSkill().run(self.store, self.plan)
        self.assertNotIn("LAVABO", self.plan.blocks)
        self.assertEqual(len(self.plan.blocks), 7)
        self.assertTrue(any("LAVABO" in n and "gỡ" in n for n in result.notes))

    def test_conflicting_block_used_by_other_skill_not_overwritten(self):
        plan = new_plan(self.store)
        other = BlockDef("SOFA_3", [{"kind": "line", "data": {"p1": [0, 0], "p2": [1, 0]}}], size=[1, 1])
        plan.add_block(other)
        plan.add("insert", "khung_ten", "10", "10/thu", block="SOFA_3", insert=[0, 0], rotation=0, scale=[1, 1])
        _, result = run_skill(NoiThatSkill, self.store, plan)
        self.assertIn("không ghi đè", skipped_map(result)["noi_that:F3"])
        self.assertEqual(plan.blocks["SOFA_3"].to_dict(), other.to_dict())
        self.assertEqual(len(plan.ops_of(skill="06")), 7)


# ─────────────────────────────────────────────────────────────────────────────

class IntegrationTest(unittest.TestCase):
    def _run_01_06(self, store):
        plan = new_plan(store)
        for code in ("01", "02", "03", "04"):
            skill_class(code)().run(store, plan)
        before = {c: plan.fingerprint(c) for c in ("01", "02", "03", "04")}
        r5 = skill_class("05")().run(store, plan)
        r6 = skill_class("06")().run(store, plan)
        return plan, before, r5, r6

    def test_full_sequence_ownership_and_isolation(self):
        for filled in (True, False):
            with self.subTest(filled=filled):
                store = load_sample(filled=filled)
                plan, before, r5, r6 = self._run_01_06(store)
                self.assertEqual(plan.ownership_violations(), [])
                self.assertEqual({c: plan.fingerprint(c) for c in before}, before)   # không đụng phần skill khác
                self.assertEqual(r5.skipped, [])
                self.assertEqual(r6.skipped, [])
                self.assertEqual(plan.count_by_role()["noi_that"], 8)
                self.assertEqual(plan.count_by_role()["thang"], r5.ops_added)

    def test_plan_round_trip_keeps_blocks_and_ops(self):
        store = load_sample()
        plan, _, _, _ = self._run_01_06(store)
        again = DrawingPlan.from_dict(plan.to_dict())
        self.assertEqual(again.to_dict(), plan.to_dict())
        self.assertEqual(again.fingerprint("05"), plan.fingerprint("05"))
        self.assertEqual(again.fingerprint("06"), plan.fingerprint("06"))

    def test_store_not_modified(self):
        store = load_sample()
        h = store.data_hash()
        self._run_01_06(store)
        self.assertEqual(store.data_hash(), h)

    def test_stair_flight_dataclass_defaults(self):
        # vế thang chỉ có điểm gốc: bỏ qua, kể đủ 3 số liệu thiếu
        store = stair_store([{"id": "ST3", "flights": [{"origin": "1/A"}]}])
        self.assertIsInstance(store.stairs[0].flights[0], StairFlight)
        _, result = run_skill(CauThangSkill, store)
        why = skipped_map(result)["thang:ST3/0"]
        for f in ("width", "going", "n_treads"):
            self.assertIn(f"stairs:ST3.flights[0].{f}", why)


if __name__ == "__main__":
    unittest.main()
