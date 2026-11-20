"""Проверки кухни: суммы рядов, высоты, пересечения, окно, дверь, коммуникации, открывание дверей."""
from __future__ import annotations

import itertools
import math

from ..checks import Finding, _f
from ..geom import Box
from ..parts import fmt
from .layout import Kitchen, box_minus

ROOM_KINDS = {"room", "wall", "window", "door", "point"}
EPS = 0.01


def _pieces(s):
    return box_minus(s.box, s.cut) if s.cut else [s.box]


def _hit(boxes_a, boxes_b) -> Box | None:
    best = None
    for a, b in itertools.product(boxes_a, boxes_b):
        x = a.intersect(b)
        if x is not None and min(x.size) > EPS and (best is None or x.volume() > best.volume()):
            best = x
    return best


def _sz(b: Box) -> str:
    s = b.size
    return f"{fmt(s[0])}×{fmt(s[1])}×{fmt(s[2])}"


def check_sums(k: Kitchen) -> list[Finding]:
    out = []
    names = {"lower_a": "нижние вдоль A (от угла)", "lower_b": "нижние вдоль B (от угла)",
             "upper_a": "верхние вдоль A", "upper_b": "верхние вдоль B"}
    src = k.cfg["kitchen"].get("source_word", "ТЗ")
    for key, target in (k.cfg.get("targets") or {}).items():
        if key not in names:
            continue
        got = k.runs.get(key, 0.0)
        lvl = "нижний" if key.startswith("lower") else "верхний"
        mods = [m for m in k.modules if m.run == key[-1].upper() and m.level == lvl
                and m.type not in ("end_panel", "corner_filler") and m.in_run]
        chain = " + ".join(f"{m.id} {fmt(m.width)}" for m in sorted(mods, key=lambda m: m.u0))
        if abs(got - float(target)) > 0.5:
            out.append(_f("error", "сумма модулей", f"{names[key]}: {fmt(got)} мм, а по {src} {fmt(target)} ({chain})"))
        else:
            start = min((m.u0 for m in mods), default=0)
            pre = f"угол {fmt(start)} + " if start else ""
            out.append(_f("ok", "сумма модулей", f"{names[key]}: {pre}{chain} = {fmt(got)} мм = {src}"))
    return out


def check_heights(k: Kitchen) -> list[Finding]:
    g = k.geo
    h = k.cfg["heights"]
    out = []
    zw = h["plinth"] + h["lower_carcass"] + h["worktop"]
    txt = f"цоколь {h['plinth']} + корпус {h['lower_carcass']} + столешница {h['worktop']} = {fmt(zw)}"
    target = (k.cfg.get("targets") or {}).get("worktop_z")
    if target is not None:
        if abs(zw - float(target)) > 0.5:
            out.append(_f("error", "высоты", f"{txt}, а по заданию верх столешницы {fmt(target)}"))
        else:
            out.append(_f("ok", "высоты", f"{txt} = заданию"))
    if k.cfg["room"]["window"].get("wall", "A") == "A":
        sill = k.cfg["room"]["window"]["z0"]
        if abs(zw - sill) > 0.5:
            out.append(_f("error", "высоты", f"{txt}, а подоконник {sill} — не вровень"))
        else:
            out.append(_f("ok", "высоты", f"{txt} = подоконник {sill}"))
    wt = [s for s in k.kind("worktop")]
    if any(abs(s.box.hi[2] - zw) > 0.5 for s in wt):
        out.append(_f("error", "высоты", "верх столешницы в модели не совпадает с расчётом"))
    carc = [s for s in k.kind("carcass") if s.panel is not None and s.panel.role == "side" and s.box.hi[2] <= g["zc"] + 1]
    bad = [s.id for s in carc if abs(s.box.hi[2] - g["zc"]) > 0.5]
    if bad:
        out.append(_f("error", "высоты", f"боковины нижних не доходят до столешницы: {bad}"))
    else:
        out.append(_f("ok", "высоты", f"боковины нижних ({len(carc)} шт) ровно до низа столешницы {fmt(g['zc'])}, "
                      f"фасады нижних {fmt(g['fz0'])}..{fmt(g['fz1'])} = {fmt(g['fz1'] - g['fz0'])} мм"))
    up = k.cfg["heights"]
    hood_gap = up["hood_bottom"] - zw
    if k.cfg["kitchen"].get("hob", "induction") != "gas":
        lvl = "ok" if 650 <= hood_gap <= 750 else "warn"
        out.append(_f(lvl, "высоты", f"верхние Z {up['upper_bottom']}..{up['upper_top']} ({up['upper_bottom'] - zw} над "
                      f"столешницей), низ вытяжки {up['hood_bottom']} = {hood_gap} над варкой (норма индукции 650–750)"))
    else:
        uf = up['upper_bottom'] - g["udrop"]
        out.append(_f("ok", "высоты", f"верхние: фасады с {fmt(uf)} ({fmt(uf - zw)} над столешницей), корпус "
                      f"{up['upper_bottom']}..{up['upper_top']}; вытяжка — проверка «газ»"))
    cs = up.get("ceiling_strip")
    if cs:
        H = float(k.cfg["room"]["height"])
        gap = H - up["upper_top"]
        strip = k.geo.get("ceiling_strip", 0)
        lvl = "ok" if 0 < gap - strip <= 5 else "warn"
        out.append(_f(lvl, "высоты", f"от верха шкафов {up['upper_top']} до потолка {fmt(H)} — {fmt(gap)} мм: планка "
                      f"{fmt(strip)} + {fmt(gap - strip)} на подгонку по месту"))
    return out


def check_overlaps(k: Kitchen) -> list[Finding]:
    items = [(s, _pieces(s)) for s in k.solids if s.kind != "point"]
    bad = []
    for (a, pa), (b, pb) in itertools.combinations(items, 2):
        if a.kind in ROOM_KINDS and b.kind in ROOM_KINDS:
            continue
        if a.meta.get("part_of") and a.meta.get("part_of") == b.meta.get("part_of"):
            continue                      # куски одной детали техники (решётка варочной)
        if not a.box.intersect(b.box):
            continue
        x = _hit(pa, pb)
        if x is not None:
            bad.append(_f("error", "пересечения", f"«{a.name}» ({a.id}) и «{b.name}» ({b.id}) залезают друг в друга "
                          f"на {_sz(x)} мм"))
    if not bad:
        n = sum(1 for s, _ in items if s.kind not in ROOM_KINDS)
        return [_f("ok", "пересечения", f"{n} тел мебели и техники не залезают друг в друга и в стены "
                   "(вырезы под профиль, мойку и варку учтены)")]
    return bad


def check_inside_room(k: Kitchen) -> list[Finding]:
    room = k.geo["room"]
    out = [_f("error", "стены", f"«{s.name}» выходит за помещение: {s.box.lo}..{s.box.hi}")
           for s in k.solids if s.kind not in ROOM_KINDS and not room.contains(s.box, tol=0.01)]
    return out or [_f("ok", "стены", "вся мебель и техника внутри помещения (в стены не заходит)")]


def check_window(k: Kitchen) -> list[Finding]:
    w = k.geo["window"]
    sash = 700  # створка открывается внутрь — зона перед окном
    if k.geo.get("window_wall", "A") == "C":
        a = float(k.cfg["room"]["a"])
        zone = Box((a - sash, w.lo[1], w.lo[2]), (w.hi[0], w.hi[1], w.hi[2]))
        bad = [s for s in k.solids if s.kind not in ROOM_KINDS and _hit(_pieces(s), [zone])]
        out = [_f("error", "окно", f"«{s.name}» ({s.id}) заходит в зону створки окна на стене C "
                  f"(Y {fmt(w.lo[1])}..{fmt(w.hi[1])}, {sash} мм в комнату)") for s in bad]
        if not bad:
            out.append(_f("ok", "окно", f"окно на стене C (Y {fmt(w.lo[1])}..{fmt(w.hi[1])}): в зону створки "
                          f"{sash} мм ничего не заходит; положение окна — сверить замером"))
        return out
    zone = Box(w.lo, (w.hi[0], sash, w.hi[2]))
    bad = [s for s in k.solids if s.kind not in ROOM_KINDS and _hit(_pieces(s), [zone])]
    out = [_f("error", "окно", f"«{s.name}» ({s.id}) заходит в проём окна или зону створки "
              f"(X {fmt(w.lo[0])}..{fmt(w.hi[0])}, Z {fmt(w.lo[2])}..{fmt(w.hi[2])}, {sash} мм в комнату)") for s in bad]
    if not bad:
        out.append(_f("ok", "окно", f"в проём окна и зону створки ({sash} мм в комнату) ничего не заходит; "
                      f"столешница вровень с подоконником {fmt(w.lo[2])}"))
    ups = [s for s in k.kind("carcass", "facade", "filler") if s.box.lo[2] >= 1000 and s.box.lo[1] < 400
           and s.box.hi[0] <= w.lo[0]]
    if ups:
        x = max(s.box.hi[0] for s in ups)
        gap = w.lo[0] - x
        out.append(_f("ok" if gap >= 50 else "warn", "окно",
                      f"верхние вдоль A кончаются на X {fmt(x)}, до откоса окна {fmt(gap)} мм"))
    return out


def check_door(k: Kitchen) -> list[Finding]:
    d = k.geo["door"]
    clear = 800
    zone = Box((0.0, d.lo[1], 0.0), (clear, d.hi[1], d.hi[2]))
    width = d.size[1]
    out = []
    bad = [s for s in k.solids if s.kind not in ROOM_KINDS and _hit(_pieces(s), [zone])]
    for s in bad:
        out.append(_f("error", "дверь", f"«{s.name}» ({s.id}) стоит в проёме двери или в зоне прохода перед ней "
                      f"(Y {fmt(d.lo[1])}..{fmt(d.hi[1])}, {clear} мм в комнату)"))
    if width < 800:
        out.append(_f("error", "дверь", f"ширина проёма {fmt(width)} < 800"))
    fr = k.geo.get("fridge")
    if fr and fr["run"] == "B":
        y_open = fr["u1"] if fr["hinge"] == "far" else fr["u0"]
        sw = Box.of(fr["v1"], fr["v1"] + (fr["u1"] - fr["u0"]), y_open - 30, y_open + 30, 0, 2000)
        if _hit([sw], [zone]):
            out.append(_f("error", "дверь", "дверь холодильника при открытии заходит в проход у двери"))
    if not bad and width >= 800:
        near = max((s.box.hi[1] for s in k.solids if s.kind not in ROOM_KINDS and s.box.lo[0] < clear
                    and s.box.hi[1] <= d.lo[1] + EPS and s.box.lo[2] < d.hi[2]), default=0.0)
        out.append(_f("ok", "дверь", f"проём Y {fmt(d.lo[1])}..{fmt(d.hi[1])} = {fmt(width)} мм свободен, перед ним "
                      f"{clear} мм прохода; ближайшая мебель кончается на Y {fmt(near)} "
                      f"({fmt(d.lo[1] - near)} мм до проёма)"))
    return out


def _point(k: Kitchen, pid: str):
    return next((p for p in k.points if p["id"] == pid), None)


def check_utilities(k: Kitchen) -> list[Finding]:
    out = []
    mods = {m.type: m for m in k.modules}
    # мойка над водой
    wp = _point(k, "water")
    sk = k.appl.get("sink")
    sink = k.module(sk.module) if sk is not None else mods.get("sink")
    if wp and sink:
        x = wp["pt"][0] if sink.run == "A" else wp["pt"][1]
        inner = (sink.u0 + k.geo["t"], sink.u1 - k.geo["t"])
        if sink.type == "corner_sink":               # в угловом — только зона мойки (за стойкой), не глухая часть
            inner = k.geo["corner_sink"]["zone"]
        sb = k.geo["sink_box"]
        sc = (sb.lo[0] + sb.hi[0]) / 2
        if wp["wall"] != "A" or sink.run != "A" or not inner[0] < x < inner[1]:
            out.append(_f("error", "мойка над водой", f"вывод воды {wp['wall']}:{fmt(x)} не внутри шкафа мойки "
                          f"{sink.id} ({fmt(inner[0])}..{fmt(inner[1])})"))
        elif wp["pt"][2] >= k.geo["sink_bowl_z"] - 50:
            out.append(_f("error", "мойка над водой", f"вывод воды на {fmt(wp['pt'][2])} не ниже чаши "
                          f"({fmt(k.geo['sink_bowl_z'])}) — сифону некуда"))
        else:
            out.append(_f("ok", "мойка над водой", f"вывод воды X {fmt(x)} Z {fmt(wp['pt'][2])} внутри {sink.id} "
                          f"(внутри {fmt(inner[0])}..{fmt(inner[1])}), ниже дна чаши {fmt(k.geo['sink_bowl_z'])}; "
                          f"центр мойки X {fmt(sc)}, до вывода {fmt(abs(sc - x))} мм"))
    # варка под вентиляцией
    vp = _point(k, "vent")
    hood, hob = k.appl.get("hood"), k.appl.get("hob")
    if vp and hood and hob:
        hc = (hood.box.lo[0] + hood.box.hi[0]) / 2
        bc = (hob.box.lo[0] + hob.box.hi[0]) / 2
        x = vp["pt"][0]
        ok = hood.box.lo[0] < x < hood.box.hi[0] and abs(hc - bc) <= 1
        top = max(s.box.hi[2] for s in k.solids if s.module == hood.module and s.kind == "carcass") - k.geo["t"]
        fits = vp["pt"][2] + vp.get("d", 150) / 2 <= top
        if ok and fits:
            out.append(_f("ok", "варка под вентиляцией", f"варка по центру X {fmt(bc)}, вытяжка X {fmt(hc)}, вывод X "
                          f"{fmt(x)} Z {vp['z']} внутри шкафа {hood.module} (Ø{vp.get('d', 150)} помещается под "
                          f"крышей {fmt(top)})"))
        else:
            out.append(_f("error", "варка под вентиляцией", f"вытяжка X {fmt(hc)} / варка X {fmt(bc)} / вывод X "
                          f"{fmt(x)} Z {vp['z']}: не сходится (или вывод выше крыши шкафа {fmt(top)})"))
    # розетка варки
    hp = _point(k, "hob_power")
    oven = k.appl.get("oven")
    if hp and oven:
        z0, z1 = k.geo["oven_z"]
        x = hp["pt"][0]
        behind = oven.box.lo[0] <= x <= oven.box.hi[0] and z0 <= hp["pt"][2] <= z1
        gap = k.geo["oven_back_v"]
        if behind and gap < 50:
            out.append(_f("warn", "розетка варки",
                          f"розетка X {fmt(x)} Z {fmt(hp['pt'][2])} оказывается за корпусом духовки (Z {fmt(z0)}.."
                          f"{fmt(z1)}), от стены до духовки {fmt(gap)} мм — вилка с розеткой (~50–60 мм) не влезет. "
                          f"Перенести розетку на Z≈150 (под полку духовки, за съёмную фальш-панель) "
                          f"или в соседний шкаф"))
        else:
            out.append(_f("ok", "розетка варки", f"розетка X {fmt(x)} Z {fmt(hp['pt'][2])} доступна"))
    fp = _point(k, "fridge_power")
    fr = k.appl.get("fridge")
    if fp and fr:
        y = fp["pt"][1]
        inside = fr.box.lo[1] <= y <= fr.box.hi[1] and fp["wall"] == "B"
        gap = fr.box.lo[0]
        lvl = "ok" if inside and gap >= 40 else "warn"
        extra = f" ({fp['assumed']})" if fp.get("assumed") else ""
        out.append(_f(lvl, "розетка холодильника", f"розетка Y {fmt(y)} Z {fmt(fp['pt'][2])}{extra}: за холодильником "
                      f"Y {fmt(fr.box.lo[1])}..{fmt(fr.box.hi[1])}, зазор до стены {fmt(gap)} мм"))
    return out


def check_dishwasher(k: Kitchen) -> list[Finding]:
    dw = k.appl.get("dw")
    if not dw:
        return []
    ap = k.cfg["appliances"]["dishwasher"]
    out = []
    h = k.geo["dw_niche_h"]
    lvl = "ok" if ap["niche_min"] <= h <= ap["niche_max"] else "error"
    out.append(_f(lvl, "посудомойка", f"ниша ПММ по высоте {fmt(h)} мм (типовые {ap['niche_min']}–{ap['niche_max']})"))
    fac = next(f for m in k.modules if m.type == "dishwasher" for f in m.facades)
    lvl = "ok" if fac.h <= ap["facade_max"] else "warn"
    out.append(_f(lvl, "посудомойка", f"фасад ПММ {fmt(fac.w)}×{fmt(fac.h)} — сверить с паспортом модели "
                  f"(высота и вес фасада, «скользящая петля»)"))
    if k.geo.get("opening", "gola") == "gola":
        out.append(_f("warn", "посудомойка", f"профиль Gola L заходит в нишу ПММ сверху спереди на "
                      f"{k.shop['kitchen']['gola_L']['depth']} мм: верх двери ПММ должен быть не выше "
                      f"{fmt(k.geo['dw_door_top'])} мм от пола — выбрать модель, где это допускается (проверить по паспорту)"))
    else:
        rng = ap.get("facade_h")
        if rng:
            lvl = "ok" if rng[0] <= fac.h <= rng[1] else "warn"
            out.append(_f(lvl, "посудомойка", f"фасад ПММ {fmt(fac.h)} при цоколе {fmt(k.geo['zp'])}: по инструкции "
                          f"допускается {rng[0]}–{rng[1]} ({ap.get('facade_src', 'паспорт модели')})"))
        out.append(_f("warn", "посудомойка", "фасад без ручки: нужна ПММ с открыванием нажатием (у Bosch 45 см такой "
                      "модели в инструкциях не нашли — искать у других марок) или ручка/выборка на фасаде ПММ"))
    sink = k.geo.get("sink_box")
    if sink and "corner_sink" in k.geo:
        dwb = dw.box
        d = abs((dwb.lo[0] + dwb.hi[0]) / 2 - (sink.lo[0] + sink.hi[0]) / 2) + \
            abs((dwb.lo[1] + dwb.hi[1]) / 2 - (sink.lo[1] + sink.hi[1]) / 2)
        out.append(_f("ok" if d <= 1500 else "warn", "посудомойка",
                      f"ПММ рядом с мойкой (~{d / 1000:.1f} м по полу и стене): шланги слива и залива — в глухую часть "
                      f"{k.geo['corner_sink']['module']} через отверстие Ø60 в дне (по месту), слив — в сифон мойки"))
    elif sink:
        d = abs((dw.box.lo[0] + dw.box.hi[0]) / 2 - (sink.lo[0] + sink.hi[0]) / 2)
        lvl = "warn" if d > 1000 else "ok"
        out.append(_f(lvl, "посудомойка", f"ПММ в {fmt(d)} мм от мойки: шланг слива до сифона ~{d / 1000 + 0.3:.1f} м — "
                      "нужен удлинитель/отдельный отвод в канализацию; шланги идут через Н4 и Н3 (отверстия в боковинах)"))
    return out


def door_swing_box(s, opened_margin=3.0) -> Box:
    """Дверь, открытая на 90°: коробка, которую она занимает перед плоскостью фасадов."""
    b = s.box
    run, hinge = s.meta["run"], s.meta["hinge"]
    ua, va = (0, 1) if run == "A" else (1, 0)
    t = b.size[va]
    w = b.size[ua]
    mirrored = s.meta.get("mirrored")
    front = b.hi[va] if not (mirrored and run == "B") else b.lo[va]
    sign = 1 if front == b.hi[va] else -1
    lo_side = (hinge == "corner") != bool(mirrored and run == "A")
    piv = b.lo[ua] if lo_side else b.hi[ua]
    u_rng = (piv - t - opened_margin, piv) if lo_side else (piv, piv + t + opened_margin)
    v_rng = (front, front + sign * w)
    lo, hi = [0.0] * 3, [0.0] * 3
    lo[ua], hi[ua] = u_rng
    lo[va], hi[va] = min(v_rng), max(v_rng)
    lo[2], hi[2] = b.lo[2], b.hi[2]
    return Box(tuple(lo), tuple(hi))


def check_swing(k: Kitchen) -> list[Finding]:
    out = []
    doors = [s for s in k.kind("facade") if s.meta.get("hinge")]
    others = [s for s in k.solids if s.kind in ("appliance", "wall", "carcass", "filler", "worktop") or
              (s.kind == "facade" and not s.meta.get("hinge"))]
    for d in doors:
        sw = door_swing_box(d)
        for o in others:
            if o.module == d.module and o.kind == "carcass":
                continue
            x = _hit([sw], _pieces(o))
            if x is not None:
                out.append(_f("error", "открывание дверей", f"«{d.name}» при открытии на 90° цепляет «{o.name}» "
                              f"({_sz(x)} мм)"))
    if not out:
        out.append(_f("ok", "открывание дверей", f"{len(doors)} распашных дверей открываются на 90° без касаний "
                      "(холодильник, стены, соседние корпуса)"))
    return out


def check_worktop(k: Kitchen) -> list[Finding]:
    out = []
    lens = k.shop["kitchen_materials"][k.cfg["materials"]["worktop"]]["lengths"]
    for s in k.kind("worktop"):
        L = max(s.box.size[0], s.box.size[1])
        if L > max(lens):
            out.append(_f("error", "столешница", f"«{s.name}» {fmt(L)} мм длиннее заготовки {max(lens)}"))
    hs = k.geo["worktop_holes"]
    if len(hs) == 2:
        a, b = sorted(hs, key=lambda h: h.lo[0])
        gap = b.lo[0] - a.hi[0]
        out.append(_f("ok" if gap >= 200 else "warn", "столешница",
                      f"между вырезами мойки и варки {fmt(gap)} мм (рабочее место)"))
    if not any(f.level == "error" for f in out):
        out.append(_f("ok", "столешница", "куски столешницы помещаются в стандартные заготовки"))
    return out


def _dist_box(pt, b: Box) -> float:
    return sum(max(lo - c, 0.0, c - hi) ** 2 for c, lo, hi in zip(pt, b.lo, b.hi)) ** 0.5


def _module_at(k: Kitchen, pt, level="нижний"):
    """Модуль, внутри корпуса которого стоит точка на стене (по оси ряда и высоте)."""
    for m in k.modules:
        if m.level != level or not m.carcass or m.run not in ("A", "B"):
            continue
        u = pt[0] if m.run == "A" else pt[1]
        v = pt[1] if m.run == "A" else pt[0]
        if m.u0 < u < m.u1 and m.z0 < pt[2] < m.z1 and v < 5:
            return m
    return None


def check_gas(k: Kitchen) -> list[Finding]:
    """Газовая варочная: высота вытяжки над решётками, кран перед прибором (доступ, шланг), розетки от крана."""
    if k.cfg["kitchen"].get("hob") != "gas":
        return []
    gc = k.cfg.get("gas", {})
    out = []
    hood, hob = k.appl.get("hood"), k.appl.get("hob")
    if hood is not None and hob is not None:
        top = k.geo.get("hob_top", hob.box.hi[2])
        zh = hood.box.lo[2]
        need = float(gc.get("hood_min", 650))
        gap = zh - top
        txt = (f"низ вытяжки {fmt(zh)} над решётками газовой панели ({fmt(top)}) — {fmt(gap)} мм, над столешницей "
               f"{fmt(zh - k.geo['zw'])}; по инструкции вытяжки над газом не меньше {fmt(need)} "
               f"({gc.get('hood_src', 'инструкция производителя вытяжки')})")
        if gap + 0.5 < need:
            up = need - gap
            up10 = math.ceil(up / 10) * 10
            out.append(_f("critical", "газ", txt + f". НЕ ХВАТАЕТ {fmt(up)} мм. Варианты: (1) поднять шкаф вытяжки на "
                          f"{fmt(up10)} (нужно ≥ {fmt(up)}) — низ {fmt(zh + up10)}, его дверь короче на {fmt(up10)}, "
                          f"соседние шкафы без изменений; (2) индукция вместо газа — тогда хватает "
                          f"{gc.get('hood_min_electric', 'по инструкции')}, высоты остаются как есть"))
        else:
            out.append(_f("ok", "газ", txt))
        side = gc.get("upper_side_min")
        if side:
            ups = [m for m in k.modules if m.level == "верхний" and m.type not in ("hood", "end_panel", "ceiling_strip")
                   and m.carcass]
            low = min(min(f.solid.box.lo[2] for f in m.facades) if m.facades else m.z0 for m in ups)
            gap = low - k.geo["zw"]
            out.append(_f("ok" if gap >= float(side[1]) else "critical", "газ",
                          f"навесные шкафы сбоку от газовой панели: низ {fmt(low)} = {fmt(gap)} над столешницей "
                          f"(нужно ≥ {side[1]} — инструкция газовой панели BSH 8001317828, рис. 1)"))
    gp = _point(k, "gas")
    if gp is None:
        out.append(_f("critical", "газ", "не задан кран газа перед варочной (Требования МВД РК № 673, п. 232: отключающее "
                      "устройство перед каждым газовым прибором) — указать, где выход газа"))
        return out
    pt = gp["pt"]
    m = _module_at(k, pt)
    doors = [f for f in m.facades if f.hinge] if m else []
    if m and doors and m.type in ("doors", "corner_sink"):
        out.append(_f("ok", "газ", f"кран газа X {fmt(pt[0])} Z {fmt(pt[2])} — в шкафу {m.id} за распашной дверью "
                      f"(доступен без инструмента); п. 232 Требований № 673 — кран перед прибором"))
    else:
        where = f"в {m.id} ({m.type})" if m else "не в шкафу с дверью"
        out.append(_f("critical", "газ", f"кран газа X {fmt(pt[0])} Z {fmt(pt[2])} {where}: должен быть доступен — "
                      "перенести в шкаф с распашной дверью рядом с варочной"))
    if hob is not None:
        conn = (hob.box.hi[0] - 40, hob.box.lo[1] + 60, k.geo["zc"] - 30)   # штуцер панели — сзади справа (допущение)
        hose = abs(conn[0] - pt[0]) + abs(conn[1] - pt[1]) + abs(conn[2] - pt[2]) + 150
        hmax = float(gc.get("hose_max", 1500))
        out.append(_f("ok" if hose <= hmax else "warn", "газ",
                      f"шланг от крана до штуцера панели ~{hose / 1000:.1f} м (по стенам, с запасом), предел "
                      f"{hmax / 1000:.1f} м ({gc.get('hose_src', 'допущение — сверить с газовой службой')}); "
                      f"проход через боковину {m.id if m else ''} — отверстие Ø40"))
    smin = float(gc.get("socket_min", 500))
    close = []
    for p in k.points:
        if p.get("kind") == "power":
            d = sum((a - b) ** 2 for a, b in zip(p["pt"], pt)) ** 0.5
            if d < smin:
                close.append(f"{p['name']} {fmt(d)}")
    if close:
        out.append(_f("warn", "газ", f"розетки ближе {fmt(smin)} мм к крану газа: {', '.join(close)} — "
                      f"развести ({gc.get('socket_src', 'практика газовых служб, сверить')})"))
    else:
        out.append(_f("ok", "газ", f"все розетки дальше {fmt(smin)} мм от крана газа "
                      f"({gc.get('socket_src', 'практика газовых служб, сверить')})"))
    room = k.cfg["room"]
    vol = float(room["a"]) * float(room["b"]) * float(room["height"]) / 1e9
    out.append(_f("ok" if vol >= 15 and float(room["height"]) >= 2200 else "warn", "газ",
                  f"кухня по допущенным размерам {vol:.1f} м³, высота {room['height']}: для плиты на 4 конфорки нужно "
                  "≥ 15 м³ и высота ≥ 2,2 м, окно с открывающейся створкой, вентканал (Требования № 673, п. 234) — "
                  "подтвердить замером"))
    return out


SERVES = {"pw_oven": ("oven", "духовка"), "pw_ign": ("hob", "поджиг варочной"), "pw_dw": ("dw", "ПММ"),
          "pw_fridge": ("fridge", "холодильник"), "pw_mw": ("mw", "СВЧ"), "pw_hood": ("hood", "вытяжка и LED")}


def check_sockets(k: Kitchen) -> list[Finding]:
    """Розетки техники: есть, не за корпусом прибора (кроме холодильника — он с зазором от стены), шнур дотягивается."""
    pts = {p["id"]: p for p in k.points if p.get("kind") == "power"}
    if not pts:
        return []
    out = []
    cord = float(k.cfg.get("power", {}).get("cord", 1200))
    bodies = [s for s in k.kind("appliance") if s.id in ("oven_body", "dw_body", "mw_body", "hood")]
    for pid, (ap, nm) in SERVES.items():
        a = k.appl.get(ap)
        if a is None:
            continue
        p = pts.get(pid)
        if p is None:
            out.append(_f("warn", "розетки", f"нет розетки: {nm}"))
            continue
        pt = p["pt"]
        zone = k.cfg["appliances"].get("oven", {}).get("socket_zone") if ap in ("oven", "hob") else None
        if zone and "oven" in k.appl:
            om = k.module(k.appl["oven"].module)
            z0 = k.geo["oven_z"][0]
            if (om.u0 + k.geo["t"] + zone["from_left"] <= pt[0] <= om.u1 - k.geo["t"] - zone["from_right"]
                    and z0 <= pt[2] <= z0 + zone["h"] and pt[1] < 5):
                d = _dist_box(pt, a.box)
                out.append(_f("ok", "розетки", f"{nm}: {p['name']} — в зоне за духовкой, где инструкция духовки "
                              f"разрешает розетку ({zone['from_left']} от левой и {zone['from_right']} от правой стенки "
                              f"ниши, до {zone['h']} от её дна); до прибора {fmt(d)} мм"))
                continue
        al, dp = (0, 1) if p["wall"] == "A" else (1, 0)       # вдоль стены / от стены
        behind = [s.name for s in bodies if s.box.lo[al] - 1 <= pt[al] <= s.box.hi[al] + 1 and
                  s.box.lo[dp] <= 60 and s.box.lo[2] - 40 <= pt[2] <= s.box.hi[2] + 40 and ap != "fridge"]
        d = _dist_box(pt, a.box)
        m = _module_at(k, pt) or _module_at(k, pt, "верхний")
        where = f"в {m.id}" if m else "на стене"
        if behind:
            out.append(_f("warn", "розетки", f"{p['name']} ({where}) за корпусом: {', '.join(behind)} — вилка не встанет"))
        elif d > cord:
            out.append(_f("warn", "розетки", f"{p['name']} {where}: до прибора {fmt(d)} мм, шнур ~{fmt(cord)}"))
        else:
            out.append(_f("ok", "розетки", f"{nm}: {p['name']} {where}, до прибора {fmt(d)} мм — доступна"))
    return out


def check_microwave(k: Kitchen) -> list[Finding]:
    mw = k.geo.get("mw")
    if not mw:
        return []
    sp = k.cfg["appliances"]["microwave"]
    out = []
    w, h, d = mw["niche"]
    src = sp.get("src", "инструкция СВЧ")
    for nm, val, rng in (("ширина", w, sp.get("niche_w")), ("высота", h, sp.get("niche_h_range"))):
        if rng:
            out.append(_f("ok" if rng[0] <= val <= rng[1] else "error", "СВЧ",
                          f"ниша {nm} {fmt(val)} (нужно {rng[0]}–{rng[1]}, {src})"))
    dmin = sp.get("depth_min")
    if dmin:
        out.append(_f("ok" if d >= dmin else "error", "СВЧ", f"глубина ниши {fmt(d)} (корпус верхних {fmt(k.geo['Du'])}, "
                      f"нужно ≥ {dmin}, {src})"))
    p = _point(k, "pw_mw")
    if p:
        m = _module_at(k, p["pt"], "верхний")
        ok = m is not None and m.id == mw["module"] and p["pt"][2] > mw["zf"]
        out.append(_f("ok" if ok else "warn", "СВЧ", f"розетка СВЧ Z {fmt(p['pt'][2])} " +
                      ("в том же шкафу над нишей — доступна, открыв дверь" if ok else "не над нишей в шкафу СВЧ")))
    if sp.get("vent_note"):
        out.append(_f("warn", "СВЧ", sp["vent_note"]))
    return out


def run_all(k: Kitchen) -> list[Finding]:
    out = []
    for fn in (check_sums, check_heights, check_overlaps, check_inside_room, check_window, check_door,
               check_utilities, check_dishwasher, check_swing, check_worktop, check_gas, check_sockets,
               check_microwave):
        out += fn(k)
    return out


def errors(findings) -> list[Finding]:
    return [f for f in findings if f.level == "error"]
