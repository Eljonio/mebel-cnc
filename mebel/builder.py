"""Параметры изделия -> панели + крепёж + присадка.

Корпусная мебель «ящик»: боковины, дно, крышка (накладная или между боковинами), цоколь, полки,
распашные двери (накладные), задняя стенка (накладная или в паз). Все цеховые числа — из shop.yaml.
Оси: X — ширина (слева направо), Y — глубина (0 — лицо фасадов, растёт к стене), Z — вверх от пола.
"""
from __future__ import annotations

import itertools

from .geom import Box, add, mul, seg_seg_dist, spread, sub, unit
from .model import Groove, Hole, Panel, Product


class BuildError(ValueError):
    pass


def _hinge_count(height: float, table) -> int:
    for max_h, n in table:
        if height <= max_h:
            return int(n)
    raise BuildError(f"дверь {height:.0f} мм выше таблицы петель ({table[-1][0]} мм) — нужна другая конструкция")


def build(cfg: dict, shop: dict) -> Product:
    pr = cfg["product"]
    W, D, H = (float(cfg["size"][k]) for k in ("width", "depth", "height"))
    mats = shop["materials"]
    mkeys = cfg["materials"]
    mc, mf, mb = mats[mkeys["carcass"]], mats[mkeys["facade"]], mats[mkeys["back"]]
    t, tf, tb = float(mc["thickness"]), float(mf["thickness"]), float(mb["thickness"])
    con = cfg["construction"]
    top_type = con.get("top", "overlay")
    top_joint = con.get("top_joint", "confirmat")
    ph = float(con.get("plinth", 0) or 0)
    back_type = con.get("back", "overlay")
    sh_cfg = con.get("shelves", {}) or {}
    n_shelves = int(sh_cfg.get("count", 0))
    fixed = set(int(i) for i in (sh_cfg.get("fixed") or []))
    dr = con.get("doors", {}) or {}
    n_doors = int(dr.get("count", 0))

    if top_type not in ("overlay", "inset"):
        raise BuildError(f"construction.top: overlay/inset, а не {top_type!r}")
    if back_type not in ("overlay", "groove"):
        raise BuildError(f"construction.back: overlay/groove, а не {back_type!r}")
    if n_doors not in (0, 1, 2):
        raise BuildError("пока поддержано 0, 1 или 2 распашные двери")
    if fixed - set(range(1, n_shelves + 1)):
        raise BuildError(f"shelves.fixed {sorted(fixed)} вне 1..{n_shelves}")

    car, fac, bk = shop["carcass"], shop["facades"], shop["back"]
    fs = shop["fasteners"]
    notes: list[str] = []
    jid = itertools.count(1)

    def J(prefix: str) -> str:
        return f"{prefix}{next(jid)}"

    # --- плоскости корпуса ---
    cy0 = tf if n_doors else 0.0                       # передний край корпуса (за фасадами)
    cy1 = D - tb if back_type == "overlay" else D      # задний край корпуса
    if back_type == "groove":
        gy1 = D - bk["groove_offset"]
        gy0 = gy1 - bk["groove_width"]
        back_plane = gy0                               # всё внутреннее — до паза
    else:
        back_plane = cy1
    side_top = H - t if top_type == "overlay" else H
    inner_z0, inner_z1 = ph + t, H - t
    back_role = "joint" if back_type == "overlay" else "hidden"

    panels: list[Panel] = []

    def P(**kw) -> Panel:
        p = Panel(**kw)
        panels.append(p)
        return p

    side_edges = {"-y": "visible", "+y": back_role, "-z": "hidden", "+z": "joint" if top_type == "overlay" else "hidden"}
    sL = P(id="side_left", name="Боковина левая", role="side_left", material=mkeys["carcass"], thickness=t,
           box=Box.of(0, t, cy0, cy1, 0, side_top), thin=0, face=+1, grain=2, edges=dict(side_edges))
    sR = P(id="side_right", name="Боковина правая", role="side_right", material=mkeys["carcass"], thickness=t,
           box=Box.of(W - t, W, cy0, cy1, 0, side_top), thin=0, face=-1, grain=2, edges=dict(side_edges))

    if top_type == "overlay":
        top = P(id="top", name="Крышка", role="top", material=mkeys["carcass"], thickness=t,
                box=Box.of(0, W, 0, cy1, H - t, H), thin=2, face=-1, grain=0,
                edges={"-y": "visible", "-x": "visible", "+x": "visible", "+y": back_role})
    else:
        top = P(id="top", name="Крышка", role="top", material=mkeys["carcass"], thickness=t,
                box=Box.of(t, W - t, cy0, cy1, H - t, H), thin=2, face=-1, grain=0,
                edges={"-y": "visible", "-x": "joint", "+x": "joint", "+y": back_role})

    bot = P(id="bottom", name="Дно", role="bottom", material=mkeys["carcass"], thickness=t,
            box=Box.of(t, W - t, cy0, cy1, ph, ph + t), thin=2, face=+1, grain=0,
            edges={"-y": "visible", "-x": "joint", "+x": "joint", "+y": back_role})

    plinth = None
    if ph > 0:
        py0 = cy0 + car["plinth_setback"]
        plinth = P(id="plinth", name="Цоколь", role="plinth", material=mkeys["carcass"], thickness=t,
                   box=Box.of(t, W - t, py0, py0 + t, 0, ph), thin=1, face=-1, grain=0,
                   edges={"-z": "hidden", "+z": "joint", "-x": "joint", "+x": "joint"})

    # --- полки: равные промежутки по внутренней высоте ---
    shelves: list[Panel] = []
    if n_shelves:
        gap = (inner_z1 - inner_z0 - n_shelves * t) / (n_shelves + 1)
        if gap < 100:
            raise BuildError(f"полок {n_shelves} не влезает: промежуток {gap:.0f} мм")
        sy0 = cy0 + car["shelf_front_setback"]
        sy1 = back_plane - car["shelf_back_gap"]
        for k in range(1, n_shelves + 1):
            z0 = round(inner_z0 + k * gap + (k - 1) * t)
            if k in fixed:
                box = Box.of(t, W - t, sy0, sy1, z0, z0 + t)
                role, name, sides = "shelf_fixed", "Полка неподвижная", "joint"
            else:
                g = car["shelf_side_gap"]
                box = Box.of(t + g, W - t - g, sy0, sy1, z0, z0 + t)
                role, name, sides = "shelf", "Полка", "hidden"
            shelves.append(P(id=f"shelf_{k}", name=name, role=role, material=mkeys["carcass"], thickness=t,
                             box=box, thin=2, face=+1, grain=0,
                             edges={"-y": "visible", "+y": "hidden", "-x": sides, "+x": sides}))

    # --- задняя стенка ---
    if back_type == "overlay":
        ins = bk["overlay_inset"]
        back = P(id="back", name="Задняя стенка", role="back", material=mkeys["back"], thickness=tb,
                 box=Box.of(ins, W - ins, D - tb, D, ph + ins, H - ins), thin=1, face=-1,
                 grain=0 if mb.get("grain") else None,
                 edges={"-x": "none", "+x": "none", "-z": "none", "+z": "none"}, group="back")
    else:
        gd, cl = bk["groove_depth"], bk["groove_clearance"]
        by0 = gy0 + (bk["groove_width"] - tb) / 2
        back = P(id="back", name="Задняя стенка", role="back", material=mkeys["back"], thickness=tb,
                 box=Box.of(t - gd + cl, W - t + gd - cl, by0, by0 + tb, ph + t - gd + cl, H - t + gd - cl),
                 thin=1, face=-1, grain=0 if mb.get("grain") else None,
                 edges={"-x": "none", "+x": "none", "-z": "none", "+z": "none"}, group="back")
        gw = bk["groove_width"]
        sL.grooves.append(Groove(sL.id, Box.of(t - gd, t, gy0, gy1, 0, side_top), gw, gd))
        sR.grooves.append(Groove(sR.id, Box.of(W - t, W - t + gd, gy0, gy1, 0, side_top), gw, gd))
        bot.grooves.append(Groove(bot.id, Box.of(t, W - t, gy0, gy1, ph + t - gd, ph + t), gw, gd))
        if top_type == "inset":
            top.grooves.append(Groove(top.id, Box.of(t, W - t, gy0, gy1, H - t, H - t + gd), gw, gd))
        else:  # накладная крышка: торцы видны — паз глухой, только фрезой
            top.grooves.append(Groove(top.id, Box.of(t - gd, W - t + gd, gy0, gy1, H - t, H - t + gd), gw, gd,
                                      stopped=True))
            notes.append("Паз в накладной крышке глухой (не выходит на видимые торцы) — только фрезой на ЧПУ.")

    # --- двери ---
    doors: list[Panel] = []
    field = {}
    if n_doors:
        fz0, fz1 = ph, (H - t if top_type == "overlay" else H)
        g, eg = fac["gap"], fac["edge_gap"]
        dw = (W - 2 * eg - (n_doors - 1) * g) / n_doors
        dz0, dz1 = fz0 + eg, fz1 - eg
        field = {"x0": 0.0, "x1": W, "z0": fz0, "z1": fz1, "gap": g, "edge_gap": eg}
        sides = ["left", "right"] if n_doors == 2 else [dr.get("hinge_side", "left")]
        names = {"left": "Дверь левая", "right": "Дверь правая"} if n_doors == 2 else {sides[0]: "Дверь"}
        for i, hs in enumerate(sides):
            x0 = eg + i * (dw + g)
            d = P(id=f"door_{i + 1}", name=names[hs], role="door", material=mkeys["facade"], thickness=tf,
                  box=Box.of(x0, x0 + dw, 0, tf, dz0, dz1), thin=1, face=+1, grain=2,
                  edges={"-x": "visible", "+x": "visible", "-z": "visible", "+z": "visible"}, group="facade",
                  meta={"hinge_side": hs})
            doors.append(d)

    # ================= крепёж =================
    cf = fs["confirmat"]

    def confirmat(face_p: Panel, edge_p: Panel, pt, n):
        """Конфирмат: сквозное в пласть face_p, глухое в торец edge_p. pt — точка на плоскости стыка, n — из face_p в edge_p."""
        j = J("CF")
        face_p.holes.append(Hole(face_p.id, sub(pt, mul(n, face_p.thickness)), n, cf["face_d"], face_p.thickness,
                                 "confirmat_face", j, through=True))
        edge_p.holes.append(Hole(edge_p.id, pt, n, cf["edge_d"], cf["length"] - face_p.thickness + cf["edge_extra"],
                                 "confirmat_edge", j))

    def row(a, b):
        return spread(a, b, cf["edge_offset"], cf["max_pitch"])

    # боковины <-> дно, неподвижные полки, крышка между боковинами
    horizontals = [(bot, ph + t / 2)] + [(s, s.box.lo[2] + t / 2) for s in shelves if s.role == "shelf_fixed"]
    if top_type == "inset":
        horizontals.append((top, H - t / 2))
    for hp, zc in horizontals:
        for y in row(hp.box.lo[1], hp.box.hi[1]):
            confirmat(sL, hp, (t, y, zc), unit(0, +1))
            confirmat(sR, hp, (W - t, y, zc), unit(0, -1))

    if plinth is not None:
        pyc = (plinth.box.lo[1] + plinth.box.hi[1]) / 2
        for z in spread(0, ph, cf["edge_offset"], cf["max_pitch"]):
            confirmat(sL, plinth, (t, pyc, z), unit(0, +1))
            confirmat(sR, plinth, (W - t, pyc, z), unit(0, -1))
        for x in row(t, W - t):
            confirmat(bot, plinth, (x, pyc, ph), unit(2, -1))

    # накладная крышка <-> боковины
    if top_type == "overlay":
        ys = row(cy0, cy1)
        if top_joint == "confirmat":
            for y in ys:
                confirmat(top, sL, (t / 2, y, H - t), unit(2, -1))
                confirmat(top, sR, (W - t / 2, y, H - t), unit(2, -1))
            notes.append("Крышка на конфирматах: шляпки сверху, под заглушки.")
        elif top_joint == "minifix":
            mf_ = fs["minifix"]
            dw_ = fs["dowel"]
            ends = [ys[0], ys[-1]] if len(ys) > 1 else ys
            mids = ys[1:-1] if len(ys) > 2 else ([round((ys[0] + ys[-1]) / 2, 1)] if len(ys) == 2 else [])
            for side, xc, cam_dir in ((sL, t / 2, unit(0, -1)), (sR, W - t / 2, unit(0, +1))):
                for y in ends:
                    j = J("MF")
                    pt = (xc, y, H - t)
                    n = unit(2, +1)  # из боковины в крышку
                    c = sub(pt, mul(n, mf_["cam_offset"]))
                    c_face = sub(c, mul(cam_dir, t / 2))
                    side.holes.append(Hole(side.id, c_face, cam_dir, mf_["cam_d"], mf_["cam_depth"], "minifix_cam", j))
                    side.holes.append(Hole(side.id, pt, unit(2, -1), mf_["edge_d"], mf_["cam_offset"], "minifix_edge", j))
                    top.holes.append(Hole(top.id, pt, n, mf_["bolt_d"], mf_["bolt_depth"], "minifix_bolt", j))
                for y in mids:
                    j = J("DW")
                    pt = (xc, y, H - t)
                    top.holes.append(Hole(top.id, pt, unit(2, +1), dw_["d"], dw_["face_depth"], "dowel_face", j))
                    side.holes.append(Hole(side.id, pt, unit(2, -1), dw_["d"], dw_["edge_depth"], "dowel_edge", j))
        else:
            raise BuildError(f"top_joint: minifix/confirmat, а не {top_joint!r}")

    # --- петли ---
    hg = shop["hinges"]
    shelf_spans = [(s.box.lo[2], s.box.hi[2]) for s in shelves]

    def hinge_conflict(z):
        return any(z + hg["zone"] > a and z - hg["zone"] < b for a, b in shelf_spans)

    for d in doors:
        z0, z1 = d.box.lo[2], d.box.hi[2]
        n = _hinge_count(z1 - z0, hg["count_by_height"])
        lo, hi = z0 + hg["end_offset"], z1 - hg["end_offset"]
        zs = [round(lo + (hi - lo) * i / (n - 1), 1) for i in range(n)]
        for i, inward in ((0, +1), (n - 1, -1)):
            if hinge_conflict(zs[i]):
                for k in range(1, 4):  # крайнюю петлю двигаем только внутрь двери, до 3 шагов по 32 мм
                    z = zs[i] + inward * k * hg["plate_pitch"]
                    others = [zz for j, zz in enumerate(zs) if j != i]
                    if not hinge_conflict(z) and all(abs(z - zz) >= 2 * hg["zone"] for zz in others):
                        notes.append(f"{d.name}: крайняя петля сдвинута с {zs[i]:.0f} на {z:.0f} мм — мешала полка.")
                        zs[i] = z
                        break
                else:
                    raise BuildError(f"{d.name}: петля на {zs[i]:.0f} мм упирается в полку — сдвиньте полку")
        for i in range(1, n - 1):
            if hinge_conflict(zs[i]):
                for k in itertools.chain.from_iterable((s, -s) for s in range(1, 8)):
                    z = zs[i] + k * hg["plate_pitch"]
                    if lo + 64 <= z <= hi - 64 and not hinge_conflict(z):
                        notes.append(f"{d.name}: петля сдвинута с {zs[i]:.0f} на {z:.0f} мм — мешала полка.")
                        zs[i] = z
                        break
                else:
                    raise BuildError(f"{d.name}: не нашёл места для петли без полки")
        hs = d.meta["hinge_side"]
        side = sL if hs == "left" else sR
        cx = d.box.lo[0] + hg["cup_center_from_edge"] if hs == "left" else d.box.hi[0] - hg["cup_center_from_edge"]
        sx, sdir = (t, unit(0, -1)) if hs == "left" else (W - t, unit(0, +1))
        py = cy0 + hg["plate_line"]
        d.meta.update(hinges=zs, pivot_x=(d.box.lo[0] if hs == "left" else d.box.hi[0]))
        for z in zs:
            j = J("HG")
            d.holes.append(Hole(d.id, (cx, tf, z), unit(1, -1), hg["cup_d"], hg["cup_depth"], "hinge_cup", j))
            for dz in (-hg["plate_pitch"] / 2, hg["plate_pitch"] / 2):
                side.holes.append(Hole(side.id, (sx, py, z + dz), sdir, hg["plate_d"], hg["plate_depth"], "hinge_plate", j))

    # --- ручки ---
    hcfg = con.get("handle")
    if hcfg and doors:
        for d in doors:
            hs = d.meta["hinge_side"]
            hx = d.box.hi[0] - hcfg["edge_offset"] if hs == "left" else d.box.lo[0] + hcfg["edge_offset"]
            if "from_top" in hcfg:
                zc = d.box.hi[2] - hcfg["from_top"]
            else:
                zc = float(hcfg["from_floor"])
            if not (d.box.lo[2] + 50 < zc < d.box.hi[2] - 50):
                raise BuildError(f"{d.name}: ручка на {zc:.0f} мм вне двери")
            j = J("HN")
            for dz in (-hcfg["pitch"] / 2, hcfg["pitch"] / 2):
                d.holes.append(Hole(d.id, (hx, tf, zc + dz), unit(1, -1), shop["handle"]["d"], tf, "handle", j,
                                    through=True))
            d.meta["handle"] = {"x": hx, "z": zc, "pitch": hcfg["pitch"]}

    # --- полкодержатели: ряд ±N шагов вокруг полки, пропуская места, занятые другим крепежом ---
    sp = shop["shelf_pins"]
    wall = fs["min_wall"]
    rows_y = [cy0 + sp["line"], back_plane - sp["line"]]
    for s in shelves:
        if s.role != "shelf":
            continue
        z_nom = s.box.lo[2] - sp["drop"]
        j = J("SP")
        for side, sx, sdir in ((sL, t, unit(0, -1)), (sR, W - t, unit(0, +1))):
            for y in rows_y:
                placed = 0
                for k in range(-sp["extra_positions"], sp["extra_positions"] + 1):
                    z = z_nom + k * sp["pitch"]
                    h = Hole(side.id, (sx, y, z), sdir, sp["d"], sp["depth"], "shelf_pin", j)
                    blocked = any(seg_seg_dist(h.p, h.end, o.p, o.end) < (h.d + o.d) / 2 + wall for o in side.holes)
                    in_other = any(a - 8 < z < b + 8 for a, b in shelf_spans if (a, b) != (s.box.lo[2], s.box.hi[2]))
                    outside = not (inner_z0 + 8 < z < inner_z1 - 8)
                    if blocked or in_other or outside:
                        if k == 0:
                            raise BuildError(f"{s.name} {s.id}: основное отверстие полкодержателя занято")
                        notes.append(f"{side.name}: пропущено отверстие полкодержателя на {z:.0f} мм (занято/вне проёма).")
                        continue
                    side.holes.append(h)
                    placed += 1

    # --- фурнитура без своих отверстий ---
    hardware = []
    if back_type == "overlay":
        bw, bh = back.box.size[0], back.box.size[2]
        nails = int(round(2 * (bw + bh) / bk["fastener_pitch"]))
        hardware.append(("Гвоздь/саморез для ХДФ", nails, "шт", "задняя стенка накладная, шаг ~%d мм" % bk["fastener_pitch"]))

    prod = Product(
        id=pr["id"], name=pr["name"], prefix=pr.get("prefix", "D"), qty=int(pr.get("qty", 1)),
        size=(W, D, H), panels=panels, materials={k: mats[k] for k in set(mkeys.values())}, shop=shop,
        params=cfg, notes=notes, facade_field=field, hardware=hardware,
    )
    prod.meta = {"cy0": cy0, "cy1": cy1, "back_plane": back_plane, "inner_z": (inner_z0, inner_z1),
                 "top_type": top_type, "back_type": back_type, "plinth": ph}
    return prod
