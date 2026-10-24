# -*- coding: utf-8 -*-
"""Test Skill 08 (kích thước) và Skill 10 (kiểm tra & xuất: khung bản vẽ, khung tên, đánh dấu) của agent dựng CAD.

Skill 01..07 được viết song song nên plan dùng Op giả của skill "01"/"03" cho bao nội dung (fake_content); một test
tích hợp riêng chạy thêm các skill khác nếu đã nạp được.
"""

import re
import unittest

import ezdxf

from tools.cad_drafting.layers import (LAYOUT_PAPER_MM, SHEET_SIZES_MM, dimstyle_name, paper_to_model, roles_of,
                                       text_height)
from tools.cad_drafting.plan import dim_measurement, iter_points
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan, skill_class
from tools.cad_drafting.skills.s08_dimension import DimensionSkill, detail_chain, outer_axis
from tools.cad_drafting.skills.s10_kiem_tra_xuat import KiemTraXuatSkill, content_bbox, status_text
from tools.cad_drafting.store import DATA_SECTIONS, ProjectStore, Provenance

FORBIDDEN = (re.compile(r"hợp lệ", re.IGNORECASE), re.compile(r"\bOK\b"), re.compile(r"100\s*%"))


def fake_content(plan):
    """Op giả của skill 01 (lưới trục + vòng tròn) và 03 (một đường bao tường) — thay cho skill đang viết song song."""
    plan.add("line", "truc", "01", "01/gia/truc/1", p1=(0.0, -4200.0), p2=(0.0, 12600.0))
    plan.add("line", "truc", "01", "01/gia/truc/A", p1=(-4200.0, 0.0), p2=(15000.0, 0.0))
    plan.add("circle", "truc_kh", "01", "01/gia/bubble/4", center=(10800.0, 12200.0), r=400.0)
    plan.add("pline", "tuong", "03", "03/gia/outline/0",
             points=[(-110.0, -110.0), (10910.0, -110.0), (10910.0, 8510.0), (-110.0, 8510.0)], closed=True)


def dims(plan, level=None, side=None):
    pref = "08/dim/" + (f"L{level}/" if level else "")
    out = [o for o in plan.ops_of(skill="08") if o.eid.startswith(pref)]
    if side:
        out = [o for o in out if o.eid.split("/")[3] == side]
    return sorted(out, key=lambda o: int(o.eid.split("/")[-1]))


def skipped_map(result):
    return {s["id"]: s["ly_do"] for s in result.skipped}


def run_08_10(store, with_fake=True):
    plan = new_plan(store)
    if with_fake:
        fake_content(plan)
    r8 = DimensionSkill().run(store, plan)
    r10 = KiemTraXuatSkill().run(store, plan)
    return plan, r8, r10


def texts_of(plan, skill="10", role=None):
    return [o for o in plan.ops_of(skill=skill, role=role) if o.kind in ("text", "mtext")]


# ─────────────────────────────────────────────────────────────────────────────
# SKILL 08
# ─────────────────────────────────────────────────────────────────────────────

class DimensionSkillTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan = new_plan(self.store)
        self.result = DimensionSkill().run(self.store, self.plan)

    def test_registration(self):
        self.assertIs(skill_class("08"), DimensionSkill)
        s = DimensionSkill()
        self.assertEqual((s.code, s.name), ("08", "Kích thước"))
        self.assertEqual(s.reads, ("project", "axes", "walls", "openings", "columns"))
        self.assertEqual(s.roles, ("dim",))

    def test_level2_bottom_three_spans_of_3600(self):
        l2 = dims(self.plan, 2, "duoi")
        self.assertEqual([o.eid for o in l2], [f"08/dim/L2/duoi/{i}" for i in range(3)])
        self.assertEqual([round(dim_measurement(o.data), 6) for o in l2], [3600.0] * 3)
        # điểm đo = giao trục V với cạnh dưới khung trục H (y = 0)
        self.assertEqual([o.data["p1"] for o in l2], [[0.0, 0.0], [3600.0, 0.0], [7200.0, 0.0]])

    def test_level3_overall(self):
        for side, value in (("duoi", 10800.0), ("tren", 10800.0), ("trai", 8400.0), ("phai", 8400.0)):
            l3 = dims(self.plan, 3, side)
            self.assertEqual(len(l3), 1, side)
            self.assertEqual(l3[0].eid, f"08/dim/L3/{side}/0")
            self.assertAlmostEqual(dim_measurement(l3[0].data), value, places=6)

    def test_level1_bottom_chain_contains_opening_edges(self):
        l1 = dims(self.plan, 1, "duoi")
        xs = sorted({o.data["p1"][0] for o in l1} | {o.data["p2"][0] for o in l1})
        self.assertEqual(xs, [-110.0, 0.0, 1000.0, 2600.0, 3600.0, 4600.0, 6400.0, 7200.0, 8100.0, 9600.0,
                              10800.0, 10910.0])          # CD1 1000/2600, CS2 4600/6400, CS1 8100/9600
        self.assertEqual([round(dim_measurement(o.data)) for o in l1],
                         [110, 1000, 1600, 1000, 1000, 1800, 800, 900, 1500, 1200, 110])
        # điểm đo trên MẶT NGOÀI tường W1 (dày 220)
        self.assertTrue(all(o.data["p1"][1] == -110.0 and o.data["p2"][1] == -110.0 for o in l1))

    def test_level1_other_sides(self):
        expect = {"tren": [110, 3600, 1200, 1200, 1200, 3600, 110],
                  "trai": [110, 4200, 1500, 1200, 1500, 110],
                  "phai": [110, 4200, 4200, 110]}
        for side, values in expect.items():
            self.assertEqual([round(dim_measurement(o.data)) for o in dims(self.plan, 1, side)], values, side)

    def test_native_dimension_tcvn_style_no_override(self):
        ops = self.plan.ops_of(skill="08")
        self.assertEqual(len(ops), 42)
        self.assertEqual(dimstyle_name(100), "TCVN_KT_100")
        for o in ops:
            self.assertEqual((o.kind, o.role), ("dim_linear", "dim"))
            self.assertEqual(o.data["dimstyle"], "TCVN_KT_100")
            self.assertNotIn("text_override", o.data)
        self.assertIn("TCVN_KT_100", self.plan.dimstyles)
        self.assertEqual(self.plan.ops_of(skill="08", kind="line"), [])
        self.assertEqual(self.plan.ops_of(skill="08", kind="text"), [])

    def test_dimension_line_offsets_and_angles(self):
        k = 100.0
        for level in (1, 2, 3):
            d = LAYOUT_PAPER_MM[f"dim_level_{level}"] * k
            for side, axis, coord, angle in (("duoi", 1, -d, 0.0), ("tren", 1, 8400.0 + d, 0.0),
                                             ("trai", 0, -d, 90.0), ("phai", 0, 10800.0 + d, 90.0)):
                for o in dims(self.plan, level, side):
                    self.assertAlmostEqual(o.data["base"][axis], coord, places=6, msg=o.eid)
                    self.assertEqual(o.data["angle"], angle, o.eid)

    def test_ezdxf_measures_same_values(self):
        """DIMENSION dựng bằng ezdxf từ đúng p1/p2/base/angle của Op phải đo ra cùng giá trị."""
        doc = ezdxf.new("R2010", setup=True)
        msp = doc.modelspace()
        for o in self.plan.ops_of(skill="08"):
            d = o.data
            dim = msp.add_linear_dim(base=d["base"], p1=d["p1"], p2=d["p2"], angle=d["angle"])
            dim.render()
            self.assertAlmostEqual(dim.dimension.get_measurement(), dim_measurement(d), places=6, msg=o.eid)

    def test_no_skip_when_data_complete(self):
        self.assertEqual(self.result.skipped, [])
        self.assertEqual(self.plan.ownership_violations(), [])

    def test_rerun_does_not_duplicate(self):
        fp = self.plan.fingerprint("08")
        n = len(self.plan.ops)
        DimensionSkill().run(self.store, self.plan)
        self.assertEqual(len(self.plan.ops), n)
        self.assertEqual(self.plan.fingerprint("08"), fp)

    def test_missing_span_skips_level3_and_pairs(self):
        store = load_sample(filled=False)
        plan = new_plan(store)
        r = DimensionSkill().run(store, plan)
        sk = skipped_map(r)
        self.assertIn("dim/L3/duoi", sk)
        self.assertIn("dim/L3/tren", sk)
        self.assertIn("axes:V.spans[1]", sk["dim/L3/duoi"])
        self.assertIn("không tự suy ngược", sk["dim/L3/duoi"])
        l2 = dims(plan, 2, "duoi")
        self.assertTrue(1 <= len(l2) <= 2, len(l2))
        self.assertEqual([round(dim_measurement(o.data)) for o in l2], [3600])
        self.assertIn("dim/L2/duoi/1", sk)
        self.assertIn("dim/L2/duoi/2", sk)
        # nhóm trục H đủ toạ độ → cấp 3 trái vẫn ghi
        self.assertEqual([round(dim_measurement(o.data)) for o in dims(plan, 3, "trai")], [8400])
        # trục ngoài cùng phía phải (4) chưa có toạ độ → không lấy nhầm tường trong W7 làm tường ngoài
        self.assertIn("dim/L1/phai", sk)
        name, off, why = outer_axis(store, "phai")
        self.assertIsNone(name)
        self.assertIn("axes:V.spans[1]", why)
        # tường W1 trên trục A chưa dựng được → cấp 1 phía dưới bỏ qua kèm lý do
        self.assertIn("W1", sk["dim/L1/duoi"])
        self.assertTrue(dims(plan, 1, "trai"))
        self.assertTrue(any("sẽ đổi khi đủ số liệu" in n for n in r.notes))
        for o in plan.ops_of(skill="08"):
            self.assertGreater(dim_measurement(o.data), 0.0)

    def test_interpolated_span_still_dimensioned_and_listed(self):
        store = load_sample()
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("nội suy thử"))
        plan = new_plan(store)
        r = DimensionSkill().run(store, plan)
        self.assertEqual(len(dims(plan, 2, "duoi")), 3)
        notes = [n for n in r.notes if "axes:V.spans[1]" in n]
        self.assertEqual(len(notes), 1, r.notes)
        listed = set(notes[0].split(": ", 1)[1].split(", "))
        for eid in ("dim/L2/duoi/1", "dim/L2/tren/1", "dim/L3/duoi/0", "dim/L3/tren/0"):
            self.assertIn(eid, listed)
        # nhịp 1–2, 3–4 và đoạn cấp 1 không phụ thuộc nhịp 2–3 thì không bị liệt kê
        self.assertNotIn("dim/L2/duoi/0", listed)
        self.assertNotIn("dim/L2/duoi/2", listed)
        self.assertNotIn("dim/L1/duoi/4", listed)        # trục 2 (3600) → mép CS2 (4600): không phụ thuộc
        self.assertIn("dim/L1/duoi/6", listed)           # mép CS2 (6400) → trục 3 (7200): phụ thuộc nhịp 2–3

    def test_opening_without_width_is_noted(self):
        store = load_sample()
        store.get("openings", "CS1").width = None
        plan = new_plan(store)
        r = DimensionSkill().run(store, plan)
        self.assertTrue(any("CS1" in n and "cấp 1" in n for n in r.notes), r.notes)
        xs = {o.data["p1"][0] for o in dims(plan, 1, "duoi")} | {o.data["p2"][0] for o in dims(plan, 1, "duoi")}
        self.assertNotIn(9600.0, xs)
        self.assertNotIn(8100.0, xs)
        self.assertIn(7200.0, xs)                         # trục 3 vẫn có

    def test_column_protruding_wall_face_is_warned(self):
        store = load_sample()
        col = store.get("columns", "C-1A")
        col.b, col.h = 400.0, 400.0
        plan = new_plan(store)
        r = DimensionSkill().run(store, plan)
        self.assertTrue(any("C-1A" in n and "phía dưới" in n for n in r.notes), r.notes)
        self.assertTrue(any("C-1A" in n and "phía trái" in n for n in r.notes), r.notes)

    def test_collinear_walls_junction_is_not_an_outer_end(self):
        """Hai tường thẳng hàng nối nhau tại trục 2: biên wall_polygon ở mối nối nằm trong tường kia, không phải mép."""
        store = ProjectStore.from_dict({
            "project": {"scale": 100},
            "axes": {"V": {"names": ["1", "2", "3"], "spans": [3600, 3600]},
                     "H": {"names": ["A", "B"], "spans": [3000]}},
            "walls": [{"id": "W1a", "start": "1/A", "end": "2/A", "thickness": 220},
                      {"id": "W1b", "start": "2/A", "end": "3/A", "thickness": 220},
                      {"id": "W2", "start": "3/A", "end": "3/B", "thickness": 220},
                      {"id": "W3", "start": "3/B", "end": "1/B", "thickness": 220},
                      {"id": "W4", "start": "1/B", "end": "1/A", "thickness": 220}]})
        plan = new_plan(store)
        r = DimensionSkill().run(store, plan)
        self.assertEqual([round(dim_measurement(o.data)) for o in dims(plan, 1, "duoi")], [110, 3600, 3600, 110])
        self.assertEqual(detail_chain(store, "duoi")["walls"], ["W1a", "W1b"])
        self.assertEqual(r.skipped, [])

    def test_detail_chain_dedupes_points(self):
        ch = detail_chain(load_sample(), "duoi")
        s = [p.s for p in ch["points"]]
        self.assertEqual(s, sorted(s))
        self.assertTrue(all(b - a > 1.0 for a, b in zip(s, s[1:])))
        self.assertEqual(ch["walls"], ["W1"])


# ─────────────────────────────────────────────────────────────────────────────
# SKILL 10
# ─────────────────────────────────────────────────────────────────────────────

class KiemTraXuatSkillTest(unittest.TestCase):
    def setUp(self):
        self.store = load_sample()
        self.plan, self.r8, self.r10 = run_08_10(self.store)

    def test_registration(self):
        self.assertIs(skill_class("10"), KiemTraXuatSkill)
        s = KiemTraXuatSkill()
        self.assertEqual((s.code, s.name), ("10", "Kiểm tra & xuất"))
        self.assertEqual(tuple(s.reads), tuple(DATA_SECTIONS))
        self.assertEqual(set(s.roles), {"khung_ten", "kiem_tra"})

    def test_sheet_frame_a3_1_100_contains_content(self):
        f = self.plan.meta["sheet_frame"]
        self.assertEqual((f[2] - f[0], f[3] - f[1]), (42000.0, 29700.0))
        self.assertEqual(self.plan.meta["sheet"], {"size": "A3", "scale": 100, "paper_mm": [420.0, 297.0]})
        self.assertNotIn("khung_ban_ve", skipped_map(self.r10))
        k = 100.0
        inner = (f[0] + LAYOUT_PAPER_MM["sheet_margin_left"] * k, f[1] + LAYOUT_PAPER_MM["sheet_margin"] * k,
                 f[2] - LAYOUT_PAPER_MM["sheet_margin"] * k, f[3] - LAYOUT_PAPER_MM["sheet_margin"] * k)
        for o in self.plan.ops:
            for x, y in iter_points(o):
                self.assertTrue(f[0] <= x <= f[2] and f[1] <= y <= f[3], (o.eid, x, y))
                if o.eid == "10/khung_ten/vien_giay":
                    continue
                self.assertTrue(inner[0] <= x <= inner[2] and inner[1] <= y <= inner[3], (o.eid, x, y))
        # nội dung không đè khung tên
        tb = self.plan.ops_of(skill="10")
        tb = [o for o in tb if o.eid == "10/khung_ten/o/vien"][0].data["points"]
        tb_box = (min(p[0] for p in tb), min(p[1] for p in tb), max(p[0] for p in tb), max(p[1] for p in tb))
        self.assertAlmostEqual(tb_box[2] - tb_box[0], 18000.0)
        self.assertAlmostEqual(tb_box[3] - tb_box[1], 4000.0)
        self.assertAlmostEqual(tb_box[2], inner[2])
        self.assertAlmostEqual(tb_box[1], inner[1])
        bb = content_bbox(self.plan)
        self.assertTrue(bb[1] > tb_box[3] or bb[2] < tb_box[0])

    def test_frame_plines(self):
        by = {o.eid: o for o in self.plan.ops_of(skill="10")}
        paper = by["10/khung_ten/vien_giay"]
        inner = by["10/khung_ten/khung_ve"]
        self.assertEqual((paper.kind, paper.role, paper.data["closed"]), ("pline", "khung_ten", True))
        self.assertLess(paper.data["lineweight"], inner.data["lineweight"])
        f = self.plan.meta["sheet_frame"]
        self.assertEqual(paper.data["points"][0], [f[0], f[1]])
        self.assertEqual(paper.data["points"][2], [f[2], f[3]])

    def test_title_block_values_and_blank_fields(self):
        vals = {o.eid.split("/")[-1]: o.data["text"] for o in self.plan.ops_of(skill="10")
                if o.eid.startswith("10/khung_ten/gia_tri/")}
        self.assertEqual(vals["du_an"], self.store.project.name)
        self.assertEqual(vals["ban_ve"], "MẶT BẰNG TẦNG 1")
        self.assertEqual(vals["so_hieu"], "KT-01")
        self.assertEqual(vals["ty_le"], "1:100")
        self.assertEqual(vals["lan_sua"], "00")
        self.assertEqual(vals["trang_thai"], "CHỜ DUYỆT")
        # ProjectInfo không có người thiết kế / kiểm tra / ngày → để trống, không bịa
        for blank in ("thiet_ke", "kiem_tra", "ngay"):
            self.assertNotIn(blank, vals)
        labels = " ".join(o.data["text"] for o in self.plan.ops_of(skill="10")
                          if o.eid.startswith("10/khung_ten/nhan/"))
        for lab in ("THIẾT KẾ", "KIỂM TRA", "TỶ LỆ", "SỐ HIỆU", "LẦN SỬA", "NGÀY", "TRẠNG THÁI"):
            self.assertIn(lab, labels)
        self.assertTrue(any("để trống" in n for n in self.r10.notes))

    def test_drawing_title_under_content(self):
        by = {o.eid: o for o in self.plan.ops_of(skill="10")}
        title, sc = by["10/khung_ten/ten_ban_ve"], by["10/khung_ten/ty_le"]
        self.assertEqual(title.data["text"], "MẶT BẰNG TẦNG 1")
        self.assertEqual(title.data["height"], text_height("tieu_de", 100))
        self.assertEqual(sc.data["text"], "TỶ LỆ 1:100")
        bb = content_bbox(self.plan)
        self.assertAlmostEqual(title.data["insert"][0], (bb[0] + bb[2]) / 2.0)
        self.assertAlmostEqual(sc.data["insert"][0], title.data["insert"][0])
        self.assertLess(title.data["insert"][1], bb[1])
        self.assertLess(sc.data["insert"][1], title.data["insert"][1])

    def test_no_typed_status_words_and_ownership(self):
        for o in texts_of(self.plan):
            for pat in FORBIDDEN:
                self.assertIsNone(pat.search(o.data["text"]), (o.eid, o.data["text"]))
        for n in self.r10.notes:
            for pat in FORBIDDEN:
                self.assertIsNone(pat.search(n), n)
        self.assertEqual(self.plan.ownership_violations(), [])
        self.assertEqual({o.role for o in self.plan.ops_of(skill="10")} - set(roles_of("10")), set())

    def test_rerun_does_not_duplicate(self):
        fp, n, frame = self.plan.fingerprint("10"), len(self.plan.ops), list(self.plan.meta["sheet_frame"])
        KiemTraXuatSkill().run(self.store, self.plan)
        self.assertEqual(len(self.plan.ops), n)
        self.assertEqual(self.plan.fingerprint("10"), fp)
        self.assertEqual(self.plan.meta["sheet_frame"], frame)
        self.assertEqual(self.plan.ops_of(role="kiem_tra"), [])      # dữ liệu đủ, đã xác nhận → không có dấu

    def test_interpolated_values_status_and_markers(self):
        store = load_sample()
        store.set_value("axes:V.spans[1]", 3600, Provenance.interpolated("nội suy thử"))
        store.set_value("openings:CD1.width", 1600, Provenance.interpolated("nội suy thử"))
        plan, _, r10 = run_08_10(store)
        vals = {o.eid: o.data["text"] for o in texts_of(plan)}
        status = vals["10/khung_ten/gia_tri/trang_thai"]
        self.assertTrue(status.startswith("CHỜ XÁC NHẬN") and "NỘI SUY" in status, status)
        self.assertEqual(status, "CHỜ XÁC NHẬN 2 SỐ LIỆU NỘI SUY")
        by = {o.eid: o for o in plan.ops_of(role="kiem_tra")}
        span = by["10/kiem_tra/axes:V.spans[1]/vong"]
        self.assertEqual(span.kind, "circle")
        self.assertEqual(span.data["r"], paper_to_model(4.0, 100))
        # trung điểm trục 2–3 trên đường kích thước cấp 2 phía dưới
        self.assertEqual(span.data["center"], [5400.0, -LAYOUT_PAPER_MM["dim_level_2"] * 100.0])
        self.assertEqual(by["10/kiem_tra/axes:V.spans[1]/chu"].data["text"],
                         "NỘI SUY – CHƯA XÁC NHẬN: axes:V.spans[1]")
        door = by["10/kiem_tra/openings:CD1.width/vong"]
        self.assertEqual(door.data["center"], [1800.0, 0.0])        # trung điểm ô cửa CD1
        self.assertEqual(len(by), 4)

    def test_missing_values_status_and_markers(self):
        store = load_sample(filled=False)
        plan, r8, r10 = run_08_10(store)
        vals = {o.eid: o.data["text"] for o in texts_of(plan)}
        self.assertEqual(vals["10/khung_ten/gia_tri/trang_thai"], "THIẾU 2 KÍCH THƯỚC")
        by = {o.eid: o for o in plan.ops_of(role="kiem_tra")}
        # nhịp 2–3 thiếu: trục 2 có toạ độ → dấu ngay sau trục 2 trên đường kích thước cấp 2 phía dưới
        span = by["10/kiem_tra/axes:V.spans[1]/vong"]
        self.assertGreater(span.data["center"][0], 3600.0)
        self.assertEqual(span.data["center"][1], -2000.0)
        self.assertEqual(by["10/kiem_tra/axes:V.spans[1]/chu"].data["text"], "THIẾU: axes:V.spans[1]")
        # CD4 nằm trên tường W8 (trục 3 chưa có toạ độ) → không định vị được → liệt kê trong mtext ở góc khung
        lst = by["10/kiem_tra/thieu_chua_dinh_vi"]
        self.assertEqual(lst.kind, "mtext")
        self.assertIn("THIẾU: openings:CD4.width", lst.data["text"])
        f = plan.meta["sheet_frame"]
        x, y = lst.data["insert"]
        self.assertTrue(f[0] <= x <= f[2] and f[1] <= y <= f[3])
        self.assertNotIn("khung_ban_ve", skipped_map(r10))

    def test_approved_status(self):
        store = load_sample()
        store.approve("KS_KIEM_TRA_MAU", "2026-10-24")
        plan, _, _ = run_08_10(store)
        vals = {o.eid: o.data["text"] for o in texts_of(plan)}
        self.assertEqual(vals["10/khung_ten/gia_tri/trang_thai"], "ĐÃ DUYỆT (KS_KIEM_TRA_MAU)")

    def test_status_text_is_computed(self):
        self.assertEqual(status_text({"trang_thai": "THIEU_KICH_THUOC", "so_lieu_thieu": 3,
                                      "noi_suy_chua_xac_nhan": 1}),
                         "THIẾU 3 KÍCH THƯỚC + 1 SỐ LIỆU NỘI SUY CHƯA XÁC NHẬN")
        self.assertEqual(status_text({"trang_thai": "CHO_DUYET", "so_lieu_thieu": 0, "noi_suy_chua_xac_nhan": 0}),
                         "CHỜ DUYỆT")

    def test_content_larger_than_sheet_is_skipped_but_frame_drawn(self):
        store = load_sample()
        plan = new_plan(store)
        plan.add("line", "truc", "01", "01/gia/rat_dai", p1=(0.0, 0.0), p2=(100000.0, 0.0))
        r = KiemTraXuatSkill().run(store, plan)
        sk = skipped_map(r)
        self.assertIn("khung_ban_ve", sk)
        self.assertIn("nội dung vượt khổ A3 ở tỷ lệ 1:100", sk["khung_ban_ve"])
        self.assertTrue(any("vượt khổ" in n for n in r.notes))
        f = plan.meta["sheet_frame"]
        self.assertEqual((f[2] - f[0], f[3] - f[1]), (42000.0, 29700.0))
        self.assertTrue(any(o.eid == "10/khung_ten/vien_giay" for o in plan.ops))

    def test_unknown_sheet_size_is_skipped(self):
        store = load_sample()
        store.project.sheet = "A0"
        plan = new_plan(store)
        plan.meta["sheet_frame"] = [0, 0, 1, 1]                  # khung cũ phải bị bỏ, không để lại số liệu cũ
        fake_content(plan)
        r = KiemTraXuatSkill().run(store, plan)
        self.assertIn("khung_ban_ve", skipped_map(r))
        self.assertNotIn("sheet_frame", plan.meta)
        self.assertFalse(any(o.eid == "10/khung_ten/vien_giay" for o in plan.ops))
        self.assertTrue(any(o.eid == "10/khung_ten/ty_le" for o in plan.ops))
        self.assertNotIn("A0", SHEET_SIZES_MM)

    def test_empty_plan_is_reported(self):
        store = load_sample()
        plan = new_plan(store)
        r = KiemTraXuatSkill().run(store, plan)
        self.assertIn("khung_ban_ve", skipped_map(r))

    def test_validator_issue_markers(self):
        store = load_sample()
        plan = new_plan(store)
        fake_content(plan)
        plan.meta["validator_issues"] = [
            {"severity": "LOI", "code": "VA_CHAM", "message": "thử", "skill": "VAL", "eids": [], "where": [500.0, 600.0]},
            {"severity": "LOI", "code": "VA_CHAM", "message": "trùng", "skill": "VAL", "eids": [], "where": [500.0, 600.0]},
        ]
        KiemTraXuatSkill().run(store, plan)
        by = {o.eid: o for o in plan.ops_of(role="kiem_tra")}
        self.assertEqual(by["10/kiem_tra/val/0/vong"].data["center"], [500.0, 600.0])
        self.assertEqual(by["10/kiem_tra/val/0/chu"].data["text"], "LỖI: VA_CHAM")
        self.assertNotIn("10/kiem_tra/val/1/vong", by)


class IntegrationWithAvailableSkillsTest(unittest.TestCase):
    """Chạy các skill 01..09 đã nạp được (skill đang viết song song thì bỏ qua) + 08 + 10 trên đề bài mẫu."""

    def test_available_skills_fit_a3(self):
        store = load_sample()
        plan = new_plan(store)
        ran = []
        for code in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
            try:
                cls = skill_class(code)
            except ImportError:
                continue
            cls().run(store, plan)
            ran.append(code)
        self.assertIn("08", ran)
        r10 = KiemTraXuatSkill().run(store, plan)
        self.assertNotIn("khung_ban_ve", skipped_map(r10), r10.skipped)
        f = plan.meta["sheet_frame"]
        for o in plan.ops:
            for x, y in iter_points(o):
                self.assertTrue(f[0] <= x <= f[2] and f[1] <= y <= f[3], (o.eid, x, y))
        self.assertEqual(plan.ownership_violations(), [])


if __name__ == "__main__":
    unittest.main()
