"""Файлы для станка кухни (второй этап): DXF деталей ЛДСП/ХДФ и листов раскроя по слоям + сверка обратным чтением,
DXF присадки фасадов (чашки петель) и видимой боковины МДФ, вход постпроцессора (ops/*.json), README.

Станок не задан — G-code не делаем. Всё в файлах — для проверки конструктором и цехом, не для запуска.
"""
from __future__ import annotations

import json
import os

import ezdxf

from .. import dxf_out
from ..parts import fmt
from ..post import sheet_operations
from .layout import Kitchen

README = """{title}
DXF для ПРОВЕРКИ, НЕ для запуска: станок не задан. На станок — только после проверки конструктором, первый рез —
холостой проход или дешёвый материал.

parts/  — детали корпусов (ЛДСП 16, ХДФ 3) по одной: смотрим на обрабатываемую пласть, ноль — левый нижний угол
          ПИЛЬНОЙ заготовки (до кромления). Одинаковые детали — один файл, количество в шапке.
sheets/ — листы раскроя: детали на местах, ноль — левый нижний угол листа, X — вдоль длины листа.
fasady/ — присадка фасадов МДФ (их режет и красит фасадный цех; чашки петель сверлятся после покраски):
          X — от кромки СО СТОРОНЫ ПЕТЕЛЬ, Y — от нижней кромки, сверлим с ОБРАТНОЙ стороны двери.
          Видимая боковина МДФ (В7): X — от переднего края, Y — от низа, смотрим С ВНУТРЕННЕЙ стороны (к шкафу).
ops/    — операции листов в JSON — вход постпроцессора (G-code появится, когда будет известен станок).

Слои:
  CONTOUR                — контур (пильный размер у деталей ЛДСП, чистовой у фасадов)
  DRILL_V_D<Ø>_Z<гл.>    — отверстие в пласть сверху (DRILL_V_D35_Z13 — чашка петли Ø35 глубиной 13)
  DRILL_V_D<Ø>_THRU      — сквозное (конфирмат Ø7)
  DRILL_VB_...           — с обратной пласти (нужен переворот)
  DRILL_H_D<Ø>_Z<гл.>    — отверстие в торец: отрезок от торца внутрь, ось на середине толщины (конфирмат Ø5)
  CUT_THRU               — вырез насквозь (под трубы в ХДФ, под воздуховод в полке, выборка)
  POCKET_Z<гл.>          — выборка на глубину
  SHEET / TRIM           — лист и граница обрезки;  LABELS — номера деталей, НЕ РЕЗАТЬ
Точка в числе заменена на «p»: D7p5 = Ø7,5. Шапка (изделие, дата, материал, толщина, ноль, станок, инструмент) —
в свойствах файла ($CUSTOMPROPERTY), не в геометрии.

Не в станочной присадке (по месту/по кондуктору): {not_cnc}.
"""


def _facade_dxf(path, title, mat, name, W, H, holes, extra):
    meta = dxf_out.header_meta(title, mat, {"Деталь": name, "Чистовой размер": f"{fmt(W)}x{fmt(H)}", **extra})
    doc = dxf_out._new_doc(meta)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                       dxfattribs={"layer": dxf_out._layer(doc, "CONTOUR")})
    for x, y, d, depth, through in holes:
        layer = f"DRILL_V_D{dxf_out.num(d)}_THRU" if through else f"DRILL_V_D{dxf_out.num(d)}_Z{dxf_out.num(depth)}"
        msp.add_circle((x, y), d / 2, dxfattribs={"layer": dxf_out._layer(doc, layer)})
    doc.saveas(path)
    return path


def _verify_facade(path, holes, W, H) -> list[str]:
    doc = ezdxf.readfile(path)
    errs = [f"{os.path.basename(path)}: аудит DXF — {len(doc.audit().errors)} ошибок"] if doc.audit().has_errors else []
    got = sorted((round(e.dxf.center.x, 2), round(e.dxf.center.y, 2)) for e in doc.modelspace().query("CIRCLE"))
    exp = sorted((round(x, 2), round(y, 2)) for x, y, *_ in holes)
    if got != exp:
        errs.append(f"{os.path.basename(path)}: отверстия в файле не совпали с расчётом")
    if any(not (0 < x < W and 0 < y < H) for x, y, *_ in holes):
        errs.append(f"{os.path.basename(path)}: отверстие вне детали")
    return errs


def export(k: Kitchen, parts, results, out: str) -> dict:
    title = k.cfg["kitchen"]["name"]
    shop = k.shop
    mats = shop["materials"]
    d = os.path.join(out, "dxf")
    for sub in ("parts", "sheets", "fasady", "ops"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        for f in os.listdir(os.path.join(d, sub)):
            os.remove(os.path.join(d, sub, f))
    errs, files = [], {"parts": [], "sheets": [], "fasady": [], "ops": []}
    for p in parts:
        path = os.path.join(d, "parts", f"{p.no}_{dxf_out.slug(p.name)}.dxf")
        dxf_out.write_part_dxf(p, path, title, mats[p.material])
        errs += dxf_out.verify_part_dxf(p, path)
        doc = ezdxf.readfile(path)
        n_cut = len(doc.modelspace().query('LWPOLYLINE[layer=="CUT_THRU"]'))
        if n_cut != sum(1 for c in p.detail.cuts if c.through):
            errs.append(f"{os.path.basename(path)}: вырезов в файле {n_cut}, в расчёте {len(p.detail.cuts)}")
        files["parts"].append(path)
    for r in results:
        for s in r.sheets:
            path = os.path.join(d, "sheets", f"{r.material}_list{s.index:02d}.dxf")
            dxf_out.write_sheet_dxf(s, path, title, mats[r.material])
            errs += dxf_out.verify_sheet_dxf(s, path)
            files["sheets"].append(path)
            op = os.path.join(d, "ops", f"{r.material}_list{s.index:02d}.json")
            with open(op, "w", encoding="utf-8") as f:
                json.dump(sheet_operations(s, title, mats[r.material]), f, ensure_ascii=False, indent=1)
            files["ops"].append(op)
    # фасады: чашки петель
    fm = mats[k.cfg["materials"]["facade"]]
    sol = {s.id: s for s in k.solids}
    by_solid: dict = {}
    for o in k.facade_ops:
        by_solid.setdefault(o["solid"], []).append(o)
    groups: dict = {}
    for sid, ops in by_solid.items():
        s = sol[sid]
        m = k.module(s.module)
        ua = 0 if m.run == "A" else 1
        if ops[0]["kind"] == "hinge_cup":
            W, H = s.box.size[ua], s.box.size[2]
            edge = ops[0]["edge"]
            e0 = s.box.lo[ua] if edge == "lo" else s.box.hi[ua]
            holes = tuple(sorted((round(abs(o["u"] - e0), 2), round(o["z"] - s.box.lo[2], 2), o["d"], o["depth"], False)
                                 for o in ops))
            key = ("door", round(W, 1), round(H, 1), holes)
        else:                                                 # видимая боковина МДФ
            va = 1 if m.run == "A" else 0
            W, H = s.box.size[va], s.box.size[2]
            front = s.box.hi[va]
            holes = tuple(sorted((round(front - o["p"][va], 2), round(o["p"][2] - s.box.lo[2], 2), o["d"], o["depth"],
                                  o["kind"] == "confirmat_face") for o in ops))
            key = ("side", round(W, 1), round(H, 1), holes)
        groups.setdefault(key, []).append(s.name)
    for i, (key, names) in enumerate(groups.items(), 1):
        kind, W, H, holes = key
        nm = f"F-{i:02d}"
        path = os.path.join(d, "fasady", f"{nm}_{dxf_out.slug(names[0].split(' ', 1)[1])}.dxf")
        extra = {"Кол-во": len(names), "Где": ", ".join(n.split(" ")[0] for n in names),
                 "Ноль": ("X от кромки со стороны петель, Y от низа; сверлим с обратной стороны" if kind == "door" else
                          "X от переднего края, Y от низа; смотрим с внутренней стороны")}
        _facade_dxf(path, title, fm, f"{nm} {names[0]}", W, H, holes, extra)
        errs += _verify_facade(path, holes, W, H)
        files["fasady"].append(path)
    with open(os.path.join(d, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README.format(title=title, not_cnc="; ".join(k.drill_stats.get("not_cnc", []))))
    return {"errors": errs, "files": files}
