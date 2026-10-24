# Báo cáo kiểm tra bản vẽ KT-01 — MẶT BẰNG TẦNG 1

- Dự án: NHÀ Ở MẪU (DỮ LIỆU MINH HOẠ) · Tỷ lệ 1:100 · Khổ A3
- **Kết luận (tính tự động): ĐẠT KIỂM TRA TỰ ĐỘNG — CHỜ KỸ SƯ DUYỆT**
- Trạng thái số liệu: `CHO_DUYET` — thiếu 0, nội suy chưa xác nhận 0
- Đếm: 0 lỗi · 0 nghi vấn · 2 cảnh báo · 0 đối tượng chưa vẽ · 343 lệnh vẽ

## Nguồn dữ liệu

| File | Loại | Dùng cho | SHA-256 (12 ký tự đầu) | Ghi chú |
|---|---|---|---|---|
| de_bai_mat_bang_tang1.json | json | du_lieu | 82df5f320096 | Đề bài minh hoạ — số liệu tự đặt để chạy thử, KHÔNG phải hồ sơ thiết kế thật |
| kich_thuoc_nhap.json | kich_thuoc_nhap | du_lieu | 7c7ee3d25f47 | Đề bài minh hoạ — giá trị người dùng nhập để chạy thử, không phải hồ sơ thật (hồ sơ thật phải ghi số trang và số hiệu bản vẽ); 2 giá trị nhập, 0 xác nhận nội suy |

## Số liệu nội suy (B) — CHƯA được coi là đã xác nhận

Không có.

## Kích thước còn thiếu

Không có.

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
| 09 | Hoàn thiện | chạy | 97 | 0 | 0 | 0 | 1 |
| 10 | Kiểm tra & xuất | chạy | 29 | 0 | 0 | 0 | 0 |

### Ghi chú của skill

- Skill 01: trục đứng (V): đã vẽ 4/4 trục
- Skill 01: trục ngang (H): đã vẽ 3/3 trục
- Skill 02: đã vẽ 12/12 cột
- Skill 03: đã vẽ 9/9 tường
- Skill 03: đường bao thân tường: 24 đường (0 đường kín)
- Skill 04: đã vẽ 8/8 ô cửa (cửa đi: 4/4, cửa sổ: 4/4)
- Skill 05: ST1 vế 1: bậc: 11 × 260, cao bậc 170
- Skill 05: đã vẽ 1/1 vế thang, 0/0 chiếu nghỉ (1 thang)
- Skill 06: đã chèn 8/8 đồ vật nội thất
- Skill 07: hatch cột: 12/12 cột
- Skill 07: hatch tường: 9/9 tường — 21 vùng tường xây, 0 vùng tường BTCT
- Skill 07: hatch sàn: 6/6 phòng
- Skill 08: đã ghi 42 kích thước DIMENSION (kiểu TCVN_KT_100): cấp 1: 28, cấp 2: 10, cấp 3: 4; không có text_override
- Skill 09: đã ghi nhãn (tên, diện tích, cote) 6/6 phòng
- Skill 09: CẢNH BÁO không còn chỗ trống đủ cho nhãn, nhãn đè lên nội thất/thang/cửa (vẫn trong sàn) — đặt room.label_at để chỉnh: P4
- Skill 09: diện tích tính theo đường bao nhập; 6/6 phòng có đường bao trùng tim trục/tim tường — chưa trừ chiều dày tường, KHÔNG phải diện tích thông thủy.
- Skill 09: bảng hoàn thiện: 6 hàng phòng, góc trên-trái (16800, 12200); tổng diện tích 90,72 m² (tính 6/6 phòng)
- Skill 10: khổ A3 1:100: khung giấy 42000 × 29700 mm (model); khối nội dung + tên bản vẽ 376 × 192 mm giấy đặt trên khung tên
- Skill 10: khung tên: trạng thái số liệu TÍNH từ store.status() = CHO_DUYET → "CHỜ DUYỆT"
- Skill 10: khung tên: để trống ô THIẾT KẾ, KIỂM TRA, NGÀY vì ProjectInfo chưa có số liệu (không tự điền)
- Skill 10: đánh dấu kiểm tra (layer không in): 0 số liệu thiếu định vị được, 0 thiếu chưa định vị (liệt kê ở góc khung), 0 số liệu nội suy chưa xác nhận, 0 phát hiện của Validator

## Danh sách phát hiện

### LỖI (0)

Không có.

### NGHI VẤN (0)

Không có.

### CẢNH BÁO (2)

| Bước | Mã | Nội dung | Vị trí |
|---|---|---|---|
| 00 | NGUON_NHAP_THIEU_TRANG | kich_thuoc_nhap.json: nguồn nhập tay 'Đề bài minh hoạ — giá trị người dùng nhập để chạy thử, không phải hồ sơ thật (hồ sơ thật phải ghi số trang và số hiệu bản vẽ)' chưa ghi trang dạng [Trang N] kèm số hiệu bản vẽ (quy ước repo cho số liệu trích từ bản vẽ). |  |
| 09 | SKILL_CANH_BAO | CẢNH BÁO không còn chỗ trống đủ cho nhãn, nhãn đè lên nội thất/thang/cửa (vẫn trong sàn) — đặt room.label_at để chỉnh: P4 |  |

## Đầu ra

| Loại | File | Ghi chú |
|---|---|---|
| lenh_ve_json | KT-01_NHAP_TAY_lenh_ve.json | 118.749 byte |
| du_lieu_du_an | KT-01_NHAP_TAY_du_lieu_du_an.json | 27.701 byte |
| dxf | KT-01_NHAP_TAY.dxf |  |
| lisp | KT-01_NHAP_TAY.lsp | kiểm tra tĩnh: không phát hiện lỗi cú pháp tĩnh; chạy trên AutoCAD: CHƯA chạy thử · 98.925 byte |
| pdf | KT-01_NHAP_TAY.pdf |  |
| png | KT-01_NHAP_TAY.png |  |
| dwg | — | Không sinh DWG: cần AutoCAD (mở DXF → SAVEAS, hoặc máy chủ cad-mcp). |
| bao_cao | KT-01_NHAP_TAY_BAO_CAO_KIEM_TRA.md |  |

## Chưa làm / giới hạn

- Không sinh DWG trực tiếp: mở file DXF trong AutoCAD rồi SAVEAS, hoặc giao danh sách lệnh vẽ JSON cho máy chủ cad-mcp.
- File AutoLISP chỉ được kiểm tra cú pháp tĩnh, chưa chạy thử trên AutoCAD.
- PDF/ảnh đầu vào chỉ làm ảnh nền tham chiếu, không tự nhận dạng số liệu (cấm đoán số OCR mờ) — số liệu nhập theo đề bài JSON.
- Phạm vi hình học: tường thẳng (nối vuông góc hoặc xiên), cột chữ nhật, thang vế thẳng + chiếu nghỉ, kích thước tường ngoài 3 cấp 4 phía (chưa ghi kích thước trong nhà).
- Kiểu đường của template không có trong bảng của bộ xuất (vd ACAD_ISO*) được thay bằng nét liền trong DXF và báo cảnh báo XUAT_DXF_CANH_BAO; file AutoLISP nạp kiểu đó từ acadiso.lin.
