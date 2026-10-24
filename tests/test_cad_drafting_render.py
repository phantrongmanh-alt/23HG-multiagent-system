# -*- coding: utf-8 -*-
"""Test bộ xuất DXF / AutoLISP / PDF-PNG của agent dựng CAD mặt bằng (tools/cad_drafting/render_*.py).

Plan thử tự dựng bằng plan.add trên new_plan(load_sample()) — không phụ thuộc skill 01–10."""

import math
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import ezdxf
from ezdxf.lldxf import const

from tools.cad_drafting import render_dxf, render_lisp, render_preview
from tools.cad_drafting.layers import SHEET_SIZES_MM, dimstyle_name
from tools.cad_drafting.plan import BlockDef
from tools.cad_drafting.sample import load_sample
from tools.cad_drafting.skills import new_plan

A3 = SHEET_SIZES_MM["A3"]
PT_PER_MM = 72.0 / 25.4


def build_plan(filled=True):
    """Plan nhỏ đủ mọi loại Op: line, pline, circle, arc, text (tiếng Việt), mtext, insert + block,
    hatch có lỗ + hatch SOLID, dim_linear (có và không có text_override), đánh dấu trên KT-KIEM-TRA (không in)."""
    store = load_sample(filled=filled)
    plan = new_plan(store)
    ds = dimstyle_name(int(store.project.scale))
    plan.add_block(BlockDef(name="BAN_THU", size=[800, 600], description="Bàn thử", ops=[
        {"kind": "pline", "data": {"points": [[0, 0], [800, 0], [800, 600], [0, 600]], "closed": True}},
        {"kind": "line", "data": {"p1": [0, 0], "p2": [800, 600]}},
        {"kind": "circle", "data": {"center": [400, 300], "r": 100}},
        {"kind": "arc", "data": {"center": [400, 300], "r": 200, "start_angle": 0, "end_angle": 90}},
        {"kind": "text", "data": {"insert": [400, 300], "text": "BÀN", "height": 100, "rotation": 0,
                                  "align": "MIDDLE_CENTER"}},
    ]))
    plan.add("line", "truc", "01", "01/truc/V/1", p1=[0, -1500], p2=[0, 9900])
    plan.add("circle", "truc_kh", "01", "01/truc_kh/V/1/o", center=[0, -1900], r=400)
    plan.add("pline", "cot", "02", "02/C-1A", points=[[-110, -110], [110, -110], [110, 110], [-110, 110]], closed=True)
    plan.add("pline", "tuong", "03", "03/W1/outline/0", points=[[0, 0], [3600, 0], [3600, 220]], closed=False)
    plan.add("arc", "cua", "04", "04/D1/cung", center=[1000, 0], r=900, start_angle=0, end_angle=90)
    plan.add("text", "cua_kh", "04", "04/D1/ky_hieu", insert=[1450, -400], text="D1", height=200, rotation=0,
             align="CENTER")
    plan.add("line", "thang", "05", "05/ST1/bac/0", p1=[5000, 1000], p2=[6000, 1000], color=6, lineweight=35)
    plan.add("insert", "noi_that", "06", "06/noi_that/F1", block="BAN_THU", insert=[1000, 1000], rotation=90,
             scale=[1.0, 1.5])
    plan.add("hatch", "hatch", "07", "07/hatch/san/P1",
             boundaries=[[[0, 0], [3000, 0], [3000, 3000], [0, 3000]], [[1000, 1000], [2000, 1000], [2000, 2000],
                                                                        [1000, 2000]]],
             pattern="NET", pattern_scale=600 / 3.175, angle=0)
    plan.add("hatch", "hatch", "07", "07/hatch/cot/C-1A",
             boundaries=[[[-110, -110], [110, -110], [110, 110], [-110, 110]]], pattern="SOLID", pattern_scale=1.0,
             angle=0)
    plan.add("dim_linear", "dim", "08", "08/dim/L2/duoi/0", p1=[0, 0], p2=[3600, 0], base=[1800, -2000], angle=0,
             dimstyle=ds)
    plan.add("dim_linear", "dim", "08", "08/dim/L2/trai/0", p1=[0, 0], p2=[0, 4200], base=[-2000, 2100], angle=90,
             dimstyle=ds, text_override="4200 (đo lại)")
    plan.add("text", "hoan_thien", "09", "09/phong/R1/ten", insert=[1800, 2500], text="PHÒNG KHÁCH", height=300,
             rotation=0, align="MIDDLE_CENTER")
    plan.add("mtext", "hoan_thien", "09", "09/ghi_chu", insert=[4000, 3000], text="GHI CHÚ:\\PẠ \"trích\" \\ 1",
             height=200, width=3000, attach="TOP_LEFT")
    plan.add("pline", "khung_ten", "10", "10/khung", points=[[-7900, -13400], [34100, -13400], [34100, 16300],
                                                            [-7900, 16300]], closed=True)
    plan.add("circle", "kiem_tra", "10", "10/kiem_tra/0", center=[1800, 1500], r=500)
    return plan


def expected_by_layer(plan):
    out = {}
    for role, n in plan.count_by_role().items():
        name = plan.layer_name(role)
        out[name] = out.get(name, 0) + n
    return out


def write_png(path, size=(40, 30)):
    from PIL import Image
    Image.new("RGB", size, (200, 200, 200)).save(path)


def white_only(png_path):
    from PIL import Image
    with Image.open(png_path) as im:
        lo, hi = im.convert("L").getextrema()
    return lo >= 250


class RenderDxfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cad_render_")
        cls.plan = build_plan()
        write_png(os.path.join(cls.tmp, "nen.png"))
        cls.dxf = os.path.join(cls.tmp, "mat_bang.dxf")
        cls.underlays = [
            {"name": "nen.png", "kind": "anh", "underlay": {"insert": [-500, -500], "scale": 10.0}},
            {"name": "ban_ve.pdf", "kind": "pdf", "underlay": {"insert": [0, 0], "scale": 1.0, "page": 2}},
            {"name": "thieu_ty_le.png", "kind": "anh", "underlay": {"insert": [0, 0], "pixels": [10, 10]}},
        ]
        cls.summary = render_dxf.render_dxf(cls.plan, cls.dxf, underlays=cls.underlays)
        cls.doc = ezdxf.readfile(cls.dxf)
        cls.msp = cls.doc.modelspace()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def plan_entities(self):
        return [e for e in self.msp if e.dxf.layer != self.plan.layer_name("anh_nen")]

    def test_counts_match_plan(self):
        got = render_dxf.read_back_counts(self.dxf)
        exp = expected_by_layer(self.plan)
        for layer, n in exp.items():
            self.assertEqual(got.get(layer, 0), n, layer)
        self.assertEqual(self.summary["so_lenh"], len(self.plan.ops))
        self.assertEqual(self.summary["da_ve"], len(self.plan.ops))
        self.assertEqual(len(self.plan_entities()), len(self.plan.ops))
        self.assertEqual(self.summary["theo_layer"], got)
        kinds = {"line": "LINE", "pline": "LWPOLYLINE", "circle": "CIRCLE", "arc": "ARC", "text": "TEXT",
                 "mtext": "MTEXT", "insert": "INSERT", "hatch": "HATCH", "dim_linear": "DIMENSION"}
        for kind, dxftype in kinds.items():
            self.assertEqual(self.summary["theo_loai"].get(dxftype, 0), len(self.plan.ops_of(kind=kind)), kind)
        self.assertEqual(self.summary["theo_loai"].get("IMAGE", 0), 1)          # ảnh nền, ngoài plan

    def test_header_audit_layers(self):
        self.assertEqual(self.doc.header["$INSUNITS"], 4)
        self.assertEqual(self.doc.header["$MEASUREMENT"], 1)
        self.assertAlmostEqual(self.doc.header["$LTSCALE"], 100 * render_dxf.LTSCALE_FACTOR)
        self.assertEqual(self.summary["insunits"], 4)
        self.assertEqual(self.summary["audit_errors"], 0, self.summary["audit_chi_tiet"])
        self.assertEqual(self.doc.audit().has_errors, False)
        kt = self.doc.layers.get("KT-KIEM-TRA")
        self.assertEqual(kt.dxf.plot, 0)
        self.assertEqual(self.doc.layers.get("KT-TUONG").dxf.plot, 1)
        self.assertEqual(self.doc.layers.get("KT-TUONG").dxf.lineweight, 50)
        self.assertEqual(self.doc.layers.get("KT-TRUC").dxf.linetype, "CENTER")
        self.assertEqual(self.doc.layers.get("00-ANH-NEN").dxf.plot, 0)
        # kiểu đường theo độ dài acadiso.lin (CENTER = 31,75 / −6,35 / 6,35 / −6,35)
        lt = self.doc.linetypes.get("CENTER")
        lengths = [t.value for t in lt.pattern_tags.tags if t.code == 49]
        self.assertEqual([round(v, 3) for v in lengths], [31.75, -6.35, 6.35, -6.35])
        st = self.doc.styles.get("VN_ARIAL")
        self.assertEqual(st.dxf.font, "arial.ttf")

    def test_xdata_eid_on_every_entity(self):
        eids = set()
        for e in self.plan_entities():
            xd = e.get_xdata(render_dxf.APPID)
            self.assertEqual(len(xd), 2)
            eids.add(xd[0].value)
            op = next(o for o in self.plan.ops if o.eid == xd[0].value)
            self.assertEqual(xd[1].value, op.skill)
            self.assertEqual(e.dxf.layer, self.plan.layer_name(op.role))
        self.assertEqual(eids, {o.eid for o in self.plan.ops})

    def test_dimension_style_and_measurement(self):
        dims = list(self.msp.query("DIMENSION"))
        self.assertEqual(len(dims), 2)
        by_eid = {d.get_xdata(render_dxf.APPID)[0].value: d for d in dims}
        d0 = by_eid["08/dim/L2/duoi/0"]
        self.assertEqual(d0.dxf.dimstyle, "TCVN_KT_100")
        self.assertAlmostEqual(d0.get_measurement(), 3600.0, places=6)
        d1 = by_eid["08/dim/L2/trai/0"]
        self.assertAlmostEqual(d1.get_measurement(), 4200.0, places=6)
        self.assertEqual(d1.dxf.text, "4200 (đo lại)")
        ds = self.doc.dimstyles.get("TCVN_KT_100")
        self.assertEqual(ds.dxf.dimtad, 1)
        self.assertAlmostEqual(ds.dxf.dimtxt, 2.2)
        self.assertAlmostEqual(ds.dxf.dimscale, 100.0)
        self.assertEqual(ds.dxf.dimdec, 0)
        self.assertEqual(ds.dxf.get("dimtxsty"), "VN_ARIAL")
        self.assertEqual(ds.dxf.dimblk.upper().lstrip("_"), "ARCHTICK")
        self.assertIn("_ARCHTICK", [b.name.upper() for b in self.doc.blocks])

    def test_text_unicode_and_alignment(self):
        texts = {t.dxf.text: t for t in self.msp.query("TEXT")}
        self.assertIn("PHÒNG KHÁCH", texts)
        t = texts["PHÒNG KHÁCH"]
        self.assertEqual(t.dxf.style, "VN_ARIAL")
        self.assertEqual((t.dxf.halign, t.dxf.valign), (1, 2))
        self.assertEqual(tuple(round(v, 6) for v in t.dxf.align_point)[:2], (1800.0, 2500.0))
        self.assertEqual((texts["D1"].dxf.halign, texts["D1"].dxf.valign), (1, 0))
        mt = list(self.msp.query("MTEXT"))[0]
        self.assertEqual(mt.text, "GHI CHÚ:\\PẠ \"trích\" \\ 1")
        self.assertAlmostEqual(mt.dxf.char_height, 200.0)
        self.assertEqual(mt.dxf.attachment_point, 1)

    def test_hatch_with_hole_and_solid(self):
        hatches = {h.get_xdata(render_dxf.APPID)[0].value: h for h in self.msp.query("HATCH")}
        net = hatches["07/hatch/san/P1"]
        self.assertEqual(net.dxf.pattern_name, "NET")
        self.assertAlmostEqual(net.dxf.pattern_scale, 600 / 3.175, places=6)
        self.assertEqual(len(net.paths), 2)
        self.assertTrue(net.paths[0].path_type_flags & const.BOUNDARY_PATH_EXTERNAL)
        self.assertTrue(net.paths[0].path_type_flags & const.BOUNDARY_PATH_OUTERMOST)
        self.assertFalse(net.paths[1].path_type_flags & const.BOUNDARY_PATH_EXTERNAL)
        self.assertEqual(net.dxf.color, const.BYLAYER)
        solid = hatches["07/hatch/cot/C-1A"]
        self.assertEqual(solid.dxf.solid_fill, 1)
        self.assertEqual(solid.dxf.color, const.BYLAYER)

    def test_block_and_insert(self):
        self.assertIn("BAN_THU", self.doc.blocks)
        blk = self.doc.blocks.get("BAN_THU")
        self.assertEqual(sorted(e.dxftype() for e in blk), ["ARC", "CIRCLE", "LINE", "LWPOLYLINE", "TEXT"])
        self.assertTrue(all(e.dxf.layer == "0" for e in blk))
        ins = list(self.msp.query("INSERT"))[0]
        self.assertEqual(ins.dxf.name, "BAN_THU")
        self.assertAlmostEqual(ins.dxf.rotation, 90.0)
        self.assertAlmostEqual(ins.dxf.yscale, 1.5)
        line = [e for e in self.msp.query("LINE") if e.dxf.layer == "KT-THANG"][0]
        self.assertEqual((line.dxf.color, line.dxf.lineweight), (6, 35))

    def test_underlays_image_pdf_and_skipped(self):
        imgs = list(self.msp.query("IMAGE"))
        self.assertEqual(len(imgs), 1)
        img = imgs[0]
        self.assertEqual(img.dxf.layer, "00-ANH-NEN")
        self.assertEqual(img.image_def.dxf.filename, "nen.png")      # tên tương đối, không đường dẫn máy
        self.assertAlmostEqual(img.dxf.image_size.x, 40)
        sx, sy = img.dxf.u_pixel.magnitude * 40, img.dxf.v_pixel.magnitude * 30
        self.assertAlmostEqual(sx, 400.0, places=6)
        self.assertAlmostEqual(sy, 300.0, places=6)
        pdfs = list(self.msp.query("PDFUNDERLAY"))
        self.assertEqual(len(pdfs), 1)
        self.assertEqual(pdfs[0].get_underlay_def().dxf.filename, "ban_ve.pdf")
        self.assertEqual(pdfs[0].get_underlay_def().dxf.name, "2")
        skipped = {s["id"]: s["ly_do"] for s in self.summary["bo_qua"]}
        self.assertIn("anh_nen:thieu_ty_le.png", skipped)
        self.assertIn("scale", skipped["anh_nen:thieu_ty_le.png"])
        self.assertEqual([u["name"] for u in self.summary["underlays"]], ["nen.png", "ban_ve.pdf"])
        with open(self.dxf, "rb") as f:
            raw = f.read()
        self.assertNotIn(self.tmp.encode("utf-8"), raw)              # không ghi đường dẫn tuyệt đối

    def test_summary_is_json_serializable(self):
        import json
        json.dumps(self.summary, ensure_ascii=False)


class RenderDxfMissingDataTest(unittest.TestCase):
    """Dữ liệu thiếu / sai: không bỏ im lặng — vào "bo_qua", số đọc lại lệch để Master bắt được."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_render_miss_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unfilled_store_and_bad_ops_are_reported(self):
        plan = build_plan(filled=False)
        self.assertEqual(plan.meta["scale"], 100)
        plan.add("insert", "noi_that", "06", "06/noi_that/F_LA", block="KHONG_CO", insert=[0, 0], rotation=0,
                 scale=[1, 1])
        plan.add("hatch", "hatch", "07", "07/hatch/la", boundaries=[[[0, 0], [10, 0], [10, 10]]],
                 pattern="MAU_LA", pattern_scale=1.0, angle=0)
        path = os.path.join(self.tmp, "thieu.dxf")
        underlays = [{"name": "khong_scale.png", "kind": "anh", "underlay": {"insert": [0, 0]}},
                     {"name": "khong_insert.png", "kind": "anh", "underlay": {"scale": 1.0, "pixels": [5, 5]}},
                     {"name": "khong_file.png", "kind": "anh", "underlay": {"insert": [0, 0], "scale": 1.0}},
                     {"name": "x.tif", "kind": "dwg", "underlay": {"insert": [0, 0], "scale": 1.0}}]
        s = render_dxf.render_dxf(plan, path, underlays=underlays)
        skipped = {x["id"] for x in s["bo_qua"]}
        self.assertTrue({"06/noi_that/F_LA", "07/hatch/la", "anh_nen:khong_scale.png", "anh_nen:khong_insert.png",
                         "anh_nen:khong_file.png", "anh_nen:x.tif"} <= skipped)
        self.assertEqual(s["da_ve"], len(plan.ops) - 2)
        got = render_dxf.read_back_counts(path)
        exp = expected_by_layer(plan)
        self.assertEqual(got["KT-NOI-THAT"], exp["KT-NOI-THAT"] - 1)
        self.assertEqual(got["KT-HATCH"], exp["KT-HATCH"] - 1)
        self.assertEqual(s["audit_errors"], 0)
        self.assertNotIn("IMAGE", s["theo_loai"])

    def test_bad_layer_name_and_odd_attributes(self):
        plan = build_plan()
        plan.layers["kiem_tra"].name = "SAI<TEN>"
        plan.add("line", "thang", "05", "05/ST1/bac/la", p1=[0, 0], p2=[1, 1], lineweight=27, linetype="KHONG_CO")
        plan.add("text", "hoan_thien", "09", "09/hai_dong", insert=[0, 0], text="DÒNG 1\nDÒNG 2", height=200,
                 rotation=0, align="LEFT")
        path = os.path.join(self.tmp, "sai.dxf")
        s = render_dxf.render_dxf(plan, path)
        self.assertIn("10/kiem_tra/0", {x["id"] for x in s["bo_qua"]})
        joined = " ".join(s["canh_bao"])
        self.assertIn("SAI<TEN>", joined)
        self.assertIn("27", joined)
        self.assertIn("KHONG_CO", joined)
        self.assertIn("xuống dòng", joined)
        doc = ezdxf.readfile(path)
        line = [e for e in doc.modelspace().query("LINE") if e.get_xdata(render_dxf.APPID)[0].value == "05/ST1/bac/la"]
        self.assertEqual(line[0].dxf.lineweight, 25)
        txt = [e for e in doc.modelspace().query("TEXT") if e.dxf.text.startswith("DÒNG")][0]
        self.assertEqual(txt.dxf.text, "DÒNG 1 DÒNG 2")
        self.assertEqual(s["audit_errors"], 0)


class RenderLispTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cad_lisp_")
        cls.plan = build_plan()
        cls.path = os.path.join(cls.tmp, "mat_bang.lsp")
        cls.summary = render_lisp.render_lisp(cls.plan, cls.path)
        with open(cls.path, "rb") as f:
            cls.raw = f.read()
        cls.text = cls.raw.decode("ascii")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ascii_and_static_check(self):
        self.assertTrue(all(b < 128 for b in self.raw))
        self.assertEqual(render_lisp.lisp_static_check(self.text), [])
        self.assertEqual(self.summary["loi_cu_phap_tinh"], [])
        self.assertTrue(self.summary["thuan_ascii"])
        self.assertIn("CHUA chay thu tren AutoCAD", self.text)
        self.assertEqual(self.summary["so_lenh"], len(self.plan.ops))

    def test_vietnamese_as_unicode_escapes(self):
        self.assertIn('"PH\\U+00D2NG KH\\U+00C1CH"', self.text)
        self.assertIn("\\U+1EA0", self.text)                      # "Ạ" trong MTEXT
        self.assertIn('GHI CH\\U+00DA:\\\\P\\U+1EA0 \\"tr\\U+00EDch\\" \\\\ 1', self.text)
        self.assertIn('"4200 (\\U+0111o l\\U+1EA1i)"', self.text)

    def test_tables_and_entities(self):
        t = self.text
        self.assertIn("(defun C:23HG_VE", t)
        self.assertIn("(vl-load-com)", t)
        self.assertIn("vla-StartUndoMark", t)
        self.assertIn('"acadiso.lin"', t)
        self.assertIn('(regapp "23HG_CAD")', t)
        self.assertIn('(hg23:layer "KT-KIEM-TRA" 1 "Continuous" 25 nil', t)
        self.assertIn('(hg23:layer "KT-TRUC" 1 "CENTER" 18 T', t)
        self.assertIn('(hg23:style "VN_ARIAL" "arial.ttf")', t)
        self.assertIn('(hg23:dimstyle "TCVN_KT_100"', t)
        self.assertIn('("DIMBLK" . "_ARCHTICK")', t)
        self.assertIn('("DIMSCALE" . 100.0)', t)
        self.assertIn('("DIMTXSTY" . "VN_ARIAL")', t)
        self.assertIn('"_.-DIMSTYLE" "_Save"', t)
        self.assertIn("(entmake '((0 . \"BLOCK\") (2 . \"BAN_THU\")", t)
        self.assertIn("(entmake '((0 . \"ENDBLK\"))", t)
        self.assertIn("vla-AddDimRotated", t)
        self.assertIn("vla-AddHatch", t)
        self.assertIn("vla-AppendOuterLoop", t)
        self.assertIn("vla-AppendInnerLoop", t)
        self.assertIn("vla-put-TextOverride", t)
        self.assertIn("vla-put-StyleName", t)
        # mọi Op đều có mặt với eid + XDATA
        for op in self.plan.ops:
            self.assertIn(f'"{op.eid}"', t)
        self.assertEqual(t.count('(-3 ("23HG_CAD"'),
                         len([o for o in self.plan.ops if o.kind not in ("hatch", "dim_linear")]))
        self.assertEqual(t.count("'hg23:dim1"), 2)
        self.assertEqual(t.count("'hg23:hatch1"), 2)
        # dim đứng: góc 90° = π/2 radian
        self.assertIn(render_lisp._n(math.pi / 2, 12), t)
        self.assertIn("(72 . 1) (73 . 2)", t)                     # MIDDLE_CENTER
        self.assertIn("(71 . 1)", t)                              # MTEXT TOP_LEFT
        self.assertIn('(0 . "INSERT") (2 . "BAN_THU")', t)
        self.assertIn("(62 . 6)", t)
        self.assertIn("(370 . 35)", t)
        self.assertIn('(setvar "LTSCALE" 50.0)', t)

    def test_number_format(self):
        self.assertEqual(render_lisp._n(3600), "3600.0")
        self.assertEqual(render_lisp._n(-0.0000001), "0.0")
        self.assertEqual(render_lisp._n(1e12), "1000000000000.0")
        self.assertEqual(render_lisp._n(-12.5), "-12.5")
        self.assertNotIn("e", render_lisp._n(1e-9))

    def test_escape_and_comment(self):
        self.assertEqual(render_lisp.lisp_escape('a"b\\c'), 'a\\"b\\\\c')
        self.assertEqual(render_lisp.lisp_escape("Ạ"), "\\U+1EA0")
        self.assertEqual(render_lisp.lisp_escape("x\ty"), "x y")
        warn = []
        self.assertEqual(render_lisp.lisp_escape("\U0001F600", warn, "t"), "?")
        self.assertEqual(len(warn), 1)
        self.assertEqual(render_lisp.ascii_comment("ĐỒ ÁN Nhà ở"), "DO AN Nha o")

    def test_static_check_finds_errors(self):
        chk = render_lisp.lisp_static_check
        self.assertEqual(chk('(princ "a ( b ; c")\n; ) ) chú thích\n(setq x 1) ;| ) |;'), ["có 2 ký tự ngoài ASCII (dòng 2)"])
        self.assertEqual(chk('(princ "a ( b ; c")\n; ) ) chu thich\n(setq x 1) ;| ) |;'), [])
        self.assertTrue(any("thiếu 1" in p for p in chk("(defun f () (princ)")))
        self.assertTrue(any("thừa" in p for p in chk("(princ))")))
        self.assertTrue(any("chưa đóng" in p for p in chk('(princ "abc)')))
        self.assertTrue(any("escape lạ" in p for p in chk('(princ "a\\Pb")')))
        self.assertEqual(chk('(princ "\\\\P \\U+1EA0 \\n \\" \\101")'), [])
        self.assertTrue(any("ngoài ASCII" in p for p in chk('(princ "Ạ")')))
        self.assertTrue(any("xuống dòng" in p for p in chk('(princ "a\nb")')))

    def test_unfilled_store_plan(self):
        plan = build_plan(filled=False)
        path = os.path.join(self.tmp, "thieu.lsp")
        s = render_lisp.render_lisp(plan, path)
        plan.add("insert", "noi_that", "06", "06/noi_that/F_LA", block="KHONG_CO", insert=[0, 0], rotation=0,
                 scale=[1, 1])
        s2 = render_lisp.render_lisp(plan, path)
        self.assertEqual(s["loi_cu_phap_tinh"], [])
        self.assertTrue(any("KHONG_CO" in w for w in s2["canh_bao"]))
        self.assertEqual(s2["so_lenh"], len(plan.ops))


class RenderPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cad_preview_")
        cls.plan = build_plan()
        write_png(os.path.join(cls.tmp, "nen.png"))
        cls.dxf = os.path.join(cls.tmp, "mat_bang.dxf")
        render_dxf.render_dxf(cls.plan, cls.dxf, underlays=[
            {"name": "nen.png", "kind": "anh", "underlay": {"insert": [0, 0], "scale": 10.0}}])
        cls.frame = [-7900.0, -13400.0, 34100.0, 16300.0]          # A3 ở 1:100

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_pdf_a3_true_scale(self):
        out = os.path.join(self.tmp, "mat_bang.pdf")
        info = render_preview.render_preview(self.dxf, out, frame=self.frame, paper_mm=list(A3), dpi=72)
        self.assertTrue(os.path.getsize(out) > 0)
        with open(out, "rb") as f:
            raw = f.read()
        m = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", raw)
        self.assertIsNotNone(m)
        w_pt, h_pt = float(m.group(3)) - float(m.group(1)), float(m.group(4)) - float(m.group(2))
        self.assertAlmostEqual(w_pt / PT_PER_MM, A3[0], places=2)
        self.assertAlmostEqual(h_pt / PT_PER_MM, A3[1], places=2)
        self.assertTrue(info["dung_ty_le"])
        self.assertAlmostEqual(info["ty_le_in"], 100.0)
        self.assertEqual(info["paper_mm"], [420.0, 297.0])
        self.assertIn("KT-KIEM-TRA", info["an_layer"])
        self.assertIn("00-ANH-NEN", info["an_layer"])

    def test_png_size_and_fit_mode(self):
        out = os.path.join(self.tmp, "mat_bang.png")
        info = render_preview.render_preview(self.dxf, out, frame=self.frame, paper_mm=list(A3), dpi=50)
        from PIL import Image
        with Image.open(out) as im:
            size = im.size
        self.assertEqual(list(size), info["kich_thuoc_px"])
        self.assertLessEqual(abs(size[0] - 420 / 25.4 * 50), 1.0)
        self.assertLessEqual(abs(size[1] - 297 / 25.4 * 50), 1.0)
        self.assertFalse(white_only(out))
        fit = os.path.join(self.tmp, "vua.png")
        info2 = render_preview.render_preview(self.dxf, fit, dpi=40)
        self.assertTrue(os.path.exists(fit))
        self.assertFalse(info2["dung_ty_le"])
        self.assertIsNone(info2["ty_le_in"])
        # khung khác tỷ lệ với khổ giấy → không "đúng tỷ lệ", có cảnh báo
        info3 = render_preview.render_preview(self.dxf, os.path.join(self.tmp, "lech.png"),
                                              frame=[0, 0, 42000, 42000], paper_mm=list(A3), dpi=20)
        self.assertFalse(info3["dung_ty_le"])
        self.assertTrue(info3["canh_bao"])

    def test_hidden_layers_not_drawn(self):
        plan = new_plan(load_sample(filled=False))
        big = [[0, 0], [42000, 0], [42000, 29700], [0, 29700]]
        plan.add("hatch", "kiem_tra", "10", "10/kiem_tra/to", boundaries=[big], pattern="SOLID", pattern_scale=1,
                 angle=0)
        p1 = os.path.join(self.tmp, "an.dxf")
        render_dxf.render_dxf(plan, p1)
        png1 = os.path.join(self.tmp, "an.png")
        render_preview.render_preview(p1, png1, frame=[0, 0, 42000, 29700], paper_mm=list(A3), dpi=10)
        self.assertTrue(white_only(png1))                         # layer plot = 0 không vẽ
        png1b = os.path.join(self.tmp, "an_hien.png")
        info1b = render_preview.render_preview(p1, png1b, frame=[0, 0, 42000, 29700], paper_mm=list(A3), dpi=10,
                                               show_layers=["KT-KIEM-TRA"])
        self.assertFalse(white_only(png1b))                       # PNG soát lỗi: hiện lại layer không in
        self.assertNotIn("KT-KIEM-TRA", info1b["an_layer"])
        plan2 = new_plan(load_sample(filled=False))
        plan2.add("hatch", "hatch", "07", "07/hatch/to", boundaries=[big], pattern="SOLID", pattern_scale=1, angle=0)
        p2 = os.path.join(self.tmp, "hien.dxf")
        render_dxf.render_dxf(plan2, p2)
        png2 = os.path.join(self.tmp, "hien.png")
        render_preview.render_preview(p2, png2, frame=[0, 0, 42000, 29700], paper_mm=list(A3), dpi=10)
        self.assertFalse(white_only(png2))
        png3 = os.path.join(self.tmp, "hien_an.png")
        info = render_preview.render_preview(p2, png3, frame=[0, 0, 42000, 29700], paper_mm=list(A3), dpi=10,
                                             hide_layers=["KT-HATCH", "KHONG-CO"])
        self.assertTrue(white_only(png3))
        self.assertIn("KT-HATCH", info["an_layer"])
        self.assertTrue(any("KHONG-CO" in w for w in info["canh_bao"]))

    def test_bad_extension_and_missing_matplotlib(self):
        with self.assertRaises(ValueError):
            render_preview.render_preview(self.dxf, os.path.join(self.tmp, "x.svg"))
        with mock.patch.dict(sys.modules, {"matplotlib": None, "matplotlib.pyplot": None}):
            with self.assertRaises(render_preview.RenderUnavailable) as cm:
                render_preview.render_preview(self.dxf, os.path.join(self.tmp, "x.png"))
        self.assertIn("matplotlib", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
