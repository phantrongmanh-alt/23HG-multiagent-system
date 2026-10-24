# -*- coding: utf-8 -*-
"""Test Skill 03 (tường) và Skill 04 (cửa) của agent dựng CAD mặt bằng (tools/cad_drafting)."""

import math
import unittest

from shapely.geometry import LineString, MultiLineString, Point as ShPoint

from tools.cad_drafting import geom
from tools.cad_drafting.layers import paper_to_model, roles_of, text_height
from tools.cad_drafting.plan import DrawingPlan, PlanError
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.skills.s01_luoi_truc import LuoiTrucSkill
from tools.cad_drafting.skills.s02_cot import CotSkill
from tools.cad_drafting.skills.s03_tuong import (TuongSkill, opening_skip_reason, outline_polylines,
                                                 wall_skip_reason)
from tools.cad_drafting.skills.s04_cua import CuaSkill, readable_angle
from tools.cad_drafting.store import SRC_USER, Column, Opening, ProjectStore, Provenance, Wall

TOL = 1e-6


def run_all(store, plan=None):
    """Chạy Skill 01 → 04 theo thứ tự; trả (plan, kết quả 03, kết quả 04)."""
    plan = plan or new_plan(store)
    LuoiTrucSkill().run(store, plan)
    CotSkill().run(store, plan)
    r3 = TuongSkill().run(store, plan)
    r4 = CuaSkill().run(store, plan)
    return plan, r3, r4


def ops_by_eid(plan):
    return {o.eid: o for o in plan.ops}


def skipped_map(result):
    return {s["id"]: s["ly_do"] for s in result.skipped}


def segments(op):
    pts = [tuple(p) for p in op.data["points"]]
    if op.data["closed"]:
        pts = pts + [pts[0]]
    return list(zip(pts, pts[1:]))


def wall_outline(plan):
    return MultiLineString([LineString(a_b) for op in plan.ops_of(skill="03") for a_b in segments(op)])


def mini_store(walls, openings=(), columns=(), scale=100):
    return ProjectStore.from_dict({
        "project": {"scale": scale},
        "axes": {"V": {"names": ["1", "2"], "spans": [4000]}, "H": {"names": ["A", "B"], "spans": [3000]}},
        "walls": list(walls), "openings": list(openings), "columns": list(columns)})


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


class RegistryTest(unittest.TestCase):
    def test_skill_classes_and_metadata(self):
        self.assertIs(skill_class("03"), TuongSkill)
        self.assertIs(skill_class("04"), CuaSkill)
        s3, s4 = TuongSkill(), CuaSkill()
        self.assertEqual((s3.code, s3.name, s3.reads),
                         ("03", "Tường", ("project", "axes", "columns", "walls", "openings")))
        self.assertEqual((s4.code, s4.name, s4.reads), ("04", "Cửa", ("project", "axes", "walls", "openings")))
        self.assertEqual(s3.roles, ("tuong",))
        self.assertEqual(set(s4.roles), {"cua", "cua_kh"})
        self.assertEqual(s4.roles, roles_of("04"))

    def test_add_refuses_foreign_role(self):
        store = load_sample()
        plan = new_plan(store)
        with self.assertRaises(PlanError):
            TuongSkill().add(plan, "line", "cua", "x", p1=[0, 0], p2=[1, 0])
        with self.assertRaises(PlanError):
            CuaSkill().add(plan, "line", "tuong", "x", p1=[0, 0], p2=[1, 0])
        with self.assertRaises(PlanError):
            CuaSkill().add(plan, "hatch", "hatch", "x", boundaries=[[[0, 0], [1, 0], [1, 1]]],
                           pattern="SOLID", pattern_scale=1.0, angle=0.0)


class TuongSampleTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan, self.r3, self.r4 = run_all(self.store)
        self.walls = self.plan.ops_of(skill="03")

    def test_outline_plines_match_geom_in_deterministic_order(self):
        self.assertEqual(self.r3.skipped, [])
        self.assertIn("đã vẽ 9/9 tường", self.r3.notes)
        expected = outline_polylines(geom.wall_outline_lines(self.store))
        self.assertEqual(len(expected), len(geom.wall_outline_lines(self.store)))
        self.assertEqual(len(self.walls), len(expected))
        self.assertEqual(self.r3.ops_added, len(expected))
        self.assertIn(f"đường bao thân tường: {len(expected)} đường (0 đường kín)", self.r3.notes)
        keys = []
        for i, (op, (pts, closed)) in enumerate(zip(self.walls, expected)):
            self.assertEqual(op.eid, f"03/tuong/outline/{i}")
            self.assertEqual((op.kind, op.role), ("pline", "tuong"))
            self.assertEqual(op.data["closed"], closed)
            self.assertEqual([tuple(p) for p in op.data["points"]], pts)
            xs = [p[0] for p in op.data["points"]]
            ys = [p[1] for p in op.data["points"]]
            keys.append((round(min(xs)), round(min(ys)), len(xs)))
        self.assertEqual(keys, sorted(keys))
        # tổng chiều dài nét tường = chiều dài đường bao geom (không mất, không thêm đoạn nào)
        total = sum(LineString(ln).length for ln in geom.wall_outline_lines(self.store))
        self.assertAlmostEqual(wall_outline(self.plan).length, total, delta=1e-6)
        self.assertEqual(self.plan.ops_of(skill="03", kind="hatch"), [])

    def test_wall_lines_never_enter_openings(self):
        frames = {o.id: geom.opening_frame(self.store, o) for o in self.store.openings}
        self.assertTrue(all(f is not None for f in frames.values()))
        for oid, f in frames.items():
            inner = f["poly"].buffer(-0.25)
            for op in self.walls:
                for p in op.data["points"]:
                    self.assertFalse(f["poly"].contains(ShPoint(p)), f"{op.eid} có điểm {p} trong ô cửa {oid}")
                for a, b in segments(op):
                    self.assertFalse(LineString([a, b]).intersects(inner), f"{op.eid} cắt qua ô cửa {oid}")

    def test_jamb_closes_both_sides_of_every_opening(self):
        outline = wall_outline(self.plan).buffer(1e-3)
        for o in self.store.openings:
            f = geom.opening_frame(self.store, o)
            for edge in (f["a"], f["b"]):
                jamb = LineString([geom.add(edge, geom.mul(f["n"], -f["t"] / 2.0)),
                                   geom.add(edge, geom.mul(f["n"], f["t"] / 2.0))])
                self.assertTrue(outline.contains(jamb), f"thiếu nét đóng mép tường tại ô cửa {o.id} ({edge})")

    def test_no_wall_segment_on_column_faces(self):
        cols = [geom.column_polygon(self.store, c) for c in self.store.columns]
        self.assertEqual(len(cols), 12)
        # đối chứng: đường bao thô của thân tường CÓ đoạn trùng mặt cột → phép thử dưới đây có ý nghĩa
        raw = geom.wall_body(self.store).boundary
        self.assertGreater(sum(raw.intersection(c.boundary).length for c in cols), 100.0)
        for op in self.walls:
            for a, b in segments(op):
                mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                for c in cols:
                    on_face = all(c.boundary.distance(ShPoint(p)) < TOL for p in (a, b, mid))
                    self.assertFalse(on_face, f"{op.eid}: đoạn {a}→{b} trùng mặt cột")

    def test_store_not_modified(self):
        store = load_sample()
        before = store.data_hash()
        run_all(store)
        self.assertEqual(store.data_hash(), before)


class CuaSampleTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan, self.r3, self.r4 = run_all(self.store)
        self.eids = ops_by_eid(self.plan)

    def test_counts_four_doors_four_windows(self):
        self.assertEqual(self.r4.skipped, [])
        self.assertIn("đã vẽ 8/8 ô cửa (cửa đi: 4/4, cửa sổ: 4/4)", self.r4.notes)
        self.assertFalse(any("CẢNH BÁO" in n or "CHƯA xác nhận" in n for n in self.r4.notes + self.r3.notes))
        arcs = self.plan.ops_of(skill="04", kind="arc")
        self.assertEqual(len(arcs), 5)                       # CD1 2 cánh + CD2, CD3, CD4
        per_door = {d: len([a for a in arcs if a.eid.startswith(f"04/cua/{d}/arc/")])
                    for d in ("CD1", "CD2", "CD3", "CD4")}
        self.assertEqual(per_door, {"CD1": 2, "CD2": 1, "CD3": 1, "CD4": 1})
        for w in ("CS1", "CS2", "CS3", "CS4"):
            self.assertEqual(len([o for o in self.plan.ops_of(skill="04") if o.eid.startswith(f"04/cua/{w}/")]), 6)
            self.assertFalse(any(o.eid.startswith(f"04/cua/{w}/arc") for o in arcs))
        self.assertEqual(len(self.plan.ops_of(skill="04", kind="line")), 5 + 4 * 6)
        self.assertEqual(len(self.plan.ops_of(skill="04", role="cua_kh")), 8)
        self.assertEqual(self.r4.ops_added, 5 + 5 + 24 + 8)
        self.assertEqual({o.role for o in self.plan.ops_of(skill="04")}, {"cua", "cua_kh"})

    def test_cd3_arc_and_leaf(self):
        arc = self.eids["04/cua/CD3/arc/0"].data
        self.assertEqual((tuple(arc["center"]), arc["r"]), ((7255.0, 4800.0), 700.0))
        self.assertEqual((arc["start_angle"], arc["end_angle"]), (0.0, 90.0))
        leaf = self.eids["04/cua/CD3/leaf/0"].data
        self.assertEqual((leaf["p1"], leaf["p2"]), ([7255.0, 4800.0], [7955.0, 4800.0]))
        self.assertEqual(self.eids["04/cua/CD3/leaf/0"].role, "cua")

    def test_cd1_double_leaf_and_cd2_hinge_at_end(self):
        a0, a1 = self.eids["04/cua/CD1/arc/0"].data, self.eids["04/cua/CD1/arc/1"].data
        self.assertEqual((a0["center"], a0["r"], a0["start_angle"], a0["end_angle"]),
                         ([1000.0, 110.0], 800.0, 0.0, 90.0))
        self.assertEqual((a1["center"], a1["r"], a1["start_angle"], a1["end_angle"]),
                         ([2600.0, 110.0], 800.0, 90.0, 180.0))
        cd2 = self.eids["04/cua/CD2/leaf/0"].data
        self.assertEqual((cd2["p1"], cd2["p2"]), ([3300.0, 4255.0], [3300.0, 5155.0]))

    def test_every_leaf_matches_its_arc(self):
        for o in self.store.openings:
            if o.kind != "cua_di":
                continue
            leaves = geom.door_leaves(self.store, o)
            for k, lf in enumerate(leaves):
                line = self.eids[f"04/cua/{o.id}/leaf/{k}"].data
                arc = self.eids[f"04/cua/{o.id}/arc/{k}"].data
                self.assertEqual(line["p1"], arc["center"])
                self.assertAlmostEqual(geom.length(geom.sub(line["p2"], line["p1"])), arc["r"], delta=TOL)
                ends = [geom.add(arc["center"], geom.mul(geom.dir_from_angle(a), arc["r"]))
                        for a in (arc["start_angle"], arc["end_angle"])]
                self.assertTrue(any(geom.length(geom.sub(line["p2"], e)) < TOL for e in ends))
                self.assertEqual((arc["start_angle"], arc["end_angle"]), (lf["start_angle"], lf["end_angle"]))

    def test_window_four_parallel_lines_and_two_end_lines(self):
        cs1 = {k: self.eids[f"04/cua/CS1/line/{k}"].data for k in range(6)}
        self.assertEqual((cs1[0]["p1"], cs1[0]["p2"]), ([8100.0, -110.0], [9600.0, -110.0]))
        self.assertEqual((cs1[1]["p1"], cs1[1]["p2"]), ([8100.0, -25.0], [9600.0, -25.0]))
        self.assertEqual((cs1[2]["p1"], cs1[2]["p2"]), ([8100.0, 25.0], [9600.0, 25.0]))
        self.assertEqual((cs1[3]["p1"], cs1[3]["p2"]), ([8100.0, 110.0], [9600.0, 110.0]))
        self.assertEqual((cs1[4]["p1"], cs1[4]["p2"]), ([8100.0, -110.0], [8100.0, 110.0]))
        self.assertEqual((cs1[5]["p1"], cs1[5]["p2"]), ([9600.0, -110.0], [9600.0, 110.0]))
        for o in self.store.openings:
            if o.kind != "cua_so":
                continue
            f = geom.opening_frame(self.store, o)
            half = f["t"] / 2.0
            for k, d in enumerate((-half, -25.0, 25.0, half)):
                ln = self.eids[f"04/cua/{o.id}/line/{k}"].data
                self.assertAlmostEqual(dot(geom.sub(ln["p1"], f["a"]), f["n"]), d, delta=TOL)
                self.assertAlmostEqual(dot(geom.sub(ln["p2"], f["b"]), f["n"]), d, delta=TOL)
                self.assertAlmostEqual(geom.length(geom.sub(ln["p2"], ln["p1"])), o.width, delta=TOL)
            for k, edge in ((4, f["a"]), (5, f["b"])):
                ln = self.eids[f"04/cua/{o.id}/line/{k}"].data
                self.assertAlmostEqual(geom.dist_point_segment(edge, ln["p1"], ln["p2"]), 0.0, delta=TOL)
                self.assertAlmostEqual(geom.length(geom.sub(ln["p2"], ln["p1"])), f["t"], delta=TOL)
            for k in range(6):
                ln = self.eids[f"04/cua/{o.id}/line/{k}"].data
                self.assertTrue(f["poly"].buffer(TOL).contains(LineString([ln["p1"], ln["p2"]])))

    def test_marks_text_side_and_rotation(self):
        scale = int(self.store.project.scale)
        gap = paper_to_model(2.5, scale)
        expect = {"CD1": ((1800.0, -360.0), 0.0), "CD3": ((6895.0, 5150.0), 90.0),
                  "CS3": ((-360.0, 6300.0), 90.0), "CS4": ((5400.0, 8760.0), 0.0)}
        walls = geom.walls_union(self.store)
        for o in self.store.openings:
            op = self.eids[f"04/cua_kh/{o.id}"]
            d = op.data
            self.assertEqual((op.kind, op.role), ("text", "cua_kh"))
            self.assertEqual(d["text"], o.mark)
            self.assertEqual(d["height"], text_height("cua_kh", scale))
            self.assertEqual(d["align"], "MIDDLE_CENTER")
            self.assertTrue(-90.0 < d["rotation"] <= 90.0)
            f = geom.opening_frame(self.store, o)
            mid = geom.mul(geom.add(f["a"], f["b"]), 0.5)
            off = geom.sub(d["insert"], mid)
            self.assertAlmostEqual(geom.length(off), f["t"] / 2.0 + gap, delta=TOL)
            self.assertAlmostEqual(dot(off, f["u"]), 0.0, delta=TOL)
            if o.kind == "cua_di":
                lf = geom.door_leaves(self.store, o)[0]
                self.assertLess(dot(off, geom.sub(lf["open"], lf["hinge"])), 0.0, o.id)
            else:
                self.assertLess(dot(off, f["n"]), 0.0, o.id)
            self.assertFalse(walls.contains(ShPoint(d["insert"])), f"ký hiệu {o.id} nằm trong tường")
            if o.id in expect:
                (x, y), rot = expect[o.id]
                self.assertAlmostEqual(d["insert"][0], x, delta=TOL)
                self.assertAlmostEqual(d["insert"][1], y, delta=TOL)
                self.assertEqual(d["rotation"], rot)

    def test_empty_mark_uses_id_and_scale_changes_mark(self):
        store = load_sample()
        store.get("openings", "CS1").mark = "  "
        store.project.scale = 50
        plan, _, _ = run_all(store)
        eids = ops_by_eid(plan)
        self.assertEqual(eids["04/cua_kh/CS1"].data["text"], "CS1")
        cd1 = eids["04/cua_kh/CD1"].data
        self.assertEqual(cd1["height"], 100.0)
        self.assertEqual(cd1["insert"], [1800.0, -235.0])

    def test_readable_angle(self):
        cases = {(1, 0): 0.0, (-1, 0): 0.0, (0, 1): 90.0, (0, -1): 90.0,
                 (1, 1): 45.0, (-1, -1): 45.0, (1, -1): -45.0, (-1, 1): -45.0}
        for u, a in cases.items():
            got = readable_angle(geom.unit(u))
            self.assertAlmostEqual(got, a, delta=1e-9, msg=str(u))
            self.assertTrue(-90.0 < got <= 90.0)
            self.assertFalse(math.copysign(1.0, got) < 0 and got == 0.0)


class ThieuSoLieuTest(unittest.TestCase):
    """load_sample(filled=False): nhịp trục 2–3 và bề rộng CD4 để trống."""

    def setUp(self):
        self.store = load_sample(filled=False)
        self.plan, self.r3, self.r4 = run_all(self.store)

    def test_walls_on_axes_3_4_skipped_with_reason_and_key(self):
        skipped = skipped_map(self.r3)
        self.assertEqual(set(skipped), {f"tuong:{w}" for w in ("W1", "W2", "W3", "W6", "W8", "W9")})
        for w in self.store.walls:
            why = skipped.get(f"tuong:{w.id}")
            if why is None:
                continue
            self.assertTrue(why.startswith(geom.wall_reason(self.store, w)), why)
            self.assertIn("chưa có toạ độ", why)
            self.assertIn("axes:V.spans[1]", why)
            self.assertEqual(why, wall_skip_reason(self.store, w))
        self.assertIn("đã vẽ 3/9 tường", self.r3.notes)
        # chỉ còn W4, W5, W7 (x ≤ 3600 + 55)
        xs = [p[0] for op in self.plan.ops_of(skill="03") for p in op.data["points"]]
        self.assertTrue(xs)
        self.assertLessEqual(max(xs), 3655.0 + TOL)

    def test_cd4_skipped_for_missing_width(self):
        skipped = skipped_map(self.r4)
        self.assertEqual(set(skipped), {f"cua:{o}" for o in ("CD1", "CD3", "CD4", "CS1", "CS2", "CS4")})
        cd4 = self.store.get("openings", "CD4")
        why = skipped["cua:CD4"]
        self.assertTrue(why.startswith(geom.opening_reason(self.store, cd4)), why)
        self.assertIn("thiếu bề rộng cửa", why)
        self.assertIn("openings:CD4.width", why)
        self.assertNotIn("thiếu bề rộng", skipped["cua:CD3"])
        self.assertIn("đã vẽ 2/8 ô cửa (cửa đi: 1/4, cửa sổ: 1/4)", self.r4.notes)
        eids = ops_by_eid(self.plan)
        self.assertIn("04/cua/CD2/arc/0", eids)
        self.assertIn("04/cua/CS3/line/5", eids)
        self.assertFalse(any(e.startswith("04/cua/CD4/") or e == "04/cua_kh/CD4" for e in eids))
        notes = [n for n in self.r3.notes if n.startswith("ô cửa CD4 chưa trừ khỏi tường W8 vì")]
        self.assertEqual(len(notes), 1)
        self.assertIn("thiếu bề rộng cửa", notes[0])

    def test_only_width_missing_wall_kept_and_note_says_so(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600.0, Provenance(SRC_USER, "nhập tay khi kiểm thử"))
        plan, r3, r4 = run_all(store)
        self.assertEqual(r3.skipped, [])
        self.assertIn("đã vẽ 9/9 tường", r3.notes)
        self.assertIn("ô cửa CD4 chưa trừ khỏi tường W8 vì thiếu bề rộng cửa (khoá openings:CD4.width) — "
                      "đường bao tường W8 đang vẽ liền qua vị trí cửa", r3.notes)
        self.assertEqual(skipped_map(r4), {"cua:CD4": "thiếu bề rộng cửa (khoá openings:CD4.width)"})
        self.assertEqual(geom.opening_reason(store, store.get("openings", "CD4")), "thiếu bề rộng cửa")
        # mặt tường W8 phía phải (x = 7255) vẫn liền qua chỗ CD4 (y 6800 → …)
        outline = wall_outline(plan)
        self.assertLess(outline.distance(ShPoint(7255.0, 7250.0)), TOL)
        # CD3 vẫn được trừ
        self.assertGreater(outline.distance(ShPoint(7255.0, 5150.0)), 1.0)

    def test_interpolated_values_drawn_but_flagged_until_confirmed(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600.0, Provenance.interpolated("tổng 10800 − 3600 − 3600"))
        store.set_value("openings:CD4.width", 900.0, Provenance.interpolated("bằng cửa D2 cùng ký hiệu"))
        plan, r3, r4 = run_all(store)
        self.assertEqual((r3.skipped, r4.skipped), ([], []))
        w_note = [n for n in r3.notes if n.startswith("tường dựa trên số liệu nội suy CHƯA xác nhận")]
        self.assertEqual(len(w_note), 1)
        for w in ("W1", "W2", "W3", "W6", "W8", "W9"):
            self.assertIn(f"{w} (axes:V.spans[1])", w_note[0])
        for w in ("W4", "W5", "W7"):
            self.assertNotIn(f"{w} (", w_note[0])
        self.assertIn("ô cửa trừ khỏi tường theo số liệu nội suy CHƯA xác nhận: CD4 (openings:CD4.width)", r3.notes)
        o_note = [n for n in r4.notes if n.startswith("ô cửa dựa trên số liệu nội suy CHƯA xác nhận")]
        self.assertEqual(len(o_note), 1)
        self.assertIn("CD4 (openings:CD4.width, axes:V.spans[1])", o_note[0])
        self.assertIn("CD1 (axes:V.spans[1])", o_note[0])
        self.assertNotIn("CD2", o_note[0])
        self.assertNotIn("CS3", o_note[0])
        store.confirm("axes:V.spans[1]", by="kỹ sư kiểm tra")
        store.confirm("openings:CD4.width", by="kỹ sư kiểm tra")
        _, r3b, r4b = run_all(store)
        self.assertFalse(any("CHƯA xác nhận" in n for n in r3b.notes + r4b.notes))


class DuLieuSaiVaBienTest(unittest.TestCase):
    def test_malformed_wall_column_opening_do_not_break_the_rest(self):
        clean, _, _ = run_all(load_sample())
        store = load_sample()
        store.walls.append(Wall(id="WX", start="9/A", end="1/A", thickness=110))
        store.columns.append(Column(id="KX", axis_v="9", axis_h="A", b=220, h=220))
        store.openings.append(Opening(id="CX", wall_id="WX", kind="cua_di", offset=100, width=800))
        n_walls, n_cols, n_ops = len(store.walls), len(store.columns), len(store.openings)
        plan = new_plan(store)
        r3 = TuongSkill().run(store, plan)
        r4 = CuaSkill().run(store, plan)
        self.assertEqual((len(store.walls), len(store.columns), len(store.openings)), (n_walls, n_cols, n_ops))
        s3, s4 = skipped_map(r3), skipped_map(r4)
        self.assertEqual(set(s3), {"tuong:WX"})
        self.assertIn("sai cấu trúc", s3["tuong:WX"])
        self.assertEqual(set(s4), {"cua:CX"})
        self.assertIn("sai cấu trúc", s4["cua:CX"])
        self.assertTrue(any(n.startswith("cột KX chưa trừ khỏi tường vì dữ liệu cột sai cấu trúc") for n in r3.notes))
        self.assertTrue(any(n.startswith("ô cửa CX chưa trừ khỏi tường WX vì tường WX: dữ liệu sai cấu trúc")
                            for n in r3.notes))
        self.assertEqual(plan.fingerprint("03"), clean.fingerprint("03"))
        self.assertEqual(plan.fingerprint("04"), clean.fingerprint("04"))

    def test_free_standing_wall_gives_closed_plines_split_by_window(self):
        store = mini_store([{"id": "W1", "start": "1/A", "end": "2/A", "thickness": 200}])
        plan = new_plan(store)
        r3 = TuongSkill().run(store, plan)
        ops = plan.ops_of(skill="03")
        self.assertEqual(len(ops), 1)
        self.assertTrue(ops[0].data["closed"])
        self.assertEqual(sorted(map(tuple, ops[0].data["points"])),
                         sorted([(0.0, -100.0), (4000.0, -100.0), (4000.0, 100.0), (0.0, 100.0)]))
        self.assertIn("đường bao thân tường: 1 đường (1 đường kín)", r3.notes)

        store = mini_store([{"id": "W1", "start": "1/A", "end": "2/A", "thickness": 200}],
                           [{"id": "S", "wall_id": "W1", "kind": "cua_so", "offset": 1500, "width": 1000}])
        plan = new_plan(store)
        TuongSkill().run(store, plan)
        r4 = CuaSkill().run(store, plan)
        ops = plan.ops_of(skill="03")
        self.assertEqual([o.eid for o in ops], ["03/tuong/outline/0", "03/tuong/outline/1"])
        self.assertTrue(all(o.data["closed"] and len(o.data["points"]) == 4 for o in ops))
        self.assertEqual(min(p[0] for p in ops[0].data["points"]), 0.0)
        self.assertEqual(min(p[0] for p in ops[1].data["points"]), 2500.0)
        self.assertEqual(r4.skipped, [])
        self.assertEqual(ops_by_eid(plan)["04/cua_kh/S"].data["insert"], [2000.0, -350.0])   # phía phải (−n)

    def test_thin_wall_window_and_range_warnings(self):
        store = mini_store(
            [{"id": "W1", "start": "1/A", "end": "2/A", "thickness": 40},
             {"id": "W2", "start": "1/B", "end": "2/B", "thickness": 200}],
            [{"id": "S1", "wall_id": "W1", "kind": "cua_so", "offset": 1000, "width": 800},
             {"id": "S2", "wall_id": "W2", "kind": "cua_so", "offset": 3500, "width": 800},
             {"id": "D1", "wall_id": "W2", "kind": "cua_di", "offset": 1000, "width": 900},
             {"id": "D2", "wall_id": "W2", "kind": "cua_di", "offset": 1500, "width": 900}])
        plan = new_plan(store)
        r4 = CuaSkill().run(store, plan)
        self.assertEqual(r4.skipped, [])
        s1 = sorted(o.eid for o in plan.ops_of(skill="04", role="cua") if o.eid.startswith("04/cua/S1/"))
        self.assertEqual(s1, [f"04/cua/S1/line/{k}" for k in (0, 3, 4, 5)])
        self.assertTrue(any(n.startswith("CẢNH BÁO tường mỏng") and "S1" in n for n in r4.notes), r4.notes)
        self.assertTrue(any("CẢNH BÁO ô cửa S2 vượt ra ngoài tim tường W2" in n for n in r4.notes), r4.notes)
        self.assertTrue(any("CẢNH BÁO ô cửa D1 và D2 chồng nhau trên tường W2" in n for n in r4.notes), r4.notes)

    def test_missing_wall_thickness_and_unknown_wall(self):
        store = mini_store([{"id": "W1", "start": "1/A", "end": "2/A"}],
                           [{"id": "D1", "wall_id": "W1", "kind": "cua_di", "offset": 500},
                            {"id": "D2", "wall_id": "WZ", "kind": "cua_di", "offset": 500, "width": 800}])
        plan = new_plan(store)
        r3 = TuongSkill().run(store, plan)
        r4 = CuaSkill().run(store, plan)
        self.assertEqual(skipped_map(r3), {"tuong:W1": "thiếu chiều dày tường (khoá walls:W1.thickness)"})
        s4 = skipped_map(r4)
        self.assertEqual(s4["cua:D1"], "tường W1: thiếu chiều dày tường (khoá walls:W1.thickness); "
                                       "thiếu bề rộng cửa (khoá openings:D1.width)")
        self.assertEqual(s4["cua:D2"], "không có tường 'WZ'")
        self.assertEqual(s4["cua:D1"], opening_skip_reason(store, store.get("openings", "D1")))
        self.assertEqual(plan.ops, [])
        self.assertIn("ô cửa D2 chưa trừ khỏi tường WZ vì không có tường 'WZ'", r3.notes)


class ChayLaiTest(unittest.TestCase):
    def test_rerun_does_not_duplicate_and_keeps_other_skills(self):
        store = load_sample()
        plan, r3, r4 = run_all(store)
        n = len(plan.ops)
        fps = plan.fingerprints()
        self.assertEqual(set(fps), {"01", "02", "03", "04"})
        r3b = TuongSkill().run(store, plan)
        r4b = CuaSkill().run(store, plan)
        self.assertEqual(len(plan.ops), n)
        self.assertEqual((r3b.ops_added, r4b.ops_added), (r3.ops_added, r4.ops_added))
        self.assertEqual(plan.fingerprints(), fps)
        r4c = CuaSkill().run(store, plan)               # chạy lại riêng Skill 04: 01–03 không đổi
        self.assertEqual(r4c.ops_added, r4.ops_added)
        self.assertEqual(plan.fingerprints(), fps)
        eids = [o.eid for o in plan.ops]
        self.assertEqual(len(eids), len(set(eids)))
        self.assertEqual(plan.ownership_violations(), [])

    def test_fingerprint_stable_between_independent_runs_and_roundtrip(self):
        p1, _, _ = run_all(load_sample())
        p2, _, _ = run_all(load_sample())
        self.assertEqual(p1.fingerprints(), p2.fingerprints())
        p3 = DrawingPlan.from_dict(p1.to_dict())
        self.assertEqual(p3.fingerprints(), p1.fingerprints())
        self.assertEqual(p3.ownership_violations(), [])
        p4, _, _ = run_all(load_sample(filled=False))
        self.assertEqual(p4.ownership_violations(), [])


if __name__ == "__main__":
    unittest.main()
