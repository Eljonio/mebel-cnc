"""Сквозной конвейер: изделия (YAML) -> модель -> проверки -> деталировка -> раскрой -> DXF -> Excel -> 3D -> сверка."""
from __future__ import annotations

import json
import os
import shutil

from . import assumptions as assum
from . import checks as chk
from . import cutmap, dxf_out, nesting, xlsx_out
from .builder import build
from .config import load_product, load_shop
from .parts import detailing, fmt
from .post import MachineNotConfigured, MachineProfile, PostProcessor, sheet_operations
from .viewer import build_viewer, model_json


class CheckFailed(RuntimeError):
    pass


def run(product_paths: list[str], out_dir: str, shop_path: str | None = None, viewer: bool = True,
        strict: bool = True) -> dict:
    shop = load_shop(shop_path)
    products = [build(load_product(p), shop) for p in product_paths]
    title = " + ".join(p.name + (f" ×{p.qty}" if p.qty > 1 else "") for p in products)
    parts = detailing(products)

    findings = {p.id: chk.run_all(p, detailing([p])) for p in products}
    errs = [f for fl in findings.values() for f in chk.errors(fl)]
    if errs and strict:
        raise CheckFailed("\n".join(f"{e.check}: {e.text}" for e in errs))

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    for sub in ("dxf/parts", "dxf/sheets", "cutmap", "ops"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    # раскрой по материалам
    results = []
    nest_errs = []
    for m in sorted({p.material for p in parts}, key=lambda k: -shop["materials"][k]["thickness"]):
        r = nesting.nest(parts, shop, m)
        results.append(r)
        nest_errs += nesting.verify(r, parts, shop)
    if nest_errs and strict:
        raise CheckFailed("\n".join(nest_errs))
    pngs = cutmap.render(results, title, shop["materials"], os.path.join(out_dir, "cutmap"),
                         os.path.join(out_dir, "cutmap.pdf"))

    # DXF: деталь и лист + обратное чтение
    dxf_errs = []
    part_files = []
    for p in parts:
        mat = shop["materials"][p.material]
        path = os.path.join(out_dir, "dxf/parts", f"{p.no}_{dxf_out.slug(p.name)}.dxf")
        dxf_out.write_part_dxf(p, path, title, mat)
        dxf_errs += dxf_out.verify_part_dxf(p, path)
        part_files.append(path)
    sheet_files = []
    ops_files = []
    for r in results:
        mat = shop["materials"][r.material]
        for s in r.sheets:
            path = os.path.join(out_dir, "dxf/sheets", f"{r.material}_list{s.index:02d}.dxf")
            dxf_out.write_sheet_dxf(s, path, title, mat)
            dxf_errs += dxf_out.verify_sheet_dxf(s, path)
            sheet_files.append(path)
            ops = sheet_operations(s, title, mat)
            op_path = os.path.join(out_dir, "ops", f"{r.material}_list{s.index:02d}.json")
            with open(op_path, "w", encoding="utf-8") as f:
                json.dump(ops, f, ensure_ascii=False, indent=1)
            ops_files.append(op_path)
    if dxf_errs and strict:
        raise CheckFailed("\n".join(dxf_errs))
    with open(os.path.join(out_dir, "dxf", "README.txt"), "w", encoding="utf-8") as f:
        f.write(DXF_README.format(title=title))

    # постпроцессор: только охрана — станка нет
    post_state = "G-code не выдан: станок не задан"
    try:
        PostProcessor(MachineProfile.load("none")).generate({})
        post_state = "ОШИБКА: постпроцессор что-то выдал без станка"
    except MachineNotConfigured:
        pass

    xlsx = os.path.join(out_dir, "specifikaciya.xlsx")
    xlsx_out.write(xlsx, title, parts, products, results, findings, shop, assum.build(shop))
    xlsx_errs = xlsx_out.verify(xlsx, parts, results)

    models = [model_json(p, detailing([p])) for p in products]
    with open(os.path.join(out_dir, "model.json"), "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False)
    viewer_paths = []
    if viewer:
        for mj in models:
            vp = os.path.join(out_dir, f"3d_{mj['id']}.html")
            build_viewer(vp, mj)
            viewer_paths.append(vp)

    summary = {
        "title": title, "out": out_dir, "parts": len(parts), "pieces": sum(p.qty for p in parts),
        "holes": sum(len(p.holes) * p.qty for p in parts),
        "sheets": [(r.material, len(r.sheets), [round(s.util * 100, 1) for s in r.sheets]) for r in results],
        "errors": [e.text for e in errs] + nest_errs + dxf_errs + xlsx_errs,
        "dxf_checked": len(part_files) + len(sheet_files), "post": post_state,
        "files": {"xlsx": xlsx, "pdf": os.path.join(out_dir, "cutmap.pdf"), "png": pngs, "dxf_parts": part_files,
                  "dxf_sheets": sheet_files, "ops": ops_files, "viewer": viewer_paths},
    }
    with open(os.path.join(out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(format_summary(summary, findings))
    return {"summary": summary, "products": products, "parts": parts, "results": results, "findings": findings,
            "shop": shop, "models": models}


def format_summary(s: dict, findings: dict) -> str:
    lines = [f"{s['title']}", f"Позиций деталей: {s['parts']}, деталей всего: {s['pieces']}, отверстий: {s['holes']}"]
    for m, n, utils in s["sheets"]:
        lines.append(f"Раскрой {m}: листов {n}, использование {', '.join(fmt(u) + ' %' for u in utils)}")
    lines.append(f"DXF записано и прочитано обратно: {s['dxf_checked']} файлов, расхождений: "
                 f"{len([e for e in s['errors'] if 'слой' in e or 'контур' in e])}")
    lines.append(f"Постпроцессор: {s['post']}")
    lines.append("Проверки:")
    for pid, fl in findings.items():
        for f in fl:
            mark = {"ok": "  ✓", "info": "  i", "warn": "  !", "error": "  ✗"}[f.level]
            lines.append(f"{mark} [{pid}] {f.check}: {f.text}")
    lines.append("Ошибок: " + (str(len(s["errors"])) if s["errors"] else "0"))
    return "\n".join(lines) + "\n"


DXF_README = """{title}
DXF для проверки, НЕ для запуска: станок не задан.

parts/  — каждая деталь отдельно: смотрим на обрабатываемую пласть, ноль — левый нижний угол пильной заготовки.
sheets/ — листы раскроя: детали на своих местах, ноль — левый нижний угол листа, X — вдоль длины (текстура).

Слои:
  CONTOUR                — контур (пильный размер, кромка ещё не наклеена)
  DRILL_V_D<Ø>_Z<гл.>    — отверстие в пласть сверху (пример: DRILL_V_D35_Z13 — чашка петли Ø35 глубиной 13)
  DRILL_V_D<Ø>_THRU      — сквозное
  DRILL_H_D<Ø>_Z<гл.>    — отверстие в торец: отрезок от торца внутрь, ось на середине толщины
  GROOVE_W<шир.>_Z<гл.>  — паз, осевая линия
  SHEET / TRIM           — лист и граница обрезки
  LABELS                 — номера деталей, НЕ РЕЗАТЬ
Точка в числе заменена на «p»: D7p5 = Ø7,5.
Шапка (изделие, дата, материал, толщина, ноль, станок, инструмент) — в свойствах файла.
"""
