# -*- coding: utf-8 -*-
"""Đề bài minh hoạ (nhà ở mẫu 1 tầng) dùng cho kiểm thử và chạy thử. Số liệu tự đặt, không phải hồ sơ thật."""

from __future__ import annotations

import os

from tools.cad_drafting.store import SRC_USER, ProjectStore, Provenance

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_SPEC = os.path.join(ROOT, "examples", "DUNG_CAD_NHA_MAU", "de_bai_mat_bang_tang1.json")

# Hai số liệu đề bài cố ý để trống (để chạy thử nội suy). filled=True điền như NGƯỜI DÙNG nhập.
SAMPLE_FILL = {"axes:V.spans[1]": 3600.0, "openings:CD4.width": 900.0}


def load_sample(filled: bool = True) -> ProjectStore:
    store = ProjectStore.load(SAMPLE_SPEC)
    if filled:
        for key, value in SAMPLE_FILL.items():
            store.set_value(key, value, Provenance(SRC_USER, "giá trị điền sẵn cho kiểm thử"))
    return store
