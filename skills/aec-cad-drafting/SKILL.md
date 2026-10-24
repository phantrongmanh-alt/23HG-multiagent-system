---
name: aec-cad-drafting
description: Agent dựng bản vẽ mặt bằng CAD tất định theo quy trình "1 Master Agent + Skill 00 + 10 skill + Validator" — đọc DXF hoặc đề bài JSON nhập tay một lần vào kho dữ liệu dự án, dựng lưới trục, cột, tường, cửa, cầu thang, nội thất, hatch, kích thước, hoàn thiện, khung tên; kiểm tra xung đột sau mỗi bước; xuất DXF, PDF/PNG đúng tỷ lệ, AutoLISP và danh sách lệnh vẽ JSON cho máy chủ MCP. Kích thước thiếu thì người dùng nhập hoặc nội suy có đánh dấu, không bao giờ tự coi nội suy là đã xác nhận.
---

# Agent dựng bản vẽ CAD (AEC-CAD-Drafting)

Mã nguồn: `tools/cad_drafting/`. Quy trình chi tiết: `workflows/16_QUY_TRINH_DUNG_BAN_VE_CAD_TU_DONG.md`.

## 1. Khi nào dùng

- Cần dựng (hoặc dựng lại) mặt bằng kiến trúc 2D từ số liệu: DXF có sẵn, hoặc số liệu đọc từ bản vẽ PDF/ảnh và gõ vào đề bài JSON.
- Cần bản vẽ có kiểm tra: mỗi đối tượng thiếu số liệu, mỗi xung đột (cửa đè cột, nội thất đè tường...) phải hiện ra trong báo cáo.

Không dùng để: đoán số từ ảnh mờ (repo cấm), sinh DWG trực tiếp (cần AutoCAD), thiết kế kết cấu.

## 2. Lệnh

```bash
# Đề bài mẫu, cho phép nội suy (B) — kết quả CHƯA ĐẠT vì còn số liệu nội suy chưa xác nhận
python -m tools.cad_drafting --dau-vao examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json --noi-suy --ra out/

# Người dùng nhập / xác nhận kích thước (A)
python -m tools.cad_drafting --dau-vao de_bai.json --kich-thuoc-nhap nhap.json --ra out/

# DXF có sẵn + template layer/block của đơn vị + ảnh scan làm nền (chỉ làm nền, không nhận dạng)
python -m tools.cad_drafting --dau-vao ban_ve.dxf anh_scan.png --anh-nen-ty-le 10 --template mau.dxf --ra out/

# Sửa dữ liệu rồi chỉ chạy lại skill bị ảnh hưởng
python -m tools.cad_drafting --dau-vao out/KT-01_du_lieu_du_an.json --ra out/ --cap-nhat
```

Mã thoát: 0 = đạt kiểm tra tự động (vẫn chờ kỹ sư duyệt), 2 = đã xuất nhưng chưa đạt, 1 = lỗi đầu vào.

File nhập tay (A) — khoá số liệu theo `tools/cad_drafting/store.py`:

```json
{"nguon": "[Trang 2] KT-01",
 "gia_tri": {"axes:V.spans[1]": 3600, "openings:CD4.width": 900},
 "xac_nhan": [{"key": "axes:V.spans[1]", "by": "<người xác nhận>", "ghi_chu": "đã đối chiếu bản vẽ"}]}
```

## 3. Kiến trúc

| Thành phần | File | Việc |
|---|---|---|
| Skill 00 — đọc bản vẽ | `reader.py` | DXF (trục, cột, tường, cửa, DIMENSION), đề bài JSON, template, ảnh nền; A. nhập tay; B. nội suy |
| Project Data Store | `store.py` | Một kho dữ liệu, mỗi số liệu mang nguồn (dxf / nguoi_nhap / noi_suy); trạng thái duyệt TÍNH |
| 10 skill | `skills/s01..s10_*.py` | Lưới trục, cột, tường, cửa, cầu thang, nội thất, hatch, kích thước, hoàn thiện, kiểm tra & xuất |
| CAD Validator | `validator.py` | Kiểm tra trước khi vẽ, sau mỗi skill, và cuối cùng |
| Danh sách lệnh vẽ | `plan.py` | Đầu ra chung của skill; JSON là giao thức gửi máy chủ MCP |
| Xuất | `render_dxf.py`, `render_lisp.py`, `render_preview.py` | DXF (ezdxf), AutoLISP, PDF/PNG |
| Master Agent | `master.py`, `__main__.py` | Điều phối, chế độ cập nhật, báo cáo |

Mỗi skill chỉ được ghi vào layer (vai trò) của mình — `layers.ROLE_OWNER`. Validator bắt skill vẽ lấn sang layer khác
(`SKILL_LAN_PHAN`) và skill làm đổi Op của skill khác (`SKILL_SUA_PHAN_KHAC`).

## 4. Giao tiếp AutoCAD / MCP

- DXF mở thẳng trong AutoCAD; muốn DWG thì SAVEAS. Mỗi thực thể mang XDATA `23HG_CAD` = mã đối tượng (eid) để sửa đúng chỗ.
- `<số hiệu>.lsp`: nạp bằng APPLOAD rồi gõ `23HG_VE`. Chỉ mới kiểm tra cú pháp tĩnh, chưa chạy thử trên AutoCAD.
- `<số hiệu>_lenh_ve.json` (schema `23hg-cad-plan/1`): danh sách lệnh vẽ cho máy chủ MCP điều khiển AutoCAD (repo `cad-mcp` riêng). Giao thức
  phía máy chủ chưa được đối chiếu vì repo đó không truy cập được từ đây.

## 5. Quy tắc bắt buộc

1. Không tự coi kích thước nội suy là đã xác nhận: chỉ `store.confirm(khoá, người)` (mục `xac_nhan` của file nhập) mới đổi.
2. Không bỏ đối tượng im lặng: đối tượng thiếu số liệu vào mục "Đối tượng chưa vẽ (kèm lý do)" của báo cáo.
3. Không gõ tay trạng thái: kết luận, khung tên, báo cáo đều tính từ dữ liệu và kết quả Validator.
4. PDF/ảnh chỉ làm nền tham chiếu; số liệu trích từ bản vẽ ghi `[Trang N]` và số hiệu bản vẽ vào `nguon_mac_dinh` / `nguon`.
