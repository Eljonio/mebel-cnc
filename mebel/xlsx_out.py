"""Спецификация Excel (openpyxl, MIT): детали, присадка, кромка, фурнитура, листы, проверки, допущения."""
from __future__ import annotations

from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .parts import EDGE_NAMES, KIND_RU, Part, fmt

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="16233B")
WRAP = Alignment(wrap_text=True, vertical="top")


def _sheet(wb, title, header, rows, widths=None):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font, c.fill, c.alignment = HEAD, HEAD_FILL, WRAP
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def edge_totals(parts: list[Part], shop: dict) -> list[dict]:
    """Кромка по типам: чистые метры, число отрезков, метры с запасом."""
    allow = float(shop["edges"]["piece_allowance"])
    acc = defaultdict(lambda: {"m": 0.0, "pieces": 0})
    for p in parts:
        mat = shop["materials"][p.material]
        for e in EDGE_NAMES:
            th = p.edges[e]
            if not th:
                continue
            length = p.L if e.startswith("Д") else p.W
            key = (th, mat["thickness"], mat["name"])
            acc[key]["m"] += length * p.qty / 1000
            acc[key]["pieces"] += p.qty
    out = []
    for (th, t, mname), v in sorted(acc.items(), key=lambda kv: -kv[0][0]):
        out.append({"thickness": th, "width": t, "material": mname, "m": v["m"], "pieces": v["pieces"],
                    "m_allow": v["m"] + v["pieces"] * allow / 1000})
    return out


def hardware(parts: list[Part], products, shop: dict) -> list[tuple]:
    """Фурнитура из присадки: считаем по соединениям, а не по отверстиям."""
    fs = shop["fasteners"]
    cnt = Counter()
    for p in parts:
        for h in p.holes:
            cnt[h.kind] += p.qty
    rows = []
    if cnt["confirmat_face"]:
        rows.append((fs["confirmat"]["name"], cnt["confirmat_face"], "шт", "корпус", fs["confirmat"]["source"]))
        rows.append(("Заглушка под конфирмат (в цвет)", cnt["confirmat_face"], "шт", "шляпки конфирматов", "допущение"))
    if cnt["minifix_cam"]:
        rows.append((fs["minifix"]["name"], cnt["minifix_cam"], "компл", "крышка", fs["minifix"]["source"]))
    if cnt["dowel_face"]:
        rows.append((fs["dowel"]["name"], cnt["dowel_face"], "шт", "крышка", fs["dowel"]["source"]))
    if cnt["hinge_cup"]:
        rows.append((shop["hinges"]["name"], cnt["hinge_cup"], "шт", "двери", shop["hinges"]["source"]))
    if cnt["shelf_pin"]:
        n_shelves = sum(p.qty for p in parts if p.panel.role == "shelf")
        rows.append((shop["shelf_pins"]["name"], 4 * n_shelves, "шт",
                     f"съёмные полки ({n_shelves} шт × 4); отверстий {cnt['shelf_pin']} — с запасом под перестановку",
                     shop["shelf_pins"]["source"]))
    if cnt["handle"]:
        rows.append((shop["handle"]["name"] + " (межцентровое из изделия)", cnt["handle"] // 2, "шт", "двери",
                     shop["handle"]["source"]))
        rows.append(("Винт для ручки М4", cnt["handle"], "шт", "ручки", "допущение"))
    for prod in products:
        for name, qty, unit, note in prod.hardware:
            rows.append((name, qty * prod.qty, unit, note, "допущение"))
    return rows


def write(path: str, title: str, parts: list[Part], products, nest_results, findings_by_product, shop,
          assumptions: list[tuple]) -> str:
    wb = Workbook()
    wb.remove(wb.active)
    mats = shop["materials"]

    rows = []
    for p in parts:
        n_face = sum(1 for h in p.holes if not h.is_edge)
        n_edge = sum(1 for h in p.holes if h.is_edge)
        note = []
        if n_edge:
            note.append(f"торцевых отв. {n_edge}")
        if p.grooves:
            note.append("паз " + ", ".join(f"{fmt(g.width)}×{fmt(g.depth)}" + (" глухой" if g.stopped else "")
                                          for g in p.grooves))
        rows.append((p.no, p.name, mats[p.material]["name"], p.t, p.qty, p.L, p.W, p.L_saw, p.W_saw,
                     "вдоль длины" if p.grain else "нет",
                     *[p.edges[e] or None for e in EDGE_NAMES], n_face, "; ".join(note)))
    _sheet(wb, "Детали", ["№", "Деталь", "Материал", "Толщина", "Кол-во", "Длина чист.", "Ширина чист.",
                          "Длина пил.", "Ширина пил.", "Текстура", "Кромка Д1", "Кромка Д2", "Кромка Ш1",
                          "Кромка Ш2", "Отв. в пласть", "Примечание"], rows,
           [7, 22, 26, 8, 7, 10, 10, 10, 10, 11, 9, 9, 9, 9, 9, 30])

    rows = []
    for p in parts:
        for h in sorted(p.holes, key=lambda h: (h.side, h.x, h.y)):
            sx, sy = p.to_saw(h.x, h.y)
            rows.append((p.no, p.name, "пласть " + h.side if not h.is_edge else "торец " + h.side, h.d,
                         "насквозь" if h.through else h.depth, round(h.x, 2), round(h.y, 2), round(h.z, 2) if h.is_edge else None,
                         round(sx, 2), round(sy, 2), KIND_RU.get(h.kind, h.kind), p.qty))
    _sheet(wb, "Присадка", ["№", "Деталь", "Где", "Ø", "Глубина", "X чист.", "Y чист.", "Z (торец)", "X пил.",
                            "Y пил.", "Назначение", "Деталей"], rows, [7, 22, 12, 6, 9, 9, 9, 9, 9, 9, 26, 8])

    et = edge_totals(parts, shop)
    tape = {float(k): v for k, v in shop["edges"].get("tape_width", {}).items()}
    rows = [(f"Кромка {fmt(e['thickness'])} мм", f"{fmt(tape.get(float(e['width']), 0)) or '?'} мм (плита {fmt(e['width'])})", e["material"],
             round(e["m"], 3), e["pieces"], round(e["m_allow"], 3)) for e in et]
    _sheet(wb, "Кромка", ["Кромка", "Ширина ленты", "Под материал", "Метры чистые", "Отрезков",
                          f"Метры с запасом (+{shop['edges']['piece_allowance']} мм на отрезок)"], rows,
           [16, 22, 30, 13, 10, 26])

    _sheet(wb, "Фурнитура", ["Наименование", "Кол-во", "Ед.", "Куда", "Источник числа"],
           hardware(parts, products, shop), [40, 9, 7, 46, 30])

    rows = []
    for res in nest_results:
        m = mats[res.material]
        for s in res.sheets:
            rows.append((m["name"], f"{fmt(s.L)}×{fmt(s.W)}", s.index, len(s.placements), round(s.parts_area / 1e6, 3),
                         round(s.L * s.W / 1e6, 3), round(s.util * 100, 1), s.kerf, s.trim, res.strategy))
    _sheet(wb, "Листы", ["Материал", "Лист", "№ листа", "Деталей", "Площадь деталей, м²", "Площадь листа, м²",
                         "Использование, %", "Пропил", "Обрезка", "Как разложено"], rows,
           [28, 12, 8, 8, 14, 14, 13, 8, 8, 34])

    rows = []
    for pid, fl in findings_by_product.items():
        for f in fl:
            rows.append((pid, {"ok": "✓", "info": "i", "warn": "!", "error": "ОШИБКА"}[f.level], f.check, f.text))
    ws = _sheet(wb, "Проверки", ["Изделие", "Итог", "Проверка", "Что проверено"], rows, [12, 8, 16, 110])
    for row in ws.iter_rows(min_row=2):
        row[3].alignment = WRAP

    ws = _sheet(wb, "Допущения", ["Параметр", "Значение", "Источник", "Что сверить"], assumptions, [36, 22, 16, 60])
    for row in ws.iter_rows(min_row=2):
        row[3].alignment = WRAP

    wb.properties.title = title
    wb.save(path)
    return path


def verify(path: str, parts: list[Part], nest_results) -> list[str]:
    """Открыть xlsx обратно и сверить с деталировкой."""
    wb = load_workbook(path, read_only=True)
    errs = []
    rows = list(wb["Детали"].iter_rows(min_row=2, values_only=True))
    if len(rows) != len(parts):
        errs.append(f"xlsx: строк деталей {len(rows)}, позиций {len(parts)}")
    for r, p in zip(rows, parts):
        if r[0] != p.no or r[4] != p.qty or abs(r[7] - p.L_saw) > 0.01 or abs(r[8] - p.W_saw) > 0.01:
            errs.append(f"xlsx: строка {r[0]} не совпала с деталью {p.no}")
    n_holes = sum(len(p.holes) for p in parts)
    got = sum(1 for _ in wb["Присадка"].iter_rows(min_row=2, values_only=True))
    if got != n_holes:
        errs.append(f"xlsx: строк присадки {got}, отверстий {n_holes}")
    n_sheets = sum(len(r.sheets) for r in nest_results)
    got = sum(1 for _ in wb["Листы"].iter_rows(min_row=2, values_only=True))
    if got != n_sheets:
        errs.append(f"xlsx: листов {got}, в раскрое {n_sheets}")
    return errs
