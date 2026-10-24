# -*- coding: utf-8 -*-
"""
Hồi quy cho các lỗi vòng review độc lập của agent dựng CAD (Validator, Master, bộ xuất) — mỗi test tái hiện một kịch
bản "bản vẽ sai mà vẫn báo đạt" hoặc "bỏ dữ liệu im lặng" đã được phát hiện, và khẳng định nay đã bị bắt.
"""

import json
import os
import shutil
import tempfile
import unittest

from tools.cad_drafting import validator
from tools.cad_drafting.master import CadDraftingMaster
from tools.cad_drafting.plan import BlockDef, DrawingPlan
from tools.cad_drafting.render_dxf import render_dxf
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan
from tools.cad_drafting.store import SEV_ERROR, Furniture, Wall


def _quiet(*_a, **_k):
    pass


def _codes(issues):
    return [i.code for i in issues]


class ValidatorReviewTest(unittest.TestCase):
    def _plan_with_block(self, store, name, size):
        plan = new_plan(store)
        plan.add_block(BlockDef(name=name, ops=[{"kind": "line", "data": {"p1": [0, 0], "p2": list(size)}}],
                                size=list(size)))
        return plan

    def test_furniture_inside_window_opening_is_a_clash(self):
        """Ô cửa sổ không phải chỗ trống cho đồ đạc: tủ cắm vào chiều dày tường tại ô cửa sổ CS1 phải bị bắt."""
        store = load_sample()
        store.furniture.append(Furniture(id="FX", block="HOP", insert=[8500, -50], rotation=0.0, room_id="P2"))
        plan = self._plan_with_block(store, "HOP", (600, 400))
        issues = validator.check_step(store, plan, "06", plan.fingerprints())
        hits = [i for i in issues if i.code == "NOI_THAT_XUNG_DOT" and "FX" in i.eids]
        self.assertTrue(hits, _codes(issues))
        self.assertEqual(hits[0].severity, SEV_ERROR)

    def test_parallel_walls_offset_by_a_few_mm_are_duplicates(self):
        store = load_sample()
        store.walls.append(Wall(id="W1B", start="1/A@0,5", end="4/A@0,5", thickness=220))
        plan = new_plan(store)
        issues = validator.check_step(store, plan, "03", plan.fingerprints())
        self.assertIn("TUONG_CHONG_THAN", _codes(issues))

    def test_landing_into_wall_is_reported(self):
        store = load_sample()
        # chiếu nghỉ x 3300–3900, y 7760–8045 đè tường W7 (x 3545–3655)
        store.stairs[0].landings = [["2/B@-300,3560", "2/B@300,3560", "2/B@300,3845", "2/B@-300,3845"]]
        plan = new_plan(store)
        issues = validator.check_step(store, plan, "05", plan.fingerprints())
        self.assertTrue([i for i in issues if i.code == "THANG_DAM_TUONG" and "chiếu nghỉ" in i.message.lower()],
                        _codes(issues))

    def test_summarize_matches_master_rule(self):
        store = load_sample()
        store.get("furniture", "F8").block = "KHONG_CO"
        rep = CadDraftingMaster(log=_quiet).run(store, tempfile.mkdtemp(prefix="cad_rv_"), pdf=False)
        self.assertEqual(validator.summarize(rep.all_issues())["dat"], rep.dat)
        self.assertFalse(rep.dat)


class MasterReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_rv_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tampered_plan_is_redrawn_not_kept(self):
        """Lệnh vẽ lần trước bị sửa tay (mất hết cầu thang) → chế độ cập nhật phải chạy lại skill 05, không giữ nguyên."""
        master = CadDraftingMaster(log=_quiet)
        master.run(load_sample(), self.tmp, pdf=False)
        path = os.path.join(self.tmp, "KT-01_lenh_ve.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["ops"] = [o for o in d["ops"] if o["skill"] != "05"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        rep = master.run(load_sample(), self.tmp, cap_nhat=True, pdf=False)
        self.assertIn("05", rep.rerun)
        self.assertGreater(len(DrawingPlan.load(path).ops_of(skill="05")), 0)

    def test_report_saves_fingerprints(self):
        CadDraftingMaster(log=_quiet).run(load_sample(), self.tmp, pdf=False)
        with open(os.path.join(self.tmp, "KT-01_bao_cao_kiem_tra.json"), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(sorted(rep["dau_van_tay"]), [f"{i:02d}" for i in range(1, 11)])

    def test_only_mode_keeps_dimstyles_of_kept_dimensions(self):
        """Đổi tỷ lệ rồi chỉ chạy lại skill 01: kích thước cũ vẫn phải xuất bằng đúng kiểu của nó, không rơi về Standard."""
        master = CadDraftingMaster(log=_quiet)
        master.run(load_sample(), self.tmp, pdf=False)
        store = load_sample()
        store.project.scale = 50
        rep = master.run(store, self.tmp, only=["01"], pdf=False)
        self.assertFalse([i for i in rep.export_issues if i.code in ("XUAT_DXF_BO_QUA", "XUAT_DXF_LECH")],
                         [i.message for i in rep.export_issues])


class MasterPrinciplesReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_rv_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cli(self, argv):
        import contextlib
        import io
        from tools.cad_drafting.__main__ import main
        with contextlib.redirect_stdout(io.StringIO()):
            return main(argv)

    def _texts10(self, out, base="KT-01"):
        plan = DrawingPlan.load(os.path.join(out, f"{base}_lenh_ve.json"))
        return " ".join(o.data["text"] for o in plan.ops_of(skill="10") if o.kind == "text")

    def test_approval_refused_when_not_passed_and_title_block_follows_approval(self):
        from tools.cad_drafting.sample import SAMPLE_SPEC
        a = os.path.join(self.tmp, "a")
        self.assertEqual(self._cli(["--dau-vao", SAMPLE_SPEC, "--noi-suy", "--ra", a, "--khong-pdf",
                                    "--duyet", "KS A", "--ngay", "2026-10-24"]), 2)
        self.assertNotIn("ĐÃ DUYỆT", self._texts10(a))
        nhap = os.path.join(self.tmp, "nhap.json")
        with open(nhap, "w", encoding="utf-8") as f:
            json.dump({"nguon": "[Trang 1] KT-01", "gia_tri": {"axes:V.spans[1]": 3600, "openings:CD4.width": 900}}, f)
        b = os.path.join(self.tmp, "b")
        self.assertEqual(self._cli(["--dau-vao", SAMPLE_SPEC, "--kich-thuoc-nhap", nhap, "--ra", b, "--khong-pdf",
                                    "--duyet", "KS A", "--ngay", "2026-10-24"]), 0)
        self.assertIn("ĐÃ DUYỆT (KS A)", self._texts10(b))

    def test_layer_roles_file_reaches_reader(self):
        """--vai-tro-layer: khai báo layer cố ý bỏ qua → không còn NGHI_VAN "layer lạ" cho layer đó."""
        import ezdxf
        src = os.path.join(self.tmp, "nguon.dxf")
        doc = ezdxf.new("R2018", units=4)
        doc.layers.add("NOI_THAT_KHAC")
        doc.modelspace().add_lwpolyline([(0, 0), (500, 0), (500, 500), (0, 500)], close=True,
                                        dxfattribs={"layer": "NOI_THAT_KHAC"})
        doc.saveas(src)
        roles = os.path.join(self.tmp, "vai_tro.json")
        with open(roles, "w", encoding="utf-8") as f:
            json.dump({"bo_qua": "noi.?that"}, f)
        out1, out2 = os.path.join(self.tmp, "o1"), os.path.join(self.tmp, "o2")
        self._cli(["--dau-vao", src, "--ra", out1, "--khong-pdf"])
        self._cli(["--dau-vao", src, "--ra", out2, "--khong-pdf", "--vai-tro-layer", roles])

        def doubts(out):
            with open(os.path.join(out, "BAN_VE_bao_cao_kiem_tra.json"), encoding="utf-8") as f:
                rep = json.load(f)
            return [i["code"] for i in rep["kiem_tra_truoc_khi_ve"] if i["severity"] == "NGHI_VAN"]
        self.assertIn("LAYER_KHONG_NHAN_DIEN", doubts(out1))
        self.assertNotIn("LAYER_KHONG_NHAN_DIEN", doubts(out2))

    def test_invalid_only_codes_rejected(self):
        from tools.cad_drafting.sample import SAMPLE_SPEC
        self.assertEqual(self._cli(["--dau-vao", SAMPLE_SPEC, "--ra", self.tmp, "--chi-chay", "O5"]), 1)

    def test_drawing_number_with_slash_does_not_crash(self):
        store = load_sample()
        store.project.drawing_no = "KT/01"
        rep = CadDraftingMaster(log=_quiet).run(store, self.tmp, pdf=False)
        self.assertEqual(rep.base, "KT_01")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "KT_01.dxf")))

    def test_stop_on_error_lists_skills_not_run(self):
        store = load_sample()
        store.columns.append(store.columns[0].__class__(id="C-DUP", axis_v="1", axis_h="A", b=220, h=220))
        rep = CadDraftingMaster(stop_on_error=True, log=_quiet).run(store, self.tmp, pdf=False)
        not_run = [i for s in rep.steps for i in s.issues if i.code == "BUOC_CHUA_CHAY"]
        self.assertEqual(len(not_run), 8, "dừng sau skill 02 (cột chồng cột) → 03..10 phải được báo chưa chạy")
        self.assertFalse(rep.dat)

    def test_old_reader_issues_are_not_reloaded(self):
        from tools.cad_drafting.store import Issue, ProjectStore
        store = load_sample()
        store.issues.append(Issue(severity=SEV_ERROR, code="LOI_CU", message="lỗi của lần đọc trước", skill="00"))
        path = os.path.join(self.tmp, "du_lieu.json")
        store.save(path)
        self.assertEqual(ProjectStore.load(path).issues, [])

    def test_interpolation_table_and_confirm_cover_entity_level_keys(self):
        from tools.cad_drafting.store import Provenance
        store = load_sample()
        store.get("furniture", "F1").prov = Provenance.interpolated("vị trí ước lượng")
        rep = CadDraftingMaster(log=_quiet).run(store, self.tmp, pdf=False)
        with open(os.path.join(self.tmp, "KT-01_BAO_CAO_KIEM_TRA.md"), encoding="utf-8") as f:
            self.assertIn("`furniture:F1`", f.read())
        self.assertFalse(rep.dat)
        store.confirm("furniture:F1", "KS A")
        self.assertEqual(store.unconfirmed(), [])

    def test_update_run_places_labels_like_a_full_run(self):
        master = CadDraftingMaster(log=_quiet)
        full = os.path.join(self.tmp, "full")
        upd = os.path.join(self.tmp, "upd")
        store = load_sample()
        store.get("rooms", "P1").wall_finish = "Sơn 2 lớp"
        master.run(store, full, pdf=False)
        master.run(load_sample(), upd, pdf=False)
        master.run(store, upd, cap_nhat=True, pdf=False)
        fp = lambda d: DrawingPlan.load(os.path.join(d, "KT-01_lenh_ve.json")).fingerprint("09")
        self.assertEqual(fp(full), fp(upd))


class DeterminismTest(unittest.TestCase):
    def test_two_runs_give_identical_plan_data_lisp_and_report(self):
        tmp = tempfile.mkdtemp(prefix="cad_det_")
        try:
            outs = []
            for i in (1, 2):
                out = os.path.join(tmp, str(i))
                CadDraftingMaster(log=_quiet).run(load_sample(), out, pdf=False)
                outs.append(out)
            for name in ("KT-01_lenh_ve.json", "KT-01_du_lieu_du_an.json", "KT-01.lsp",
                         "KT-01_bao_cao_kiem_tra.json", "KT-01_BAO_CAO_KIEM_TRA.md"):
                with open(os.path.join(outs[0], name), "rb") as a, open(os.path.join(outs[1], name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RendererReviewTest(unittest.TestCase):
    def test_missing_dimstyle_is_skipped_not_drawn_as_standard(self):
        store = load_sample()
        plan = new_plan(store)
        plan.add("dim_linear", "dim", "08", "08/x", p1=[0, 0], p2=[3600, 0], base=[0, -1000], angle=0,
                 dimstyle="KHONG_CO")
        tmp = tempfile.mkdtemp(prefix="cad_rv_")
        try:
            summary = render_dxf(plan, os.path.join(tmp, "x.dxf"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual([b["id"] for b in summary["bo_qua"]], ["08/x"])
        self.assertEqual(summary["da_ve"], 0)


if __name__ == "__main__":
    unittest.main()
