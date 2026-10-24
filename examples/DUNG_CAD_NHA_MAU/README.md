# Dựng bản vẽ CAD — nhà ở mẫu (dữ liệu minh hoạ)

Số liệu trong đề bài là **tự đặt để chạy thử**, không phải hồ sơ thiết kế thật. Đề bài cố ý để trống hai số liệu
(nhịp trục 2–3 và bề rộng cửa CD4) để chạy thử hai phương án xử lý kích thước thiếu.

| File | Nội dung |
|---|---|
| `de_bai_mat_bang_tang1.json` | Đề bài nhập tay (schema `23hg-cad-store/1`): trục, cột, tường, cửa, thang, phòng, nội thất |
| `kich_thuoc_nhap.json` | Phương án A — người dùng nhập hai số liệu thiếu |
| `ket_qua/KT-01_NOI_SUY.*` | Phương án B — nội suy (`--noi-suy`): kết luận CHƯA ĐẠT, 2 nghi vấn vì nội suy chưa xác nhận |
| `ket_qua/KT-01_NHAP_TAY.*` | Phương án A: đạt kiểm tra tự động, chờ kỹ sư duyệt |

Mỗi bộ kết quả: `.dxf` (mở bằng AutoCAD), `.pdf` (A3, đúng tỷ lệ 1:100), `.png` (xem nhanh, hiện cả layer kiểm tra),
`.lsp` (AutoLISP — chưa chạy thử trên AutoCAD), `_lenh_ve.json` (lệnh vẽ cho máy chủ MCP), `_du_lieu_du_an.json`,
`_BAO_CAO_KIEM_TRA.md` / `_bao_cao_kiem_tra.json`.

Sinh lại:

```bash
python -m tools.cad_drafting --dau-vao examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json --noi-suy \
    --ra examples/DUNG_CAD_NHA_MAU/ket_qua --ten KT-01_NOI_SUY
python -m tools.cad_drafting --dau-vao examples/DUNG_CAD_NHA_MAU/de_bai_mat_bang_tang1.json \
    --kich-thuoc-nhap examples/DUNG_CAD_NHA_MAU/kich_thuoc_nhap.json --ra examples/DUNG_CAD_NHA_MAU/ket_qua --ten KT-01_NHAP_TAY
```

Lệnh vẽ JSON, dữ liệu dự án, AutoLISP và báo cáo tất định (hai lần sinh giống hệt từng byte); DXF khác nhau ở dấu thời
gian do thư viện ghi, PDF/PNG có thể khác vài điểm ảnh — báo cáo không ghi kích thước ba file này vì lý do đó.
