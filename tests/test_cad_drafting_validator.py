# -*- coding: utf-8 -*-
"""
Test CAD Validator (tools/cad_drafting/validator.py) của agent dựng CAD mặt bằng.

Không phụ thuộc skill 01–10: plan nhỏ dựng tay bằng plan.add, block nội thất (BlockDef có size) tự tạo trong test.
Mỗi mã lỗi được kiểm bằng dữ liệu cố ý sai (sửa store từ load_sample()); đề bài mẫu đúng không sinh LOI / NGHI_VAN.
"""

import unittest

from tools.cad_drafting import geom, validator
from tools.cad_drafting.plan import BlockDef
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import SkillResult, new_plan
from tools.cad_drafting.store import SEV_DOUBT, SEV_ERROR, SEV_WARN, Column, Issue, MeasuredDim, Provenance, Wall

DIMSTYLE = "TCVN_KT_100"

# kích thước block nội thất tự đặt cho test (rộng X, sâu Y — mm), khớp vị trí chèn sát tường của đề bài mẫu
BLOCK_SIZES = {
    "GIUONG_DOI": (1600, 2000), "TU_AO": (1200, 600), "SOFA_3": (2000, 800), "BAN_TRA": (1000, 500),
    "BAN_AN_4": (1200, 1200), "TU_BEP": (2400, 600), "BON_CAU": (400, 700), "LAVABO": (500, 450),
}


def add_sample_blocks(plan):
    for name, (w, d) in BLOCK_SIZES.items():
        plan.add_block(BlockDef(name=name, size=[w, d], ops=[
            {"kind": "pline", "data": {"points": [[0, 0], [w, 0], [w, d], [0, d]], "closed": True}}]))
    return plan


def codes(issues, severity=None):
    return [i.code for i in issues if severity is None or i.severity == severity]


def of(issues, code):
    return [i for i in issues if i.code == code]


def step(store, plan, code, before=None):
    """Chạy check_step với dấu vân tay chụp trước (mặc định: như hiện tại → không có thay đổi lấn phần)."""
    return validator.check_step(store, plan, code, plan.fingerprints() if before is None else before)


class PrecheckSampleTest(unittest.TestCase):
    def test_sample_has_no_error_or_doubt(self):
        issues = validator.precheck(load_sample())
        self.assertEqual(codes(issues, SEV_ERROR), [], [i.message for i in issues])
        self.assertEqual(codes(issues, SEV_DOUBT), [], [i.message for i in issues])

    def test_unfilled_sample_has_exactly_two_missing(self):
        issues = validator.precheck(load_sample(filled=False))
        missing = of(issues, "THIEU_KICH_THUOC")
        self.assertEqual(len(missing), 2)
        self.assertEqual(len(codes(issues, SEV_ERROR)), 2, [i.message for i in issues])
        self.assertEqual({i.eids[0] for i in missing}, {"axes:V.spans[1]", "openings:CD4.width"})
        for i in missing:
            self.assertEqual((i.severity, i.skill), (SEV_ERROR, "VAL"))
            self.assertIn(i.eids[0], i.message)
        self.assertIn("nhịp trục 2–3", missing[0].message)

    def test_deterministic(self):
        a = [(i.code, i.message, i.where) for i in validator.precheck(load_sample(filled=False))]
        b = [(i.code, i.message, i.where) for i in validator.precheck(load_sample(filled=False))]
        self.assertEqual(a, b)


class PrecheckAxesTest(unittest.TestCase):
    def test_non_positive_span_and_sum_mismatch(self):
        store = load_sample()
        store.axes["H"].spans[0] = -4200.0
        issues = validator.precheck(store)
        span = of(issues, "NHIP_TRUC_KHONG_DUONG")
        self.assertEqual(len(span), 1)
        self.assertIn("axes:H.spans[0]", span[0].message)
        self.assertIn("A–B", span[0].message)
        self.assertEqual(len(of(issues, "TONG_NHIP_LECH")), 1)

    def test_sum_differs_from_overall(self):
        store = load_sample()
        store.axes["V"].overall = 10900.0
        issues = validator.precheck(store)
        lech = of(issues, "TONG_NHIP_LECH")
        self.assertEqual(len(lech), 1)
        self.assertEqual(lech[0].severity, SEV_ERROR)
        self.assertIn("10800", lech[0].message)
        self.assertIn("10900", lech[0].message)
        self.assertIn("axes:V.overall", lech[0].message)

    def test_sum_within_tolerance_passes(self):
        store = load_sample()
        store.axes["V"].overall = 10800.5
        self.assertEqual(of(validator.precheck(store), "TONG_NHIP_LECH"), [])

    def test_sum_not_checked_when_span_missing(self):
        store = load_sample(filled=False)
        store.axes["V"].overall = 99999.0
        self.assertEqual(of(validator.precheck(store), "TONG_NHIP_LECH"), [])


class PrecheckReferencesTest(unittest.TestCase):
    def test_bad_references_reported_not_raised(self):
        store = load_sample()
        store.get("walls", "W9").start = "3/Z"
        store.get("rooms", "P1").boundary[0] = "1A"
        store.get("furniture", "F1").insert = "1/2"
        store.get("stairs", "ST1").flights[0].origin = "Q/B@1,2"
        issues = validator.precheck(store)
        bad = of(issues, "THAM_CHIEU_SAI")
        self.assertEqual(sorted(i.eids[0] for i in bad), ["F1", "P1", "ST1", "W9"])
        self.assertTrue(all(i.severity == SEV_ERROR for i in bad))
        self.assertTrue(any("'Z'" in i.message for i in bad))

    def test_wall_zero_length(self):
        store = load_sample()
        store.get("walls", "W5").end = "1/B"
        issues = validator.precheck(store)
        self.assertEqual([i.eids for i in of(issues, "TUONG_DAI_0")], [["W5"]])

    def test_non_positive_and_non_numeric_sizes(self):
        store = load_sample()
        store.get("columns", "C-1A").b = 0.0
        store.get("walls", "W6").thickness = -10.0
        store.get("walls", "W5").thickness = "abc"
        issues = validator.precheck(store)
        self.assertEqual(sorted(i.eids[0] for i in of(issues, "KICH_THUOC_KHONG_DUONG")),
                         ["columns:C-1A.b", "walls:W6.thickness"])
        self.assertEqual([i.eids[0] for i in of(issues, "SO_LIEU_KHONG_PHAI_SO")], ["walls:W5.thickness"])


class PrecheckOpeningsTest(unittest.TestCase):
    def test_opening_without_wall(self):
        store = load_sample()
        store.get("openings", "CD1").wall_id = "W99"
        issues = validator.precheck(store)
        self.assertEqual([i.eids for i in of(issues, "CUA_KHONG_CO_TUONG")], [["CD1"]])
        self.assertIn("W99", of(issues, "CUA_KHONG_CO_TUONG")[0].message)

    def test_opening_beyond_wall(self):
        store = load_sample()
        store.get("openings", "CS1").offset = 9800.0       # 9800 + 1500 > 10800
        store.get("openings", "CS3").offset = -100.0
        issues = validator.precheck(store)
        beyond = {i.eids[0]: i for i in of(issues, "CUA_VUOT_TUONG")}
        self.assertEqual(sorted(beyond), ["CS1", "CS3"])
        self.assertIn("11300", beyond["CS1"].message)
        self.assertIn("10800", beyond["CS1"].message)
        self.assertIn("< 0", beyond["CS3"].message)
        self.assertEqual(beyond["CS1"].where, [10550.0, 0.0])

    def test_opening_flush_with_wall_end_passes(self):
        store = load_sample()
        store.get("openings", "CS1").offset = 9300.0       # 9300 + 1500 = 10800 đúng bằng chiều dài tim
        self.assertEqual(of(validator.precheck(store), "CUA_VUOT_TUONG"), [])

    def test_two_openings_overlap_on_same_wall(self):
        store = load_sample()
        store.get("openings", "CS2").offset = 2000.0       # [2000–3800] chồng CD1 [1000–2600]
        issues = validator.precheck(store)
        ov = of(issues, "CUA_CHONG_NHAU")
        self.assertEqual(len(ov), 1)
        self.assertEqual(set(ov[0].eids), {"CD1", "CS2", "W1"})
        self.assertIn("600 mm", ov[0].message)
        self.assertEqual(ov[0].where, [2300.0, 0.0])


class PrecheckRoomsTest(unittest.TestCase):
    def test_bad_room_boundaries(self):
        store = load_sample()
        store.get("rooms", "P1").boundary = ["1/A", "3/B", "3/A", "1/B"]     # tự cắt (hình nơ)
        store.get("rooms", "P2").boundary = ["3/A", "4/A"]                   # 2 điểm
        store.get("rooms", "P6").boundary = ["3/C", "4/C", "1/C"]            # thẳng hàng, diện tích 0
        issues = validator.precheck(store)
        self.assertEqual(sorted(i.eids[0] for i in of(issues, "PHONG_BIEN_HONG")), ["P1", "P2", "P6"])
        p1 = [i for i in of(issues, "PHONG_BIEN_HONG") if i.eids == ["P1"]][0]
        self.assertEqual(p1.where, [3600.0, 2100.0])          # điểm tự cắt

    def test_rooms_overlap(self):
        store = load_sample()
        store.get("rooms", "P2").boundary = ["2/A", "4/A", "4/B", "2/B"]     # chồng P1 3600 × 4200
        issues = validator.precheck(store)
        ov = of(issues, "PHONG_CHONG_NHAU")
        self.assertEqual(len(ov), 1)
        self.assertEqual(set(ov[0].eids), {"P1", "P2"})
        self.assertIn("15,12 m²", ov[0].message)
        self.assertEqual(ov[0].where, [5400.0, 2100.0])

    def test_tiny_room_overlap_below_threshold(self):
        store = load_sample()
        store.get("rooms", "P2").boundary = ["3/A@-2,0", "4/A", "4/B", "3/B@-2,0"]   # 2 × 4200 = 8400 mm² < 0,01 m²
        self.assertEqual(of(validator.precheck(store), "PHONG_CHONG_NHAU"), [])
        store.get("rooms", "P2").boundary = ["3/A@-50,0", "4/A", "4/B", "3/B@-50,0"]
        self.assertEqual(len(of(validator.precheck(store), "PHONG_CHONG_NHAU")), 1)


class PrecheckMeasuredDimTest(unittest.TestCase):
    def _store_with(self, **kw):
        store = load_sample()
        data = {"id": "DIM-1", "p1": [0.0, -1500.0], "p2": [3600.0, -1500.0], "angle": 0.0, "measurement": 3600.0}
        data.update(kw)
        store.measured_dims.append(MeasuredDim(**data))
        return store

    def test_override_text_differs(self):
        for text in ("3650", "XEM CHI TIẾT", "{\\fArial|b0;3700}"):
            issues = validator.precheck(self._store_with(text=text))
            dd = of(issues, "DIM_GHI_DE")
            self.assertEqual(len(dd), 1, text)
            self.assertEqual(dd[0].severity, SEV_DOUBT)
            self.assertEqual(dd[0].where, [1800.0, -1500.0])

    def test_override_text_matching_measurement(self):
        for text in ("3600", "3.600", "3,600", "<>", "<> (tim trục)", "3600 mm", ""):
            self.assertEqual(of(validator.precheck(self._store_with(text=text)), "DIM_GHI_DE"), [], text)

    def test_dim_differs_from_axis_spacing(self):
        issues = validator.precheck(self._store_with(measurement=3650.0))
        lech = of(issues, "DIM_LECH_TRUC")
        self.assertEqual(len(lech), 1)
        self.assertEqual(lech[0].severity, SEV_DOUBT)
        self.assertIn("trục 1 và 2", lech[0].message)
        self.assertIn("3650", lech[0].message)

    def test_dim_on_horizontal_axes(self):
        store = self._store_with(p1=[-1500.0, 0.0], p2=[-1500.0, 4200.0], angle=90.0, measurement=4100.0)
        lech = of(validator.precheck(store), "DIM_LECH_TRUC")
        self.assertEqual(len(lech), 1)
        self.assertIn("trục A và B", lech[0].message)

    def test_dim_matching_axes_or_not_across_axes(self):
        self.assertEqual(of(validator.precheck(self._store_with()), "DIM_LECH_TRUC"), [])
        # đo theo phương Y giữa hai điểm nằm trên trục V → không phải khoảng cách trục, không đối chiếu
        store = self._store_with(angle=90.0, measurement=50.0)
        self.assertEqual(of(validator.precheck(store), "DIM_LECH_TRUC"), [])
        # một điểm không nằm trên trục nào
        store = self._store_with(p2=[3000.0, -1500.0], measurement=3000.0)
        self.assertEqual(of(validator.precheck(store), "DIM_LECH_TRUC"), [])


class PrecheckInterpolationTest(unittest.TestCase):
    def test_interpolated_never_confirmed_until_person_confirms(self):
        store = load_sample(filled=False)
        store.set_value("axes:V.spans[1]", 3600.0, Provenance.interpolated("10800 − 2 × 3600 từ kích thước tổng"))
        issues = validator.precheck(store)
        doubt = of(issues, "NOI_SUY_CHUA_XAC_NHAN")
        self.assertEqual(len(doubt), 1)
        self.assertEqual(doubt[0].severity, SEV_DOUBT)
        self.assertEqual(doubt[0].eids, ["axes:V.spans[1]"])
        self.assertIn("kích thước tổng", doubt[0].message)
        self.assertEqual(doubt[0].where, [5400.0, 0.0])
        self.assertFalse(validator.summarize(issues)["dat"])
        store.confirm("axes:V.spans[1]", by="kỹ sư kiểm tra")
        self.assertEqual(of(validator.precheck(store), "NOI_SUY_CHUA_XAC_NHAN"), [])


class CheckStepGeneralTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = new_plan(self.store)

    def test_foreign_role_reported(self):
        before = self.plan.fingerprints()
        self.plan.add("line", "tuong", "03", "03/tuong/a", p1=[0, 0], p2=[100, 0])
        self.plan.add("line", "dim", "03", "03/lan", p1=[0, -500], p2=[100, -500])
        issues = validator.check_step(self.store, self.plan, "03", before)
        lan = of(issues, "SKILL_LAN_PHAN")
        self.assertEqual(len(lan), 1)
        self.assertEqual((lan[0].severity, lan[0].skill, lan[0].eids), (SEV_ERROR, "03", ["03/lan"]))
        self.assertIn("'dim'", lan[0].message)
        self.assertIn("skill 08", lan[0].message)
        self.assertEqual(lan[0].where, [0.0, -500.0])

    def test_editing_another_skill_reported(self):
        self.plan.add("pline", "cot", "02", "02/cot/C-1A", points=[[0, 0], [220, 0], [220, 220]], closed=True)
        self.plan.add("line", "truc", "01", "01/truc/1/line", p1=[0, -1000], p2=[0, 9000])
        before = self.plan.fingerprints()
        # "skill 03" vẽ phần của mình nhưng sửa cột của skill 02, xoá trục của skill 01, ghi hộ skill 05
        self.plan.add("line", "tuong", "03", "03/tuong/a", p1=[0, 0], p2=[100, 0])
        self.plan.ops_of(skill="02")[0].data["points"][0] = [5.0, 5.0]
        self.plan.remove_skill("01")
        self.plan.add("line", "thang", "05", "05/thang/x", p1=[0, 0], p2=[10, 10])
        issues = validator.check_step(self.store, self.plan, "03", before)
        sua = {i.message.split("dấu vân tay của skill ")[1][:2]: i for i in of(issues, "SKILL_SUA_PHAN_KHAC")}
        self.assertEqual(sorted(sua), ["01", "02", "05"])
        self.assertIn("đã bị xoá", sua["01"].message)
        self.assertIn("trước đó không có lệnh vẽ nào", sua["05"].message)
        self.assertTrue(all(i.severity == SEV_ERROR and i.skill == "03" for i in sua.values()))

    def test_own_changes_and_unchanged_plan_not_reported(self):
        self.plan.add("line", "tuong", "03", "03/tuong/a", p1=[0, 0], p2=[100, 0])
        self.plan.add("line", "truc", "01", "01/truc/1/line", p1=[0, -1000], p2=[0, 9000])
        before = self.plan.fingerprints()
        self.plan.remove_skill("03")
        self.plan.add("line", "tuong", "03", "03/tuong/b", p1=[0, 0], p2=[200, 0])
        issues = validator.check_step(self.store, self.plan, "03", before)
        self.assertEqual(of(issues, "SKILL_SUA_PHAN_KHAC"), [])
        self.assertEqual(of(issues, "SKILL_LAN_PHAN"), [])

    def test_foreign_role_by_unknown_skill_code_reported_at_any_step(self):
        self.plan.add("line", "tuong", "99", "99/la", p1=[0, 0], p2=[100, 0])
        lan = of(step(self.store, self.plan, "05"), "SKILL_LAN_PHAN")
        self.assertEqual([(i.skill, i.eids) for i in lan], [("99", ["99/la"])])
        self.plan.add("line", "dim", "03", "03/lan", p1=[0, 0], p2=[100, 0])
        # vi phạm của skill 03 được báo ở bước 03, không báo lặp ở bước khác
        self.assertEqual([i.skill for i in of(step(self.store, self.plan, "05"), "SKILL_LAN_PHAN")], ["99"])

    def test_missing_before_fingerprints_is_reported(self):
        issues = validator.check_step(self.store, self.plan, "03", None)
        self.assertEqual(codes(issues), ["CHUA_CO_DAU_VAN_TAY"])
        self.assertEqual(issues[0].severity, SEV_WARN)

    def test_duplicate_strokes_same_role_only(self):
        p = self.plan
        p.add("line", "tuong", "03", "03/a", p1=[0, 0], p2=[1000, 0])
        p.add("line", "tuong", "03", "03/b", p1=[1500, 0], p2=[500, 0])      # chồng 03/a 500 mm (ngược chiều)
        p.add("line", "tuong", "03", "03/c", p1=[1500, 0], p2=[2000, 0])     # chỉ chạm đầu 03/b
        p.add("pline", "tuong", "03", "03/d", points=[[3000, 0], [4000, 0], [4000, 1000]], closed=True)
        p.add("line", "tuong", "03", "03/e", p1=[3200, 0], p2=[3800, 0])     # nằm trên cạnh pline 03/d
        p.add("line", "tuong", "03", "03/f", p1=[0, 0.5], p2=[1000, 0.5])    # lệch 0,5 mm ≤ TOL → vẫn trùng 03/a
        p.add("line", "truc", "01", "01/x", p1=[0, 0], p2=[1000, 0])         # skill khác: không xét ở bước 03
        issues = of(step(self.store, p, "03"), "TRUNG_NET")
        pairs = sorted(tuple(i.eids) for i in issues)
        self.assertEqual(pairs, [("03/a", "03/b"), ("03/a", "03/f"), ("03/b", "03/f"), ("03/d", "03/e")])
        ab = [i for i in issues if i.eids == ["03/a", "03/b"]][0]
        self.assertEqual(ab.severity, SEV_WARN)
        self.assertIn("500 mm", ab.message)
        self.assertEqual(ab.where, [750.0, 0.0])

    def test_duplicate_strokes_different_roles_not_reported(self):
        self.plan.add("line", "truc", "01", "01/a", p1=[0, 0], p2=[1000, 0])
        self.plan.add("line", "truc_kh", "01", "01/b", p1=[0, 0], p2=[1000, 0])
        self.assertEqual(of(step(self.store, self.plan, "01"), "TRUNG_NET"), [])

    def test_clean_sample_steps_without_error(self):
        plan = add_sample_blocks(new_plan(self.store))
        for code in [f"{i:02d}" for i in range(1, 10)]:
            issues = step(self.store, plan, code)
            self.assertEqual([i for i in issues if i.severity in (SEV_ERROR, SEV_DOUBT)], [], code)
            self.assertEqual(issues, [], (code, [i.message for i in issues]))
        self.assertEqual(codes(step(self.store, plan, "10")), ["KHUNG_CHUA_CO"])


class RobustnessTest(unittest.TestCase):
    def test_broken_store_reports_instead_of_raising(self):
        store = load_sample()
        store.get("walls", "W1").start = [1.0, 2.0, 3.0]
        store.get("walls", "W2").end = None
        store.get("rooms", "P1").boundary = ["1/A", {"x": 1}, "3/B"]
        store.get("furniture", "F1").insert = None
        store.get("furniture", "F2").rotation = "xoay"
        store.get("openings", "CD2").offset = "abc"
        store.get("stairs", "ST1").flights[0].n_treads = 0
        store.columns.append(Column(id="C-LA", axis_v="9", axis_h="Z", b=220.0, h=220.0))
        issues = validator.precheck(store)
        self.assertGreaterEqual(len(of(issues, "THAM_CHIEU_SAI")), 5)
        self.assertIn(["openings:CD2.offset"], [i.eids for i in of(issues, "SO_LIEU_KHONG_PHAI_SO")])
        self.assertIn(["stairs:ST1.flights[0].n_treads"], [i.eids for i in of(issues, "KICH_THUOC_KHONG_DUONG")])
        plan = add_sample_blocks(new_plan(store))
        plan.meta["sheet_frame"] = [-5000.0, -5000.0, 20000.0, 15000.0]
        for code in [f"{i:02d}" for i in range(1, 11)]:
            for i in step(store, plan, code):
                self.assertIn(i.severity, (SEV_ERROR, SEV_WARN, SEV_DOUBT))
        chua = {i.eids[0]: i.message for i in of(step(store, plan, "06"), "NOI_THAT_CHUA_KIEM_TRA")}
        self.assertEqual(sorted(chua), ["F1", "F2", "F3", "F4"])
        self.assertIn("va chạm", chua["F1"])                 # điểm chèn sai
        self.assertIn("góc xoay", chua["F2"])
        self.assertIn("phòng P1", chua["F3"])                # phòng P1 có đường bao hỏng
        # vị trí cửa sai kiểu: geom trả lý do (không ném) → precheck đã báo SO_LIEU_KHONG_PHAI_SO ở trên, bước 04 chạy
        # tiếp không lỗi và không kiểm tra hình học trên ô cửa không dựng được
        self.assertIn("không phải số", geom.opening_reason(store, store.get("openings", "CD2")))
        self.assertFalse([i for i in step(store, plan, "04") if "CD2" in i.eids and i.code != "CHUA_KIEM_TRA_HINH_HOC"
                          and i.severity == SEV_ERROR])


class CheckStep0102Test(unittest.TestCase):
    def test_axes_same_position(self):
        store = load_sample()
        store.axes["V"].spans[0] = 0.0
        issues = step(store, new_plan(store), "01")
        trung = of(issues, "TRUC_TRUNG_VI_TRI")
        self.assertEqual(len(trung), 1)
        self.assertEqual(trung[0].eids, ["1", "2"])
        self.assertEqual(trung[0].where, [0.0, 0.0])

    def test_columns_overlap_and_offset(self):
        store = load_sample()
        store.columns.append(Column(id="C-1A-BIS", axis_v="1", axis_h="A", b=220.0, h=220.0, dx=50.0, mark="C1"))
        issues = step(store, new_plan(store), "02")
        ov = of(issues, "COT_CHONG_NHAU")
        self.assertEqual(len(ov), 1)
        self.assertEqual(set(ov[0].eids), {"C-1A", "C-1A-BIS"})
        self.assertIn("37400 mm²", ov[0].message)          # 170 × 220
        self.assertEqual(ov[0].where, [25.0, 0.0])
        off = of(issues, "COT_LECH_TRUC")
        self.assertEqual([(i.severity, i.eids) for i in off], [(SEV_WARN, ["C-1A-BIS"])])
        self.assertIn("dx = 50", off[0].message)


class CheckStep03Test(unittest.TestCase):
    def test_sample_walls_clean(self):
        store = load_sample()
        self.assertEqual(step(store, new_plan(store), "03"), [])

    def test_duplicate_wall(self):
        store = load_sample()
        store.walls.append(Wall(id="W10", start="1/A", end="2/A", thickness=220.0))
        issues = step(store, new_plan(store), "03")
        trung = of(issues, "TUONG_TRUNG")
        self.assertEqual([(i.severity, set(i.eids)) for i in trung], [(SEV_ERROR, {"W1", "W10"})])
        self.assertIn("3600 mm", trung[0].message)
        self.assertEqual(trung[0].where, [1800.0, 0.0])

    def test_numeric_wall_off_axis_and_crossing(self):
        store = load_sample()
        store.walls.append(Wall(id="W11", start=[1800.0, -500.0], end=[1800.0, 500.0], thickness=110.0))
        store.walls.append(Wall(id="W12", start=[3600.0, 500.0], end=[3600.0, 3000.0], thickness=110.0))  # trên trục 2
        issues = step(store, new_plan(store), "03")
        self.assertEqual([i.eids for i in of(issues, "TUONG_LECH_TRUC")], [["W11"]])
        cat = of(issues, "TUONG_CAT_NHAU")
        self.assertEqual([(i.severity, set(i.eids)) for i in cat], [(SEV_WARN, {"W1", "W11"})])
        self.assertEqual(cat[0].where, [1800.0, 0.0])
        self.assertEqual(of(issues, "TUONG_TRUNG"), [])


class CheckStep04Test(unittest.TestCase):
    def test_sample_doors_clean(self):
        store = load_sample()
        self.assertEqual(step(store, new_plan(store), "04"), [])

    def test_opening_on_column(self):
        store = load_sample()
        store.get("openings", "CD1").offset = 0.0           # ô cửa [0–1600] đè cột C-1A
        issues = step(store, new_plan(store), "04")
        dam = of(issues, "CUA_DAM_COT")
        self.assertEqual([(i.severity, i.eids) for i in dam], [(SEV_ERROR, ["CD1", "C-1A"])])

    def test_swing_hits_wall(self):
        store = load_sample()
        store.get("openings", "CD3").offset = 0.0           # bản lề sát góc 3/B, cánh quét vào tường W6
        issues = step(store, new_plan(store), "04")
        vuong = of(issues, "CANH_CUA_VUONG")
        self.assertIn(["CD3", "W6"], [i.eids for i in vuong])
        self.assertTrue(all(i.severity == SEV_WARN for i in vuong))

    def test_two_swings_overlap(self):
        store = load_sample()
        store.get("openings", "CD4").offset = 1000.0        # CD4 [5200–6100] sát CD3 [4800–5500], cùng mở sang phải
        issues = step(store, new_plan(store), "04")
        chong = of(issues, "CANH_CUA_CHONG")
        self.assertEqual([(i.severity, set(i.eids)) for i in chong], [(SEV_WARN, {"CD3", "CD4"})])


class CheckStep05Test(unittest.TestCase):
    def test_sample_stair_clean(self):
        store = load_sample()
        self.assertEqual(step(store, new_plan(store), "05"), [])

    def test_stair_on_wall(self):
        store = load_sample()
        store.get("stairs", "ST1").flights[0].origin = "2/B@-300,700"   # vế 3300–4300 cắt tường W7 (x = 3600)
        issues = step(store, new_plan(store), "05")
        dam = of(issues, "THANG_DAM_TUONG")
        self.assertEqual([(i.severity, i.eids) for i in dam], [(SEV_ERROR, ["ST1.flights[0]", "W7"])])
        self.assertTrue(dam[0].message.startswith("Vế 1 thang ST1 đè tường W7"), dam[0].message)
        self.assertEqual(len(of(issues, "THANG_NGOAI_PHONG")), 1)

    def test_stair_outside_rooms(self):
        store = load_sample()
        store.rooms = [r for r in store.rooms if r.id != "P4"]
        issues = step(store, new_plan(store), "05")
        self.assertEqual([(i.severity, i.code) for i in issues], [(SEV_WARN, "THANG_NGOAI_PHONG")])

    def test_door_swing_into_stair(self):
        store = load_sample()
        store.get("stairs", "ST1").flights[0].origin = "2/B@2500,500"   # vế 6100–7100 × 4700–7560
        store.get("openings", "CD3").opens_to = "trai"                 # CD3 mở vào sảnh thang
        issues = step(store, new_plan(store), "05")
        self.assertEqual([(i.code, i.eids) for i in issues], [("CUA_VUONG_THANG", ["CD3", "ST1.flights[0]"])])


class CheckStep06Test(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = add_sample_blocks(new_plan(self.store))

    def test_sample_furniture_clean(self):
        self.assertEqual(step(self.store, self.plan, "06"), [])

    def test_bed_moved_into_wall(self):
        self.store.get("furniture", "F1").insert = [1000.0, 6500.0]     # giường 6500–8500 đè tường W3
        issues = step(self.store, self.plan, "06")
        xd = of(issues, "NOI_THAT_XUNG_DOT")
        self.assertEqual([(i.severity, i.eids) for i in xd], [(SEV_ERROR, ["F1", "W3"])])
        self.assertIn("tường W3", xd[0].message)
        self.assertEqual(xd[0].where, [1800.0, 8395.0])
        self.assertEqual([i.eids for i in of(issues, "NOI_THAT_NGOAI_PHONG")], [["F1", "P3"]])

    def test_furniture_on_stair_and_wall(self):
        self.store.get("furniture", "F2").insert = [4200.0, 6800.0]     # tủ áo 3600–4200 × 6800–8000 đè vế thang
        self.store.get("furniture", "F3").insert = [-50.0, 3200.0]      # sofa lấn vào tường W4 (x = −110…110)
        issues = of(step(self.store, self.plan, "06"), "NOI_THAT_XUNG_DOT")
        pairs = [i.eids for i in issues]
        self.assertIn(["F2", "ST1.flights[0]"], pairs)
        self.assertIn(["F3", "W4"], pairs)
        f2 = [i for i in issues if i.eids == ["F2", "ST1.flights[0]"]][0]
        self.assertIn("vế 1 thang ST1", f2.message)

    def test_door_blocked_and_furniture_overlap(self):
        self.store.get("furniture", "F4").insert = [1150.0, 300.0]      # bàn trà trong vùng quét cửa CD1
        self.store.get("furniture", "F5").insert = [9600.0, 1500.0]     # bàn ăn 9600–10800 chồng tủ bếp 10090–10690
        issues = step(self.store, self.plan, "06")
        self.assertEqual([i.eids for i in of(issues, "NOI_THAT_CHAN_CUA")], [["F4", "CD1"]])
        self.assertEqual([set(i.eids) for i in of(issues, "NOI_THAT_CHONG_NHAU")], [{"F5", "F6"}])

    def test_unknown_room_and_missing_block(self):
        self.store.get("furniture", "F8").room_id = "P99"
        self.plan.blocks.pop("BON_CAU")
        issues = step(self.store, self.plan, "06")
        self.assertIn(["F8"], [i.eids for i in of(issues, "NOI_THAT_NGOAI_PHONG")])
        chua = of(issues, "NOI_THAT_CHUA_KIEM_TRA")
        self.assertEqual([i.eids for i in chua], [["F7"]])
        self.assertIn("BON_CAU", chua[0].message)


class CheckStep070809Test(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = new_plan(self.store)

    def _hatch(self, eid, boundaries):
        self.plan.add("hatch", "hatch", "07", eid, boundaries=boundaries, pattern="SOLID", pattern_scale=1.0,
                      angle=0.0)

    def test_hatch_boundaries(self):
        self._hatch("07/no", [[[0, 0], [100, 100], [100, 0], [0, 100]]])                       # hình nơ
        self._hatch("07/thang", [[[0, 0], [100, 0], [200, 0]]])                                # diện tích 0
        self._hatch("07/lo_ngoai", [[[0, 0], [100, 0], [100, 100], [0, 100]],
                                    [[200, 200], [300, 200], [300, 300]]])                     # lỗ nằm ngoài
        self._hatch("07/dung", [[[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
                                [[200, 200], [300, 200], [300, 300], [200, 300]]])             # có lỗ, đúng
        issues = of(step(self.store, self.plan, "07"), "HATCH_BIEN_HONG")
        self.assertEqual(sorted(i.eids[0] for i in issues), ["07/lo_ngoai", "07/no", "07/thang"])
        self.assertTrue(all(i.severity == SEV_ERROR for i in issues))
        no = [i for i in issues if i.eids == ["07/no"]][0]
        self.assertEqual(no.where, [50.0, 50.0])

    def test_dimensions(self):
        p = self.plan
        p.add("dim_linear", "dim", "08", "08/zero", p1=[0, 0], p2=[0, 0], base=[0, -500], angle=0.0, dimstyle=DIMSTYLE)
        p.add("dim_linear", "dim", "08", "08/doc", p1=[0, 0], p2=[0, 1000], base=[-500, 0], angle=0.0,
              dimstyle=DIMSTYLE)                                            # đo theo X giữa hai điểm cùng x → 0
        p.add("dim_linear", "dim", "08", "08/ghi_de", p1=[0, 0], p2=[3600, 0], base=[0, -500], angle=0.0,
              dimstyle=DIMSTYLE, text_override="3650")
        p.add("dim_linear", "dim", "08", "08/dung", p1=[0, 0], p2=[3600, 0], base=[0, -800], angle=0.0,
              dimstyle=DIMSTYLE, text_override="<>")
        issues = step(self.store, p, "08")
        self.assertEqual(sorted(i.eids[0] for i in of(issues, "DIM_BANG_0")), ["08/doc", "08/zero"])
        gd = of(issues, "DIM_GHI_DE")
        self.assertEqual([(i.severity, i.eids) for i in gd], [(SEV_DOUBT, ["08/ghi_de"])])
        self.assertIn("3650", gd[0].message)

    def test_room_label_outside(self):
        p = self.plan
        kw = dict(height=300.0, rotation=0.0, align="MIDDLE_CENTER")
        p.add("text", "hoan_thien", "09", "09/hoan_thien/P1/ten", insert=[3600, 2100], text="PHÒNG KHÁCH", **kw)
        p.add("text", "hoan_thien", "09", "09/hoan_thien/P3/ten", insert=[3600, 2100], text="PHÒNG NGỦ", **kw)
        p.add("text", "hoan_thien", "09", "09/hoan_thien/PX/ten", insert=[-5000, -5000], text="LẠ", **kw)
        p.add("text", "hoan_thien", "09", "09/hoan_thien/PY/ten", insert=[9000, 1000], text="TRONG P2", **kw)
        p.add("text", "hoan_thien", "09", "09/hoan_thien/P3/dien_tich", insert=[-5000, 0], text="S = 15 m²", **kw)
        issues = step(self.store, p, "09")
        self.assertEqual(sorted(i.eids[0] for i in of(issues, "NHAN_NGOAI_PHONG")),
                         ["09/hoan_thien/P3/ten", "09/hoan_thien/PX/ten"])
        self.assertTrue(all(i.severity == SEV_WARN for i in issues))


class CheckStep10Test(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = new_plan(self.store)

    def test_content_outside_frame_grouped_by_skill(self):
        p = self.plan
        p.meta["sheet_frame"] = [0.0, 0.0, 20000.0, 20000.0]
        p.add("line", "tuong", "03", "03/trong", p1=[100, 100], p2=[19000, 100])
        p.add("line", "tuong", "03", "03/ngoai_1", p1=[100, 100], p2=[25000, 100])
        p.add("line", "tuong", "03", "03/ngoai_2", p1=[-300, 100], p2=[100, 100])
        p.add_block(BlockDef(name="HOP", size=[1000, 1000], ops=[
            {"kind": "line", "data": {"p1": [0, 0], "p2": [1000, 1000]}}]))
        p.add("insert", "noi_that", "06", "06/noi_that/X", block="HOP", insert=[19500, 100], rotation=0.0,
              scale=[1.0, 1.0])                                            # điểm chèn trong khung, hộp block thò ra
        p.add("circle", "kiem_tra", "10", "10/kiem_tra/x/vong", center=[30000, 0], r=200)   # không in → bỏ qua
        p.add("pline", "khung_ten", "10", "10/khung_ten/vien_giay",
              points=[[0, 0], [20000, 0], [20000, 20000], [0, 20000]], closed=True)          # đúng mép khung
        issues = of(step(self.store, p, "10"), "NOI_DUNG_NGOAI_KHUNG")
        by_text = {i.eids[0][:2]: i for i in issues}
        self.assertEqual(sorted(by_text), ["03", "06"])
        self.assertEqual(by_text["03"].eids, ["03/ngoai_1", "03/ngoai_2"])
        self.assertIn("skill 03", by_text["03"].message)
        self.assertEqual(by_text["03"].where, [25000.0, 100.0])
        self.assertEqual(by_text["06"].eids, ["06/noi_that/X"])
        self.assertTrue(all(i.severity == SEV_ERROR and i.skill == "10" for i in issues))

    def test_frame_missing_or_unreadable(self):
        self.assertEqual(codes(step(self.store, self.plan, "10")), ["KHUNG_CHUA_CO"])
        self.plan.meta["sheet_frame"] = "khung"
        self.assertEqual(codes(step(self.store, self.plan, "10")), ["KHUNG_KHONG_DOC_DUOC"])

    def _text(self, eid, insert, text="AAAA", align="LEFT", rotation=0.0, role="hoan_thien", skill="09"):
        self.plan.add("text", role, skill, eid, insert=insert, text=text, height=100.0, rotation=rotation, align=align)

    def test_text_over_text(self):
        self.plan.meta["sheet_frame"] = [-10000.0, -10000.0, 10000.0, 10000.0]
        self._text("09/hoan_thien/P1/ten", [0, 0])
        self._text("04/cua_kh/CD1", [50, 20], text="D1", role="cua_kh", skill="04")          # đè
        self._text("10/khung_ten/nhan/du_an/0", [3000, 0], role="khung_ten", skill="10")
        self._text("10/khung_ten/nhan/du_an/1", [3000, 0], role="khung_ten", skill="10")       # cùng eid gốc → bỏ qua
        self._text("09/hoan_thien/P2/ten", [5000, 0], align="MIDDLE_CENTER")
        self._text("09/hoan_thien/P2/dien_tich", [5200, 0], text="BBBB")   # MIDDLE_CENTER của P2 kết thúc ở 5150
        self._text("10/kiem_tra/a/chu", [0, 0], role="kiem_tra", skill="10")                    # không in → bỏ qua
        issues = of(step(self.store, self.plan, "10"), "CHU_DE_CHU")
        self.assertEqual([i.eids for i in issues], [["09/hoan_thien/P1/ten", "04/cua_kh/CD1"]])
        self.assertEqual(issues[0].severity, SEV_WARN)

    def test_text_rotation_considered(self):
        self.plan.meta["sheet_frame"] = [-10000.0, -10000.0, 10000.0, 10000.0]
        self._text("09/a/ten", [0, 0])                                     # hộp 0–300 × 0–100
        self._text("08/b/chu", [150, -150], role="dim", skill="08")        # chưa xoay: 150–450 × −150…−50, không đè
        self.assertEqual(of(step(self.store, self.plan, "10"), "CHU_DE_CHU"), [])
        self.plan.remove_skill("08")
        self._text("08/b/chu", [150, -150], rotation=90.0, role="dim", skill="08")   # xoay 90°: 50–150 × −150…150
        issues = of(step(self.store, self.plan, "10"), "CHU_DE_CHU")
        self.assertEqual(len(issues), 1)
        self.assertIn("33 %", issues[0].message)


class CheckFinalAndSummaryTest(unittest.TestCase):
    def test_skipped_items_reported(self):
        store = load_sample()
        r6 = SkillResult("06", "Nội thất")
        r6.skip("noi_that:F1", "không có block 'GIUONG_DOI'")
        r9 = {"code": "09", "name": "Hoàn thiện", "skipped": [{"id": "hoan_thien:P5/ten", "ly_do": "phòng chưa có tên"}]}
        issues = validator.check_final(store, new_plan(store), [r6, r9])
        chua = of(issues, "DOI_TUONG_CHUA_VE")
        self.assertEqual([(i.severity, i.skill, i.eids) for i in chua],
                         [(SEV_WARN, "06", ["noi_that:F1"]), (SEV_WARN, "09", ["hoan_thien:P5/ten"])])
        self.assertIn("GIUONG_DOI", chua[0].message)
        self.assertEqual(chua[0].where, [1000.0, 6250.0])
        self.assertEqual(chua[1].where, [9000.0, 5200.0])
        self.assertEqual(len(issues), 2)

    def test_missing_repeated_with_same_message_as_precheck(self):
        store = load_sample(filled=False)
        pre = [(i.code, i.message) for i in validator.precheck(store) if i.code == "THIEU_KICH_THUOC"]
        fin = [(i.code, i.message) for i in validator.check_final(store, new_plan(store), [])
               if i.code == "THIEU_KICH_THUOC"]
        self.assertEqual(len(fin), 2)
        self.assertEqual(pre, fin)

    def test_summarize_computed(self):
        mk = lambda sev, code: Issue(severity=sev, code=code, message="x", skill="VAL")
        s = validator.summarize([mk(SEV_ERROR, "A"), mk(SEV_WARN, "B"), mk(SEV_WARN, "B"), mk(SEV_DOUBT, "C")])
        self.assertEqual(s["tong"], 4)
        self.assertEqual(s["theo_muc_do"], {SEV_ERROR: 1, SEV_WARN: 2, SEV_DOUBT: 1})
        self.assertEqual(s["theo_ma"], {"A": 1, "B": 2, "C": 1})
        self.assertEqual(s["theo_ma_muc_do"]["B"], {SEV_WARN: 2})
        self.assertFalse(s["dat"])
        self.assertFalse(validator.summarize([mk(SEV_DOUBT, "C")])["dat"])
        self.assertTrue(validator.summarize([mk(SEV_WARN, "B")])["dat"])
        self.assertTrue(validator.summarize([])["dat"])


if __name__ == "__main__":
    unittest.main()
