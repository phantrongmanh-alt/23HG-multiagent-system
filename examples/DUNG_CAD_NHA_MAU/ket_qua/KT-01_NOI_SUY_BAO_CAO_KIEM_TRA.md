# Báo cáo kiểm tra bản vẽ KT-01 — MẶT BẰNG TẦNG 1

- Dự án: NHÀ Ở MẪU (DỮ LIỆU MINH HOẠ) · Tỷ lệ 1:100 · Khổ A3
- **Kết luận (tính tự động): CHƯA ĐẠT: 0 lỗi, 2 nghi vấn, 0 đối tượng chưa vẽ, 1 cảnh báo**
- Trạng thái số liệu: `CHO_XAC_NHAN_NOI_SUY` — thiếu 0, nội suy chưa xác nhận 2
- Đếm: 0 lỗi · 2 nghi vấn · 1 cảnh báo · 0 đối tượng chưa vẽ · 349 lệnh vẽ

## Nguồn dữ liệu

| File | Loại | Dùng cho | SHA-256 (12 ký tự đầu) | Ghi chú |
|---|---|---|---|---|
| de_bai_mat_bang_tang1.json | json | du_lieu | 82df5f320096 | Đề bài minh hoạ — số liệu tự đặt để chạy thử, KHÔNG phải hồ sơ thiết kế thật |

## Số liệu nội suy (B) — CHƯA được coi là đã xác nhận

| Khoá | Giá trị | Cách nội suy | Xác nhận |
|---|---|---|---|
| `axes:V.spans[1]` | 3600.0 | 10800 − (3600 + 3600) từ kích thước tổng trục V (1–4) | **chưa** |
| `openings:CD4.width` | 900.0 | width = 900 lấy từ cửa cùng ký hiệu D2: CD2 | **chưa** |

## Kích thước còn thiếu

Không có.

Còn 2 số liệu nội suy chưa xác nhận: xác nhận bằng file kích thước nhập (mục `xac_nhan`) sau khi đối chiếu bản vẽ.

## Các bước (Validator chạy sau mỗi bước)

| Skill | Tên | Chạy | Lệnh vẽ | Bỏ qua | Lỗi | Nghi vấn | Cảnh báo |
|---|---|---|---|---|---|---|---|
| 01 | Lưới trục | chạy | 35 | 0 | 0 | 0 | 0 |
| 02 | Cột | chạy | 12 | 0 | 0 | 0 | 0 |
| 03 | Tường | chạy | 24 | 0 | 0 | 0 | 0 |
| 04 | Cửa | chạy | 42 | 0 | 0 | 0 | 0 |
| 05 | Cầu thang | chạy | 15 | 0 | 0 | 0 | 0 |
| 06 | Nội thất | chạy | 8 | 0 | 0 | 0 | 0 |
| 07 | Hatch | chạy | 39 | 0 | 0 | 0 | 0 |
| 08 | Kích thước | chạy | 42 | 0 | 0 | 0 | 0 |
| 09 | Hoàn thiện | chạy | 99 | 0 | 0 | 0 | 1 |
| 10 | Kiểm tra & xuất | chạy | 33 | 0 | 0 | 0 | 0 |

### Ghi chú của skill

- Skill 01: trục đứng (V): đã vẽ 4/4 trục
- Skill 01: trục ngang (H): đã vẽ 3/3 trục
- Skill 01: trục 3: toạ độ dựa trên số liệu nội suy CHƯA xác nhận (axes:V.spans[1])
- Skill 01: trục 4: toạ độ dựa trên số liệu nội suy CHƯA xác nhận (axes:V.spans[1])
- Skill 02: đã vẽ 12/12 cột
- Skill 02: cột dựa trên số liệu nội suy CHƯA xác nhận: C-3A (axes:V.spans[1]); C-4A (axes:V.spans[1]); C-3B (axes:V.spans[1]); C-4B (axes:V.spans[1]); C-3C (axes:V.spans[1]); C-4C (axes:V.spans[1])
- Skill 03: đã vẽ 9/9 tường
- Skill 03: đường bao thân tường: 24 đường (0 đường kín)
- Skill 03: tường dựa trên số liệu nội suy CHƯA xác nhận: W1 (axes:V.spans[1]); W2 (axes:V.spans[1]); W3 (axes:V.spans[1]); W6 (axes:V.spans[1]); W8 (axes:V.spans[1]); W9 (axes:V.spans[1])
- Skill 03: ô cửa trừ khỏi tường theo số liệu nội suy CHƯA xác nhận: CD4 (openings:CD4.width)
- Skill 04: đã vẽ 8/8 ô cửa (cửa đi: 4/4, cửa sổ: 4/4)
- Skill 04: ô cửa dựa trên số liệu nội suy CHƯA xác nhận: CD1 (axes:V.spans[1]); CD3 (axes:V.spans[1]); CD4 (openings:CD4.width, axes:V.spans[1]); CS1 (axes:V.spans[1]); CS2 (axes:V.spans[1]); CS4 (axes:V.spans[1])
- Skill 05: ST1 vế 1: bậc: 11 × 260, cao bậc 170
- Skill 05: đã vẽ 1/1 vế thang, 0/0 chiếu nghỉ (1 thang)
- Skill 06: đã chèn 8/8 đồ vật nội thất
- Skill 07: hatch cột: 12/12 cột
- Skill 07: hatch tường: 9/9 tường — 21 vùng tường xây, 0 vùng tường BTCT
- Skill 07: hatch sàn: 6/6 phòng
- Skill 07: hatch dựa trên số liệu nội suy CHƯA xác nhận: cột C-3A (axes:V.spans[1]); cột C-4A (axes:V.spans[1]); cột C-3B (axes:V.spans[1]); cột C-4B (axes:V.spans[1]); cột C-3C (axes:V.spans[1]); cột C-4C (axes:V.spans[1]); tường W1 (axes:V.spans[1]); tường W2 (axes:V.spans[1]); tường W3 (axes:V.spans[1]); tường W6 (axes:V.spans[1]); tường W8 (axes:V.spans[1]); tường W9 (axes:V.spans[1]); phòng P1 (axes:V.spans[1]); phòng P2 (axes:V.spans[1]); phòng P4 (axes:V.spans[1]); phòng P5 (axes:V.spans[1]); phòng P6 (axes:V.spans[1])
- Skill 08: đã ghi 42 kích thước DIMENSION (kiểu TCVN_KT_100): cấp 1: 28, cấp 2: 10, cấp 3: 4; không có text_override
- Skill 08: kích thước ghi theo số liệu NỘI SUY CHƯA xác nhận axes:V.spans[1] (8 kích thước, Skill 10 đánh dấu): dim/L2/duoi/1, dim/L3/duoi/0, dim/L1/duoi/6, dim/L1/duoi/7, dim/L1/duoi/9, dim/L2/tren/1, dim/L3/tren/0, dim/L1/tren/2
- Skill 09: đã ghi nhãn (tên, diện tích, cote) 6/6 phòng
- Skill 09: CẢNH BÁO không còn chỗ trống đủ cho nhãn, nhãn đè lên nội thất/thang/cửa (vẫn trong sàn) — đặt room.label_at để chỉnh: P4
- Skill 09: diện tích tính theo đường bao nhập; 6/6 phòng có đường bao trùng tim trục/tim tường — chưa trừ chiều dày tường, KHÔNG phải diện tích thông thủy.
- Skill 09: bảng hoàn thiện: 6 hàng phòng, góc trên-trái (16800, 12200); tổng diện tích 90,72* m² (tính 6/6 phòng)
- Skill 09: diện tích/cote dựa trên số liệu nội suy CHƯA xác nhận (đánh dấu *): P1 (axes:V.spans[1]); P2 (axes:V.spans[1]); P4 (axes:V.spans[1]); P5 (axes:V.spans[1]); P6 (axes:V.spans[1])
- Skill 10: khổ A3 1:100: khung giấy 42000 × 29700 mm (model); khối nội dung + tên bản vẽ 376 × 192 mm giấy đặt trên khung tên
- Skill 10: khung tên: trạng thái số liệu TÍNH từ store.status() = CHO_XAC_NHAN_NOI_SUY → "CHỜ XÁC NHẬN 2 SỐ LIỆU NỘI SUY"
- Skill 10: khung tên: để trống ô THIẾT KẾ, KIỂM TRA, NGÀY vì ProjectInfo chưa có số liệu (không tự điền)
- Skill 10: đánh dấu kiểm tra (layer không in): 0 số liệu thiếu định vị được, 0 thiếu chưa định vị (liệt kê ở góc khung), 2 số liệu nội suy chưa xác nhận, 0 phát hiện của Validator

## Danh sách phát hiện

### LỖI (0)

Không có.

### NGHI VẤN (2)

| Bước | Mã | Nội dung | Vị trí |
|---|---|---|---|
| VAL | NOI_SUY_CHUA_XAC_NHAN | Số liệu nội suy CHƯA xác nhận: axes:V.spans[1] = 3600 (nguồn: 10800 − (3600 + 3600) từ kích thước tổng trục V (1–4)) — cần người có thẩm quyền xác nhận hoặc nhập giá trị đo từ bản vẽ. | (5400, 0) |
| VAL | NOI_SUY_CHUA_XAC_NHAN | Số liệu nội suy CHƯA xác nhận: openings:CD4.width = 900 (nguồn: width = 900 lấy từ cửa cùng ký hiệu D2: CD2) — cần người có thẩm quyền xác nhận hoặc nhập giá trị đo từ bản vẽ. | (7200, 7250) |

### CẢNH BÁO (1)

| Bước | Mã | Nội dung | Vị trí |
|---|---|---|---|
| 09 | SKILL_CANH_BAO | CẢNH BÁO không còn chỗ trống đủ cho nhãn, nhãn đè lên nội thất/thang/cửa (vẫn trong sàn) — đặt room.label_at để chỉnh: P4 |  |

## Đầu ra

| Loại | File | Ghi chú |
|---|---|---|
| lenh_ve_json | KT-01_NOI_SUY_lenh_ve.json | 119.914 byte |
| du_lieu_du_an | KT-01_NOI_SUY_du_lieu_du_an.json | 26.551 byte |
| dxf | KT-01_NOI_SUY.dxf | 190.951 byte |
| lisp | KT-01_NOI_SUY.lsp | kiểm tra tĩnh: không phát hiện lỗi cú pháp tĩnh; chạy trên AutoCAD: CHƯA chạy thử · 100.027 byte |
| pdf | KT-01_NOI_SUY.pdf | 340.141 byte |
| png | KT-01_NOI_SUY.png | 569.356 byte |
| dwg | — | Không sinh DWG: cần AutoCAD (mở DXF → SAVEAS, hoặc máy chủ cad-mcp). |
| bao_cao | KT-01_NOI_SUY_BAO_CAO_KIEM_TRA.md |  |

## Chưa làm / giới hạn

- Không sinh DWG trực tiếp: mở file DXF trong AutoCAD rồi SAVEAS, hoặc giao danh sách lệnh vẽ JSON cho máy chủ cad-mcp.
- File AutoLISP chỉ được kiểm tra cú pháp tĩnh, chưa chạy thử trên AutoCAD.
- PDF/ảnh đầu vào chỉ làm ảnh nền tham chiếu, không tự nhận dạng số liệu (cấm đoán số OCR mờ) — số liệu nhập theo đề bài JSON.
- Phạm vi hình học: tường thẳng, cột chữ nhật, thang vế thẳng, kích thước tường ngoài 3 cấp 4 phía (chưa ghi kích thước trong nhà).
