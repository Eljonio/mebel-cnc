"""Выходы кухни: xlsx (модули, фасады, спецификация, техника, детали, раскрой, проверки, допущения), html-просмотр."""
from __future__ import annotations

import html
import json
import os

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..config import ROOT
from ..parts import fmt
from . import spec

KBUNDLE = os.path.join(ROOT, "viewer", "dist", "kitchen.bundle.js")
LEVEL_RU = {"ok": "OK", "warn": "ВНИМАНИЕ", "error": "ОШИБКА", "info": "инфо", "critical": "❗ КРИТИЧНО"}


def _sheet(wb, title, header, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="16233B")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    return ws


def write_xlsx(path, k, parts, results, findings):
    wb = Workbook()
    wb.remove(wb.active)
    mr = spec.module_rows(k)
    _sheet(wb, "Модули", ["№", "Тип", "Уровень", "Ряд", "Положение", "Z, мм", "Корпус Ш×В×Г", "Фасады Ш×В", "Петли",
                          "Что внутри"],
           [(r["id"], r["type"], r["level"], r["run"], r["pos"], r["z"], r["carcass"], r["facades"], r["hinges"],
             r["inside"]) for r in mr], [6, 26, 9, 6, 20, 12, 15, 48, 7, 60])
    fr = spec.facade_rows(k)
    rows = [(r["module"], r["name"], fmt(r["w"]), fmt(r["h"]), 1, round(r["area"], 3), r["hinge"], r["hinges"],
             k.shop["materials"][k.cfg["materials"]["facade"]]["name"]) for r in fr]
    rows.append(("Итого", f"{len(fr)} шт", "", "", len(fr), round(sum(r["area"] for r in fr), 3), "", "", ""))
    _sheet(wb, "Фасады", ["Модуль", "Фасад", "Ширина", "Высота", "Кол-во", "м²", "Петли со стороны", "Петель",
                          "Материал"], rows, [8, 40, 9, 9, 8, 8, 16, 8, 60])
    _sheet(wb, "Спецификация", ["Раздел", "Позиция", "Кол-во", "Ед.", "Примечание (цены не ставились — нет источника)"],
           spec.material_spec(k, parts, results), [13, 70, 9, 10, 90])
    _sheet(wb, "Техника (отдельно)", ["Что", "Размер, мм", "Где и что учесть"], spec.appliance_rows(k), [36, 26, 90])
    _sheet(wb, "Детали ЛДСП и ХДФ", ["№", "Деталь", "Модули", "Материал", "Кол-во", "Длина", "Ширина",
                                      "Пильная длина", "Пильная ширина", "Кромка Д1 Д2 Ш1 Ш2"],
           spec.parts_rows(k, parts), [7, 42, 22, 10, 7, 8, 8, 10, 10, 26])
    rows = []
    for r in results:
        for s in r.sheets:
            rows.append((k.shop["materials"][r.material]["name"], s.index, len(s.placements), f"{s.util * 100:.1f}%"))
    _sheet(wb, "Раскрой (предв.)", ["Материал", "Лист №", "Деталей", "Заполнение"], rows, [60, 8, 9, 12])
    _sheet(wb, "Проверки", ["Итог", "Проверка", "Что"],
           [(LEVEL_RU.get(f.level, f.level), f.check, f.text) for f in findings], [11, 22, 120])
    _sheet(wb, "Допущения", ["Что", "Принято", "Почему"], spec.assumptions(k), [24, 60, 70])
    sh = k.cfg.get("share")
    if sh:
        crit = [(f.check, f.text) for f in findings if f.level == "critical"] + [("", t) for t in sh.get("critical", [])]
        _sheet(wb, "❗ Критично", ["Проверка", "Что"], crit, [14, 150])
        _sheet(wb, "Отличия от эскиза", ["На эскизе", "В проекте", "Почему"], sh["deviations"], [40, 60, 70])
        _sheet(wb, "Вопросы", ["№", "Вопрос / на замер"], list(enumerate(sh["questions"], 1)), [5, 150])
    if k.facade_ops:
        from .drilling import facade_drill_rows
        _sheet(wb, "Присадка фасадов", ["Модуль", "Фасад", "Петли (вид спереди)", "Ось чашки от кромки", "Ось от низа",
                                        "Чашка"], facade_drill_rows(k), [8, 40, 14, 16, 12, 10])
        st = k.drill_stats
        _sheet(wb, "Присадка (итог)", ["Что", "Сколько"],
               [("Конфирматов (пара отверстий Ø7 сквозное + Ø5 в торец)", st["confirmat"]),
                ("Петель (чашка Ø35 в фасаде + 2×Ø5 планка)", st["hinge"]),
                ("Отверстий под полкодержатели Ø5", st["shelf_pin"]),
                ("Пропущено полкодержателей (занято)", st["skipped_pins"])] +
               [("Сдвиг петель", t) for t in st["moved_hinges"]] + [("Не на станке", t) for t in st["not_cnc"]],
               [60, 80])
    wb.save(path)
    # обратное чтение: число модулей и фасадов совпадает
    wb2 = load_workbook(path, read_only=True)
    n_mod = wb2["Модули"].max_row - 1
    n_fac = wb2["Фасады"].max_row - 2
    errs = []
    if n_mod != len(mr):
        errs.append(f"xlsx: модулей {n_mod}, а в модели {len(mr)}")
    if n_fac != len(fr):
        errs.append(f"xlsx: фасадов {n_fac}, а в модели {len(fr)}")
    return errs


TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — 3D</title>
<style>
:root{--ink:#16233b;--bg:#eef1f5;--line:#d4d9e1;--acc:#036afd}
html,body{margin:0;height:100%;background:var(--bg);font:14px Inter,system-ui,sans-serif;color:var(--ink)}
#app{position:fixed;inset:0}
.bar{position:fixed;left:12px;top:12px;right:12px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;z-index:5}
.bar h1{font-size:15px;margin:0 10px 0 4px;font-weight:650}
button{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;padding:6px 10px;
 font:inherit;cursor:pointer}
button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
#info{position:fixed;left:12px;bottom:12px;max-width:420px;background:#fff;border:1px solid var(--line);
 border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.45;z-index:5}
#info b{font-weight:650}
@media (max-width:700px){.bar h1{width:100%}#info{right:12px}}
</style></head><body>
<div id="app"></div>
<div class="bar"><h1>__TITLE__</h1>
__VIEWBTNS__
<button id="walls">Стены C, D</button><button id="fac" class="on">Фасады</button>
<button id="pts">Коммуникации</button><button id="lbl">Номера модулей</button></div>
<div id="info">Крутить — мышью, приблизить — колесом. Нажмите на деталь — покажу, что это.<br>
Модель та же, из которой считаются детали и раскрой. Размеры — в таблице и на плане.</div>
<script>__BUNDLE__</script>
<script>
const S = __SCENE__;
const info = document.getElementById('info');
let wallsOn = false;
const v = KitchenViewer.mount(document.getElementById('app'), S, {
  view: location.hash.slice(1) || 'angle',
  onView: (name, hide) => {
    document.querySelectorAll('[data-v]').forEach(b => b.classList.toggle('on', b.dataset.v === name));
    wallsOn = hide.length === 0; document.getElementById('walls').classList.toggle('on', wallsOn);
  },
  onPick: s => {
    if (!s) { info.innerHTML = 'Ничего не выбрано.'; return; }
    const [w, d, h] = s.size;
    info.innerHTML = `<b>${s.name}</b>${s.module ? ' · модуль ' + s.module : ''}<br>габарит ${w} × ${d} × ${h} мм (X × Y × Z)`;
  }
});
document.querySelectorAll('[data-v]').forEach(b => b.onclick = () => v.view(b.dataset.v));
const tog = (id, fn, start) => { const b = document.getElementById(id); let on = start;
  b.onclick = () => { on = !on; b.classList.toggle('on', on); fn(on); }; };
document.getElementById('walls').onclick = e => { wallsOn = !wallsOn; e.target.classList.toggle('on', wallsOn); v.walls(wallsOn); };
tog('fac', v.facades, true); tog('pts', v.points, false); tog('lbl', v.labels, false);
const p = new URLSearchParams(location.search);
if (p.get('pts')) { v.points(true); document.getElementById('pts').classList.add('on'); }
if (p.get('lbl')) { v.labels(true); document.getElementById('lbl').classList.add('on'); }
if (p.get('nofac')) { v.facades(false); document.getElementById('fac').classList.remove('on'); }
if (p.get('clean')) { document.querySelector('.bar').style.display = 'none'; info.style.display = 'none'; }
</script></body></html>
"""


def write_html(path, scene: dict):
    if not os.path.exists(KBUNDLE):
        raise RuntimeError("нет viewer/dist/kitchen.bundle.js — npm run build:kitchen")
    with open(KBUNDLE, encoding="utf-8") as f:
        bundle = f.read().replace("</script", "<\\/script")
    names = {"front": "Спереди", "angle": "Под углом", "top": "Сверху", "photo": "Как на эскизе"}
    first = "photo" if "photo" in scene["cameras"] else "angle"
    btns = "".join(f'<button data-v="{v}"{" class=\"on\"" if v == first else ""}>{names.get(v, v)}</button>'
                   for v in scene["cameras"])
    out = (TEMPLATE.replace("__TITLE__", html.escape(scene["title"])).replace("__VIEWBTNS__", btns)
           .replace("location.hash.slice(1) || 'angle'", f"location.hash.slice(1) || '{first}'")
           .replace("__BUNDLE__", bundle)
           .replace("__SCENE__", json.dumps(scene, ensure_ascii=False).replace("</", "<\\/")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path
