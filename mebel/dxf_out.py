"""DXF по слоям (ezdxf, MIT) + обратное чтение и сверка с деталировкой.

Соглашение (пока не знаем станок — наше, переименуем под CAM станка):
  ноль — левый нижний угол ПИЛЬНОЙ заготовки (деталь режется до кромления, координаты сдвинуты на кромку);
  смотрим на обрабатываемую пласть (A), Z=0 — её поверхность, глубина вниз;
  CONTOUR                 — контур заготовки (пильный размер), замкнутая полилиния;
  DRILL_V_D<Ø>_Z<глуб.>   — вертикальные отверстия в пласть A (окружности), _THRU — сквозные;
  DRILL_VB_...            — отверстия с обратной пласти (нужен переворот), координаты как сквозь деталь;
  DRILL_H_D<Ø>_Z<глуб.>   — отверстия в торец: отрезок от торца внутрь (длина = глубина), ось на середине толщины;
  GROOVE_W<ширина>_Z<глуб.> — паз: осевая линия;
  на листе ещё SHEET (лист), TRIM (граница обрезки), LABELS (подписи — НЕ РЕЗАТЬ).
Шапка (изделие, материал, толщина, дата, ноль, станок/инструмент) — в свойствах файла ($CUSTOMPROPERTY)
и в соседнем README.txt, чтобы не попасть в геометрию.
"""
from __future__ import annotations

import datetime as dt
import os

import ezdxf

from .cutmap import place_xy
from .nesting import Sheet
from .parts import Part, fmt

DXF_VERSION = "R2010"
ACI = {"CONTOUR": 7, "SHEET": 8, "TRIM": 9, "LABELS": 8}
DRILL_COLORS = {5: 3, 7: 4, 8: 5, 15: 6, 35: 1}

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                     "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(s: str) -> str:
    out = "".join(TRANSLIT.get(c, c) for c in s.lower())
    return "".join(c if c.isalnum() else "-" for c in out).strip("-").replace("--", "-")


def num(v: float) -> str:
    return fmt(v).replace(".", "p")


def hole_layer(h) -> str:
    if h.is_edge:
        return f"DRILL_H_D{num(h.d)}_Z{num(h.depth)}"
    pre = "DRILL_VB" if h.side == "B" else "DRILL_V"
    return f"{pre}_D{num(h.d)}_THRU" if h.through else f"{pre}_D{num(h.d)}_Z{num(h.depth)}"


def groove_layer(g) -> str:
    return f"GROOVE{'B' if g.side == 'B' else ''}_W{num(g.width)}_Z{num(g.depth)}"


def _edge_vec(side: str):
    return {"Ш1": (1, 0), "Ш2": (-1, 0), "Д1": (0, 1), "Д2": (0, -1)}[side]


def part_ops(p: Part) -> dict:
    """Операции детали в пильных координатах — общий источник для DXF, сверки и постпроцессора."""
    circles, lines, grooves = [], [], []
    for h in p.holes:
        x, y = p.to_saw(h.x, h.y)
        if h.is_edge:
            vx, vy = _edge_vec(h.side)
            lines.append({"layer": hole_layer(h), "a": (x, y), "b": (x + vx * h.depth, y + vy * h.depth),
                          "d": h.d, "depth": h.depth, "z": h.z, "side": h.side, "kind": h.kind})
        else:
            circles.append({"layer": hole_layer(h), "c": (x, y), "d": h.d, "depth": h.depth, "through": h.through,
                            "face": h.side, "kind": h.kind})
    for g in p.grooves:
        x0, y0 = p.to_saw(g.x0, g.y0)
        x1, y1 = p.to_saw(g.x1, g.y1)
        if (x1 - x0) >= (y1 - y0):
            a, b = (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)
        else:
            a, b = ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)
        # паз не выходит за пильный контур
        a = (min(max(a[0], 0), p.L_saw), min(max(a[1], 0), p.W_saw))
        b = (min(max(b[0], 0), p.L_saw), min(max(b[1], 0), p.W_saw))
        grooves.append({"layer": groove_layer(g), "a": a, "b": b, "width": g.width, "depth": g.depth,
                        "stopped": g.stopped, "face": g.side})
    cuts = []
    for c in getattr(p.detail, "cuts", []):
        x0, y0 = p.to_saw(c.x0, c.y0)
        x1, y1 = p.to_saw(c.x1, c.y1)
        x0, x1 = max(x0, 0.0), min(x1, p.L_saw)
        y0, y1 = max(y0, 0.0), min(y1, p.W_saw)
        layer = "CUT_THRU" if c.through else f"POCKET_Z{num(c.depth)}"
        cuts.append({"layer": layer, "rect": (x0, y0, x1, y1), "depth": c.depth, "through": c.through})
    return {"contour": (p.L_saw, p.W_saw), "circles": circles, "lines": lines, "grooves": grooves, "cuts": cuts}


def _new_doc(meta: dict):
    doc = ezdxf.new(DXF_VERSION, setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for k, v in meta.items():
        doc.header.custom_vars.append(k, str(v))
    return doc


def _layer(doc, name):
    if name not in doc.layers:
        color = ACI.get(name)
        if color is None:
            if name.startswith("DRILL_H"):
                color = 2
            elif name.startswith("DRILL"):
                d = float(name.split("_D")[1].split("_")[0].replace("p", "."))
                color = DRILL_COLORS.get(int(round(d)), 140)
            elif name.startswith("GROOVE"):
                color = 30
            else:
                color = 7
        doc.layers.add(name, color=color)
    return name


def _draw_part(msp, doc, ops: dict, tf):
    L, W = ops["contour"]
    pts = [tf(0, 0), tf(L, 0), tf(L, W), tf(0, W)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": _layer(doc, "CONTOUR")})
    for c in ops["circles"]:
        msp.add_circle(tf(*c["c"]), c["d"] / 2, dxfattribs={"layer": _layer(doc, c["layer"])})
    for ln in ops["lines"]:
        msp.add_line(tf(*ln["a"]), tf(*ln["b"]), dxfattribs={"layer": _layer(doc, ln["layer"])})
    for g in ops["grooves"]:
        msp.add_line(tf(*g["a"]), tf(*g["b"]), dxfattribs={"layer": _layer(doc, g["layer"])})
    for c in ops.get("cuts", []):
        x0, y0, x1, y1 = c["rect"]
        msp.add_lwpolyline([tf(x0, y0), tf(x1, y0), tf(x1, y1), tf(x0, y1)], close=True,
                           dxfattribs={"layer": _layer(doc, c["layer"])})


def header_meta(product_title: str, material: dict, extra: dict) -> dict:
    meta = {
        "Изделие": product_title,
        "Дата": dt.date.today().isoformat(),
        "Материал": material["name"],
        "Толщина, мм": fmt(material["thickness"]),
        "Единицы": "мм",
        "Ноль": "левый нижний угол заготовки, Z=0 — верх обрабатываемой пласти",
        "Станок": "НЕ ЗАДАН — файл не для запуска, только для проверки",
        "Инструмент": "не задан (назначается в CAM станка по слоям)",
        "Сделано": "mebel-cnc, расчёт без станка",
    }
    meta.update(extra)
    return meta


def write_part_dxf(p: Part, path: str, product_title: str, material: dict) -> str:
    meta = header_meta(product_title, material, {
        "Деталь": f"{p.no} {p.name}", "Кол-во": p.qty,
        "Пильный размер": f"{fmt(p.L_saw)}x{fmt(p.W_saw)}", "Чистовой размер": f"{fmt(p.L)}x{fmt(p.W)}",
        "Кромка": " ".join(f"{k}:{fmt(v)}" for k, v in p.edges.items()),
        "Текстура": "вдоль X (длины)" if p.grain else "нет",
    })
    doc = _new_doc(meta)
    _draw_part(doc.modelspace(), doc, part_ops(p), lambda x, y: (x, y))
    doc.saveas(path)
    return path


def write_sheet_dxf(s: Sheet, path: str, product_title: str, material: dict) -> str:
    meta = header_meta(product_title, material, {
        "Лист": f"{s.index}", "Размер листа": f"{fmt(s.L)}x{fmt(s.W)}", "Пропил": fmt(s.kerf),
        "Обрезка": fmt(s.trim), "Деталей": len(s.placements), "Использование, %": f"{s.util * 100:.1f}",
        "Ноль листа": "левый нижний угол листа; X — вдоль длины (текстура)",
    })
    doc = _new_doc(meta)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (s.L, 0), (s.L, s.W), (0, s.W)], close=True, dxfattribs={"layer": _layer(doc, "SHEET")})
    t = s.trim
    msp.add_lwpolyline([(t, t), (s.L - t, t), (s.L - t, s.W - t), (t, s.W - t)], close=True,
                       dxfattribs={"layer": _layer(doc, "TRIM")})
    for pl in s.placements:
        _draw_part(msp, doc, part_ops(pl.part), lambda x, y, pl=pl: place_xy(pl, x, y))
        msp.add_text(pl.part.no, height=min(40, max(12, min(pl.w, pl.h) / 6)),
                     dxfattribs={"layer": _layer(doc, "LABELS")}).set_placement(
            (pl.x + pl.w / 2, pl.y + pl.h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(path)
    return path


# ---------- обратное чтение и сверка ----------
def _read(path: str):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    by = {}
    for e in msp:
        by.setdefault(e.dxf.layer, []).append(e)
    return doc, by


def _match_points(expected, got, tol=0.01):
    """Сопоставить два набора точек/кортежей без учёта порядка. Возвращает число несовпавших."""
    got = list(got)
    miss = 0
    for e in expected:
        for i, g in enumerate(got):
            if all(abs(a - b) <= tol for a, b in zip(e, g)):
                got.pop(i)
                break
        else:
            miss += 1
    return miss + len(got)


def _check_ops(by: dict, ops_list: list, label: str) -> list[str]:
    """ops_list — [(ops, tf)]: сверить окружности, отрезки торцевых отверстий и пазы по слоям."""
    errs = []
    exp_c, exp_l = {}, {}
    for ops, tf in ops_list:
        for c in ops["circles"]:
            x, y = tf(*c["c"])
            exp_c.setdefault(c["layer"], []).append((x, y, c["d"] / 2))
        for ln in ops["lines"] + ops["grooves"]:
            a, b = tf(*ln["a"]), tf(*ln["b"])
            exp_l.setdefault(ln["layer"], []).append(tuple(sorted([a, b])))
    for layer, exp in exp_c.items():
        got = [(e.dxf.center.x, e.dxf.center.y, e.dxf.radius) for e in by.get(layer, []) if e.dxftype() == "CIRCLE"]
        if len(got) != len(exp) or _match_points(exp, got):
            errs.append(f"{label}: слой {layer} — ждали {len(exp)} отв., в файле {len(got)} или не на местах")
    for layer, exp in exp_l.items():
        got = [tuple(sorted([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]))
               for e in by.get(layer, []) if e.dxftype() == "LINE"]
        flat_e = [(a[0], a[1], b[0], b[1]) for a, b in exp]
        flat_g = [(a[0], a[1], b[0], b[1]) for a, b in got]
        if len(got) != len(exp) or _match_points(flat_e, flat_g):
            errs.append(f"{label}: слой {layer} — ждали {len(exp)} линий, в файле {len(got)} или не на местах")
    extra = [ly for ly, es in by.items() if ly.startswith(("DRILL", "GROOVE")) and ly not in exp_c and ly not in exp_l]
    for ly in extra:
        errs.append(f"{label}: лишний слой {ly} ({len(by[ly])} объектов)")
    return errs


def _bbox_of(e):
    pts = list(e.get_points("xy"))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def verify_part_dxf(p: Part, path: str) -> list[str]:
    doc, by = _read(path)
    errs = []
    label = f"{p.no} {os.path.basename(path)}"
    if doc.header.get("$INSUNITS") != 4:
        errs.append(f"{label}: единицы не мм")
    cont = [e for e in by.get("CONTOUR", []) if e.dxftype() == "LWPOLYLINE"]
    if len(cont) != 1 or not cont[0].closed:
        errs.append(f"{label}: контур — ждали 1 замкнутую полилинию, есть {len(cont)}")
    else:
        bb = _bbox_of(cont[0])
        want = (0, 0, p.L_saw, p.W_saw)
        if any(abs(a - b) > 0.01 for a, b in zip(bb, want)):
            errs.append(f"{label}: контур {bb} ≠ пильный размер {p.L_saw}×{p.W_saw}")
    errs += _check_ops(by, [(part_ops(p), lambda x, y: (x, y))], label)
    return errs


def verify_sheet_dxf(s: Sheet, path: str) -> list[str]:
    doc, by = _read(path)
    errs = []
    label = f"лист {s.index} {os.path.basename(path)}"
    cont = [e for e in by.get("CONTOUR", []) if e.dxftype() == "LWPOLYLINE"]
    if len(cont) != len(s.placements):
        errs.append(f"{label}: контуров {len(cont)}, деталей {len(s.placements)}")
    want = sorted((pl.x, pl.y, pl.x + pl.w, pl.y + pl.h) for pl in s.placements)
    got = sorted(_bbox_of(e) for e in cont)
    if len(want) == len(got) and _match_points(want, got):
        errs.append(f"{label}: контуры деталей не совпадают с раскроем")
    errs += _check_ops(by, [(part_ops(pl.part), lambda x, y, pl=pl: place_xy(pl, x, y)) for pl in s.placements], label)
    return errs


def preview_png(dxf_path: str, png_path: str, title: str = "") -> str:
    """Картинка DXF через рисовалку ezdxf — чтобы глазами увидеть, что реально лежит в файле."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf_path)
    fig = plt.figure(figsize=(9, 9 * 0.62), dpi=130)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.9])
    ctx = RenderContext(doc)
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        min_lineweight=0.6)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    if title:
        fig.text(0.02, 0.97, title, fontsize=10, va="top")
    fig.savefig(png_path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return png_path

