# -*- coding: utf-8 -*-
"""
XUẤT XEM TRƯỚC PDF / PNG từ file DXF (ezdxf.addons.drawing + matplotlib, backend "Agg" — không cần màn hình).

  - Có khung giấy `frame` = [xmin, ymin, xmax, ymax] (mm model space, mép giấy) và `paper_mm` = [rộng, cao]:
    figure đúng khổ giấy (inch = mm / 25,4), trục phủ kín figure, giới hạn trục = frame → in PDF ra đúng tỷ lệ
    1:(frame / giấy). "dung_ty_le" được TÍNH: True chỉ khi tỷ lệ theo X và theo Y trùng nhau (sai lệch ≤ 0,1 %).
  - Không có frame: hình co giãn vừa nội dung, "dung_ty_le" = False (chỉ để xem, không để đo trên giấy).
  - monochrome=True: mọi nét đen trên nền trắng (ColorPolicy.BLACK, BackgroundPolicy.WHITE) như bản in.
  - Layer có cờ plot = 0 (KT-KIEM-TRA, ảnh nền...) và layer trong `hide_layers` không được vẽ. Muốn ảnh PNG soát lỗi
    vẫn hiện một layer không in (vd đánh dấu của Validator) thì nêu tên ở `show_layers` (hide_layers vẫn được ưu tiên).
  - Thiếu matplotlib → RenderUnavailable (thông báo rõ), Master ghi thành cảnh báo thay vì dừng.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional, Sequence

MM_PER_INCH = 25.4
SCALE_TOLERANCE = 1e-3               # sai lệch tương đối cho phép giữa tỷ lệ X và Y khi coi là "đúng tỷ lệ"
FORMATS = (".pdf", ".png")


class RenderUnavailable(RuntimeError):
    """Không xuất được xem trước vì thiếu thư viện (matplotlib / ezdxf.addons.drawing)."""


def _load_backend():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    except ImportError as e:
        raise RenderUnavailable(
            f"Không xuất được PDF/PNG: thiếu thư viện vẽ ({e}). Cài matplotlib (pip install matplotlib) "
            f"— DXF và AutoLISP vẫn xuất bình thường.") from e
    return plt, Frontend, RenderContext, MatplotlibBackend, Configuration, ColorPolicy, BackgroundPolicy


def _frame_scale(frame: Sequence[float], paper_mm: Sequence[float]) -> Dict[str, Any]:
    xmin, ymin, xmax, ymax = (float(v) for v in frame)
    w, h = float(paper_mm[0]), float(paper_mm[1])
    if xmax <= xmin or ymax <= ymin:
        raise ValueError(f"khung giấy sai: {list(frame)} (cần xmin < xmax, ymin < ymax)")
    if w <= 0 or h <= 0:
        raise ValueError(f"khổ giấy sai: {list(paper_mm)}")
    sx, sy = (xmax - xmin) / w, (ymax - ymin) / h
    same = abs(sx - sy) <= SCALE_TOLERANCE * max(sx, sy)
    return {"sx": sx, "sy": sy, "dung_ty_le": bool(same)}


# Backend matplotlib của ezdxf dùng thẳng lineweight (mm) làm linewidth (pt) và chặn dưới ở 72/dpi pt (≈ 0,25 mm),
# làm mọi nét ≤ 0,7 mm in ra như nhau. Quy đổi mm → pt để PDF giữ đúng phân cấp nét (0,09 … 0,5 mm).
MM_TO_PT = 72.0 / 25.4
MIN_LINEWEIGHT_MM = 0.05


def render_preview(dxf_path: str, out_path: str, frame: Optional[Sequence[float]] = None,
                   paper_mm: Optional[Sequence[float]] = None, dpi: int = 200, monochrome: bool = True,
                   hide_layers: Iterable[str] = (), show_layers: Iterable[str] = ()) -> Dict[str, Any]:
    """Vẽ model space của `dxf_path` ra `out_path` (.pdf hoặc .png). Trả dict tóm tắt:

      file, dinh_dang, dung_ty_le, ty_le_in (1:N khi đúng tỷ lệ, None nếu không), paper_mm, frame, dpi,
      kich_thuoc_px (PNG), an_layer (layer không vẽ: plot = 0 + hide_layers), monochrome, canh_bao.
    """
    ext = os.path.splitext(out_path)[1].lower()
    if ext not in FORMATS:
        raise ValueError(f"định dạng xem trước '{ext}' không hỗ trợ (chỉ {', '.join(FORMATS)})")
    plt, Frontend, RenderContext, MatplotlibBackend, Configuration, ColorPolicy, BackgroundPolicy = _load_backend()
    import ezdxf

    warn = []
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    hide = {str(n).upper() for n in (hide_layers or ())}
    show = {str(n).upper() for n in (show_layers or ())} - hide
    no_plot = {layer.dxf.name.upper() for layer in doc.layers if not layer.dxf.get("plot", 1)}
    hidden = hide | (no_plot - show)
    off_layers = {layer.dxf.name.upper() for layer in doc.layers if not layer.is_on() or layer.is_frozen()}
    shown_names = {layer.dxf.name.upper() for layer in doc.layers}
    for n in sorted(hide - shown_names):
        warn.append(f"layer cần ẩn '{n}' không có trong DXF")

    # export_mode=True: frontend tự bỏ layer plot = 0; override bỏ thêm hide_layers (kể cả hình trong block)
    # và bật lại layer không in được nêu trong show_layers (trừ layer đang tắt/đóng băng trong DXF)
    ctx = RenderContext(doc, export_mode=True)

    def _override(layers):
        for lp in layers:
            name = str(lp.layer).upper()
            if name in hidden:
                lp.is_visible = False
            elif name in show and name not in off_layers:
                lp.is_visible = True

    ctx.set_layer_properties_override(_override)
    if monochrome:
        config = Configuration(color_policy=ColorPolicy.BLACK, background_policy=BackgroundPolicy.WHITE,
                               lineweight_scaling=MM_TO_PT, min_lineweight=MIN_LINEWEIGHT_MM * MM_TO_PT)
    else:
        config = Configuration(background_policy=BackgroundPolicy.WHITE,
                               lineweight_scaling=MM_TO_PT, min_lineweight=MIN_LINEWEIGHT_MM * MM_TO_PT)

    scale_info: Optional[Dict[str, Any]] = None
    if frame is not None and paper_mm is not None:
        scale_info = _frame_scale(frame, paper_mm)
        fig = plt.figure(figsize=(float(paper_mm[0]) / MM_PER_INCH, float(paper_mm[1]) / MM_PER_INCH))
        ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
        backend = MatplotlibBackend(ax, adjust_figure=False)
    else:
        if frame is not None or paper_mm is not None:
            warn.append("cần cả frame và paper_mm để in đúng tỷ lệ — xuất dạng vừa nội dung")
        fig = plt.figure()
        ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
        backend = MatplotlibBackend(ax, adjust_figure=True)

    try:
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        Frontend(ctx, backend, config=config).draw_layout(
            msp, finalize=True, filter_func=lambda e: e.dxf.get("layer", "0").upper() not in hidden)
        if scale_info is not None:
            xmin, ymin, xmax, ymax = (float(v) for v in frame)
            ax.set_aspect("auto")
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)
            ax.set_position((0.0, 0.0, 1.0, 1.0))
        ax.set_axis_off()
        fig.savefig(out_path, dpi=int(dpi), facecolor="white")
        width_in, height_in = (float(v) for v in fig.get_size_inches())
    finally:
        plt.close(fig)

    info: Dict[str, Any] = {
        "file": os.path.basename(out_path),
        "dinh_dang": ext[1:],
        "dung_ty_le": bool(scale_info and scale_info["dung_ty_le"]),
        "ty_le_in": None,
        "paper_mm": [round(width_in * MM_PER_INCH, 3), round(height_in * MM_PER_INCH, 3)],
        "frame": [float(v) for v in frame] if frame is not None else None,
        "dpi": int(dpi),
        "monochrome": bool(monochrome),
        "an_layer": sorted(hidden & shown_names),
        "canh_bao": warn,
    }
    if scale_info is not None:
        if scale_info["dung_ty_le"]:
            info["ty_le_in"] = round((scale_info["sx"] + scale_info["sy"]) / 2.0, 6)
        else:
            warn.append(f"khung giấy và khổ giấy khác tỷ lệ (X 1:{scale_info['sx']:.3f}, Y 1:{scale_info['sy']:.3f}) "
                        f"— PDF không đo được trên giấy")
    if ext == ".png":
        info["kich_thuoc_px"] = _png_size(out_path)
    return info


def _png_size(path: str):
    """Kích thước ảnh PNG đọc từ khối IHDR của file đã ghi (đo, không tính lại từ dpi)."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return [int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")]
