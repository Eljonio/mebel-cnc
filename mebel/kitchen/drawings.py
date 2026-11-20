"""План с размерами и развёртки стен A и B (matplotlib -> PNG + один PDF).

План: стена A сверху листа, X вправо, Y вниз — так выглядит комната сверху (оси ТЗ левые).
Развёртка A: смотрим на стену A из комнаты, X вправо. Развёртка B: смотрим на стену B из комнаты —
угол A/B справа, дверь слева (горизонталь = b − Y).
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Arc, Circle, Rectangle  # noqa: E402

from ..parts import fmt  # noqa: E402
from .layout import Kitchen  # noqa: E402
from .scene import MATS, mats_for  # noqa: E402

INK = "#16233b"
DIM = "#1d4ed8"


def _dim(ax, p0, p1, off, text=None, horiz=True, fs=7, color=DIM):
    """Размерная линия между p0 и p1 (координата вдоль), off — положение линии."""
    if horiz:
        ax.plot([p0, p1], [off, off], color=color, lw=0.7)
        for p in (p0, p1):
            ax.plot([p, p], [off - 25, off + 25], color=color, lw=0.7)
        ax.text((p0 + p1) / 2, off + 22, text or fmt(p1 - p0), ha="center", va="bottom", fontsize=fs, color=color)
    else:
        ax.plot([off, off], [p0, p1], color=color, lw=0.7)
        for p in (p0, p1):
            ax.plot([off - 25, off + 25], [p, p], color=color, lw=0.7)
        ax.text(off - 22, (p0 + p1) / 2, text or fmt(abs(p1 - p0)), ha="right", va="center", fontsize=fs,
                color=color, rotation=90)


def _chain(ax, pts, off, horiz=True, fs=7, color=DIM, map_=lambda v: v):
    pts = sorted(set(round(p, 1) for p in pts))
    for a, b in zip(pts, pts[1:]):
        if b - a < 1:
            continue
        _dim(ax, map_(a), map_(b), off, fmt(b - a), horiz, fs if b - a > 120 else fs - 1.5, color)


def numbered(k: Kitchen) -> bool:
    """Много точек коммуникаций — на чертежах номера, расшифровка в легенде (подписи иначе налезают)."""
    return len(k.points) > 5


def pcolor(p) -> str:
    key = {"water": "point_water", "vent": "point_vent", "gas": "point_gas"}.get(p.get("kind", p["id"]),
                                                                                 "point_water" if p["id"] == "water" else
                                                                                 ("point_vent" if p["id"] == "vent"
                                                                                  else "point_power"))
    return MATS[key]["color"]


def points_legend(k: Kitchen) -> list[tuple]:
    return [(i, p["name"], f"{'X' if p['wall'] == 'A' else 'Y'} {fmt(p['pos'])}, Z {fmt(p['z'])}", pcolor(p))
            for i, p in enumerate(k.points, 1)]


def plan(k: Kitchen, ax):
    room = k.cfg["room"]
    a, b, w = float(room["a"]), float(room["b"]), float(room["wall"])
    Y = lambda y: -y  # noqa: E731
    for s in k.kind("wall"):
        bx = s.box
        ax.add_patch(Rectangle((bx.lo[0], Y(bx.hi[1])), bx.size[0], bx.size[1], fc="#b9bcc2", ec="#6b7280", lw=0.5,
                               hatch="////", zorder=1))
    win, dr = k.geo["window"], k.geo["door"]
    if k.geo.get("window_wall", "A") == "A":
        ax.plot([win.lo[0], win.hi[0]], [Y(-w / 2), Y(-w / 2)], color="#38bdf8", lw=2, zorder=3)
        ax.add_patch(Rectangle((win.lo[0], Y(0)), win.size[0], w, fc="white", ec="#38bdf8", lw=0.8, zorder=2))
        ax.text((win.lo[0] + win.hi[0]) / 2, Y(-w / 2) + 15, f"окно {fmt(win.size[0])}, подоконник {fmt(win.lo[2])}",
                ha="center", va="bottom", fontsize=7, color="#0369a1", zorder=4)
    else:
        ax.plot([a + w / 2, a + w / 2], [Y(win.lo[1]), Y(win.hi[1])], color="#38bdf8", lw=2, zorder=3)
        ax.add_patch(Rectangle((a, Y(win.hi[1])), w, win.size[1], fc="white", ec="#38bdf8", lw=0.8, zorder=2))
        ax.text(a - 40, Y((win.lo[1] + win.hi[1]) / 2), f"окно {fmt(win.size[1])} (сверить)", rotation=90,
                ha="right", va="center", fontsize=7, color="#0369a1", zorder=4)
    ax.add_patch(Rectangle((-w, Y(dr.hi[1])), w, dr.size[1], fc="white", ec="#64748b", lw=0.8, zorder=2))
    r = dr.size[1]
    ax.add_patch(Arc((0, Y(dr.hi[1])), 2 * r, 2 * r, theta1=0, theta2=90, color="#64748b", lw=0.7, ls="--", zorder=3))
    ax.plot([0, r], [Y(dr.hi[1]), Y(dr.hi[1])], color="#64748b", lw=1.2, zorder=3)
    ax.text(r * 0.55, Y(dr.hi[1]) + 50, "дверь 800 (сторона открывания — уточнить)", fontsize=6.5, color="#475569", zorder=4)
    # нижний уровень: цоколь не виден; столешница, над ней техника; границы модулей — тонко
    zw = k.geo["zw"]
    MK = mats_for(k)
    for s in k.kind("worktop"):
        bx = s.box
        ax.add_patch(Rectangle((bx.lo[0], Y(bx.hi[1])), bx.size[0], bx.size[1],
                               fc="#e9d3b5" if MK["worktop"].get("wood") else "#cfd0d4", ec=INK, lw=0.9, zorder=5))
    for m in k.modules:
        if m.level != "нижний" or m.type in ("fridge",):
            continue
        d = k.geo["D"] + k.geo["tf"]
        if m.run == "A":
            r = (m.u0, Y(d), m.u1 - m.u0, d)
        elif m.run == "B":
            r = (0, Y(m.u1), d, m.u1 - m.u0)
        else:
            continue
        ax.add_patch(Rectangle(r[:2], r[2], r[3], fill=False, ec="#8a6a45", lw=0.6, ls=(0, (2, 2)), zorder=6))
    for s in k.kind("appliance"):
        bx = s.box
        if bx.hi[2] < zw - 0.5 or s.mat == "chrome" or s.id.startswith(("duct", "hood")):
            continue
        ax.add_patch(Rectangle((bx.lo[0], Y(bx.hi[1])), bx.size[0], bx.size[1], fc=MK[s.mat]["color"], ec=INK,
                               lw=0.6, zorder=8))
    hob = k.appl.get("hob")
    if hob:
        bx = hob.box
        cx, cy = (bx.lo[0] + bx.hi[0]) / 2, (bx.lo[1] + bx.hi[1]) / 2
        for dx, dy, rr in ((-140, -110, 95), (140, -110, 80), (-140, 120, 80), (140, 120, 95)):
            ax.add_patch(Circle((cx + dx, Y(cy + dy)), rr, fill=False, ec="#9ca3af", lw=0.6, zorder=12))
    # верхние — пунктиром (с фасадами)
    du = k.geo["Du"] + k.geo["tf"]
    for m in k.modules:
        if m.level != "верхний":
            continue
        if m.type == "corner_l":
            W = m.u1
            ax.plot([0, W, W, du, du, 0, 0], [Y(0), Y(0), Y(du), Y(du), Y(W), Y(W), Y(0)], color="#7c3aed", lw=0.9,
                    ls=(0, (4, 3)), zorder=13)
            continue
        r = (m.u0, Y(du), m.u1 - m.u0, du) if m.run == "A" else (0, Y(m.u1), du, m.u1 - m.u0)
        ax.add_patch(Rectangle(r[:2], r[2], r[3], fill=False, ec="#7c3aed", lw=0.9, ls=(0, (4, 3)), zorder=13))
    for m in k.modules:
        if m.type in ("corner_filler", "end_panel", "ceiling_strip"):
            continue
        if m.type == "filler":
            if m.level == "нижний":
                uc = (m.u0 + m.u1) / 2
                ax.text(k.geo["D"] + k.geo["tf"] + 70, Y(uc), "F1/F2 — планки 50", ha="left", va="center",
                        fontsize=6.5, color=INK, zorder=20)
            continue
        if m.type == "corner_l":
            pos = (150, 150)
        elif m.level == "верхний":
            uc = (m.u0 + m.u1) / 2
            pos = (uc, 200) if m.run == "A" else (200, uc)
        else:
            uc = (m.u0 + m.u1) / 2
            dv = 470 if m.type != "fridge" else 380
            pos = (uc, dv) if m.run == "A" else (dv, uc)
        col = "#7c3aed" if m.level == "верхний" else INK
        ax.text(pos[0], Y(pos[1]), m.id, ha="center", va="center", fontsize=8, fontweight="bold", color=col,
                zorder=20, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=col, lw=0.5, alpha=0.85))
    if numbered(k):
        for i, p in enumerate(k.points, 1):
            x, y, z = p["pt"]
            ax.add_patch(Circle((x, Y(y)), 52, fc=pcolor(p), ec="white", lw=0.8, zorder=21))
            ax.text(x, Y(y), str(i), ha="center", va="center", fontsize=6.5, color="white", fontweight="bold", zorder=22)
        return a, b, w
    for p in k.points:
        x, y, z = p["pt"]
        col = MATS["point_water" if p["id"] == "water" else ("point_vent" if p["id"] == "vent" else "point_power")]["color"]
        dx = {"hob_power": 70, "vent": -70}.get(p["id"], 0)
        ax.add_patch(Circle((x + dx, Y(y)), 45, fc=col, ec="white", lw=0.8, zorder=21))
        lift = {"hob_power": 95, "vent": 215}.get(p["id"], 95)
        tx, ty = (x, Y(y) + lift) if p["wall"] == "A" else (x - 245, Y(y) - 140)
        ax.text(tx, ty, f"{p['name']} (Z {fmt(z)})", fontsize=6, color=col, zorder=21,
                ha="center" if p["wall"] == "A" else "left", va="bottom" if p["wall"] == "A" else "top",
                rotation=0 if p["wall"] == "A" else 0)
    return a, b, w


def plan_figure(k: Kitchen, size=(16.5, 13.5), bare=False):
    room = k.cfg["room"]
    a, b, w = float(room["a"]), float(room["b"]), float(room["wall"])
    fig, ax = plt.subplots(figsize=size)
    Y = lambda y: -y  # noqa: E731
    _plan_body(k, ax)
    # цепочки по A (над стеной A)
    low = [m for m in k.modules if m.run == "A" and m.level == "нижний"]
    up = [m for m in k.modules if m.run == "A" and m.level == "верхний"]
    _chain(ax, [0.0] + [m.u0 for m in low] + [m.u1 for m in low], w + 180)
    ax.text(-w - 60, w + 205, "нижние", fontsize=7, color=DIM, ha="right")
    _chain(ax, [0.0] + [m.u0 for m in up] + [m.u1 for m in up], w + 430, color="#7c3aed")
    ax.text(-w - 60, w + 455, "верхние", fontsize=7, color="#7c3aed", ha="right")
    win = k.geo["window"]
    if k.geo.get("window_wall", "A") == "A":
        _chain(ax, [0.0, win.lo[0], win.hi[0], a], w + 680, color="#0369a1")
        ax.text(-w - 60, w + 705, "окно", fontsize=7, color="#0369a1", ha="right")
    else:
        _chain(ax, [0.0, win.lo[1], win.hi[1], b], a + w + 180, horiz=False, color="#0369a1", map_=Y)
    _dim(ax, 0, a, w + 930, f"стена A {fmt(a)}", True, 8, INK)
    # цепочки по B (слева от стены B)
    lowb = [m for m in k.modules if m.run == "B" and m.level == "нижний"]
    upb = [m for m in k.modules if m.run == "B" and m.level == "верхний"]
    dr = k.geo["door"]
    _chain(ax, [0.0] + [m.u0 for m in lowb] + [m.u1 for m in lowb] + [dr.lo[1], dr.hi[1], b], -w - 180,
           horiz=False, map_=Y)
    ub0 = float((k.cfg.get("upper_b") or {}).get("start", 600))
    _chain(ax, [0.0, ub0] + [m.u0 for m in upb] + [m.u1 for m in upb], -w - 430, horiz=False, color="#7c3aed",
           map_=Y)
    _dim(ax, Y(0), Y(b), -w - 680, f"стена B {fmt(b)}", False, 8, INK)
    # глубины
    g = k.geo
    _dim(ax, Y(0), Y(g["Dw"]), 3000 + 160, fmt(g["Dw"]), False, 7)
    _dim(ax, Y(0), Y(g["Du"] + g["tf"]), 1800 + 120, fmt(g["Du"] + g["tf"]), False, 7, "#7c3aed")
    if not bare:
        note = ("Точки коммуникаций — допущения (на эскизе не даны), сверить замером; номера — в легенде."
                if numbered(k) else "Точки коммуникаций — по ТЗ; положение розетки холодильника вдоль стены — уточнить.")
        ax.text(a / 2, Y(b) - w - 250,
                "План, вид сверху. Сплошное — нижние, столешница, техника; пунктир — верхние шкафы. Размеры в мм.\n"
                + note, ha="center", va="top", fontsize=8, color="#334155")
    if numbered(k) and not bare:
        x0, y0 = a * 0.42, Y(b * 0.42)
        ax.text(x0, y0 + 60, "Точки (допущения, сверить):", fontsize=7.5, fontweight="bold", color=INK, zorder=30)
        for j, (i, nm, pos, col) in enumerate(points_legend(k)):
            yy = y0 - 120 - j * 125
            ax.add_patch(Circle((x0 + 40, yy), 42, fc=col, ec="white", zorder=30))
            ax.text(x0 + 40, yy, str(i), ha="center", va="center", fontsize=6, color="white", fontweight="bold", zorder=31)
            ax.text(x0 + 110, yy, f"{nm} — {pos}", va="center", fontsize=6.8, color=INK, zorder=31)
    ax.set_xlim(-w - 1000, a + w + 300)
    ax.set_ylim(Y(b) - w - 700, w + 1150)
    ax.set_aspect("equal")
    ax.axis("off")
    if not bare:
        ax.set_title(f"{k.cfg['kitchen']['name']} — план с размерами", fontsize=13, color=INK)
    else:
        ax.set_ylim(Y(b) - w - 60, w + 1150)
    fig.tight_layout()
    return fig


def _plan_body(k: Kitchen, ax):
    plan(k, ax)


def elevation_figure(k: Kitchen, wall: str, size=(16.5, 11), bare=False):
    room = k.cfg["room"]
    a, b, H = float(room["a"]), float(room["b"]), float(room["height"])
    fig, ax = plt.subplots(figsize=size)
    if wall == "A":
        L = a
        hx = lambda bx: (bx.lo[0], bx.hi[0])  # noqa: E731
        near = lambda bx: bx.lo[1] < 650  # noqa: E731
        depth = lambda bx: bx.hi[1]  # noqa: E731
        hmap = lambda v: v  # noqa: E731
    else:
        L = b
        hx = lambda bx: (b - bx.hi[1], b - bx.lo[1])  # noqa: E731
        near = lambda bx: bx.lo[0] < 600  # noqa: E731
        depth = lambda bx: bx.hi[0]  # noqa: E731
        hmap = lambda v: b - v  # noqa: E731
    ax.add_patch(Rectangle((0, 0), L, H, fc="#faf9f6", ec=INK, lw=1.2, zorder=0))
    win_on_a = k.geo.get("window_wall", "A") == "A"
    if wall == "A":
        win = k.geo["window"]
        if win_on_a:
            ax.add_patch(Rectangle((win.lo[0], win.lo[2]), win.size[0], win.size[2], fc="#e0f2fe", ec="#0369a1", lw=1,
                                   zorder=1))
            ax.plot([(win.lo[0] + win.hi[0]) / 2] * 2, [win.lo[2], win.hi[2]], color="#0369a1", lw=0.6, zorder=1)
    else:
        dr = k.geo["door"]
        h0, h1 = b - dr.hi[1], b - dr.lo[1]
        ax.add_patch(Rectangle((h0, 0), h1 - h0, dr.hi[2], fc="#eef2f7", ec="#475569", lw=1, zorder=1))
        ax.text((h0 + h1) / 2, dr.hi[2] / 2, f"дверной проём\n{fmt(dr.size[1])}×{fmt(dr.size[2])}", ha="center",
                va="center", fontsize=8, color="#475569")
    MK = mats_for(k)
    kinds = ("plinth", "carcass", "worktop", "apron", "gola", "appliance", "facade", "filler", "led")
    other = "B" if wall == "A" else "A"
    run_of = {m.id: m.run for m in k.modules if m.type != "corner_l"}
    skip_sfx = (f"_side_{other}", f"_back_{other}")
    items = [s for s in k.solids if s.kind in kinds and near(s.box) and run_of.get(s.module) != other
             and not s.id.endswith(skip_sfx)]
    items.sort(key=lambda s: depth(s.box))
    for s in items:
        bx = s.box
        x0, x1 = hx(bx)
        if x1 - x0 < 0.5 or bx.size[2] < 0.5:
            continue
        fc = MK[s.mat]["color"] if s.mat != "worktop" else ("#d8b48a" if MK["worktop"].get("wood") else "#3a3a3e")
        lw = 0.9 if s.kind in ("facade", "filler") else 0.5
        ax.add_patch(Rectangle((x0, bx.lo[2]), x1 - x0, bx.size[2], fc=fc, ec=INK, lw=lw, zorder=2))
    # перпендикулярный ряд — в разрезе (штриховка)
    g0 = k.geo
    for (u0, u1, z0, z1, txt) in ((0, g0["D"] + g0["tf"], g0["zp"], g0["zc"], f"ряд {other} в разрезе"),
                                  (0, g0["Du"] + g0["tf"], g0["uz0"], g0["uz1"], f"ряд {other}\nв разрезе")):
        h0, h1 = sorted((hmap(u0), hmap(u1)))
        ax.add_patch(Rectangle((h0, z0), h1 - h0, z1 - z0, fc="#eef0f3", ec="#64748b", lw=0.8, hatch="xx",
                               zorder=4))
        ax.text((h0 + h1) / 2, (z0 + z1) / 2, txt, ha="center", va="center", fontsize=7, color="#334155", zorder=5,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    for s in k.kind("facade"):
        if not near(s.box) or not s.meta.get("hinge"):
            continue
        x0, x1 = hx(s.box)
        if x1 - x0 < 30:
            continue
        run = s.meta["run"]
        lo_side = s.meta["hinge"] == "corner"
        hinge_at_lo_u = lo_side
        if wall == "A":
            hx_ = x0 if hinge_at_lo_u else x1
            fx_ = x1 if hinge_at_lo_u else x0
        else:
            hx_ = x1 if hinge_at_lo_u else x0
            fx_ = x0 if hinge_at_lo_u else x1
        if (wall == "A" and run != "A") or (wall == "B" and run != "B"):
            continue
        z0, z1 = s.box.lo[2], s.box.hi[2]
        ax.plot([fx_, hx_, fx_], [z0, (z0 + z1) / 2, z1], color="#94a3b8", lw=0.6, ls="--", zorder=3)
    for m in k.modules:
        if m.type in ("corner_filler", "end_panel", "filler") or (m.run != wall and m.type != "corner_l"):
            continue
        if m.type == "fridge" and wall != "B":
            continue
        uc = (m.u0 + m.u1) / 2
        if m.type == "corner_l":
            uc = 450
        zc = (m.z0 + m.z1) / 2 if m.type != "fridge" else 1500
        ax.text(hmap(uc), zc, m.id, ha="center", va="center", fontsize=10, fontweight="bold", color=INK, zorder=6,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=INK, lw=0.5, alpha=0.9))
    for i, p in enumerate(k.points, 1):
        if p["wall"] != wall:
            continue
        x = p["pt"][0] if wall == "A" else b - p["pt"][1]
        z = p["pt"][2]
        if numbered(k):
            ax.add_patch(Circle((x, z), 48, fc=pcolor(p), ec="white", lw=1, zorder=7))
            ax.text(x, z, str(i), ha="center", va="center", fontsize=7, color="white", fontweight="bold", zorder=8)
            continue
        col = MATS["point_water" if p["id"] == "water" else ("point_vent" if p["id"] == "vent" else "point_power")]["color"]
        ax.add_patch(Circle((x, z), 38, fc=col, ec="white", lw=1, zorder=7))
        ax.annotate(f"{p['name']}\n{'X' if wall == 'A' else 'Y'} {fmt(p['pos'])}, Z {fmt(z)}", (x, z),
                    (x + 160, z + 170), fontsize=7, color=col, zorder=7,
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.6),
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=col, lw=0.4, alpha=0.9))
    g = k.geo
    zs = [0, g["zp"], g["fz1"], g["zc"], g["zw"], g["uz0"] - g["udrop"], g["uz0"], g["uz1"], H]
    if wall == "A":
        zs += [g["hz0"]]
    if g.get("ceiling_strip"):
        zs += [g["uz1"] + g["ceiling_strip"]]
    _chain(ax, zs, -170, horiz=False)
    _dim(ax, 0, H, -520, f"{fmt(H)}", False, 8, INK)
    mods = [m for m in k.modules if m.run == wall and m.level == "нижний"]
    pts = [hmap(0.0)] + [hmap(m.u0) for m in mods] + [hmap(m.u1) for m in mods]
    _chain(ax, pts, -220)
    if wall == "A":
        win = k.geo["window"]
        op = [0.0, L, win.lo[0], win.hi[0]] if win_on_a else [0.0, L]
    else:
        dr = k.geo["door"]
        op = [0.0, L, b - dr.lo[1], b - dr.hi[1]]
    _chain(ax, op, -420, color="#0369a1")
    ups = [m for m in k.modules if m.run == wall and m.level == "верхний"]
    ub0 = float((k.cfg.get("upper_b") or {}).get("start", 600))
    upts = [hmap(m.u0) for m in ups] + [hmap(m.u1) for m in ups] + ([hmap(0.0), hmap(ub0)] if wall == "B" else [0.0])
    _chain(ax, upts, H + 120, color="#7c3aed")
    side = ("угол A/B — слева, " + ("окно справа" if win_on_a else "холодильник справа")) if wall == "A" \
        else "угол A/B — справа, дверь слева"
    if not bare:
        ax.set_title(f"Развёртка стены {wall} (вид из комнаты; {side}). Размеры в мм", fontsize=12, color=INK)
    ax.set_xlim(-750, L + 250)
    ax.set_ylim(-560, H + 380)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    return fig


def figure_texts(k: Kitchen) -> str:
    """Все подписи чертежей для PDF (в SVG они кривыми — по тексту файла их не проверить)."""
    from matplotlib.text import Text
    out = []
    for fig in (plan_figure(k, (12.0, 9.6), True), elevation_figure(k, "A", (12.5, 8.4), True),
                elevation_figure(k, "B", (11.0, 8.4), True)):
        out += [t.get_text() for t in fig.findobj(Text)]
        plt.close(fig)
    return "\n".join(out)


def write_svg(k: Kitchen, out_dir: str) -> dict:
    """Векторные чертежи (текст кривыми — одинаково на любом устройстве) для страницы и PDF «поделиться»."""
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    with plt.rc_context({"svg.fonttype": "path", "svg.hashsalt": "kuhnya"}):
        for name, fig in (("plan", plan_figure(k, (12.0, 9.6), True)),
                          ("razvertka_A", elevation_figure(k, "A", (12.5, 8.4), True)),
                          ("razvertka_B", elevation_figure(k, "B", (11.0, 8.4), True))):
            p = os.path.join(out_dir, f"{name}.svg")
            fig.savefig(p, format="svg", bbox_inches="tight", pad_inches=0.05)
            plt.close(fig)
            out[name] = p
    return out


def write(k: Kitchen, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    figs = [("plan", plan_figure(k)), ("razvertka_A", elevation_figure(k, "A")),
            ("razvertka_B", elevation_figure(k, "B"))]
    paths = []
    pdf = os.path.join(out_dir, "chertezhi.pdf")
    with PdfPages(pdf) as pp:
        for name, fig in figs:
            p = os.path.join(out_dir, f"{name}.png")
            fig.savefig(p, dpi=130)
            pp.savefig(fig)
            plt.close(fig)
            paths.append(p)
    paths.append(pdf)
    return paths
