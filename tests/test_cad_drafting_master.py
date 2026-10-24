# -*- coding: utf-8 -*-
"""
Test Master Agent dựng CAD (tools/cad_drafting/master.py) — chạy trọn đề bài mẫu từ Skill 00 tới xuất file.

Bảo đảm các nguyên tắc của sơ đồ "đọc 1 lần → dữ liệu chung → vẽ theo skill → kiểm tra liên tục":
  - nội suy (phương án B) không bao giờ được coi là đã xác nhận → kết luận CHƯA ĐẠT, khung tên ghi trạng thái;
  - nhập tay + xác nhận (phương án A) → đạt kiểm tra tự động, vẫn "chờ kỹ sư duyệt";
  - chạy cập nhật chỉ chạy lại skill có dữ liệu đầu vào đổi, Op của skill khác giữ nguyên;
  - DXF đọc lại khớp danh sách lệnh vẽ.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from tools.cad_drafting import reader
from tools.cad_drafting.__main__ import main as cli_main
from tools.cad_drafting.master import CadDraftingMaster, REPORT_JSON, REPORT_MD, _dedupe
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.sample import SAMPLE_SPEC, load_sample
from tools.cad_drafting.store import SEV_DOUBT, SEV_ERROR

FORBIDDEN_STATUS_WORDS = ("Hợp lệ", "OPTIMAL", "HOÀN TẤT", "100%")


def _quiet(*_args, **_kw):
    pass


class MasterEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cad_master_")
        # B. nội suy: nhịp 2–3 và bề rộng CD4 được nội suy, chưa xác nhận
        cls.store_b = load_sample(filled=False)
        cls.interp = reader.interpolate_missing(cls.store_b)
        cls.out_b = os.path.join(cls.tmp, "noi_suy")
        cls.report_b = CadDraftingMaster(log=_quiet).run(cls.store_b, cls.out_b, interpolations=cls.interp)
        # A. người dùng nhập đủ
        cls.store_a = load_sample(filled=True)
        cls.out_a = os.path.join(cls.tmp, "nhap_tay")
        cls.report_a = CadDraftingMaster(log=_quiet).run(cls.store_a, cls.out_a)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_interpolated_values_are_never_confirmed(self):
        keys = {k for k, _ in self.store_b.unconfirmed()}
        self.assertEqual(keys, {"axes:V.spans[1]", "openings:CD4.width"})
        self.assertEqual(self.store_b.status()["trang_thai"], "CHO_XAC_NHAN_NOI_SUY")
        self.assertFalse(self.report_b.dat)
        self.assertGreater(self.report_b.counts()[SEV_DOUBT], 0)
        self.assertTrue(self.report_b.ket_luan().startswith("CHƯA ĐẠT"))

    def test_title_block_shows_computed_status(self):
        plan = DrawingPlan.load(os.path.join(self.out_b, "KT-01_lenh_ve.json"))
        texts = " ".join(o.data["text"] for o in plan.ops_of(skill="10") if o.kind in ("text", "mtext"))
        self.assertIn("NỘI SUY", texts.upper())
        markers = [o for o in plan.ops_of(role="kiem_tra")]
        self.assertGreaterEqual(len(markers), 2, "phải đánh dấu vị trí số liệu nội suy trên layer kiểm tra")

    def test_full_user_input_passes_automatic_checks(self):
        c = self.report_a.counts()
        self.assertEqual(c[SEV_ERROR], 0, [i.message for i in self.report_a.all_issues() if i.severity == SEV_ERROR])
        self.assertEqual(c[SEV_DOUBT], 0, [i.message for i in self.report_a.all_issues() if i.severity == SEV_DOUBT])
        self.assertEqual(c["doi_tuong_chua_ve"], 0)
        self.assertTrue(self.report_a.dat)
        self.assertEqual(self.report_a.ket_luan(), "ĐẠT KIỂM TRA TỰ ĐỘNG — CHỜ KỸ SƯ DUYỆT")

    def test_outputs_written(self):
        for name in ("KT-01.dxf", "KT-01.lsp", "KT-01_lenh_ve.json", "KT-01.pdf", "KT-01.png",
                     "KT-01_du_lieu_du_an.json", REPORT_JSON.format(base="KT-01"), REPORT_MD.format(base="KT-01")):
            self.assertTrue(os.path.isfile(os.path.join(self.out_a, name)), name)
        with open(os.path.join(self.out_a, REPORT_JSON.format(base="KT-01")), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["dau_ra"]["lisp"]["chay_tren_autocad"], "CHƯA chạy thử")
        self.assertEqual([s["code"] for s in rep["cac_buoc"]], [f"{i:02d}" for i in range(1, 11)])

    def test_dxf_matches_plan(self):
        issues = [i for i in self.report_a.export_issues if i.code == "XUAT_DXF_LECH"]
        self.assertEqual(issues, [])

    def test_every_skill_draws_something(self):
        for step in self.report_a.steps:
            self.assertGreater(step.ops, 0, f"skill {step.code} không vẽ gì")

    def test_report_has_no_typed_status_words(self):
        with open(os.path.join(self.out_b, REPORT_MD.format(base="KT-01")), encoding="utf-8") as f:
            md = f.read()
        for w in FORBIDDEN_STATUS_WORDS:
            self.assertNotIn(w, md)
        self.assertIn("axes:V.spans[1]", md)
        self.assertIn("Chưa làm / giới hạn", md)

    def test_store_saved_with_provenance(self):
        with open(os.path.join(self.out_b, "KT-01_du_lieu_du_an.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["axes"]["V"]["span_prov"][1]["source"], "noi_suy")
        self.assertFalse(d["axes"]["V"]["span_prov"][1]["confirmed"])


class MasterIncrementalTest(unittest.TestCase):
    """"Chỉ sửa phần liên quan": đổi dữ liệu nội thất → chỉ skill nội thất, hatch sàn (chừa vết đồ), nhãn phòng
    (tránh đồ) và khung tên chạy lại."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_update_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_reruns_only_affected_skills(self):
        store = load_sample()
        master = CadDraftingMaster(log=_quiet)
        master.run(store, self.tmp, pdf=False)
        before = DrawingPlan.load(os.path.join(self.tmp, "KT-01_lenh_ve.json")).fingerprints()

        store2 = load_sample()
        store2.get("furniture", "F4").insert = [1250, 2200]       # dời bàn trà 100 mm
        rep = master.run(store2, self.tmp, cap_nhat=True, pdf=False)
        self.assertEqual(sorted(rep.rerun), ["06", "07", "09", "10"])
        after = DrawingPlan.load(os.path.join(self.tmp, "KT-01_lenh_ve.json")).fingerprints()
        for code in before:
            if code in ("06", "07", "09", "10"):
                continue
            self.assertEqual(before[code], after[code], f"skill {code} không được đổi")
        self.assertNotEqual(before["06"], after["06"])
        self.assertFalse([i for s in rep.steps for i in s.issues if i.code == "SKILL_SUA_PHAN_KHAC"])

    def test_no_change_reruns_nothing(self):
        master = CadDraftingMaster(log=_quiet)
        master.run(load_sample(), self.tmp, pdf=False)
        rep = master.run(load_sample(), self.tmp, cap_nhat=True, pdf=False)
        self.assertEqual(rep.rerun, [])

    def test_only_mode_reruns_named_skill(self):
        master = CadDraftingMaster(log=_quiet)
        master.run(load_sample(), self.tmp, pdf=False)
        rep = master.run(load_sample(), self.tmp, only=["4"], pdf=False)
        self.assertEqual(sorted(rep.rerun), ["04", "10"])


def cli_main_quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return cli_main(argv)


class DxfInputTest(unittest.TestCase):
    """Đầu vào DXF: Skill 00 đọc → vẽ → xuất; và đọc ngược chính DXF đã xuất ra lại đúng lưới trục."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_dxf_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dxf_source_runs_end_to_end_and_reports_reader_issues(self):
        from tests.test_cad_drafting_reader import build_plan_dxf
        src = os.path.join(self.tmp, "nguon.dxf")
        build_plan_dxf(src)                          # có chữ ghi đè 7000 ≠ 7200 và một tam giác trên layer cột
        store = reader.load_inputs([src])
        rep = CadDraftingMaster(log=_quiet).run(store, os.path.join(self.tmp, "out"), pdf=False)
        codes = [i.code for i in rep.all_issues()]
        self.assertEqual(codes.count("DIM_GHI_DE"), 2, "Skill 00 và precheck cùng báo — báo cáo đếm 1 lần")
        self.assertEqual(sum(1 for i in rep.precheck if i.code == "DIM_GHI_DE"), 2)
        self.assertEqual(len([i for i in _dedupe(rep.all_issues()) if i.code == "DIM_GHI_DE"]), 1)
        self.assertFalse(rep.dat)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "out", "BAN_VE.dxf")))

    def test_round_trip_axes_from_own_output(self):
        out = os.path.join(self.tmp, "out")
        CadDraftingMaster(log=_quiet).run(load_sample(), out, pdf=False)
        back = reader.read_dxf(os.path.join(out, "KT-01.dxf"), role_patterns={
            "truc": r"^KT-TRUC", "tuong": r"^KT-TUONG$", "cot": r"^KC-COT$", "cua_di": r"^$", "cua_so": r"^$",
            "dim": r"^KT-DIM$"})
        self.assertEqual(back.axes["V"].names, ["1", "2", "3", "4"])
        self.assertEqual(back.axes["V"].spans, [3600.0, 3600.0, 3600.0])
        self.assertEqual(back.axes["H"].spans, [4200.0, 4200.0])
        self.assertEqual(len(back.columns), 12)
        self.assertNotIn("DIMLFAC_KHAC_1", [i.code for i in back.issues])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_cli_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_interpolation_returns_not_passed(self):
        code = cli_main_quiet(["--dau-vao", SAMPLE_SPEC, "--noi-suy", "--ra", self.tmp, "--khong-pdf"])
        self.assertEqual(code, 2)

    def test_cli_user_values_and_confirmation(self):
        nhap = os.path.join(self.tmp, "nhap.json")
        with open(nhap, "w", encoding="utf-8") as f:
            json.dump({"nguon": "giá trị kiểm thử", "gia_tri": {"axes:V.spans[1]": 3600, "openings:CD4.width": 900}}, f)
        code = cli_main_quiet(["--dau-vao", SAMPLE_SPEC, "--kich-thuoc-nhap", nhap, "--ra", self.tmp, "--khong-pdf"])
        self.assertEqual(code, 0)

    def test_cli_missing_file(self):
        self.assertEqual(cli_main_quiet(["--dau-vao", os.path.join(self.tmp, "khong_co.json"), "--ra", self.tmp]), 1)

    def test_cli_rejects_dwg(self):
        dwg = os.path.join(self.tmp, "ban_ve.dwg")
        with open(dwg, "wb") as f:
            f.write(b"AC1032")
        self.assertEqual(cli_main_quiet(["--dau-vao", dwg, "--ra", self.tmp]), 1)


if __name__ == "__main__":
    unittest.main()
