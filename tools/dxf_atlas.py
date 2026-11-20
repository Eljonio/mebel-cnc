"""Атлас деталей: каждый DXF кухни картинкой с подписями по-русски, в один PDF.

python tools/dxf_atlas.py <папка dxf кухни (с parts/ и fasady/)> <выход.pdf>
"""
import glob
import os
import re
import sys
import textwrap

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, Polygon

ROOT = sys.argv[1]
OUT = sys.argv[2]

COL = {"contour": "#222222", "v": "#d62728", "vb": "#ff7f0e", "h": "#1f77b4", "cut": "#2ca02c", "pocket": "#2ca02c"}


def kind(layer: str) -> str | None:
    if layer == "CONTOUR":
        return "contour"
    if layer.startswith("DRILL_VB"):
        return "vb"
    if layer.startswith("DRILL_V"):
        return "v"
    if layer.startswith("DRILL_H"):
        return "h"
    if layer.startswith("CUT"):
        return "cut"
    if layer.startswith("POCKET"):
        return "pocket"
    return None


def hole_name(layer: str) -> str:
    m = re.match(r"DRILL_V?B?_?D(\d+(?:p\d+)?)_(THRU|Z(\d+(?:p\d+)?))", layer.replace("DRILL_H_", "DRILL_"))
    if not m:
        return layer
    d = m.group(1).replace("p", ",")
    depth = "насквозь" if m.group(2) == "THRU" else f"глуб. {m.group(3).replace('p', ',')}"
    return f"Ø{d}, {depth}"


def edges_text(s: str) -> str:
    parts = dict(p.split(":") for p in s.split()) if s else {}
    names = {"Д1": "длинная 1", "Д2": "длинная 2", "Ш1": "короткая 1", "Ш2": "короткая 2"}
    got = [f"{names[k]} — {v.replace('.', ',')} мм" for k, v in parts.items() if v not in ("0", "")]
    return "кромка: " + (", ".join(got) if got else "нет")


def draw(ax, path):
    doc = ezdxf.readfile(path)
    cv = dict(doc.header.custom_vars)
    msp = doc.modelspace()
    xs, ys = [], []
    holes = {}
    circles = []
    for e in msp:
        k = kind(e.dxf.layer)
        if k is None:
            continue
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
            if k == "contour":
                ax.add_patch(Polygon(pts, closed=True, fill=True, fc="#f3efe6", ec=COL[k], lw=1.4, zorder=1))
            else:
                ax.add_patch(Polygon(pts, closed=True, fill=True, fc=COL[k], alpha=0.35, ec=COL[k], lw=1, zorder=2))
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
        elif t == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            circles.append((c.x, c.y, r, k))
            holes[(k, e.dxf.layer)] = holes.get((k, e.dxf.layer), 0) + 1
        elif t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            ax.plot([s.x, en.x], [s.y, en.y], color=COL[k], lw=3, solid_capstyle="butt", zorder=3)
            holes[(k, e.dxf.layer)] = holes.get((k, e.dxf.layer), 0) + 1
    if not xs:
        for e in msp:
            if e.dxftype() == "CIRCLE":
                xs.append(e.dxf.center.x)
                ys.append(e.dxf.center.y)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    for cx, cy, r, k in circles:
        ax.add_patch(Circle((cx, cy), max(r, max(w, h) * 0.012), fc=COL[k], ec="white", lw=0.3, zorder=3))
    pad = max(w, h) * 0.08
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad * 1.6, y1 + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.annotate("", xy=(x1, y0 - pad * 0.7), xytext=(x0, y0 - pad * 0.7), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((x0 + x1) / 2, y0 - pad * 1.3, f"{w:.0f}", ha="center", va="center", fontsize=8)
    ax.annotate("", xy=(x1 + pad * 0.5, y1), xytext=(x1 + pad * 0.5, y0), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(x1 + pad * 0.75, (y0 + y1) / 2, f"{h:.0f}", ha="left", va="center", fontsize=8, rotation=90)

    name = cv.get("Деталь") or os.path.splitext(os.path.basename(path))[0]
    qty = cv.get("Кол-во", "1")
    mat = (cv.get("Материал") or "").split(",")[0].split("(")[0].strip()
    title = f"{name}  ·  {qty} шт"
    lines = [mat] if mat else []
    if cv.get("Кромка"):
        lines.append(edges_text(cv["Кромка"]))
    hl = [f"{'торец' if k == 'h' else 'обратная сторона' if k == 'vb' else 'плоскость'}: {hole_name(l)} × {n}"
          for (k, l), n in sorted(holes.items())]
    lines.append("отверстия: " + ("; ".join(hl) if hl else "нет"))
    ax.set_title(title, fontsize=10, fontweight="bold", loc="left")
    ax.text(0, -0.02, "\n".join(textwrap.fill(l, 62) for l in lines), transform=ax.transAxes, fontsize=6.5, va="top", ha="left", wrap=True)


def cover(pdf, n_parts, n_fas):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.06, 0.9, "Детали кухни — картинками", fontsize=22, fontweight="bold")
    txt = (
        "Это те же файлы для станка (папка dxf), только нарисованные понятно.\n\n"
        "Каждая картинка — одна деталь, вид сверху, как она лежит на столе станка.\n"
        "Размеры — в миллиметрах. Для деталей из ЛДСП это размер ДО приклейки кромки (так их пилят).\n\n"
        f"Детали корпусов (ЛДСП 16 и задние стенки ХДФ 3): {n_parts} файлов.\n"
        f"Фасады МДФ (двери, ящики) с отверстиями под петли: {n_fas} файлов — их делает фасадный цех.\n\n"
        "Цвета:"
    )
    fig.text(0.06, 0.82, txt, fontsize=12, va="top", linespacing=1.5)
    legend = [
        (COL["contour"], "контур детали — по нему пилят"),
        (COL["v"], "отверстие в плоскость: Ø35 — чашка петли, Ø7 насквозь — конфирмат (винт-стяжка), Ø5 — полкодержатели и крепёж"),
        (COL["h"], "отверстие в торец (в ребро детали) — под конфирмат, которым её стягивают с соседней"),
        (COL["vb"], "отверстие с обратной стороны — деталь переворачивают"),
        (COL["cut"], "вырез или выборка — под трубы, воздуховод, профиль"),
    ]
    y = 0.42
    for c, t in legend:
        fig.patches.append(Circle((0.075, y + 0.008), 0.009, transform=fig.transFigure, fc=c, ec=c))
        fig.text(0.095, y, t, fontsize=11.5)
        y -= 0.06
    fig.text(0.06, 0.08, "Станок пока не выбран — файлы для проверки, не для запуска.", fontsize=10, color="#666")
    pdf.savefig(fig)
    plt.close(fig)


def main():
    parts = sorted(glob.glob(os.path.join(ROOT, "parts", "*.dxf")))
    fas = sorted(glob.glob(os.path.join(ROOT, "fasady", "*.dxf")))
    with PdfPages(OUT) as pdf:
        cover(pdf, len(parts), len(fas))
        for group, files in (("Детали корпусов", parts), ("Фасады МДФ", fas)):
            for i in range(0, len(files), 6):
                fig, axs = plt.subplots(2, 3, figsize=(11.69, 8.27))
                fig.suptitle(f"{group} — {i // 6 + 1}", x=0.04, ha="left", fontsize=13, fontweight="bold")
                for ax, f in zip(axs.flat, files[i:i + 6]):
                    draw(ax, f)
                for ax in list(axs.flat)[len(files[i:i + 6]):]:
                    ax.axis("off")
                fig.subplots_adjust(left=0.03, right=0.97, top=0.9, bottom=0.08, wspace=0.15, hspace=0.45)
                pdf.savefig(fig)
                plt.close(fig)
    print(OUT)


main()
