# -*- coding: utf-8 -*-
"""
Dòng lệnh agent dựng CAD.

  python -m tools.cad_drafting --dau-vao examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json --noi-suy --ra out/
  python -m tools.cad_drafting --dau-vao ban_ve.dxf --template mau.dxf --kich-thuoc-nhap nhap.json --ra out/
  python -m tools.cad_drafting --dau-vao de_bai.json anh_scan.png --anh-nen-ty-le 10 --ra out/   (ảnh chỉ làm nền)
  python -m tools.cad_drafting --dau-vao de_bai.json --ra out/ --cap-nhat      (chỉ chạy lại skill bị ảnh hưởng)

Mã thoát: 0 = đạt kiểm tra tự động, 2 = đã xuất nhưng CHƯA ĐẠT (xem <tên>_BAO_CAO_KIEM_TRA.md), 1 = lỗi đầu vào.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.cad_drafting import reader  # noqa: E402
from tools.cad_drafting.master import CadDraftingMaster  # noqa: E402
from tools.cad_drafting.skills import SKILL_MODULES  # noqa: E402
from tools.cad_drafting.store import StoreError  # noqa: E402

REFERENCE_EXT = (".pdf", ".png", ".jpg", ".jpeg")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m tools.cad_drafting",
                                 description="Agent dựng bản vẽ mặt bằng CAD (Skill 00 + 10 skill + Validator).")
    ap.add_argument("--dau-vao", nargs="+", required=True, metavar="FILE",
                    help="đề bài JSON hoặc DXF (đúng một nguồn dữ liệu) + tuỳ chọn PDF/JPG/PNG làm ảnh nền")
    ap.add_argument("--ra", required=True, metavar="THU_MUC", help="thư mục kết quả")
    ap.add_argument("--ten", help="tên gốc file kết quả (mặc định: số hiệu bản vẽ)")
    ap.add_argument("--template", help="template DXF (layer, block)")
    ap.add_argument("--vai-tro-layer", metavar="JSON",
                    help="file JSON {vai_trò: regex tên layer} khi đọc DXF (vai trò: bo_qua, truc, tuong, cot, cua_di, "
                         "cua_so, dim) — vd khai báo layer nội thất/khung tên cố ý không đọc: {\"bo_qua\": \"noi.?that|"
                         "khung|cao.?do|cote|elev|c[ốỐ]t\"} (mẫu mới THAY mẫu mặc định cùng vai trò)")
    ap.add_argument("--kich-thuoc-nhap", help="A. file JSON kích thước người dùng nhập; mục xac_nhan dùng ở lần chạy SAU "
                                               "trên <tên>_du_lieu_du_an.json để xác nhận số liệu đã nội suy")
    ap.add_argument("--noi-suy", action="store_true",
                    help="B. nội suy kích thước thiếu từ kích thước rõ gần nhất (đánh dấu CHƯA XÁC NHẬN)")
    ap.add_argument("--anh-nen-ty-le", type=float, help="mm bản vẽ trên 1 pixel (ảnh) / 1 đơn vị PDF")
    ap.add_argument("--cap-nhat", action="store_true",
                    help="dùng kết quả lần trước trong --ra, chỉ chạy lại skill có dữ liệu đầu vào thay đổi")
    ap.add_argument("--chi-chay", help="chỉ chạy lại các skill này (vd 03,04) trên lệnh vẽ lần trước")
    ap.add_argument("--dung-khi-loi", action="store_true", help="dừng ngay sau skill phát hiện LỖI")
    ap.add_argument("--khong-pdf", action="store_true", help="không xuất PDF/PNG")
    ap.add_argument("--duyet", metavar="TEN",
                    help="ghi phê duyệt (chỉ khi bản vẽ ĐẠT kiểm tra tự động: không thiếu, không nội suy chưa xác nhận, "
                         "không lỗi/nghi vấn, không đối tượng chưa vẽ)")
    ap.add_argument("--ngay", default="", help="ngày phê duyệt (YYYY-MM-DD), dùng cùng --duyet")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    refs = [p for p in args.dau_vao if p.lower().endswith(REFERENCE_EXT)]
    for p in args.dau_vao:
        if not os.path.isfile(p):
            print(f"  ❌ Không thấy file: {p}")
            return 1
    only = None
    if args.chi_chay:
        valid = {c for c, _, _ in SKILL_MODULES}
        only = [c.strip().zfill(2) for c in args.chi_chay.split(",") if c.strip()]
        bad = [c for c in only if c not in valid]
        if bad or not only:
            print(f"  ❌ --chi-chay: mã skill không hợp lệ {bad or args.chi_chay!r} (hợp lệ: 01..10)")
            return 1
    if args.duyet and not args.ngay:
        print("  ❌ --duyet cần --ngay")
        return 1
    try:
        role_patterns = None
        if args.vai_tro_layer:
            with open(args.vai_tro_layer, encoding="utf-8") as f:
                role_patterns = json.load(f)
        store = reader.load_inputs(args.dau_vao, template=args.template, user_values=args.kich_thuoc_nhap,
                                   interpolate=False, role_patterns=role_patterns)
        if args.anh_nen_ty_le:
            reader.set_reference_scale(store, args.anh_nen_ty_le)
        interpolations = reader.interpolate_missing(store) if args.noi_suy else []
    except (reader.ReaderError, StoreError, OSError, ValueError) as e:
        print(f"  ❌ {e}")
        return 1

    master = CadDraftingMaster(stop_on_error=args.dung_khi_loi)
    try:
        report = master.run(store, args.ra, base=args.ten, cap_nhat=args.cap_nhat, only=only,
                            reference_paths=refs, pdf=not args.khong_pdf, interpolations=interpolations)
        if args.duyet:
            # Phê duyệt là việc của người và chỉ ghi được khi bản vẽ ĐẠT kiểm tra tự động (0 lỗi, 0 nghi vấn,
            # 0 đối tượng chưa vẽ) — không duyệt thay cho dữ liệu đang có lỗi.
            if not report.dat:
                print(f"  ❌ Không ghi phê duyệt: {report.ket_luan()}")
                print(f"  Kết quả (chưa duyệt): {os.path.abspath(args.ra)}")
                return 2
            store.approve(args.duyet, args.ngay)
            # vẽ lại khung tên (trạng thái ĐÃ DUYỆT) và lưu dữ liệu kèm phê duyệt
            report = master.run(store, args.ra, base=report.base, cap_nhat=True, reference_paths=refs,
                                pdf=not args.khong_pdf, interpolations=interpolations)
    except StoreError as e:
        print(f"  ❌ {e}")
        return 1
    except OSError as e:
        print(f"  ❌ Không ghi được kết quả vào {os.path.abspath(args.ra)}: {e}")
        return 1
    print(f"\n  {report.ket_luan()}")
    print(f"  Kết quả: {os.path.abspath(args.ra)}")
    return 0 if report.dat else 2


if __name__ == "__main__":
    sys.exit(main())
