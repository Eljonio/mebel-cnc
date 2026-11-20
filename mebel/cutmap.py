"""Карта раскроя: PNG на каждый лист + один PDF на весь заказ (matplotlib)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .nesting import Placement, Sheet  # noqa: E402
from .parts import fmt  # noqa: E402

EDGE_COLORS = {2.0: "#c2410c", 0.4: "#2563eb"}


def place_xy(pl: Placement, x: float, y: float) -> tuple[float, float]:
    """Пильные координаты детали -> координаты листа. Поворот: длина детали вдоль Y листа, Д1 справа."""
    if not pl.rotated:
        return pl.x + x, pl.y + y
    return pl.x + (pl.part.W_saw - y), pl.y + x


def _edge_segments(pl: Placement):
    """Кромкованные стороны детали в координатах листа: [(x0, y0, x1, y1, толщина)]."""
    p = pl.part
    Ls, Ws = p.L_saw, p.W_saw
    sides = {"Д1": ((0, 0), (Ls, 0)), "Д2": ((0, Ws), (Ls, Ws)), "Ш1": ((0, 0), (0, Ws)), "Ш2": ((Ls, 0), (Ls, Ws))}
    out = []
    for name, (a, b) in sides.items():
        th = p.edges[name]
        if th:
            (x0, y0), (x1, y1) = place_xy(pl, *a), place_xy(pl, *b)
            out.append((x0, y0, x1, y1, th))
    return out


def draw_sheet(s: Sheet, title: str, mat_name: str, total: int):
    ratio = s.W / s.L
    fig = plt.figure(figsize=(14, 14 * ratio + 1.2), dpi=110)
    ax = fig.add_axes([0.02, 0.02, 0.96, (14 * ratio) / (14 * ratio + 1.2) - 0.03])
    ax.set_xlim(-30, s.L + 30)
    ax.set_ylim(-30, s.W + 30)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), s.L, s.W, facecolor="#e5e7eb", edgecolor="#111827", lw=1.2, hatch="////"))
    ax.add_patch(Rectangle((s.trim, s.trim), s.L - 2 * s.trim, s.W - 2 * s.trim, facecolor="#f3f4f6",
                           edgecolor="#9ca3af", lw=0.6, ls="--"))
    for pl in s.placements:
        p = pl.part
        ax.add_patch(Rectangle((pl.x, pl.y), pl.w, pl.h, facecolor="#f5e6cf" if p.grain else "#ffffff",
                               edgecolor="#111827", lw=1.0))
        for x0, y0, x1, y1, th in _edge_segments(pl):
            ax.plot([x0, x1], [y0, y1], color=EDGE_COLORS.get(th, "#7c3aed"), lw=3.2 if th >= 1 else 1.8,
                    solid_capstyle="butt")
        cx, cy = pl.x + pl.w / 2, pl.y + pl.h / 2
        small = min(pl.w, pl.h)
        fs = max(6.5, min(12, small / 28))
        rot = 90 if pl.h > pl.w * 1.6 and pl.w < 260 else 0
        name = p.name if small > 120 else ""
        txt = f"{p.no}\n{name}\n{fmt(p.L_saw)}×{fmt(p.W_saw)}" if name else f"{p.no}  {fmt(p.L_saw)}×{fmt(p.W_saw)}"
        ax.text(cx, cy, txt, ha="center", va="center", fontsize=fs, rotation=rot, color="#111827",
                linespacing=1.25)
        if p.grain:  # штриховка вдоль текстуры
            gx = pl.x + 18
            gy = pl.y + 14
            ax.annotate("", xy=(gx + 120, gy), xytext=(gx, gy),
                        arrowprops=dict(arrowstyle="->", color="#92400e", lw=0.9))
    used = s.util * 100
    fig.text(0.02, 0.985, title, fontsize=14, fontweight="bold", va="top", color="#111827")
    fig.text(0.02, 0.985 - 0.45 / (14 * ratio + 1.2), (
        f"{mat_name} · лист {s.index} из {total} · {fmt(s.L)}×{fmt(s.W)} мм · деталей {len(s.placements)} · "
        f"использование {used:.1f} % · пропил {fmt(s.kerf)} мм · обрезка края {fmt(s.trim)} мм\n"
        f"Размеры пильные (до кромки). Оранжевая сторона — кромка 2 мм, синяя — 0,4 мм, стрелка — направление текстуры, "
        f"серое — остаток"),
        fontsize=9.5, va="top", color="#374151")
    return fig


def render(results, products_title: str, materials: dict, png_dir: str, pdf_path: str) -> list[str]:
    import os

    os.makedirs(png_dir, exist_ok=True)
    pngs = []
    with PdfPages(pdf_path) as pdf:
        for res in results:
            mat = materials[res.material]
            for s in res.sheets:
                fig = draw_sheet(s, products_title, mat["name"], len(res.sheets))
                path = os.path.join(png_dir, f"{res.material}_list{s.index:02d}.png")
                fig.savefig(path)
                pdf.savefig(fig)
                plt.close(fig)
                pngs.append(path)
    return pngs
