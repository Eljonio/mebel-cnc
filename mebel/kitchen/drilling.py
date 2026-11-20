"""Присадка кухни (второй этап): отверстия в деталях корпусов из той же модели.

Правила (цеховые числа — shop.yaml, допущения до сверки с цехом):
- конфирмат на каждый стык «торец детали Q упирается в пласть детали P» внутри модуля: сквозное Ø7 в пласть P,
  глухое Ø5 в торец Q, оба из одной точки стыка (соосность по построению). Ряд по длине стыка: от края 50, шаг ≤ 300;
  стык короче 120 — две точки по ¼ и ¾ длины (короче 60 — одна по центру);
- петля: чашка Ø35×13 в фасаде (22 от края двери), планка — два Ø5×12 на боковине/стойке со стороны петель,
  линия 37 от переднего края, ±16 от оси петли. Оси петель — 100 от верха/низа двери, средние равномерно; петлю,
  попавшую в полку (±40), сдвигаем на шаг 32;
- полкодержатели Ø5×10 под съёмные полки: два ряда (37 от переднего края и 37 от задней стенки), основное
  положение и ±2 шага по 32, занятые места пропускаем;
- стыки соседних корпусов (стяжки), ножки, навесы, направляющие ящиков, TIP-ON — крепятся по месту/по кондуктору,
  в станочную присадку не входят (честно перечислено в итогах).
Фасады — не детали раскроя ЛДСП (их делает фасадный цех): их отверстия (чашки петель, крепёж видимых боковин МДФ)
собираются в отдельный список k.facade_ops.
"""
from __future__ import annotations

import itertools
import math

from ..geom import Box, seg_seg_dist
from ..model import Hole, Panel
from .layout import Kitchen

EPS = 0.05
NO_JOINT = ("drawer_bottom", "drawer_back")


def _axis_u(run: str) -> int:
    return 0 if run == "A" else 1


def _axis_v(run: str) -> int:
    return 1 if run == "A" else 0


def _row(a: float, b: float, edge: float, pitch: float) -> list[float]:
    L = b - a
    if L < 60:
        return [round((a + b) / 2, 1)]
    if L < 2 * edge + 20:
        return [round(a + L / 4, 1), round(b - L / 4, 1)]
    n = max(2, math.ceil((L - 2 * edge) / pitch) + 1)
    return [round(a + edge + (L - 2 * edge) * i / (n - 1), 1) for i in range(n)]


class _Pseudo:
    """Видимая боковина из МДФ (не деталь раскроя ЛДСП) — участвует в стыках как пласть."""

    def __init__(self, sid, box, thin, t):
        self.id, self.box, self.thin, self.thickness, self.holes, self.role = sid, box, thin, t, [], "side_mdf"
        self.name = "Боковина видимая (МДФ)"


def drill(k: Kitchen) -> dict:
    shop = k.shop
    cf = shop["fasteners"]["confirmat"]
    hg = shop["hinges"]
    sp = shop["shelf_pins"]
    wall = shop["fasteners"]["min_wall"]
    jid = itertools.count(1)
    k.facade_ops = []
    stats = {"confirmat": 0, "hinge": 0, "shelf_pin": 0, "skipped_pins": 0, "moved_hinges": [], "notes": []}
    for p in k.panels:
        p.holes.clear()

    mods = [m for m in k.modules if m.carcass]
    for m in mods:
        ps = [p for p in k.panels if p.meta.get("module") == m.id and p.group == "carcass" and p.role not in NO_JOINT]
        pseudo = [_Pseudo(s.id, s.box, _axis_u(m.run), s.box.size[_axis_u(m.run)]) for s in k.solids
                  if s.module == m.id and s.id.startswith(f"{m.id}_side_") and s.mat == "facade"]
        faces = ps + pseudo
        # ---- конфирматы ----
        for P in faces:
            a = P.thin
            for Q in ps:
                if Q is P or Q.thin == a:
                    continue
                if abs(Q.box.lo[a] - P.box.hi[a]) < EPS:
                    sign, plane = +1, P.box.hi[a]
                elif abs(Q.box.hi[a] - P.box.lo[a]) < EPS:
                    sign, plane = -1, P.box.lo[a]
                else:
                    continue
                b = Q.thin
                c = 3 - a - b
                lo_b, hi_b = max(P.box.lo[b], Q.box.lo[b]), min(P.box.hi[b], Q.box.hi[b])
                lo_c, hi_c = max(P.box.lo[c], Q.box.lo[c]), min(P.box.hi[c], Q.box.hi[c])
                if hi_b - lo_b < Q.thickness - EPS or hi_c - lo_c < 30:
                    continue
                bc = (Q.box.lo[b] + Q.box.hi[b]) / 2
                n = [0.0, 0.0, 0.0]
                n[a] = float(sign)
                n = tuple(n)
                for cc in _row(lo_c, hi_c, cf["edge_offset"], cf["max_pitch"]):
                    pt = [0.0, 0.0, 0.0]
                    pt[a], pt[b], pt[c] = plane, bc, cc
                    j = f"CF{next(jid)}"
                    entry = list(pt)
                    entry[a] = plane - sign * P.thickness
                    face = Hole(P.id, tuple(entry), n, cf["face_d"], P.thickness, "confirmat_face", j, through=True)
                    edge = Hole(Q.id, tuple(pt), n, cf["edge_d"], cf["length"] - P.thickness + cf["edge_extra"],
                                "confirmat_edge", j)
                    P.holes.append(face)
                    Q.holes.append(edge)
                    if isinstance(P, _Pseudo):
                        k.facade_ops.append({"solid": P.id, "module": m.id, "kind": "confirmat_face", "p": tuple(entry),
                                             "dir": n, "d": cf["face_d"], "depth": P.thickness})
                    stats["confirmat"] += 1
        # ---- петли ----
        ua, va = _axis_u(m.run), _axis_v(m.run)
        horiz = [p for p in ps + pseudo if p.thin == 2]
        for f in m.facades:
            if not f.hinges:
                continue
            s = f.solid
            lo_side = f.hinge == "corner"
            edge_u = s.box.lo[ua] if lo_side else s.box.hi[ua]
            cand = [p for p in ps if p.thin == ua and p.box.lo[ua] - 2 <= edge_u <= p.box.hi[ua] + 2
                    and p.box.lo[2] < s.box.hi[2] and p.box.hi[2] > s.box.lo[2]]
            if not cand:
                stats["notes"].append(f"{f.module} {f.name}: не нашёл боковину/стойку под планки петель")
                continue
            mp = min(cand, key=lambda p: abs((p.box.lo[ua] + p.box.hi[ua]) / 2 - edge_u))
            face_u = mp.box.hi[ua] if lo_side else mp.box.lo[ua]
            ddir = [0.0, 0.0, 0.0]
            ddir[ua] = -1.0 if lo_side else 1.0
            front = mp.box.hi[va]
            z0, z1 = s.box.lo[2], s.box.hi[2]
            lo = max(z0 + hg["end_offset"], mp.box.lo[2] + hg["zone"])    # от краёв двери, но в пределах боковины
            hi = min(z1 - hg["end_offset"], mp.box.hi[2] - hg["zone"])
            n = f.hinges
            zs = [round(lo + (hi - lo) * i / (n - 1), 1) for i in range(n)] if n > 1 else [round((lo + hi) / 2, 1)]

            # препятствия у боковины: полки/дно/крыша (±20 мм) и техника в шкафу ближе 45 мм к боковине (корпус вытяжки)
            obst = [h.box for h in horiz if h.box.lo[ua] < face_u + 20 and h.box.hi[ua] > face_u - 20]
            obst += [a.box for a in k.solids if a.module == m.id and a.kind == "appliance"
                     and a.box.lo[ua] < face_u + 45 and a.box.hi[ua] > face_u - 45
                     and a.box.hi[va] > front - hg["plate_line"] - 40]

            def bad(z):
                return any(z + hg["zone"] > b.lo[2] and z - hg["zone"] < b.hi[2] for b in obst)

            lo2, hi2 = lo, hi                       # крайние петли — в свободную зону (над техникой), средние — ровно
            while bad(lo2) and lo2 < hi:
                lo2 += 8
            while bad(hi2) and hi2 > lo2:
                hi2 -= 8
            if (lo2, hi2) != (lo, hi):
                stats["moved_hinges"].append(f"{f.module} {f.name}: зона петель {lo:.0f}..{hi:.0f} → {lo2:.0f}..{hi2:.0f}")
                zs = [round(lo2 + (hi2 - lo2) * i / (n - 1), 1) for i in range(n)] if n > 1 else [round(lo2, 1)]
            for i in range(n):
                if not bad(zs[i]):
                    continue
                step = 1 if i < n / 2 else -1
                for kk in itertools.chain.from_iterable((q * step, -q * step) for q in range(1, 8)):
                    z = zs[i] + kk * hg["plate_pitch"]
                    if lo - 40 <= z <= hi + 40 and not bad(z) and all(abs(z - zz) >= 2 * hg["zone"]
                                                                      for jj, zz in enumerate(zs) if jj != i):
                        stats["moved_hinges"].append(f"{f.module} {f.name}: {zs[i]:.0f} → {z:.0f}")
                        zs[i] = z
                        break
                else:
                    stats["notes"].append(f"{f.module} {f.name}: петля на {zs[i]:.0f} упирается в полку")
            cup_u = edge_u + (hg["cup_center_from_edge"] if lo_side else -hg["cup_center_from_edge"])
            for z in zs:
                j = f"HG{next(jid)}"
                for dz in (-hg["plate_pitch"] / 2, hg["plate_pitch"] / 2):
                    pt = [0.0, 0.0, 0.0]
                    pt[ua], pt[va], pt[2] = face_u, front - hg["plate_line"], z + dz
                    mp.holes.append(Hole(mp.id, tuple(pt), tuple(ddir), hg["plate_d"], hg["plate_depth"],
                                         "hinge_plate", j))
                k.facade_ops.append({"solid": s.id, "module": m.id, "kind": "hinge_cup", "u": cup_u, "z": z,
                                     "d": hg["cup_d"], "depth": hg["cup_depth"], "joint": j, "plate_z": z,
                                     "edge": "lo" if lo_side else "hi"})
                stats["hinge"] += 1
            s.meta["hinges_z"] = zs
        # ---- полкодержатели ----
        shelves = [p for p in ps if p.role == "shelf" and p.thin == 2]
        for sh in shelves:
            sides = [p for p in ps + pseudo if p.thin == ua and p.box.lo[2] < sh.box.lo[2] < p.box.hi[2]
                     and (0 < sh.box.lo[ua] - p.box.hi[ua] < 3 or 0 < p.box.lo[ua] - sh.box.hi[ua] < 3)]
            if any(abs(sh.box.lo[ua] - p.box.hi[ua]) < EPS or abs(p.box.lo[ua] - sh.box.hi[ua]) < EPS
                   for p in ps if p.thin == ua):
                continue                                # неподвижная (стыкуется с боковиной) — на конфирматах
            j = f"SP{next(jid)}"
            for side in sides:
                left = side.box.hi[ua] <= sh.box.lo[ua]
                fu = side.box.hi[ua] if left else side.box.lo[ua]
                ddir = [0.0, 0.0, 0.0]
                ddir[ua] = -1.0 if left else 1.0
                rows = [side.box.hi[va] - sp["line"], side.box.lo[va] + sp["line"]]
                z_nom = sh.box.lo[2] - sp["drop"]
                for vv in rows:
                    for kk in range(-sp["extra_positions"], sp["extra_positions"] + 1):
                        z = z_nom + kk * sp["pitch"]
                        pt = [0.0, 0.0, 0.0]
                        pt[ua], pt[va], pt[2] = fu, vv, z
                        h = Hole(side.id, tuple(pt), tuple(ddir), sp["d"], sp["depth"], "shelf_pin", j)
                        busy = any(seg_seg_dist(h.p, h.end, o.p, o.end) < (h.d + o.d) / 2 + wall for o in side.holes)
                        other = any(o.box.lo[2] - 8 < z < o.box.hi[2] + 8 for o in horiz if o is not sh
                                    and o.box.lo[ua] < fu + 20 and o.box.hi[ua] > fu - 20)
                        out = not (side.box.lo[2] + 20 < z < side.box.hi[2] - 20)
                        if busy or other or out:
                            if kk == 0:
                                stats["notes"].append(f"{m.id}: основное отверстие полкодержателя занято ({z:.0f})")
                            stats["skipped_pins"] += 1
                            continue
                        side.holes.append(h)
                        if isinstance(side, _Pseudo):
                            k.facade_ops.append({"solid": side.id, "module": m.id, "kind": "shelf_pin", "p": h.p,
                                                 "dir": h.dir, "d": h.d, "depth": h.depth})
                        stats["shelf_pin"] += 1
    stats["not_cnc"] = ["стяжки между соседними корпусами", "ножки (саморезы в дно)", "навесы верхних и монтажная шина",
                        "направляющие ящиков (по кондуктору/шаблону)", "TIP-ON (саморезы по месту)",
                        "задние стенки ХДФ — накладные, гвозди/саморезы, пазов нет",
                        "уголки доборных планок и планки до потолка"]
    return stats


def check(k: Kitchen) -> list:
    """Проверки присадки кухни: оси петель в чашке и планке совпадают, петли не в полках, полкодержатели парами."""
    from ..checks import _f
    out = []
    by = {}
    for p in k.panels:
        for h in p.holes:
            by.setdefault(h.joint, []).append(h)
    bad = 0
    for op in k.facade_ops:
        if op["kind"] != "hinge_cup":
            continue
        pl = [h for h in by.get(op["joint"], []) if h.kind == "hinge_plate"]
        zc = sum(h.p[2] for h in pl) / len(pl) if pl else None
        if zc is None or abs(zc - op["z"]) > 0.01:
            bad += 1
    n_cups = sum(1 for o in k.facade_ops if o["kind"] == "hinge_cup")
    out.append(_f("error" if bad else "ok", "петли (присадка)",
                  f"{n_cups} петель: ось чашки в фасаде = ось планки на боковине" + (f"; расхождений {bad}" if bad else "")))
    return out


def facade_drill_rows(k: Kitchen) -> list[tuple]:
    """Чашки петель по фасадам: от края двери со стороны петель и от низа двери."""
    rows = []
    sol = {s.id: s for s in k.solids}
    for op in k.facade_ops:
        if op["kind"] != "hinge_cup":
            continue
        s = sol[op["solid"]]
        m = k.module(op["module"])
        ua = _axis_u(m.run)
        lo = op["edge"] == "lo"
        side = ("слева" if lo else "справа") if m.run == "A" else ("справа" if lo else "слева")
        rows.append((op["module"], s.name.split(" ", 1)[1], side, f"{abs(op['u'] - (s.box.lo[ua] if op['edge'] == 'lo' else s.box.hi[ua])):.0f}",
                     f"{op['z'] - s.box.lo[2]:.0f}", f"Ø{op['d']:.0f}×{op['depth']:.0f}"))
    return rows


def panel_box(p: Panel) -> Box:
    return p.box
