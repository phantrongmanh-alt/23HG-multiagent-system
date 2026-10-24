# -*- coding: utf-8 -*-
"""
MASTER AGENT — điều phối dựng bản vẽ CAD: Skill 00 → kiểm tra dữ liệu → 10 skill (Validator sau MỖI bước) → xuất.

Tư duy cốt lõi: đọc 1 lần → lưu dữ liệu chung → vẽ theo từng skill → kiểm tra liên tục.

"Chỉ sửa phần liên quan": khi chạy lại vào cùng thư mục kết quả với cap_nhat=True, Master so dấu vân tay từng mục
dữ liệu (store.section_hashes) với lần trước, chỉ chạy lại skill có `reads` dính mục đã đổi; Op của các skill khác giữ
nguyên và Validator xác nhận dấu vân tay của chúng không đổi.

Kết luận ĐẠT được TÍNH: không LOI, không NGHI_VAN, không đối tượng nào bị bỏ qua chưa vẽ. Đạt kiểm tra tự động vẫn
chỉ là "chờ kỹ sư duyệt" — phê duyệt là việc của người (store.approve).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from tools.cad_drafting import validator
from tools.cad_drafting.layers import SHEET_SIZES_MM
from tools.cad_drafting.plan import DrawingPlan
from tools.cad_drafting.skills import SKILL_MODULES, all_skills, new_plan
from tools.cad_drafting.skills.base import WARN_PREFIX
from tools.cad_drafting.store import (SEV_DOUBT, SEV_ERROR, SEV_WARN, SRC_INTERP, Issue, ProjectStore)

REPORT_SCHEMA = "23hg-cad-report/1"
PLAN_FILE = "{base}_lenh_ve.json"          # danh sách lệnh vẽ — cũng là giao thức gửi máy chủ MCP
# tên file đều mang tên gốc bản vẽ để nhiều bản vẽ chung một thư mục không ghi đè nhau
REPORT_JSON = "{base}_bao_cao_kiem_tra.json"
REPORT_MD = "{base}_BAO_CAO_KIEM_TRA.md"
STORE_FILE = "{base}_du_lieu_du_an.json"


@dataclass
class StepRecord:
    code: str
    name: str
    ran: bool                                   # False = giữ nguyên Op lần trước (chế độ cập nhật)
    ops: int
    skipped: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "name": self.name, "ran": self.ran, "ops": self.ops,
                "skipped": self.skipped, "notes": self.notes, "issues": [_issue_dict(i) for i in self.issues]}


@dataclass
class RunReport:
    base: str
    data_status: Dict[str, Any]
    precheck: List[Issue]
    steps: List[StepRecord]
    final: List[Issue]
    export_issues: List[Issue]
    outputs: Dict[str, Dict[str, Any]]
    rerun: List[str]
    kept: List[str]
    section_hashes: Dict[str, str]
    interpolations: List[Dict[str, Any]] = field(default_factory=list)

    def all_issues(self) -> List[Issue]:
        out = list(self.precheck)
        for s in self.steps:
            out += s.issues
        return out + list(self.final) + list(self.export_issues)

    def counts(self) -> Dict[str, int]:
        c = {SEV_ERROR: 0, SEV_DOUBT: 0, SEV_WARN: 0}
        for i in _dedupe(self.all_issues()):
            c[i.severity] += 1
        c["doi_tuong_chua_ve"] = sum(len(s.skipped) for s in self.steps)
        return c

    @property
    def dat(self) -> bool:
        c = self.counts()
        return c[SEV_ERROR] == 0 and c[SEV_DOUBT] == 0 and c["doi_tuong_chua_ve"] == 0

    def ket_luan(self) -> str:
        c = self.counts()
        if self.dat:
            if self.data_status.get("trang_thai") == "DA_DUYET":
                return f"ĐẠT KIỂM TRA TỰ ĐỘNG — DỮ LIỆU ĐÃ DUYỆT ({self.data_status.get('duyet_boi')})"
            return "ĐẠT KIỂM TRA TỰ ĐỘNG — CHỜ KỸ SƯ DUYỆT"
        return (f"CHƯA ĐẠT: {c[SEV_ERROR]} lỗi, {c[SEV_DOUBT]} nghi vấn, "
                f"{c['doi_tuong_chua_ve']} đối tượng chưa vẽ, {c[SEV_WARN]} cảnh báo")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA, "base": self.base, "ket_luan": self.ket_luan(), "dat": self.dat,
            "dem": self.counts(), "trang_thai_du_lieu": self.data_status,
            "noi_suy": self.interpolations,
            "kiem_tra_truoc_khi_ve": [_issue_dict(i) for i in self.precheck],
            "cac_buoc": [s.to_dict() for s in self.steps],
            "kiem_tra_cuoi": [_issue_dict(i) for i in self.final],
            "kiem_tra_xuat": [_issue_dict(i) for i in self.export_issues],
            "skill_chay_lai": self.rerun, "skill_giu_nguyen": self.kept,
            "section_hashes": self.section_hashes, "dau_ra": self.outputs,
        }


def _issue_dict(i: Issue) -> Dict[str, Any]:
    return {"severity": i.severity, "code": i.code, "message": i.message, "skill": i.skill,
            "eids": list(i.eids), "where": i.where}


def _dedupe(issues: Iterable[Issue]) -> List[Issue]:
    """Một mục có thể được báo nhiều lần (Skill 00 và precheck cùng thấy chữ ghi đè; precheck và kiểm tra cuối cùng thấy
    thiếu kích thước / nội suy) — chỉ đếm một lần: cùng mức độ + mã + đối tượng (eids), hoặc cùng lời văn nếu không
    có eids."""
    seen, out = set(), []
    for i in issues:
        key = (i.severity, i.code, tuple(i.eids)) if i.eids else (i.severity, i.code, i.message)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class CadDraftingMaster:
    """Master Agent. Không giữ trạng thái giữa các lần chạy ngoài thư mục kết quả."""

    def __init__(self, stop_on_error: bool = False, log=print):
        self.stop_on_error = stop_on_error
        self.log = log or (lambda *_: None)

    # ── vẽ ───────────────────────────────────────────────────────────────────

    def draw(self, store: ProjectStore, plan: Optional[DrawingPlan] = None,
             rerun: Optional[Iterable[str]] = None):
        """Chạy các skill (tất cả, hoặc chỉ `rerun` khi đã có plan cũ). Trả (plan, các bước, chạy lại, giữ nguyên)."""
        fresh = new_plan(store)
        if plan is None:
            plan = fresh
            todo = {c for c, _, _ in SKILL_MODULES}
        else:
            # cập nhật layer/kiểu theo store hiện tại, giữ Op cũ
            plan.layers, plan.dimstyles, plan.text_style = fresh.layers, fresh.dimstyles, fresh.text_style
            plan.meta.update(fresh.meta)
            todo = set(rerun or ())
        steps: List[StepRecord] = []
        rerun_codes, kept = [], []
        for skill in all_skills():
            if skill.code not in todo:
                # giữ Op cũ nhưng vẫn kiểm tra lại với dữ liệu hiện tại (vd tường đổi → nội thất có thể đè tường)
                kept.append(skill.code)
                issues = validator.check_step(store, plan, skill.code, plan.fingerprints())
                steps.append(StepRecord(skill.code, skill.name, False, len(plan.ops_of(skill=skill.code)),
                                        issues=issues))
                continue
            if skill.code == "10":
                plan.meta["validator_issues"] = [
                    _issue_dict(i) for s in steps for i in s.issues if i.where is not None]
            before = plan.fingerprints()
            result = skill.run(store, plan)
            issues = validator.check_step(store, plan, skill.code, before)
            issues += [Issue(severity=SEV_WARN, code="SKILL_CANH_BAO", message=n, skill=skill.code)
                       for n in result.notes if n.startswith(WARN_PREFIX)]
            rec = StepRecord(skill.code, skill.name, True, result.ops_added, list(result.skipped),
                             list(result.notes), issues)
            steps.append(rec)
            rerun_codes.append(skill.code)
            n_err = sum(1 for i in issues if i.severity == SEV_ERROR)
            self.log(f"  [{skill.code}] {skill.name}: {result.ops_added} lệnh vẽ, {len(result.skipped)} bỏ qua, "
                     f"{len(issues)} phát hiện ({n_err} lỗi)")
            if n_err and self.stop_on_error:
                self.log(f"  ✗ Dừng sau skill {skill.code} vì có lỗi (stop_on_error)")
                break
        plan.meta.pop("validator_issues", None)
        return plan, steps, rerun_codes, kept

    # ── chạy trọn gói ───────────────────────────────────────────────────────

    def run(self, store: ProjectStore, out_dir: str, base: Optional[str] = None,
            cap_nhat: bool = False, only: Optional[Iterable[str]] = None,
            reference_paths: Optional[Iterable[str]] = None, pdf: bool = True,
            interpolations: Optional[List[Dict[str, Any]]] = None) -> RunReport:
        os.makedirs(out_dir, exist_ok=True)
        base = base or (store.project.drawing_no or "BAN_VE").replace(" ", "_")
        plan_path = os.path.join(out_dir, PLAN_FILE.format(base=base))
        report_path = os.path.join(out_dir, REPORT_JSON.format(base=base))
        md_name = REPORT_MD.format(base=base)
        store_name = STORE_FILE.format(base=base)

        self.log("[Skill 00] Kiểm tra dữ liệu trước khi vẽ")
        pre = list(store.issues) + validator.precheck(store)      # vấn đề lúc đọc bản vẽ + kiểm tra dữ liệu
        hashes = store.section_hashes()

        plan, rerun = None, None
        if only:
            rerun = {str(c).zfill(2) for c in only}
            if os.path.exists(plan_path):
                plan = DrawingPlan.load(plan_path)
            else:
                self.log("  (chưa có lệnh vẽ lần trước — chạy toàn bộ)")
                rerun = None
        elif cap_nhat and os.path.exists(plan_path) and os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as f:
                old_hashes = json.load(f).get("section_hashes", {})
            changed = {s for s, h in hashes.items() if old_hashes.get(s) != h}
            plan = DrawingPlan.load(plan_path)
            rerun = {s.code for s in all_skills() if changed & set(s.reads)}
            self.log(f"  Cập nhật: mục dữ liệu đổi {sorted(changed) or 'không có'} → chạy lại skill {sorted(rerun) or 'không'}")
        if rerun is not None and rerun:
            rerun.add("10")          # khung tên ghi trạng thái số liệu — luôn tính lại khi có thay đổi

        plan, steps, ran, kept = self.draw(store, plan, rerun)
        results = [_StepResult(s) for s in steps if s.ran]
        final = validator.check_final(store, plan, results)

        outputs: Dict[str, Dict[str, Any]] = {}
        export_issues: List[Issue] = []
        plan.save(plan_path)
        outputs["lenh_ve_json"] = {"file": os.path.basename(plan_path)}
        store.save(os.path.join(out_dir, store_name))
        outputs["du_lieu_du_an"] = {"file": store_name}
        export_issues += self._export(plan, store, out_dir, base, outputs, reference_paths, pdf)

        for meta in outputs.values():
            p = os.path.join(out_dir, meta["file"]) if meta.get("file") else ""
            if p and os.path.isfile(p):
                meta["bytes"] = os.path.getsize(p)
        report = RunReport(base=base, data_status=store.status(), precheck=pre, steps=steps, final=final,
                           export_issues=export_issues, outputs=outputs, rerun=ran, kept=kept,
                           section_hashes=hashes, interpolations=list(interpolations or []))
        outputs["bao_cao"] = {"file": md_name}
        with open(os.path.join(out_dir, md_name), "w", encoding="utf-8") as f:
            f.write(render_report_md(report, store, plan))
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=1)
        self.log(f"  ⇒ {report.ket_luan()}")
        return report

    # ── xuất ────────────────────────────────────────────────────────────────

    def _export(self, plan: DrawingPlan, store: ProjectStore, out_dir: str, base: str,
                outputs: Dict[str, Dict[str, Any]], reference_paths, pdf: bool) -> List[Issue]:
        from tools.cad_drafting import render_dxf, render_lisp

        issues: List[Issue] = []
        underlays = []
        refs = {os.path.basename(p): p for p in (reference_paths or [])}
        for src in store.sources:
            if src.used_for != "anh_nen":
                continue
            path = refs.get(src.name)
            if path and os.path.abspath(os.path.dirname(path)) != os.path.abspath(out_dir):
                shutil.copyfile(path, os.path.join(out_dir, src.name))
            underlays.append({"name": src.name, "kind": src.kind, "underlay": src.underlay or {}})

        dxf_path = os.path.join(out_dir, f"{base}.dxf")
        summary = render_dxf.render_dxf(plan, dxf_path, underlays=underlays or None)
        outputs["dxf"] = {"file": os.path.basename(dxf_path), "tom_tat": summary}
        expected: Dict[str, int] = {}
        for r, n in plan.count_by_role().items():          # template có thể gán hai vai trò vào cùng một layer
            expected[plan.layers[r].name] = expected.get(plan.layers[r].name, 0) + n
        got = render_dxf.read_back_counts(dxf_path)
        lech = {name: (n, got.get(name, 0)) for name, n in expected.items() if got.get(name, 0) != n}
        if lech:
            issues.append(Issue(severity=SEV_ERROR, code="XUAT_DXF_LECH", skill="XUAT",
                                message="Số thực thể trong DXF đọc lại khác danh sách lệnh vẽ (layer: lệnh, DXF): "
                                        + "; ".join(f"{k}: {a}≠{b}" for k, (a, b) in sorted(lech.items()))))
        if summary.get("audit_errors"):
            issues.append(Issue(severity=SEV_WARN, code="XUAT_DXF_AUDIT", skill="XUAT",
                                message=f"ezdxf audit báo {summary['audit_errors']} lỗi trong DXF"))

        lsp_path = os.path.join(out_dir, f"{base}.lsp")
        lisp_summary = render_lisp.render_lisp(plan, lsp_path)
        with open(lsp_path, encoding="ascii", errors="replace") as f:
            problems = render_lisp.lisp_static_check(f.read())
        outputs["lisp"] = {"file": os.path.basename(lsp_path), "tom_tat": lisp_summary,
                           "kiem_tra_tinh": problems or "không phát hiện lỗi cú pháp tĩnh",
                           "chay_tren_autocad": "CHƯA chạy thử"}
        if problems:
            issues.append(Issue(severity=SEV_ERROR, code="XUAT_LISP_SAI_CU_PHAP", skill="XUAT",
                                message="AutoLISP sinh ra lỗi cú pháp tĩnh: " + "; ".join(problems[:5])))

        if pdf:
            try:
                from tools.cad_drafting import render_preview
            except ImportError as e:      # pragma: no cover — thiếu matplotlib
                render_preview = None
                issues.append(Issue(severity=SEV_WARN, code="XUAT_PDF_KHONG_DUOC", skill="XUAT",
                                    message=f"Không xuất được PDF/PNG: {e}"))
            if render_preview is not None:
                frame = plan.meta.get("sheet_frame")
                paper = (plan.meta.get("sheet") or {}).get("paper_mm") or list(
                    SHEET_SIZES_MM.get(store.project.sheet, (420.0, 297.0)))
                hidden = [plan.layers[r].name for r in ("kiem_tra", "anh_nen") if r in plan.layers]
                for ext, key in ((".pdf", "pdf"), (".png", "png")):
                    out = os.path.join(out_dir, f"{base}{ext}")
                    try:
                        # PDF để in: ẩn layer kiểm tra và ảnh nền; PNG để soát: hiện đánh dấu kiểm tra
                        info = render_preview.render_preview(
                            dxf_path, out, frame=frame, paper_mm=paper if frame else None,
                            dpi=200 if ext == ".png" else 300,
                            hide_layers=hidden if ext == ".pdf" else [plan.layers["anh_nen"].name],
                            show_layers=() if ext == ".pdf" else [plan.layers["kiem_tra"].name])
                        outputs[key] = {"file": os.path.basename(out), "tom_tat": info}
                    except render_preview.RenderUnavailable as e:
                        issues.append(Issue(severity=SEV_WARN, code="XUAT_PDF_KHONG_DUOC", skill="XUAT",
                                            message=f"Không xuất được {ext}: {e}"))
        outputs["dwg"] = {"file": "", "ghi_chu": "Không sinh DWG: cần AutoCAD (mở DXF → SAVEAS, hoặc máy chủ cad-mcp)."}
        return issues


class _StepResult:
    """Bọc StepRecord thành dạng SkillResult cho validator.check_final."""

    def __init__(self, rec: StepRecord):
        self.code, self.name = rec.code, rec.name
        self.skipped, self.notes, self.ops_added = rec.skipped, rec.notes, rec.ops


# ─────────────────────────────────────────────────────────────────────────────
# BÁO CÁO
# ─────────────────────────────────────────────────────────────────────────────

_SEV_LABEL = {SEV_ERROR: "LỖI", SEV_DOUBT: "NGHI VẤN", SEV_WARN: "CẢNH BÁO"}


def _md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_report_md(report: RunReport, store: ProjectStore, plan: DrawingPlan) -> str:
    c = report.counts()
    st = report.data_status
    p = store.project
    lines = [
        f"# Báo cáo kiểm tra bản vẽ {p.drawing_no} — {p.drawing_title}",
        "",
        f"- Dự án: {p.name or '(chưa đặt tên)'} · Tỷ lệ 1:{p.scale} · Khổ {p.sheet}",
        f"- **Kết luận (tính tự động): {report.ket_luan()}**",
        f"- Trạng thái số liệu: `{st['trang_thai']}` — thiếu {st['so_lieu_thieu']}, "
        f"nội suy chưa xác nhận {st['noi_suy_chua_xac_nhan']}",
        f"- Đếm: {c[SEV_ERROR]} lỗi · {c[SEV_DOUBT]} nghi vấn · {c[SEV_WARN]} cảnh báo · "
        f"{c['doi_tuong_chua_ve']} đối tượng chưa vẽ · {len(plan.ops)} lệnh vẽ",
        "",
        "## Nguồn dữ liệu",
        "",
        "| File | Loại | Dùng cho | SHA-256 (12 ký tự đầu) | Ghi chú |",
        "|---|---|---|---|---|",
    ]
    for s in store.sources:
        lines.append(f"| {_md(s.name)} | {s.kind} | {s.used_for} | {s.sha256[:12]} | {_md(s.note)} |")
    if not store.sources:
        lines.append("| (không ghi nguồn) | | | | |")

    unconf = store.unconfirmed()
    lines += ["", "## Số liệu nội suy (B) — CHƯA được coi là đã xác nhận", ""]
    interp_keys = []
    for o, g in sorted(store.axes.items()):
        for i, pv in enumerate(g.span_prov):
            if pv is not None and pv.source == SRC_INTERP:
                interp_keys.append(f"axes:{o}.spans[{i}]")
    for coll in ("columns", "walls", "openings", "stairs"):
        for e in getattr(store, coll):
            for name, pv in sorted(e.field_prov.items()):
                if pv.source == SRC_INTERP:
                    interp_keys.append(f"{coll}:{e.id}.{name}")
    if interp_keys:
        lines += ["| Khoá | Giá trị | Cách nội suy | Xác nhận |", "|---|---|---|---|"]
        for k in interp_keys:
            pv = store.get_provenance(k)
            lines.append(f"| `{k}` | {store.get_value(k)} | {_md(pv.ref)} | "
                         f"{'đã xác nhận: ' + _md(pv.confirmed_by) if pv.confirmed else '**chưa**'} |")
    else:
        lines.append("Không có.")
    not_interp = [r for r in report.interpolations if r.get("value") is None]
    if not_interp:
        lines += ["", "Mục thiếu KHÔNG nội suy được (cần nhập tay — phương án A):", ""]
        lines += [f"- `{r.get('key')}`: {_md(r.get('reason', ''))}" for r in not_interp]
    missing = store.missing()
    lines += ["", "## Kích thước còn thiếu", ""]
    lines += [f"- `{m.key}` — {m.description}" for m in missing] or ["Không có."]
    if unconf:
        lines += ["", f"Còn {len(unconf)} số liệu nội suy chưa xác nhận: xác nhận bằng file kích thước nhập "
                      "(mục `xac_nhan`) sau khi đối chiếu bản vẽ."]

    lines += ["", "## Các bước (Validator chạy sau mỗi bước)", "",
              "| Skill | Tên | Chạy | Lệnh vẽ | Bỏ qua | Lỗi | Nghi vấn | Cảnh báo |", "|---|---|---|---|---|---|---|---|"]
    for s in report.steps:
        sev = {k: sum(1 for i in s.issues if i.severity == k) for k in (SEV_ERROR, SEV_DOUBT, SEV_WARN)}
        lines.append(f"| {s.code} | {s.name} | {'chạy' if s.ran else 'giữ nguyên'} | {s.ops} | {len(s.skipped)} | "
                     f"{sev[SEV_ERROR]} | {sev[SEV_DOUBT]} | {sev[SEV_WARN]} |")
    skipped = [(s.code, k) for s in report.steps for k in s.skipped]
    if skipped:
        lines += ["", "### Đối tượng chưa vẽ (kèm lý do)", ""]
        lines += [f"- Skill {code} — `{_md(k['id'])}`: {_md(k['ly_do'])}" for code, k in skipped]
    notes = [(s.code, n) for s in report.steps for n in s.notes]
    if notes:
        lines += ["", "### Ghi chú của skill", ""]
        lines += [f"- Skill {code}: {_md(n)}" for code, n in notes]

    issues = _dedupe(report.all_issues())
    lines += ["", "## Danh sách phát hiện", ""]
    for sev in (SEV_ERROR, SEV_DOUBT, SEV_WARN):
        group = [i for i in issues if i.severity == sev]
        lines += [f"### {_SEV_LABEL[sev]} ({len(group)})", ""]
        if not group:
            lines += ["Không có.", ""]
            continue
        lines += ["| Bước | Mã | Nội dung | Vị trí |", "|---|---|---|---|"]
        for i in group:
            where = f"({i.where[0]:.0f}, {i.where[1]:.0f})" if i.where else ""
            lines.append(f"| {i.skill} | {i.code} | {_md(i.message)} | {where} |")
        lines.append("")

    lines += ["## Đầu ra", "", "| Loại | File | Ghi chú |", "|---|---|---|"]
    for key, meta in report.outputs.items():
        note = meta.get("ghi_chu", "")
        if key == "lisp":
            note = f"kiểm tra tĩnh: {meta.get('kiem_tra_tinh')}; chạy trên AutoCAD: {meta.get('chay_tren_autocad')}"
        if "bytes" in meta:
            note = (note + " · " if note else "") + f"{meta['bytes']:,} byte".replace(",", ".")
        lines.append(f"| {key} | {meta.get('file') or '—'} | {_md(note)} |")
    lines += [
        "", "## Chưa làm / giới hạn", "",
        "- Không sinh DWG trực tiếp: mở file DXF trong AutoCAD rồi SAVEAS, hoặc giao danh sách lệnh vẽ JSON cho máy chủ cad-mcp.",
        "- File AutoLISP chỉ được kiểm tra cú pháp tĩnh, chưa chạy thử trên AutoCAD.",
        "- PDF/ảnh đầu vào chỉ làm ảnh nền tham chiếu, không tự nhận dạng số liệu (cấm đoán số OCR mờ) — số liệu nhập theo đề bài JSON.",
        "- Phạm vi hình học: tường thẳng, cột chữ nhật, thang vế thẳng, kích thước tường ngoài 3 cấp 4 phía (chưa ghi kích thước trong nhà).",
        "",
    ]
    return "\n".join(lines)
