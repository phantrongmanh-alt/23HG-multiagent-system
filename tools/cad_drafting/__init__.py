# -*- coding: utf-8 -*-
"""
CAD DRAFTING — agent dựng bản vẽ mặt bằng CAD tất định (không LLM trong lõi).

Kiến trúc (theo sơ đồ "1 Master Agent + Skill 00 + 10 Skill + Validator + AutoCAD"):

    Đầu vào (DXF / đề bài JSON nhập tay / PDF-JPG-PNG làm ảnh nền tham chiếu / template DXF)
        │
        ▼  Skill 00 — reader.py: đọc kích thước, trục, tường, cột, cửa, layer/block; thiếu kích thước thì
        │            A. người dùng nhập (file kích thước) hoặc B. nội suy — nội suy KHÔNG BAO GIỜ tự coi là đã xác nhận
        ▼  Project Data Store — store.py: đọc một lần, mọi skill dùng chung; mỗi số liệu mang nguồn gốc
        │
        ▼  10 skill dựng hình — skills/s01..s10: mỗi skill chỉ ghi vào layer (vai trò) của mình
        │  CAD Validator — validator.py: kiểm tra sau MỖI bước, phát hiện xung đột, bắt skill sửa lấn phần skill khác
        ▼  Danh sách lệnh vẽ — plan.py: một nguồn duy nhất, xuất ra DXF (ezdxf), AutoLISP và JSON cho máy chủ MCP
        │
        ▼  Đầu ra: DXF, PDF/PNG, báo cáo kiểm tra, dữ liệu dự án (JSON). DWG cần AutoCAD (mở DXF → SAVEAS).

Đơn vị: mm, toạ độ không gian mô hình (model space). Tỷ lệ in lấy từ ProjectInfo.scale.
"""
