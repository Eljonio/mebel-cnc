"""Проверки изделия. Каждая проверка независима от формул генератора: смотрит на готовую геометрию."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from .geom import Box, bbox, seg_box_dist, seg_seg_dist
from .model import Product
from .parts import Detail, Part, fmt, make_detail

TOL = 0.01


@dataclass
class Finding:
    level: str      # ok / info / warn / error
    check: str
    text: str


def _f(level, check, text):
    return Finding(level, check, text)


# ---------- 1. габарит и размерные цепочки ----------
def check_size(prod: Product) -> list[Finding]:
    W, D, H = prod.size
    b = bbox(p.box for p in prod.panels)
    got = b.size
    out = []
    if all(abs(v) < TOL for v in b.lo) and all(abs(g - e) < TOL for g, e in zip(got, (W, D, H))):
        out.append(_f("ok", "габарит", f"все детали вместе дают ровно {fmt(W)}×{fmt(D)}×{fmt(H)}"))
    else:
        out.append(_f("error", "габарит", f"детали дают {fmt(got[0])}×{fmt(got[1])}×{fmt(got[2])} от "
                      f"{tuple(fmt(v) for v in b.lo)}, а задано {fmt(W)}×{fmt(D)}×{fmt(H)}"))
    return out


def _chain(name, axis, items, start, end) -> Finding:
    """items — [(подпись, lo, hi)] по порядку. Проверяет стык-в-стык и сумму = габарит."""
    pos = start
    parts = []
    for label, lo, hi in items:
        if abs(lo - pos) > TOL:
            return _f("error", "цепочка", f"{name}: «{label}» начинается на {fmt(lo)}, ждали {fmt(pos)} (щель/нахлёст)")
        parts.append(fmt(hi - lo))
        pos = hi
    if abs(pos - end) > TOL:
        return _f("error", "цепочка", f"{name}: сумма {' + '.join(parts)} = {fmt(pos - start)}, а габарит {fmt(end - start)}")
    return _f("ok", "цепочка", f"{name}: {' + '.join(parts)} = {fmt(end - start)}")


def check_chains(prod: Product) -> list[Finding]:
    W, D, H = prod.size
    pn = {p.id: p for p in prod.panels}
    sL, sR, top, bot = pn["side_left"], pn["side_right"], pn["top"], pn["bottom"]
    out = [_chain("Ширина корпуса (боковина + дно + боковина)", 0,
                  [(sL.name, sL.box.lo[0], sL.box.hi[0]), (bot.name, bot.box.lo[0], bot.box.hi[0]),
                   (sR.name, sR.box.lo[0], sR.box.hi[0])], 0, W)]
    if prod.meta["top_type"] == "inset":
        out.append(_chain("Ширина по крышке", 0, [(sL.name, sL.box.lo[0], sL.box.hi[0]),
                                                  (top.name, top.box.lo[0], top.box.hi[0]),
                                                  (sR.name, sR.box.lo[0], sR.box.hi[0])], 0, W))
        out.append(_chain("Высота боковины", 2, [(sL.name, sL.box.lo[2], sL.box.hi[2])], 0, H))
    else:
        out.append(_chain("Ширина по крышке", 0, [(top.name, top.box.lo[0], top.box.hi[0])], 0, W))
        out.append(_chain("Высота (боковина + крышка)", 2, [(sL.name, sL.box.lo[2], sL.box.hi[2]),
                                                            (top.name, top.box.lo[2], top.box.hi[2])], 0, H))
    z_items = []
    if "plinth" in pn:
        z_items.append(("цоколь", pn["plinth"].box.lo[2], pn["plinth"].box.hi[2]))
    z_items.append(("дно", bot.box.lo[2], bot.box.hi[2]))
    z_items.append(("проём", bot.box.hi[2], top.box.lo[2]))
    z_items.append(("крышка", top.box.lo[2], top.box.hi[2]))
    out.append(_chain("Высота (цоколь + дно + проём + крышка)", 2, z_items, 0, H))
    doors = sorted(prod.by_role("door"), key=lambda p: p.box.lo[0])
    y_items = []
    if doors:
        y_items.append(("фасад", doors[0].box.lo[1], doors[0].box.hi[1]))
    y_items.append(("боковина", sL.box.lo[1], sL.box.hi[1]))
    if prod.meta["back_type"] == "overlay":
        y_items.append(("задняя стенка", pn["back"].box.lo[1], pn["back"].box.hi[1]))
    out.append(_chain("Глубина (фасад + корпус + задняя)", 1, y_items, 0, D))
    return out


# ---------- 2. пересечения панелей ----------
def check_overlaps(prod: Product) -> list[Finding]:
    out = []
    n_groove = 0
    for a, b in itertools.combinations(prod.panels, 2):
        x = a.box.intersect(b.box)
        if x is None:
            continue
        if any(g.box.contains(x) for g in a.grooves + b.grooves):
            n_groove += 1
            continue
        s = x.size
        out.append(_f("error", "пересечения", f"«{a.name}» и «{b.name}» залезают друг в друга на "
                      f"{fmt(s[0])}×{fmt(s[1])}×{fmt(s[2])} мм"))
    if not out:
        extra = f" (задняя стенка сидит в пазах, стыков: {n_groove})" if n_groove else ""
        out.append(_f("ok", "пересечения", f"детали ({len(prod.panels)} шт) не залезают друг в друга{extra}"))
    return out


# ---------- 3. зазоры фасадов ----------
def check_facades(prod: Product) -> list[Finding]:
    doors = sorted(prod.by_role("door"), key=lambda p: p.box.lo[0])
    if not doors:
        return [_f("info", "фасады", "фасадов нет")]
    f = prod.facade_field
    g, eg = f["gap"], f["edge_gap"]
    out = []
    gaps = [("слева", doors[0].box.lo[0] - f["x0"], eg), ("справа", f["x1"] - doors[-1].box.hi[0], eg)]
    for a, b in zip(doors, doors[1:]):
        gaps.append((f"между «{a.name}» и «{b.name}»", b.box.lo[0] - a.box.hi[0], g))
    for d in doors:
        gaps.append((f"«{d.name}» снизу", d.box.lo[2] - f["z0"], eg))
        gaps.append((f"«{d.name}» сверху", f["z1"] - d.box.hi[2], eg))
    bad = [(n, got, want) for n, got, want in gaps if abs(got - want) > TOL]
    for n, got, want in bad:
        out.append(_f("error", "зазоры фасадов", f"зазор {n} = {fmt(got)} мм, нужно {fmt(want)}"))
    widths = " + ".join(fmt(d.box.size[0]) for d in doors)
    if not bad:
        out.append(_f("ok", "зазоры фасадов", f"фасады {widths} мм, зазоры {fmt(g)} мм между и {fmt(eg)} мм по краям — "
                      f"все зазоры совпали ({len(gaps)} шт)"))
    return out


# ---------- 4. отверстия: в материале, не у края, не друг в друге, не в пазу ----------
def _hole_segment(d: Detail, h):
    t = d.t
    if h.side == "A":
        return (h.x, h.y, 0.0), (h.x, h.y, t if h.through else h.depth)
    if h.side == "B":
        return (h.x, h.y, t), (h.x, h.y, t - h.depth)
    sign = {"Ш1": (1, 0), "Ш2": (-1, 0), "Д1": (0, 1), "Д2": (0, -1)}[h.side]
    p = (h.x, h.y, h.z)
    return p, (h.x + sign[0] * h.depth, h.y + sign[1] * h.depth, h.z)


def _material_box(d: Detail) -> Box:
    e = d.edges
    return Box((e["Ш1"], e["Д1"], 0.0), (d.L - e["Ш2"], d.W - e["Д2"], d.t))


def check_holes(prod: Product, details: list[Detail] | None = None) -> list[Finding]:
    shop = prod.shop
    wall_edge = shop["fasteners"].get("min_edge_wall", 2)
    wall = shop["fasteners"]["min_wall"]
    bottom = shop["fasteners"]["min_bottom"]
    details = details or [make_detail(p, prod) for p in prod.panels]
    out = []
    n_holes = 0
    for d in details:
        mb = _material_box(d)
        segs = []
        for h in d.holes:
            n_holes += 1
            r = h.d / 2
            p, q = _hole_segment(d, h)
            segs.append((h, p, q))
            where = f"«{d.panel.name}»: {h.kind} Ø{fmt(h.d)}"
            if h.side in ("A", "B"):
                lat = min(h.x - r - mb.lo[0], mb.hi[0] - h.x - r, h.y - r - mb.lo[1], mb.hi[1] - h.y - r)
                if lat < wall_edge - TOL:
                    out.append(_f("error", "отверстия", f"{where} в ({fmt(h.x)}; {fmt(h.y)}) — до края материала "
                                  f"{fmt(lat)} мм, нужно ≥ {fmt(wall_edge)}"))
                if not h.through and d.t - h.depth < bottom - TOL:
                    out.append(_f("error", "отверстия", f"{where} глубина {fmt(h.depth)} в плите {fmt(d.t)} — "
                                  f"остаётся {fmt(d.t - h.depth)} мм, нужно ≥ {fmt(bottom)} (пробьёт насквозь)"))
            else:
                along_x = h.side in ("Ш1", "Ш2")
                c = h.y if along_x else h.x
                lo, hi = (mb.lo[1], mb.hi[1]) if along_x else (mb.lo[0], mb.hi[0])
                lat = min(h.z - r, d.t - h.z - r, c - r - lo, hi - c - r)
                if lat < wall_edge - TOL:
                    out.append(_f("error", "отверстия", f"{where} в торце {h.side} — стенка {fmt(lat)} мм, "
                                  f"нужно ≥ {fmt(wall_edge)}"))
                extent = d.L if along_x else d.W
                if h.depth > extent - bottom:
                    out.append(_f("error", "отверстия", f"{where} в торце {h.side} глубиной {fmt(h.depth)} длиннее детали"))
        for (h1, p1, q1), (h2, p2, q2) in itertools.combinations(segs, 2):
            if h1.joint == h2.joint:
                continue
            dist = seg_seg_dist(p1, q1, p2, q2)
            need = (h1.d + h2.d) / 2 + wall
            if dist < need - TOL:
                out.append(_f("error", "отверстия", f"«{d.panel.name}»: {h1.kind} Ø{fmt(h1.d)} ({fmt(h1.x)}; {fmt(h1.y)}) и "
                              f"{h2.kind} Ø{fmt(h2.d)} ({fmt(h2.x)}; {fmt(h2.y)}) — между осями {fmt(dist)} мм, "
                              f"нужно ≥ {fmt(need)}"))
        for g in d.grooves:
            z0, z1 = (0.0, g.depth) if g.side == "A" else (d.t - g.depth, d.t)
            gb = Box((g.x0, g.y0, z0), (g.x1, g.y1, z1))
            for h, p, q in segs:
                dist = seg_box_dist(p, q, gb)
                if dist < h.d / 2 + wall - TOL:
                    out.append(_f("error", "отверстия", f"«{d.panel.name}»: {h.kind} Ø{fmt(h.d)} слишком близко к пазу "
                                  f"({fmt(dist)} мм)"))
    if not any(f.level == "error" for f in out):
        out.append(_f("ok", "отверстия", f"отверстий {n_holes}: все в материале, стенка до края ≥ {fmt(wall_edge)} мм, "
                      f"между отверстиями ≥ {fmt(wall)} мм, глухие не пробивают плиту"))
    return out


# ---------- 5. соосность крепежа между деталями ----------
def check_joints(prod: Product) -> list[Finding]:
    by_joint: dict = {}
    for h in prod.holes:
        by_joint.setdefault(h.joint, []).append(h)
    out = []
    n = 0
    for j, hs in by_joint.items():
        kinds = {h.kind: h for h in hs}
        n += 1
        if "confirmat_face" in kinds:
            a, b = kinds["confirmat_face"], kinds["confirmat_edge"]
            if math.dist(a.end, b.p) > TOL or a.dir != b.dir or a.panel == b.panel:
                out.append(_f("error", "крепёж", f"{j}: конфирмат — отверстие в пласти и в торце не соосны"))
        elif "minifix_cam" in kinds:
            cam, ch, bolt = kinds["minifix_cam"], kinds["minifix_edge"], kinds["minifix_bolt"]
            if math.dist(ch.p, bolt.p) > TOL or seg_seg_dist(ch.p, ch.end, cam.p, cam.end) > TOL:
                out.append(_f("error", "крепёж", f"{j}: эксцентрик — канал не доходит до эксцентрика или шток не соосен"))
        elif "dowel_face" in kinds:
            a, b = kinds["dowel_face"], kinds["dowel_edge"]
            if math.dist(a.p, b.p) > TOL:
                out.append(_f("error", "крепёж", f"{j}: шкант — отверстия не соосны"))
        elif "hinge_cup" in kinds:
            cup = kinds["hinge_cup"]
            plates = [h for h in hs if h.kind == "hinge_plate"]
            zc = sum(h.p[2] for h in plates) / len(plates)
            if abs(zc - cup.p[2]) > TOL:
                out.append(_f("error", "крепёж", f"{j}: петля — чашка и планка на разной высоте"))
    if not out:
        out.append(_f("ok", "крепёж", f"соединений {n}: отверстия в соседних деталях соосны (конфирматы, эксцентрики, "
                      f"шканты, петли)"))
    return out


# ---------- 6. петли не упираются в полки ----------
def check_hinges(prod: Product) -> list[Finding]:
    zone = prod.shop["hinges"]["zone"]
    shelves = [p for p in prod.panels if p.role in ("shelf", "shelf_fixed")]
    out = []
    for d in prod.by_role("door"):
        for z in d.meta.get("hinges", []):
            for s in shelves:
                if z + zone > s.box.lo[2] and z - zone < s.box.hi[2]:
                    out.append(_f("error", "петли", f"«{d.name}»: петля на {fmt(z)} мм ближе {fmt(zone)} мм к полке"))
    if not out and prod.by_role("door"):
        cnt = ", ".join(f"«{d.name}» — {len(d.meta['hinges'])} шт" for d in prod.by_role("door"))
        out.append(_f("ok", "петли", f"петли не упираются в полки ({cnt})"))
    return out


# ---------- 7. детали и станок ----------
def check_parts(parts: list[Part], shop: dict) -> list[Finding]:
    out = []
    cut = shop["cutting"]
    trim = cut["trim"]
    bad = 0
    for p in parts:
        mat = shop["materials"][p.material]
        uL, uW = mat["sheet"][0] - 2 * trim, mat["sheet"][1] - 2 * trim
        L, W = p.L_saw, p.W_saw
        fits = (L <= uL and W <= uW) if p.grain else ((L <= uL and W <= uW) or (W <= uL and L <= uW))
        if not fits:
            bad += 1
            out.append(_f("error", "лист", f"{p.no} «{p.name}» {fmt(L)}×{fmt(W)} не влезает в полезную часть листа "
                          f"{fmt(uL)}×{fmt(uW)}" + (" с учётом текстуры" if p.grain else "")))
        if min(L, W) < cut["min_part"]:
            out.append(_f("warn", "лист", f"{p.no} «{p.name}» узкая ({fmt(min(L, W))} мм < {cut['min_part']}) — "
                          f"на пиле прижимать, на вакууме может сдвинуть"))
        if any(h.side == "B" for h in p.holes) or any(g.side == "B" for g in p.grooves):
            out.append(_f("warn", "одна сторона", f"{p.no} «{p.name}»: обработка с двух пластей — нужен переворот детали"))
        edge = [h for h in p.holes if h.is_edge]
        if edge:
            out.append(_f("info", "торцы", f"{p.no} «{p.name}»: {len(edge)} отв. в торец — нужен горизонтальный "
                          f"сверлильный узел, иначе по кондуктору вручную"))
        if any(g.stopped for g in p.grooves):
            out.append(_f("info", "пазы", f"{p.no} «{p.name}»: глухой паз — только фрезой"))
    if not bad:
        out.append(_f("ok", "лист", f"все позиции ({len(parts)} шт) влезают в лист (за вычетом обрезки {trim} мм)"))
    return out


def run_all(prod: Product, parts: list[Part] | None = None) -> list[Finding]:
    from .parts import detailing
    parts = parts if parts is not None else detailing([prod])
    out = []
    out += check_size(prod)
    out += check_chains(prod)
    out += check_overlaps(prod)
    out += check_facades(prod)
    out += check_holes(prod)
    out += check_joints(prod)
    out += check_hinges(prod)
    out += check_parts(parts, prod.shop)
    for n in prod.notes:
        out.append(_f("info", "генератор", n))
    return out


def errors(findings) -> list[Finding]:
    return [f for f in findings if f.level == "error"]
