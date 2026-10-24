# -*- coding: utf-8 -*-
"""
Test hình học dùng chung của agent dựng CAD (tools/cad_drafting/geom.py) ở các ca biên mà đề bài mẫu không có:
tường xiên (chữ L, chữ T), tường đổi chiều dày trên cùng một trục, ô cửa sát góc tường, block template có điểm chèn
không ở góc, chiếu nghỉ. So với hình đúng dựng độc lập bằng shapely, sai khác cho phép < 1 mm².
"""

import math
import unittest

from shapely.geometry import Polygon
from shapely.ops import unary_union

from tools.cad_drafting import geom, validator
from tools.cad_drafting.plan import BlockDef
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.store import ProjectStore

AREA_TOL = 1.0


def _store(walls, openings=(), columns=(), stairs=(), rooms=(), furniture=()):
    return ProjectStore.from_dict({
        "axes": {"V": {"names": ["1"], "spans": []}, "H": {"names": ["A"], "spans": []}},
        "walls": list(walls), "openings": list(openings), "columns": list(columns), "stairs": list(stairs),
        "rooms": list(rooms), "furniture": list(furniture)})


def _rect(a, b, t):
    """Hình chữ nhật dọc đoạn a→b, dày t (không kéo dài)."""
    u = geom.unit(geom.sub(b, a))
    return geom.rect_polygon(a, u, geom.length(geom.sub(b, a)), geom.left_normal(u), -t / 2.0, t / 2.0)


def _strip(a, b, t, far=1e5):
    u = geom.unit(geom.sub(b, a))
    return geom.rect_polygon(geom.sub(a, geom.mul(u, far)), u, 2 * far, geom.left_normal(u), -t / 2.0, t / 2.0)


class WallJoinTest(unittest.TestCase):
    def test_perpendicular_corner_unchanged(self):
        st = _store([{"id": "A", "start": [0, 0], "end": [3000, 0], "thickness": 220},
                     {"id": "B", "start": [0, 0], "end": [0, 3000], "thickness": 220}])
        u = geom.walls_union(st)
        expected = Polygon([(-110, -110), (3000, -110), (3000, 110), (110, 110), (110, 3000), (-110, 3000)])
        self.assertLess(u.symmetric_difference(expected).area, AREA_TOL)

    def test_skew_l_corner_is_mitred(self):
        ang = math.radians(60)
        b_end = (3000 * math.cos(ang), 3000 * math.sin(ang))
        st = _store([{"id": "A", "start": [0, 0], "end": [3000, 0], "thickness": 220},
                     {"id": "B", "start": [0, 0], "end": list(b_end), "thickness": 220}])
        u = geom.walls_union(st)
        # hình đúng: hai thân tường + hình bình hành giao của hai dải tường quanh góc (góc vát khép kín, không gai)
        expected = unary_union([_rect((0, 0), (3000, 0), 220), _rect((0, 0), b_end, 220),
                                _strip((0, 0), (3000, 0), 220).intersection(_strip((0, 0), b_end, 220))])
        self.assertLess(u.symmetric_difference(expected).area, AREA_TOL)

    def test_skew_t_junction_does_not_poke_through(self):
        ang = math.radians(60)
        a_start = (1500 + 3000 * math.cos(ang), 3000 * math.sin(ang))
        st = _store([{"id": "B", "start": [0, 0], "end": [3000, 0], "thickness": 220},
                     {"id": "A", "start": list(a_start), "end": [1500, 0], "thickness": 110}])
        u = geom.walls_union(st)
        expected = unary_union([_rect((0, 0), (3000, 0), 220), _rect(a_start, (1500, 0), 110)])
        self.assertLess(u.symmetric_difference(expected).area, AREA_TOL)
        self.assertGreaterEqual(u.bounds[1], -110 - 1e-6, "tường xiên không được nhô qua mặt xa của tường kia")

    def test_collinear_thickness_change_has_no_bump(self):
        st = _store([{"id": "D", "start": [0, 0], "end": [3000, 0], "thickness": 220},
                     {"id": "M", "start": [3000, 0], "end": [6000, 0], "thickness": 110}])
        u = geom.walls_union(st)
        expected = unary_union([_rect((0, 0), (3000, 0), 220), _rect((3000, 0), (6000, 0), 110)])
        self.assertLess(u.symmetric_difference(expected).area, AREA_TOL)

    def test_sample_walls_unchanged_and_area(self):
        st = load_sample()
        self.assertAlmostEqual(geom.walls_union(st).area, 10_493_450.0, delta=AREA_TOL)


class OpeningOwnWallTest(unittest.TestCase):
    def setUp(self):
        # cửa trên tường A bắt đầu ngay tại góc: ô cửa ăn vào tường B
        self.st = _store([{"id": "A", "start": [0, 0], "end": [3000, 0], "thickness": 220},
                          {"id": "B", "start": [0, 0], "end": [0, 3000], "thickness": 220}],
                         openings=[{"id": "D", "wall_id": "A", "kind": "cua_di", "offset": 0, "width": 800}])

    def test_opening_does_not_cut_other_wall(self):
        body = geom.wall_body(self.st)
        wall_b = geom.wall_polygon(self.st, self.st.get("walls", "B"))
        self.assertLess(wall_b.difference(body).area, AREA_TOL)

    def test_validator_reports_opening_into_other_wall(self):
        plan = new_plan(self.st)
        issues = validator.check_step(self.st, plan, "04", plan.fingerprints())
        hits = [i for i in issues if i.code == "CUA_DAM_TUONG"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].eids, ["D", "B"])

    def test_sample_has_no_opening_into_other_wall(self):
        st = load_sample()
        plan = new_plan(st)
        self.assertFalse([i for i in validator.check_step(st, plan, "04", plan.fingerprints())
                          if i.code == "CUA_DAM_TUONG"])


class FootprintOriginTest(unittest.TestCase):
    def test_centered_block_footprint(self):
        fp = geom.footprint((2000, 2000), (1000, 600), 0.0, (-500, -300))
        self.assertEqual(fp.bounds, (1500.0, 1700.0, 2500.0, 2300.0))

    def test_block_footprint_uses_origin_and_rejects_bad_rotation(self):
        st = _store([], furniture=[{"id": "F", "block": "BAN", "insert": [2000, 2000], "rotation": 90}])
        blk = BlockDef(name="BAN", ops=[{"kind": "line", "data": {"p1": [-500, -300], "p2": [500, 300]}}],
                       size=[1000, 600], origin=[-500, -300])
        fp = geom.block_footprint(st, st.get("furniture", "F"), blk)
        self.assertEqual(tuple(round(v) for v in fp.bounds), (1700, 1500, 2300, 2500))
        st.get("furniture", "F").rotation = "xoay"
        self.assertIsNone(geom.block_footprint(st, st.get("furniture", "F"), blk))

    def test_blockdef_origin_round_trip(self):
        blk = BlockDef(name="X", ops=[], size=[1, 2], origin=[-3, -4])
        self.assertEqual(BlockDef.from_dict(blk.to_dict()).origin, [-3.0, -4.0])


class LandingTest(unittest.TestCase):
    def test_landing_excluded_from_floor_hatch(self):
        st = load_sample()
        st.stairs[0].landings = [["2/B@300,7760", "2/B@1300,7760", "2/B@1300,8045", "2/B@300,8045"]]
        landing = geom.landing_polygon(st, st.stairs[0].landings[0])
        self.assertIsNotNone(landing)
        self.assertEqual(len(geom.stair_polygons(st)), 2)
        plan = new_plan(st)
        skill_class("07")().run(st, plan)
        floor = unary_union([Polygon(o.data["boundaries"][0], o.data["boundaries"][1:])
                             for o in plan.ops_of(skill="07") if "/san/P4/" in o.eid])
        self.assertLess(floor.intersection(landing).area, AREA_TOL)


if __name__ == "__main__":
    unittest.main()
