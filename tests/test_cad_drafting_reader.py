# -*- coding: utf-8 -*-
"""
Test Skill 00 — đọc bản vẽ (tools/cad_drafting/reader.py).

Bản vẽ DXF dùng để thử được dựng bằng ezdxf trong thư mục tạm (không ghi vào repo); số liệu tự đặt:
  - 3 trục đứng 1, 2, 3 (x = 0, 3600, 7200) + 2 trục ngang A, B (y = 0, 4200), có vòng tròn + tên ở đầu trục;
  - 2 cột 220×220 (1/A đúng tâm, 2/B lệch +50 theo x) + 1 đường bao tam giác trên layer cột;
  - 2 tường dày 220 (cặp LINE) góc chữ L tại 3/A + 1 đường lẻ trên layer tường;
  - 1 cửa đi INSERT 900 trên tường trục A; 2 DIMENSION (tổng trục V ghi đè sai "7000", tổng trục H).
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest

import ezdxf
from ezdxf.enums import TextEntityAlignment

from tools.cad_drafting import geom, reader
from tools.cad_drafting.reader import ReaderError
from tools.cad_drafting.sample import SAMPLE_SPEC, load_sample
from tools.cad_drafting.skills.base import new_plan
from tools.cad_drafting.store import SEV_DOUBT, SEV_ERROR, SEV_WARN, SRC_DXF, SRC_INTERP, SRC_USER

R = 400.0          # bán kính vòng tròn tên trục
V_AXES = (("1", 0.0), ("2", 3600.0), ("3", 7200.0))
H_AXES = (("A", 0.0), ("B", 4200.0))


def _door_block(doc, name="CUA_900", width=900.0):
    blk = doc.blocks.new(name)
    blk.add_line((0, 0), (0, width))          # cánh mở 90°
    blk.add_arc((0, 0), width, 0, 90)         # cung mở
    return name


def build_plan_dxf(path, unnamed=(), insunits=4, override="7000", dimlfac=None):
    doc = ezdxf.new("R2010", units=4)
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    for name in ("TRUC", "COT", "TUONG", "CUA_DI", "DIM", "GHI_CHU"):
        doc.layers.add(name)
    for name, x in V_AXES:
        msp.add_line((x, -1500), (x, 5700), dxfattribs={"layer": "TRUC"})
        if name not in unnamed:
            msp.add_circle((x, 5700 + R), R, dxfattribs={"layer": "TRUC"})
            msp.add_text(name, height=350, dxfattribs={"layer": "TRUC"}).set_placement(
                (x, 5700 + R), align=TextEntityAlignment.MIDDLE_CENTER)
    for name, y in H_AXES:
        msp.add_line((-1500, y), (8700, y), dxfattribs={"layer": "TRUC"})
        if name not in unnamed:
            msp.add_circle((-1500 - R, y), R, dxfattribs={"layer": "TRUC"})
            msp.add_text(name, height=350, dxfattribs={"layer": "TRUC"}).set_placement(
                (-1500 - R, y), align=TextEntityAlignment.MIDDLE_CENTER)
    # cột
    msp.add_lwpolyline([(-110, -110), (110, -110), (110, 110), (-110, 110)], close=True, dxfattribs={"layer": "COT"})
    msp.add_lwpolyline([(3540, 4090), (3760, 4090), (3760, 4310), (3540, 4310)], close=True,
                       dxfattribs={"layer": "COT"})
    tri = msp.add_lwpolyline([(20000, 20000), (20300, 20000), (20150, 20300)], close=True, dxfattribs={"layer": "COT"})
    # tường 1 (trục A) và tường 2 (trục 3) — góc chữ L tại 3/A
    msp.add_line((0, -110), (7200, -110), dxfattribs={"layer": "TUONG"})
    msp.add_line((0, 110), (7200, 110), dxfattribs={"layer": "TUONG"})
    msp.add_line((7090, 110), (7090, 4200), dxfattribs={"layer": "TUONG"})
    msp.add_line((7310, 110), (7310, 4200), dxfattribs={"layer": "TUONG"})
    lone = msp.add_line((0, 10000), (1000, 10000), dxfattribs={"layer": "TUONG"})
    # cửa đi: bản lề tại mặt trong tường, x = 1000
    msp.add_blockref(_door_block(doc), (1000, 110), dxfattribs={"layer": "CUA_DI"})
    # kích thước
    if dimlfac is not None:
        doc.dimstyles.new("KT_CO_GIAN", dxfattribs={"dimlfac": dimlfac})
    style = "KT_CO_GIAN" if dimlfac is not None else "Standard"
    dv = msp.add_linear_dim(base=(0, -1300), p1=(0, -1200), p2=(7200, -1200), angle=0, text=override,
                            dimstyle=style, dxfattribs={"layer": "DIM"})
    dv.render()
    dh = msp.add_linear_dim(base=(-1300, 0), p1=(-1200, 0), p2=(-1200, 4200), angle=90, dimstyle=style,
                            dxfattribs={"layer": "DIM"})
    dh.render()
    msp.add_text("GHI CHU CHUNG", height=250, dxfattribs={"layer": "GHI_CHU", "insert": (0, -3000)})
    doc.saveas(path)
    return {"tri": tri.dxf.handle, "lone": lone.dxf.handle, "dim_v": dv.dimension.dxf.handle}


def build_gap_dxf(path):
    """Tường dày 220 trục y = 0 (x 0..5000), mặt tường ngắt ở ô cửa 1000..1900 (có INSERT cửa) và ở chỗ giao chữ T
    với tường dày 110 tại x = 3000 (lên tới y = 3000); các đầu tường có nét bịt. Thêm 1 cửa không nằm trên tường nào."""
    doc = ezdxf.new("R2010", units=4)
    msp = doc.modelspace()
    a = {"layer": "TUONG"}
    for x0, x1 in ((0, 1000), (1900, 5000)):
        msp.add_line((x0, -110), (x1, -110), dxfattribs=a)
    for x0, x1 in ((0, 1000), (1900, 2945), (3055, 5000)):
        msp.add_line((x0, 110), (x1, 110), dxfattribs=a)
    for x in (0, 1000, 1900, 5000):
        msp.add_line((x, -110), (x, 110), dxfattribs=a)                   # nét bịt đầu tường / mép ô cửa
    msp.add_line((2945, 110), (2945, 3000), dxfattribs=a)
    msp.add_line((3055, 110), (3055, 3000), dxfattribs=a)
    msp.add_line((2945, 3000), (3055, 3000), dxfattribs=a)
    blk = _door_block(doc)
    msp.add_blockref(blk, (1000, 110), dxfattribs={"layer": "CUA_DI"})
    far = msp.add_blockref(blk, (20000, 20000), dxfattribs={"layer": "CUA_DI"})
    doc.saveas(path)
    return {"far_door": far.dxf.handle}


def build_room_dxf(path):
    """Phòng 6000×4000 (tim trục), tường dày 220 vẽ bằng hai đa tuyến kín; vòng tròn trục là block có ATTRIB;
    cửa D900 lật gương trên trục A, cửa xoay 180° trên trục B; một nét cửa vẽ rời (không phải block);
    một kiểu kích thước DIMLFAC = 2 không ai dùng. Layer theo kiểu tiếng Anh (A-WALL, S-GRID, A-DOOR)."""
    doc = ezdxf.new("R2010", units=4)
    msp = doc.modelspace()
    t = 110
    msp.add_lwpolyline([(-t, -t), (6000 + t, -t), (6000 + t, 4000 + t), (-t, 4000 + t)], close=True,
                       dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline([(t, t), (6000 - t, t), (6000 - t, 4000 - t), (t, 4000 - t)], close=True,
                       dxfattribs={"layer": "A-WALL"})
    bubble = doc.blocks.new("AXIS_BUBBLE")
    bubble.add_circle((0, 0), R)
    bubble.add_attdef("NAME", (0, 0), dxfattribs={"height": 350})
    for name, x in (("1", 0), ("2", 6000)):
        msp.add_line((x, -1000), (x, 5000), dxfattribs={"layer": "S-GRID"})
        msp.add_blockref("AXIS_BUBBLE", (x, 5000 + R), dxfattribs={"layer": "S-GRID"}).add_auto_attribs({"NAME": name})
    for name, y in (("A", 0), ("B", 4000)):
        msp.add_line((-1000, y), (7000, y), dxfattribs={"layer": "S-GRID"})
        msp.add_blockref("AXIS_BUBBLE", (-1000 - R, y), dxfattribs={"layer": "S-GRID"}).add_auto_attribs({"NAME": name})
    door = _door_block(doc, "D900")
    msp.add_blockref(door, (2900, t), dxfattribs={"layer": "A-DOOR", "xscale": -1})       # bản lề ở mép cuối
    msp.add_blockref(door, (4000, 4000 - t), dxfattribs={"layer": "A-DOOR", "rotation": 180})
    loose = msp.add_line((500, 4000 - t), (500, 3000), dxfattribs={"layer": "A-DOOR"})
    doc.dimstyles.new("KHONG_DUNG", dxfattribs={"dimlfac": 2.0})
    doc.saveas(path)
    return {"loose": loose.dxf.handle}


def codes(store, severity=None):
    return [i.code for i in store.issues if severity is None or i.severity == severity]


def issue(store, code):
    found = [i for i in store.issues if i.code == code]
    return found[0] if found else None


class ReaderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cad_reader_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def write_json(self, name, data):
        p = self.path(name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return p


class ReadDxfTest(ReaderTestBase):
    def setUp(self):
        super().setUp()
        self.dxf = self.path("mat_bang.dxf")
        self.handles = build_plan_dxf(self.dxf)
        self.store = reader.read_dxf(self.dxf)

    def test_axes_names_spans_and_overall(self):
        v, h = self.store.axes["V"], self.store.axes["H"]
        self.assertEqual(v.names, ["1", "2", "3"])
        self.assertEqual(v.spans, [3600.0, 3600.0])
        self.assertEqual(v.origin, 0.0)
        self.assertEqual(h.names, ["A", "B"])
        self.assertEqual(h.spans, [4200.0])
        # tổng lấy theo SỐ ĐO hình học, không theo chữ ghi đè "7000"
        self.assertEqual(v.overall, 7200.0)
        self.assertEqual(h.overall, 4200.0)
        self.assertEqual(v.span_provenance(0).source, SRC_DXF)
        self.assertIn("LINE #", v.span_provenance(0).ref)
        self.assertIn("DIMENSION #", v.overall_prov.ref)
        self.assertNotIn("TRUC_CHUA_CO_TEN", codes(self.store))

    def test_columns(self):
        cols = {c.id: c for c in self.store.columns}
        self.assertEqual(sorted(cols), ["C-1A", "C-2B"])
        c1, c2 = cols["C-1A"], cols["C-2B"]
        self.assertEqual((c1.b, c1.h, c1.dx, c1.dy, c1.mark), (220.0, 220.0, 0.0, 0.0, ""))
        self.assertEqual((c2.axis_v, c2.axis_h, c2.b, c2.h, c2.dx, c2.dy), ("2", "B", 220.0, 220.0, 50.0, 0.0))
        self.assertEqual(c2.prov.source, SRC_DXF)
        self.assertEqual(self.store.column_center(c2), (3650.0, 4200.0))
        bad = issue(self.store, "COT_KHONG_PHAI_CHU_NHAT")
        self.assertIsNotNone(bad)
        self.assertEqual(bad.severity, SEV_DOUBT)
        self.assertEqual(bad.eids, [self.handles["tri"]])

    def test_walls_pairs_and_corner(self):
        walls = self.store.walls
        self.assertEqual(len(walls), 2)
        w1, w2 = walls
        self.assertEqual((w1.start, w1.end, w1.thickness), ([0.0, 0.0], [7200.0, 0.0], 220.0))
        # đầu tường 2 chạm mặt tường 1 → đưa về giao tim (7200, 0): góc chữ L khép kín
        self.assertEqual((w2.start, w2.end, w2.thickness), ([7200.0, 0.0], [7200.0, 4200.0], 220.0))
        self.assertEqual(w1.prov.source, SRC_DXF)
        self.assertIn("đưa về giao tim tường", w2.prov.ref)
        lone = issue(self.store, "TUONG_CHUA_GHEP_CAP")
        self.assertIsNotNone(lone)
        self.assertEqual(lone.severity, SEV_DOUBT)
        self.assertEqual(lone.eids, [self.handles["lone"]])
        self.assertEqual(issue(self.store, "TUONG_CHUA_RO_VAT_LIEU").severity, SEV_WARN)
        self.assertIsNotNone(geom.wall_polygon(self.store, w1))

    def test_door(self):
        self.assertEqual(len(self.store.openings), 1)
        op = self.store.openings[0]
        self.assertEqual((op.id, op.wall_id, op.kind), ("CD1", "W1", "cua_di"))
        self.assertEqual((op.offset, op.width), (1000.0, 900.0))
        self.assertEqual((op.leaves, op.hinge, op.opens_to), (1, "dau", "trai"))
        self.assertEqual(op.prov.source, SRC_DXF)
        self.assertIsNotNone(geom.opening_frame(self.store, op))

    def test_dimension_override_flagged(self):
        dims = {d.id: d for d in self.store.measured_dims}
        self.assertEqual(len(dims), 2)
        dv = dims[f"DIM-{self.handles['dim_v']}"]
        self.assertEqual((dv.p1, dv.p2, dv.measurement, dv.text), ([0.0, -1200.0], [7200.0, -1200.0], 7200.0, "7000"))
        flagged = [i for i in self.store.issues if i.code == "DIM_GHI_DE"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].severity, SEV_DOUBT)
        self.assertEqual(flagged[0].eids, [f"DIM-{self.handles['dim_v']}"])   # cùng mã với MeasuredDim (Validator)

    def test_every_entity_used_or_reported(self):
        self.assertIn("LAYER_KHONG_NHAN_DIEN", codes(self.store, SEV_WARN))      # chữ trên layer GHI_CHU
        self.assertNotIn("THUC_THE_CHUA_XU_LY", codes(self.store))                # mọi vòng tròn/chữ trục đã dùng
        self.assertTrue(all(i.skill == "00" for i in self.store.issues))
        src = self.store.sources[-1]
        self.assertEqual((src.name, src.kind, src.used_for), ("mat_bang.dxf", "dxf", "du_lieu"))
        with open(self.dxf, "rb") as f:
            self.assertEqual(src.sha256, hashlib.sha256(f.read()).hexdigest())

    def test_no_missing_and_deterministic(self):
        self.assertEqual(self.store.missing(), [])
        self.assertEqual(self.store.status()["trang_thai"], "CHO_DUYET")
        again = reader.read_dxf(self.dxf)
        self.assertEqual(again.to_dict(), self.store.to_dict())
        new_plan(self.store)                                    # layer mặc định đủ để lập plan

    def test_unnamed_axis_gets_temporary_name(self):
        p = self.path("khong_ten.dxf")
        build_plan_dxf(p, unnamed=("2",))
        st = reader.read_dxf(p)
        self.assertEqual(st.axes["V"].names, ["1", "?1", "3"])
        doubt = [i for i in st.issues if i.code == "TRUC_CHUA_CO_TEN"]
        self.assertEqual(len(doubt), 1)
        self.assertEqual(doubt[0].severity, SEV_DOUBT)
        self.assertIn("'?1'", doubt[0].message)
        self.assertIn("C-?1B", [c.id for c in st.columns])

    def test_units_and_dimlfac_warnings(self):
        p = self.path("don_vi.dxf")
        build_plan_dxf(p, insunits=0, dimlfac=0.8)
        st = reader.read_dxf(p)
        self.assertIn("DON_VI_KHONG_KHAI_BAO", codes(st, SEV_WARN))
        self.assertIn("DIMLFAC_KHAC_1", codes(st, SEV_WARN))
        build_plan_dxf(p, insunits=6)
        self.assertIn("DON_VI_KHAC_MM", codes(reader.read_dxf(p), SEV_WARN))
        self.assertNotIn("DON_VI_KHAC_MM", codes(self.store))
        self.assertNotIn("DIMLFAC_KHAC_1", codes(self.store))

    def test_override_matching_measurement_not_flagged(self):
        p = self.path("ghi_de_dung.dxf")
        build_plan_dxf(p, override="7.200")                     # phân nhóm nghìn kiểu Việt Nam = 7200
        self.assertNotIn("DIM_GHI_DE", codes(reader.read_dxf(p)))

    def test_custom_role_patterns_and_no_axes(self):
        st = reader.read_dxf(self.dxf, role_patterns={"truc": r"^KHONG_CO_LAYER_NAY$"})
        self.assertEqual((st.axes["V"].names, st.axes["H"].names), ([], []))
        self.assertEqual(codes(st, SEV_WARN).count("KHONG_CO_TRUC"), 2)
        self.assertEqual(st.columns, [])
        self.assertIn("COT_CHUA_GAN_TRUC", codes(st, SEV_DOUBT))
        with self.assertRaises(ReaderError):
            reader.read_dxf(self.dxf, role_patterns={"mai_nha": "roof"})

    def test_door_gap_t_junction_and_caps(self):
        p = self.path("ngat_mat.dxf")
        hs = build_gap_dxf(p)
        st = reader.read_dxf(p)
        self.assertEqual(len(st.walls), 2)
        main, inner = st.walls
        self.assertEqual((main.start, main.end, main.thickness), ([0.0, 0.0], [5000.0, 0.0], 220.0))
        self.assertIn("nối qua ô cửa", main.prov.ref)
        self.assertIn("nối qua chỗ giao tường", main.prov.ref)
        self.assertEqual((inner.start, inner.end, inner.thickness), ([3000.0, 0.0], [3000.0, 3000.0], 110.0))
        self.assertNotIn("TUONG_CHUA_GHEP_CAP", codes(st))        # nét bịt đầu tường không bị coi là đường lẻ
        self.assertEqual(len(st.openings), 1)
        op = st.openings[0]
        self.assertEqual((op.wall_id, op.offset, op.width), (main.id, 1000.0, 900.0))
        lost = issue(st, "CUA_CHUA_GAN_TUONG")
        self.assertIsNotNone(lost)
        self.assertEqual((lost.severity, lost.eids), (SEV_DOUBT, [hs["far_door"]]))

    def test_closed_outlines_attrib_bubbles_and_door_swings(self):
        p = self.path("phong.dxf")
        hs = build_room_dxf(p)
        st = reader.read_dxf(p)
        self.assertEqual((st.axes["V"].names, st.axes["V"].spans), (["1", "2"], [6000.0]))
        self.assertEqual((st.axes["H"].names, st.axes["H"].spans), (["A", "B"], [4000.0]))
        ends = sorted((tuple(w.start), tuple(w.end), w.thickness) for w in st.walls)
        self.assertEqual(ends, [((0.0, 0.0), (0.0, 4000.0), 220.0), ((0.0, 0.0), (6000.0, 0.0), 220.0),
                                ((0.0, 4000.0), (6000.0, 4000.0), 220.0), ((6000.0, 0.0), (6000.0, 4000.0), 220.0)])
        # bốn góc khép kín: hợp các tường đúng bằng vành tường 6220×4220 − 5780×3780
        self.assertAlmostEqual(geom.walls_union(st).area, 6220 * 4220 - 5780 * 3780, places=3)
        doors = {o.id: o for o in st.openings}
        wall_of = {w.id: (tuple(w.start), tuple(w.end)) for w in st.walls}
        d1, d2 = doors["CD1"], doors["CD2"]
        self.assertEqual(wall_of[d1.wall_id], ((0.0, 0.0), (6000.0, 0.0)))
        self.assertEqual((d1.offset, d1.width, d1.hinge, d1.opens_to), (2000.0, 900.0, "cuoi", "trai"))
        self.assertEqual(wall_of[d2.wall_id], ((0.0, 4000.0), (6000.0, 4000.0)))
        self.assertEqual((d2.offset, d2.width, d2.hinge, d2.opens_to), (3100.0, 900.0, "cuoi", "phai"))
        loose = [i for i in st.issues if i.code == "THUC_THE_CHUA_XU_LY"]
        self.assertEqual(len(loose), 1)
        self.assertEqual(loose[0].eids, [hs["loose"]])
        self.assertIn("block INSERT", loose[0].message)
        idle = [i for i in st.issues if i.code == "DIMLFAC_KHAC_1"]
        self.assertEqual(len(idle), 1)
        self.assertIn("KHONG_DUNG", idle[0].message)

    def test_overlapping_rectangles_and_duplicate_line(self):
        """Mỗi tường là một hình chữ nhật kín, hai hình chồng nhau ở góc; thêm một nét trùng mặt tường."""
        doc = ezdxf.new("R2010", units=4)
        msp = doc.modelspace()
        msp.add_lwpolyline([(-110, -110), (5110, -110), (5110, 110), (-110, 110)], close=True,
                           dxfattribs={"layer": "TUONG"})
        msp.add_lwpolyline([(4890, -110), (5110, -110), (5110, 3000), (4890, 3000)], close=True,
                           dxfattribs={"layer": "TUONG"})
        msp.add_line((0, 110), (2000, 110), dxfattribs={"layer": "TUONG"})
        p = self.path("chong.dxf")
        doc.saveas(p)
        st = reader.read_dxf(p)
        ends = [(w.start, w.end, w.thickness) for w in st.walls]
        self.assertEqual(ends, [([-110.0, 0.0], [5000.0, 0.0], 220.0), ([5000.0, 0.0], [5000.0, 3000.0], 220.0)])
        self.assertNotIn("TUONG_CHUA_GHEP_CAP", codes(st))
        self.assertAlmostEqual(geom.walls_union(st).area, 5220 * 220 + 220 * 2890, places=3)

    def test_bad_files(self):
        with self.assertRaises(ReaderError):
            reader.read_dxf(self.path("khong_co.dxf"))
        junk = self.path("rac.dxf")
        with open(junk, "w", encoding="utf-8") as f:
            f.write("day khong phai DXF\n")
        with self.assertRaises(ReaderError):
            reader.read_dxf(junk)
        with self.assertRaises(ReaderError):
            reader.read_dxf(self.dxf, tol=0)


class ReadSpecTest(ReaderTestBase):
    def test_sample_spec(self):
        st = reader.read_spec(SAMPLE_SPEC)
        self.assertEqual(st.axes["V"].names, ["1", "2", "3", "4"])
        self.assertEqual(len(st.walls), 9)
        src = st.sources[-1]
        self.assertEqual((src.name, src.kind, src.used_for), ("de_bai_mat_bang_tang1.json", "json", "du_lieu"))
        with open(SAMPLE_SPEC, "rb") as f:
            self.assertEqual(src.sha256, hashlib.sha256(f.read()).hexdigest())
        self.assertEqual([m.key for m in st.missing()], ["axes:V.spans[1]", "openings:CD4.width"])

    def test_bad_spec(self):
        p = self.write_json("sai.json", {"schema": "23hg-cad-store/1", "columns": [{"id": "C1", "la": 1}]})
        with self.assertRaises(ReaderError):
            reader.read_spec(p)
        bad = self.path("hong.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{ khong phai json")
        with self.assertRaises(ReaderError):
            reader.read_spec(bad)


class InterpolateTest(ReaderTestBase):
    def test_sample_interpolation_never_confirmed(self):
        st = load_sample(filled=False)
        res = {r["key"]: r for r in reader.interpolate_missing(st)}
        self.assertEqual(set(res), {"axes:V.spans[1]", "openings:CD4.width"})
        span, door = res["axes:V.spans[1]"], res["openings:CD4.width"]
        self.assertEqual((span["value"], span["method"]), (3600.0, "tong_tru_nhip"))
        self.assertIn("10800 − (3600 + 3600)", span["reason"])
        self.assertEqual((door["value"], door["method"]), (900.0, "cung_ky_hieu"))
        self.assertIn("CD2", door["reason"])
        self.assertEqual(st.axes["V"].spans[1], 3600.0)
        self.assertEqual(st.get("openings", "CD4").width, 900.0)
        for key in res:
            prov = st.get_provenance(key)
            self.assertEqual(prov.source, SRC_INTERP)
            self.assertFalse(prov.confirmed)
        self.assertEqual({k for k, _ in st.unconfirmed()}, set(res))
        self.assertEqual(st.status()["trang_thai"], "CHO_XAC_NHAN_NOI_SUY")
        self.assertEqual(reader.interpolate_missing(st), [])     # hết thiếu → không làm gì thêm

    def test_two_missing_spans_not_interpolated(self):
        st = load_sample(filled=False)
        st.set_value("axes:V.spans[0]", None, st.get_provenance("axes:V.spans[0]"))
        res = {r["key"]: r for r in reader.interpolate_missing(st)}
        for key in ("axes:V.spans[0]", "axes:V.spans[1]"):
            self.assertIsNone(res[key]["value"])
            self.assertEqual(res[key]["method"], "khong_noi_suy")
            self.assertIn("thiếu 2 nhịp", res[key]["reason"])
        self.assertIsNone(st.axes["V"].spans[1])
        self.assertEqual(st.status()["trang_thai"], "THIEU_KICH_THUOC")

    def test_non_positive_remainder_is_error(self):
        st = load_sample(filled=False)
        st.set_value("axes:V.overall", 7000, st.get_provenance("axes:V.overall"))
        res = {r["key"]: r for r in reader.interpolate_missing(st)}
        self.assertIsNone(res["axes:V.spans[1]"]["value"])
        self.assertIn("NOI_SUY_NHIP_KHONG_DUONG", codes(st, SEV_ERROR))

    def test_conflicting_marks_and_other_items(self):
        st = load_sample(filled=True)
        user = st.get_provenance("columns:C-1A.b")
        st.set_value("columns:C-1A.b", None, user)
        st.set_value("columns:C-2A.b", 250, user)
        st.set_value("openings:CS1.offset", None, user)
        res = {r["key"]: r for r in reader.interpolate_missing(st)}
        self.assertIsNone(res["columns:C-1A.b"]["value"])
        self.assertIn("mâu thuẫn", res["columns:C-1A.b"]["reason"])
        self.assertIn("NOI_SUY_MAU_THUAN", codes(st, SEV_DOUBT))
        self.assertIsNone(res["openings:CS1.offset"]["value"])
        self.assertIn("không có kích thước rõ gần nhất", res["openings:CS1.offset"]["reason"])


class UserValuesTest(ReaderTestBase):
    def setUp(self):
        super().setUp()
        self.store = load_sample(filled=False)
        reader.interpolate_missing(self.store)

    def test_write_and_confirm(self):
        p = self.write_json("nhap.json", {
            "nguon": "[Trang 2] KT-01",
            "gia_tri": {"openings:CD4.width": 900},
            "xac_nhan": [{"key": "axes:V.spans[1]", "by": "Kỹ sư thiết kế", "ghi_chu": "đối chiếu bản vẽ"}]})
        keys = reader.apply_user_values(self.store, p)
        self.assertEqual(keys, ["openings:CD4.width", "axes:V.spans[1]"])
        prov = self.store.get_provenance("openings:CD4.width")
        self.assertEqual((prov.source, prov.ref), (SRC_USER, "[Trang 2] KT-01"))
        span = self.store.get_provenance("axes:V.spans[1]")
        self.assertEqual((span.source, span.confirmed, span.confirmed_by), (SRC_INTERP, True, "Kỹ sư thiết kế"))
        self.assertEqual(self.store.unconfirmed(), [])
        self.assertEqual(self.store.status()["trang_thai"], "CHO_DUYET")
        self.assertEqual(self.store.sources[-1].kind, "kich_thuoc_nhap")
        self.assertNotIn("NGUON_NHAP_THIEU_TRANG", codes(self.store))

    def test_errors_are_atomic(self):
        bad_key = self.write_json("sai_khoa.json", {"nguon": "[Trang 2] KT-01",
                                                    "gia_tri": {"openings:CD4.width": 950, "axes:V.spans[9]": 1}})
        with self.assertRaises(ReaderError) as cm:
            reader.apply_user_values(self.store, bad_key)
        self.assertIn("axes:V.spans[9]", str(cm.exception))
        self.assertEqual(self.store.get_value("openings:CD4.width"), 900.0)      # không ghi gì
        self.assertEqual(self.store.get_provenance("openings:CD4.width").source, SRC_INTERP)
        not_interp = self.write_json("xn_sai.json", {"nguon": "[Trang 2] KT-01",
                                                     "xac_nhan": [{"key": "axes:H.spans[0]", "by": "Kỹ sư"}]})
        with self.assertRaises(ReaderError):
            reader.apply_user_values(self.store, not_interp)
        no_source = self.write_json("khong_nguon.json", {"gia_tri": {"openings:CD4.width": 900}})
        with self.assertRaises(ReaderError):
            reader.apply_user_values(self.store, no_source)
        negative = self.write_json("am.json", {"nguon": "[Trang 2] KT-01", "gia_tri": {"walls:W1.thickness": -5}})
        with self.assertRaises(ReaderError):
            reader.apply_user_values(self.store, negative)

    def test_source_without_page_warns(self):
        p = self.write_json("nhap.json", {"nguon": "KT-01", "gia_tri": {"openings:CD4.width": 900}})
        reader.apply_user_values(self.store, p)
        self.assertIn("NGUON_NHAP_THIEU_TRANG", codes(self.store, SEV_WARN))


class ReferenceAndDispatchTest(ReaderTestBase):
    def make_png(self, name="scan.png", size=(40, 30)):
        from PIL import Image
        p = self.path(name)
        Image.new("RGB", size, (255, 255, 255)).save(p)
        return p

    def test_png_underlay_not_recognized(self):
        st = load_sample()
        png = self.make_png()
        sf = reader.attach_reference(st, png)
        self.assertEqual((sf.kind, sf.used_for), ("anh", "anh_nen"))
        self.assertEqual(sf.underlay, {"insert": [0.0, 0.0], "scale": None, "page": 1, "pixels": [40, 30]})
        self.assertIn(sf, st.sources)
        self.assertIn("ANH_CHUA_NHAN_DANG", codes(st, SEV_WARN))
        self.assertIn("ANH_CHUA_CO_TY_LE", codes(st, SEV_WARN))
        st2 = load_sample()
        reader.attach_reference(st2, png, insert=(100, 200), scale=10)
        self.assertNotIn("ANH_CHUA_CO_TY_LE", codes(st2))
        self.assertEqual(st2.sources[-1].underlay["scale"], 10.0)
        self.assertEqual(st2.missing(), [])                      # ảnh không thêm/sửa số liệu nào
        # đặt tỷ lệ sau khi gắn → cảnh báo thiếu tỷ lệ được tính lại (mất), cảnh báo không nhận dạng vẫn còn
        changed = reader.set_reference_scale(st, 2.5)
        self.assertEqual([s.underlay["scale"] for s in changed], [2.5])
        self.assertNotIn("ANH_CHUA_CO_TY_LE", codes(st))
        self.assertIn("ANH_CHUA_NHAN_DANG", codes(st))
        with self.assertRaises(ReaderError):
            reader.set_reference_scale(st, 0)
        with self.assertRaises(ReaderError):
            reader.set_reference_scale(st, 1, name="khong_co.png")

    def test_pdf_reference(self):
        pdf = self.path("ban_ve.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n")
        sf = reader.attach_reference(load_sample(), pdf, scale=1, page=2)
        self.assertEqual((sf.kind, sf.underlay["page"]), ("pdf", 2))
        fake = self.path("gia.pdf")
        with open(fake, "wb") as f:
            f.write(b"khong phai pdf")
        with self.assertRaises(ReaderError):
            reader.attach_reference(load_sample(), fake)

    def test_load_inputs_dispatch(self):
        png = self.make_png()
        st = reader.load_inputs([SAMPLE_SPEC, png])
        self.assertEqual([s.used_for for s in st.sources], ["du_lieu", "anh_nen"])
        with self.assertRaises(ReaderError) as cm:
            reader.load_inputs([png])
        self.assertIn("JSON", str(cm.exception))
        with self.assertRaises(ReaderError) as cm:
            reader.load_inputs(["ban_ve.dwg"])
        self.assertIn("DWG cần AutoCAD", str(cm.exception))
        dxf = self.path("mat_bang.dxf")
        build_plan_dxf(dxf)
        with self.assertRaises(ReaderError) as cm:
            reader.load_inputs([SAMPLE_SPEC, dxf])
        self.assertIn("gộp", str(cm.exception))
        with self.assertRaises(ReaderError):
            reader.load_inputs(["ghi_chu.txt"])
        self.assertEqual(len(reader.load_inputs(dxf).walls), 2)

    def test_load_inputs_order_user_values_then_interpolate(self):
        uv = self.write_json("nhap.json", {"nguon": "[Trang 2] KT-01", "gia_tri": {"openings:CD4.width": 800}})
        st = reader.load_inputs(SAMPLE_SPEC, user_values=uv, interpolate=True,
                                references=[{"path": self.make_png(), "scale": 5}])
        self.assertEqual(st.get("openings", "CD4").width, 800.0)                 # người nhập được ưu tiên
        self.assertEqual(st.get_provenance("openings:CD4.width").source, SRC_USER)
        self.assertEqual(st.get_provenance("axes:V.spans[1]").source, SRC_INTERP)
        self.assertEqual(st.status()["trang_thai"], "CHO_XAC_NHAN_NOI_SUY")
        self.assertNotIn("ANH_CHUA_CO_TY_LE", codes(st))


class TemplateTest(ReaderTestBase):
    def build_template(self, path):
        doc = ezdxf.new("R2010", setup=True, units=4)
        doc.layers.add("A-WALL", color=5, linetype="Continuous", lineweight=35)
        doc.layers.add("A-DOOR", color=3)
        doc.layers.add("S-GRID", color=1, linetype="CENTER")
        doc.layers.add("S-GRID-IDEN", color=1)
        blk = doc.blocks.new("GIUONG_DOI")
        blk.add_lwpolyline([(0, 0), (1600, 0), (1600, 2000), (0, 2000)], close=True)
        blk.add_line((0, 1700), (1600, 1700))
        blk.add_circle((400, 1850), 100)
        blk.add_arc((1200, 1850), 100, 0, 180)
        blk.add_text("GIUONG", height=150).set_placement((800, 800), align=TextEntityAlignment.MIDDLE_CENTER)
        hatch = blk.add_hatch()
        hatch.paths.add_polyline_path([(0, 0), (100, 0), (100, 100)], is_closed=True)
        doc.saveas(path)

    def test_template_layers_and_blocks(self):
        p = self.path("mau.dxf")
        self.build_template(p)
        st = load_sample()
        out = reader.read_template(st, p)
        self.assertEqual(out["layers"]["tuong"], "A-WALL")
        self.assertEqual(out["layers"]["cua"], "A-DOOR")
        self.assertEqual(out["layers"]["truc"], "S-GRID")
        self.assertEqual(out["layers"]["truc_kh"], "S-GRID-IDEN")
        wall = st.layers["tuong"]
        self.assertEqual((wall.name, wall.color, wall.lineweight, wall.linetype), ("A-WALL", 5, 35, "Continuous"))
        self.assertEqual(st.layers["truc"].linetype, "CENTER")
        self.assertIn("dim", out["unmatched_roles"])
        self.assertEqual(st.layers["dim"].name, "KT-DIM")                       # vai trò không khớp giữ mặc định
        bd = st.blocks["GIUONG_DOI"]
        self.assertEqual((bd.source, bd.size), ("mau", [1600.0, 2000.0]))
        self.assertEqual(sorted({o["kind"] for o in bd.ops}), ["arc", "circle", "line", "pline", "text"])
        self.assertEqual(out["skipped"]["GIUONG_DOI"], {"HATCH": 1})
        self.assertIn("TEMPLATE_BO_QUA_THUC_THE", codes(st, SEV_WARN))
        self.assertEqual((st.sources[-1].kind, st.sources[-1].used_for), ("template", "mau"))
        plan = new_plan(st)
        self.assertEqual(plan.layer_name("tuong"), "A-WALL")

    def test_role_map_and_errors(self):
        p = self.path("mau.dxf")
        self.build_template(p)
        st = load_sample()
        out = reader.read_template(st, p, role_map={"tuong": "a-wall"})
        self.assertEqual(out["layers"], {"tuong": "A-WALL"})
        self.assertEqual(st.layers["cua"].name, "KT-CUA")
        with self.assertRaises(ReaderError):
            reader.read_template(load_sample(), p, role_map={"tuong": "KHONG_CO"})
        with self.assertRaises(ReaderError):
            reader.read_template(load_sample(), p, role_map={"tuong": "A-WALL", "cot": "A-WALL"})
        with self.assertRaises(ReaderError):
            reader.read_template(load_sample(), self.path("mau.dwt"))


if __name__ == "__main__":
    unittest.main()
