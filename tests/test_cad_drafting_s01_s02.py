# -*- coding: utf-8 -*-
"""Test Skill 01 (lưới trục) và Skill 02 (cột) của agent dựng CAD mặt bằng (tools/cad_drafting)."""

import unittest

from tools.cad_drafting import geom
from tools.cad_drafting.layers import (AXIS_BUBBLE_DIAMETER_PAPER_MM, LAYOUT_PAPER_MM, paper_to_model,
                                       roles_of, text_height)
from tools.cad_drafting.plan import DrawingPlan, PlanError
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.skills.s01_luoi_truc import LuoiTrucSkill, axis_layout
from tools.cad_drafting.skills.s02_cot import CotSkill
from tools.cad_drafting.store import ProjectStore, Provenance

TOL = 1e-6


def run_both(store, plan=None):
    plan = plan or new_plan(store)
    r1 = LuoiTrucSkill().run(store, plan)
    r2 = CotSkill().run(store, plan)
    return plan, r1, r2


def mini_store(axes, columns=(), scale=100):
    return ProjectStore.from_dict({"project": {"scale": scale}, "axes": axes, "columns": list(columns)})


def ops_by_eid(plan):
    return {o.eid: o for o in plan.ops}


class RegistryTest(unittest.TestCase):
    def test_skill_classes_and_metadata(self):
        self.assertIs(skill_class("01"), LuoiTrucSkill)
        self.assertIs(skill_class("02"), CotSkill)
        s1, s2 = LuoiTrucSkill(), CotSkill()
        self.assertEqual((s1.code, s1.name, s1.reads), ("01", "Lưới trục", ("project", "axes")))
        self.assertEqual((s2.code, s2.name, s2.reads), ("02", "Cột", ("project", "axes", "columns")))
        self.assertEqual(set(s1.roles), {"truc", "truc_kh"})
        self.assertEqual(s1.roles, roles_of("01"))
        self.assertEqual(s2.roles, ("cot",))

    def test_add_refuses_foreign_role(self):
        store = load_sample()
        with self.assertRaises(PlanError):
            CotSkill().add(new_plan(store), "line", "hatch", "x", p1=[0, 0], p2=[1, 0])


class LuoiTrucSampleTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = new_plan(self.store)
        self.result = LuoiTrucSkill().run(self.store, self.plan)
        self.scale = 100
        self.d = paper_to_model(LAYOUT_PAPER_MM["axis_bubble_center"], self.scale)
        self.r = paper_to_model(AXIS_BUBBLE_DIAMETER_PAPER_MM, self.scale) / 2.0

    def test_all_axes_drawn_with_line_two_bubbles_two_names(self):
        self.assertEqual(self.result.skipped, [])
        names = {"V": ["1", "2", "3", "4"], "H": ["A", "B", "C"]}
        eids = ops_by_eid(self.plan)
        for o, ns in names.items():
            for n in ns:
                base = f"01/truc/{o}/{n}"
                self.assertEqual(eids[f"{base}/line"].kind, "line")
                self.assertEqual(eids[f"{base}/line"].role, "truc")
                for i in (0, 1):
                    self.assertEqual(eids[f"{base}/bubble/{i}"].kind, "circle")
                    self.assertEqual(eids[f"{base}/bubble/{i}"].role, "truc_kh")
                    self.assertEqual(eids[f"{base}/name/{i}"].kind, "text")
                    self.assertEqual(eids[f"{base}/name/{i}"].role, "truc_kh")
        self.assertEqual(len(self.plan.ops_of(skill="01", kind="line")), 7)
        self.assertEqual(len(self.plan.ops_of(skill="01", kind="circle")), 14)
        self.assertEqual(len(self.plan.ops_of(skill="01", kind="text")), 14)
        self.assertEqual(len(self.plan.ops), 35)
        self.assertEqual(self.result.ops_added, 35)
        self.assertIn("trục đứng (V): đã vẽ 4/4 trục", self.result.notes)
        self.assertIn("trục ngang (H): đã vẽ 3/3 trục", self.result.notes)

    def test_bubble_centers_radius_and_names(self):
        self.assertEqual(self.d, 3800.0)
        self.assertEqual(self.r, 400.0)
        eids = ops_by_eid(self.plan)
        # khung trục: V [0, 10800], H [0, 8400]
        expect = {
            ("V", "1"): [(0.0, -3800.0), (0.0, 12200.0)],
            ("V", "2"): [(3600.0, -3800.0), (3600.0, 12200.0)],
            ("V", "3"): [(7200.0, -3800.0), (7200.0, 12200.0)],
            ("V", "4"): [(10800.0, -3800.0), (10800.0, 12200.0)],
            ("H", "A"): [(-3800.0, 0.0), (14600.0, 0.0)],
            ("H", "B"): [(-3800.0, 4200.0), (14600.0, 4200.0)],
            ("H", "C"): [(-3800.0, 8400.0), (14600.0, 8400.0)],
        }
        for (o, n), centers in expect.items():
            for i, c in enumerate(centers):
                circ = eids[f"01/truc/{o}/{n}/bubble/{i}"].data
                self.assertEqual(tuple(circ["center"]), c, f"{o}/{n}/{i}")
                self.assertEqual(circ["r"], 400.0)
                txt = eids[f"01/truc/{o}/{n}/name/{i}"].data
                self.assertEqual(tuple(txt["insert"]), c)
                self.assertEqual(txt["text"], n)
                self.assertEqual(txt["align"], "MIDDLE_CENTER")
                self.assertEqual(txt["height"], text_height("truc", 100))
                self.assertEqual(txt["rotation"], 0.0)

    def test_axis_lines_run_edge_to_edge_and_never_enter_bubbles(self):
        eids = ops_by_eid(self.plan)
        circles = self.plan.ops_of(skill="01", kind="circle")
        for line in self.plan.ops_of(skill="01", kind="line"):
            p1, p2 = tuple(line.data["p1"]), tuple(line.data["p2"])
            base = line.eid[: -len("/line")]
            c0 = tuple(eids[f"{base}/bubble/0"].data["center"])
            c1 = tuple(eids[f"{base}/bubble/1"].data["center"])
            # đầu đường trục nằm đúng trên mép vòng tròn của chính trục đó
            self.assertAlmostEqual(geom.length(geom.sub(p1, c0)), self.r, delta=TOL)
            self.assertAlmostEqual(geom.length(geom.sub(p2, c1)), self.r, delta=TOL)
            # không đường trục nào chui vào trong bất kỳ vòng tròn nào
            for c in circles:
                dist = geom.dist_point_segment(tuple(c.data["center"]), p1, p2)
                self.assertGreaterEqual(dist, c.data["r"] - TOL, f"{line.eid} chui vào {c.eid}")
        v1 = eids["01/truc/V/1/line"].data
        self.assertEqual((v1["p1"], v1["p2"]), ([0.0, -3400.0], [0.0, 11800.0]))
        ha = eids["01/truc/H/A/line"].data
        self.assertEqual((ha["p1"], ha["p2"]), ([-3400.0, 0.0], [14200.0, 0.0]))

    def test_layout_helper_matches_plan(self):
        lay = axis_layout(self.store)
        self.assertEqual(lay["frames"], {"V": (0.0, 10800.0), "H": (0.0, 8400.0)})
        self.assertEqual(len(lay["axes"]), 7)
        self.assertEqual(lay["skipped"], [])

    def test_store_not_modified(self):
        store = load_sample()
        before = store.data_hash()
        run_both(store)
        self.assertEqual(store.data_hash(), before)


class CotSampleTest(unittest.TestCase):
    def test_twelve_columns_220_centered_on_axis_intersections(self):
        store = load_sample()
        plan, _, r2 = run_both(store)
        self.assertEqual(r2.skipped, [])
        self.assertEqual(r2.ops_added, 12)
        self.assertIn("đã vẽ 12/12 cột", r2.notes)
        cols = plan.ops_of(skill="02")
        self.assertEqual(len(cols), 12)
        self.assertEqual(plan.ops_of(skill="02", kind="hatch"), [])
        xs = {"1": 0.0, "2": 3600.0, "3": 7200.0, "4": 10800.0}
        ys = {"A": 0.0, "B": 4200.0, "C": 8400.0}
        for op in cols:
            self.assertEqual((op.kind, op.role), ("pline", "cot"))
            self.assertTrue(op.data["closed"])
            pts = op.data["points"]
            self.assertEqual(len(pts), 4)
            cid = op.eid.split("/", 2)[2]          # "02/cot/C-3B" → "C-3B"
            self.assertEqual(op.eid, f"02/cot/{cid}")
            av, ah = cid[2], cid[3]
            bx = [p[0] for p in pts]
            by = [p[1] for p in pts]
            self.assertAlmostEqual(max(bx) - min(bx), 220.0)
            self.assertAlmostEqual(max(by) - min(by), 220.0)
            self.assertAlmostEqual((max(bx) + min(bx)) / 2, xs[av])
            self.assertAlmostEqual((max(by) + min(by)) / 2, ys[ah])
        self.assertEqual(sorted(o.eid for o in cols),
                         sorted(f"02/cot/C-{v}{h}" for v in xs for h in ys))

    def test_column_offset_and_missing_size(self):
        store = mini_store(
            {"V": {"names": ["1", "2"], "spans": [3000]}, "H": {"names": ["A", "B"], "spans": [4000]}},
            [{"id": "K1", "axis_v": "2", "axis_h": "B", "b": 300, "h": 200, "dx": 50, "dy": -25},
             {"id": "K2", "axis_v": "1", "axis_h": "A", "b": 300},
             {"id": "K3", "axis_v": "1", "axis_h": "B", "b": 0, "h": 200}])
        plan, _, r2 = run_both(store)
        pts = ops_by_eid(plan)["02/cot/K1"].data["points"]
        self.assertEqual(sorted(map(tuple, pts)),
                         sorted([(2900.0, 3875.0), (3200.0, 3875.0), (3200.0, 4075.0), (2900.0, 4075.0)]))
        skipped = {s["id"]: s["ly_do"] for s in r2.skipped}
        self.assertEqual(skipped, {"cot:K2": "thiếu kích thước cột", "cot:K3": "kích thước cột ≤ 0"})
        self.assertIn("đã vẽ 1/3 cột", r2.notes)


class ThieuSoLieuTest(unittest.TestCase):
    """load_sample(filled=False): nhịp trục 2–3 để trống → trục 3, 4 và cột trên đó bị bỏ qua có lý do."""

    def setUp(self):
        self.store = load_sample(filled=False)
        self.plan, self.r1, self.r2 = run_both(self.store)

    def test_axes_3_and_4_skipped_with_reason(self):
        skipped = {s["id"]: s["ly_do"] for s in self.r1.skipped}
        self.assertEqual(set(skipped), {"truc:3", "truc:4"})
        for why in skipped.values():
            self.assertIn("axes:V.spans[1]", why)
            self.assertIn("nhịp trục 2–3", why)
        eids = ops_by_eid(self.plan)
        for n in ("3", "4"):
            self.assertFalse(any(e.startswith(f"01/truc/V/{n}/") for e in eids))
        for n in ("1", "2"):
            self.assertIn(f"01/truc/V/{n}/line", eids)
        self.assertEqual(len(self.plan.ops_of(skill="01")), 5 * 5)
        self.assertIn("trục đứng (V): đã vẽ 2/4 trục", self.r1.notes)

    def test_h_axes_use_known_frame_and_say_so(self):
        eids = ops_by_eid(self.plan)
        # khung V chỉ còn [0, 3600] → tâm vòng tròn phải của trục H ở x = 3600 + 3800
        self.assertEqual(eids["01/truc/H/B/bubble/1"].data["center"], [7400.0, 4200.0])
        self.assertTrue(any("khung nhóm V" in n and "[0, 3600]" in n for n in self.r1.notes), self.r1.notes)

    def test_columns_on_axes_3_4_skipped(self):
        skipped = {s["id"]: s["ly_do"] for s in self.r2.skipped}
        expect = {f"cot:C-{v}{h}" for v in "34" for h in "ABC"}
        self.assertEqual(set(skipped), expect)
        for col in self.store.columns:
            if f"cot:{col.id}" in skipped:
                self.assertEqual(skipped[f"cot:{col.id}"], geom.column_reason(self.store, col))
                self.assertIn("chưa có toạ độ", skipped[f"cot:{col.id}"])
        self.assertEqual(len(self.plan.ops_of(skill="02")), 6)
        self.assertIn("đã vẽ 6/12 cột", self.r2.notes)

    def test_interpolated_span_drawn_but_flagged_until_confirmed(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600.0, Provenance.interpolated("tổng 10800 − 3600 − 3600"))
        plan, r1, r2 = run_both(store)
        self.assertEqual(r1.skipped, [])
        self.assertEqual(r2.skipped, [])
        flagged = [n for n in r1.notes if "CHƯA xác nhận" in n]
        self.assertEqual(len(flagged), 2)                      # trục 3 và 4
        self.assertTrue(all("axes:V.spans[1]" in n for n in flagged))
        doubt = [n for n in r2.notes if "CHƯA xác nhận" in n]
        self.assertEqual(len(doubt), 1)
        for cid in ("C-3A", "C-4C"):
            self.assertIn(cid, doubt[0])
        self.assertNotIn("C-2A", doubt[0])
        store.confirm("axes:V.spans[1]", by="kỹ sư kiểm tra")
        _, r1b, r2b = run_both(store)
        self.assertFalse(any("CHƯA xác nhận" in n for n in r1b.notes + r2b.notes))

    def test_other_group_without_axes_skips_whole_group(self):
        store = mini_store({"V": {"names": ["1", "2"], "spans": [3000]}},
                           [{"id": "K1", "axis_v": "1", "axis_h": "A", "b": 220, "h": 220}])
        plan, r1, r2 = run_both(store)
        self.assertEqual(plan.ops, [])
        self.assertEqual({s["id"] for s in r1.skipped}, {"truc:1", "truc:2"})
        for s in r1.skipped:
            self.assertIn("nhóm trục H", s["ly_do"])
            self.assertIn("chiều dài đường trục", s["ly_do"])
        self.assertIn("không có nhóm trục ngang (H) trong dữ liệu", r1.notes)
        self.assertEqual(len(r2.skipped), 1)
        self.assertEqual(r2.skipped[0]["id"], "cot:K1")
        self.assertIn("sai cấu trúc", r2.skipped[0]["ly_do"])


class ChayLaiVaTyLeTest(unittest.TestCase):
    def test_rerun_does_not_duplicate_and_keeps_other_skill(self):
        store = load_sample()
        plan, _, _ = run_both(store)
        n, fp1, fp2 = len(plan.ops), plan.fingerprint("01"), plan.fingerprint("02")
        r1 = LuoiTrucSkill().run(store, plan)
        self.assertEqual((len(plan.ops), r1.ops_added), (n, 35))
        self.assertEqual(plan.fingerprint("02"), fp2)          # skill 02 không bị đụng tới
        self.assertEqual(plan.fingerprint("01"), fp1)
        r2 = CotSkill().run(store, plan)
        self.assertEqual((len(plan.ops), r2.ops_added), (n, 12))
        self.assertEqual(plan.fingerprints(), {"01": fp1, "02": fp2})
        eids = [o.eid for o in plan.ops]
        self.assertEqual(len(eids), len(set(eids)))
        self.assertEqual(plan.ownership_violations(), [])

    def test_fingerprint_stable_between_independent_runs_and_roundtrip(self):
        p1, _, _ = run_both(load_sample())
        p2, _, _ = run_both(load_sample())
        self.assertEqual(p1.fingerprints(), p2.fingerprints())
        self.assertEqual(p1.ownership_violations(), [])
        p3 = DrawingPlan.from_dict(p1.to_dict())
        self.assertEqual(p3.fingerprints(), p1.fingerprints())

    def test_scale_changes_bubble_distance_radius_and_text(self):
        store = load_sample()
        store.project.scale = 50
        plan, _, _ = run_both(store)
        eids = ops_by_eid(plan)
        c = eids["01/truc/V/1/bubble/0"].data
        self.assertEqual((c["center"], c["r"]), ([0.0, -1900.0], 200.0))
        self.assertEqual(eids["01/truc/V/1/name/0"].data["height"], 175.0)
        self.assertEqual(eids["01/truc/V/1/line"].data["p1"], [0.0, -1700.0])

    def test_close_axes_warn_bubble_overlap(self):
        store = mini_store({"V": {"names": ["1", "1a", "2"], "spans": [500, 3000]},
                            "H": {"names": ["A", "B"], "spans": [4000]}})
        _, r1, _ = run_both(store)
        warn = [n for n in r1.notes if "chồng nhau" in n]
        self.assertEqual(len(warn), 1)
        self.assertIn("1 và 1a", warn[0])
        _, r1s, _ = run_both(load_sample())
        self.assertFalse(any("chồng nhau" in n or "CẢNH BÁO" in n for n in r1s.notes))

    def test_single_known_axis_in_other_group_still_gives_length(self):
        store = mini_store({"V": {"names": ["1", "2"], "spans": [3000]}, "H": {"names": ["A"], "spans": []}})
        plan, r1, _ = run_both(store)
        self.assertEqual(r1.skipped, [])
        line = ops_by_eid(plan)["01/truc/V/2/line"].data
        self.assertEqual((line["p1"], line["p2"]), ([3000.0, -3400.0], [3000.0, 3400.0]))


if __name__ == "__main__":
    unittest.main()
