"""Кухня: конфиг помещения и модулей -> твёрдые тела (панели корпусов, фасады, столешница, техника, стены).

Оси помещения (как в ТЗ): X вдоль стены A (0 — угол A/B, слева, если смотреть на A из комнаты),
Y вдоль стены B в комнату (0 — плоскость стены A), Z вверх от пола. Стена B — плоскость X=0.
Внимание: такая тройка осей левая. В three.js кладём (X, Z, Y), в Blender (X, -Y, Z) — тогда картинка не зеркальная.

Ряд модулей строится в своих осях (u — вдоль стены от угла, v — от стены в комнату, z) и переводится в оси помещения:
ряд A: u=X, v=Y; ряд B: u=Y, v=X. Запасной угол A/C — зеркало X -> a - X в самом конце.
Корпусные детали — Panel движка mebel (деталировка, кромка, раскрой берутся оттуда же).
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field

from ..geom import Box
from ..model import Panel, Product


class KitchenError(ValueError):
    pass


TYPE_RU = {
    "corner_blind": "нижний угловой глухой", "sink": "нижний под мойку", "cargo": "нижний бутылочница (карго)",
    "oven": "нижний под духовку и варку", "dishwasher": "ниша посудомойки (ПММ)", "drawers": "нижний с ящиками",
    "fridge": "холодильник отдельностоящий", "filler": "доборная планка", "corner_l": "верхний угловой Г-образный",
    "dryer": "верхний с сушилкой", "shelves": "верхний с полками", "hood": "верхний под встраиваемую вытяжку",
    "corner_sink": "нижний угловой под мойку (глухая часть у угла)", "doors": "нижний распашной",
    "corner_blind_u": "верхний угловой (глухая часть у угла)", "microwave": "верхний с нишей под встраиваемую СВЧ",
    "ceiling_strip": "планка до потолка", "lower_end": "панель торцевая",
}


@dataclass
class Solid:
    id: str
    name: str
    kind: str                  # carcass/back/facade/filler/end_panel/worktop/apron/plinth/gola/led/appliance/room/...
    mat: str                   # ключ материала для картинки
    box: Box
    module: str = ""
    cut: list = field(default_factory=list)      # вычитаемые коробки: вырезы, выборки под профиль
    panel: Panel | None = None
    shape: str = "box"         # box | cyl_z
    meta: dict = field(default_factory=dict)


@dataclass
class Facade:
    module: str
    name: str
    kind: str                  # door/leaf/drawer/dw/cargo/panel/filler/end/corner
    w: float
    h: float
    solid: Solid
    hinge: str | None = None   # corner/far
    hinges: int = 0


@dataclass
class Module:
    id: str
    type: str
    run: str                   # A / B / угол
    u0: float
    u1: float
    z0: float
    z1: float
    carcass: tuple | None      # (Ш, В, Г) корпуса, мм
    inside: str = ""
    facades: list = field(default_factory=list)
    hw: Counter = field(default_factory=Counter)
    notes: list = field(default_factory=list)
    level: str = "нижний"
    in_run: bool = True        # False — стоит в ряду, но в длину ряда не входит (холодильник за мебелью)

    @property
    def width(self):
        return self.u1 - self.u0


class Run:
    """Ряд вдоль стены: u — вдоль стены от угла, v — от стены в комнату."""

    def __init__(self, name: str):
        self.name = name

    def box(self, u0, u1, v0, v1, z0, z1) -> Box:
        return Box.of(u0, u1, v0, v1, z0, z1) if self.name == "A" else Box.of(v0, v1, u0, u1, z0, z1)

    def axis(self, a: str) -> int:
        return {"A": {"u": 0, "v": 1, "z": 2}, "B": {"u": 1, "v": 0, "z": 2}}[self.name][a]

    def face(self, f: str) -> str:
        return f[0] + "xyz"[self.axis(f[1])]


def box_minus(a: Box, cuts) -> list[Box]:
    """Коробка минус коробки -> набор непересекающихся коробок."""
    pieces = [a]
    for c in cuts:
        nxt = []
        for p in pieces:
            x = p.intersect(c)
            if x is None:
                nxt.append(p)
                continue
            lo, hi = list(p.lo), list(p.hi)
            for ax in range(3):
                if lo[ax] < x.lo[ax] - 1e-9:
                    h2 = list(hi)
                    h2[ax] = x.lo[ax]
                    nxt.append(Box(tuple(lo), tuple(h2)))
                    lo[ax] = x.lo[ax]
                if hi[ax] > x.hi[ax] + 1e-9:
                    l2 = list(lo)
                    l2[ax] = x.hi[ax]
                    nxt.append(Box(tuple(l2), tuple(hi)))
                    hi[ax] = x.hi[ax]
        pieces = nxt
    return pieces


def hinge_count(h: float, table) -> int:
    for max_h, n in table:
        if h <= max_h:
            return int(n)
    raise KitchenError(f"фасад {h:.0f} мм выше таблицы петель")


@dataclass
class Kitchen:
    cfg: dict
    shop: dict
    solids: list = field(default_factory=list)
    modules: list = field(default_factory=list)
    panels: list = field(default_factory=list)       # корпусные детали (Panel) — в раскрой
    lpanels: list = field(default_factory=list)      # Г-образные детали: (Panel, кромка видимая мм)
    appl: dict = field(default_factory=dict)         # техника: имя -> Solid (корпус)
    points: list = field(default_factory=list)       # точки коммуникаций в осях помещения
    runs: dict = field(default_factory=dict)         # длины рядов
    hw: Counter = field(default_factory=Counter)     # фурнитура вне модулей
    notes: list = field(default_factory=list)        # решения генератора
    geo: dict = field(default_factory=dict)          # ключевые плоскости и уровни
    product: Product | None = None
    facade_ops: list = field(default_factory=list)   # присадка фасадов (чашки петель, видимая боковина МДФ)
    drill_stats: dict = field(default_factory=dict)  # итоги присадки (второй этап)

    def solid(self, sid: str) -> Solid:
        for s in self.solids:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def kind(self, *kinds) -> list:
        return [s for s in self.solids if s.kind in kinds]

    def module(self, mid: str) -> Module:
        for m in self.modules:
            if m.id == mid:
                return m
        raise KeyError(mid)


class _B:
    """Сборщик кухни."""

    def __init__(self, cfg: dict, shop: dict):
        self.cfg = cfg
        shop = copy.deepcopy(shop)
        shop["materials"] = {**shop["materials"], **shop.get("kitchen_materials", {})}
        self.shop = shop
        self.k = Kitchen(cfg=cfg, shop=shop)
        self.kc = shop["kitchen"]
        h, d = cfg["heights"], cfg["depths"]
        self.mat = cfg["materials"]
        mats = shop["materials"]
        self.t = float(mats[self.mat["carcass"]]["thickness"])
        self.tb = float(mats[self.mat["back"]]["thickness"])
        self.tf = float(d["facade"])
        self.zp = float(h["plinth"])                        # верх цоколя = низ корпуса
        self.zc = self.zp + float(h["lower_carcass"])       # верх корпуса = низ столешницы
        self.zw = self.zc + float(h["worktop"])             # верх столешницы
        self.D = float(d["lower_carcass"])                  # корпус нижних с задней стенкой
        self.Dw = float(d["worktop"])
        self.Du = float(d["upper_carcass"])
        self.uz0, self.uz1 = float(h["upper_bottom"]), float(h["upper_top"])
        self.hz0 = float(h["hood_bottom"])
        # открывание: gola — скрытый профиль-ручка (ТЗ-кухня), push — без ручек, нажатием (TIP-ON)
        self.opening = cfg["kitchen"].get("opening", "gola")
        if self.opening not in ("gola", "push"):
            raise KitchenError("kitchen.opening: gola или push")
        self.push = self.kc.get("push", {})
        self.corner_owner = cfg["kitchen"].get("corner_owner", "B")     # чей нижний модуль занимает угол
        self.udrop = float(h.get("upper_facade_drop", self.kc["upper_facade_drop"]))
        gl = self.kc["gola_L"]
        self.fz0 = self.zp                                  # низ фасадов нижних
        # верх фасадов нижних: под профилем L (gola) или на зазор ниже столешницы (push)
        self.fz1 = self.zc - (gl["gap"] if self.opening == "gola" else float(self.push["top_gap"]))
        self.ufz1 = self.uz1 - self.kc["upper_facade_top_gap"]
        self.g2 = self.kc["facade_gap"] / 2
        self.hinge_table = shop["hinges"]["count_by_height"]
        self.k.geo = {"zp": self.zp, "zc": self.zc, "zw": self.zw, "D": self.D, "Dw": self.Dw, "Du": self.Du,
                      "tf": self.tf, "uz0": self.uz0, "uz1": self.uz1, "hz0": self.hz0, "fz0": self.fz0,
                      "fz1": self.fz1, "t": self.t, "tb": self.tb, "udrop": self.udrop, "opening": self.opening}

    # ---------- примитивы ----------
    def add(self, sid, name, kind, mat, box, module="", cut=(), shape="box", **meta) -> Solid:
        s = Solid(sid, name, kind, mat, box, module, list(cut), None, shape, dict(meta))
        self.k.solids.append(s)
        return s

    def panel(self, run: Run, pid, name, role, mkey, u0, u1, v0, v1, z0, z1, thin, edges, module,
              cut_local=(), group="carcass", kind=None, lshape=None) -> Solid:
        mat = self.shop["materials"][self.mat[mkey]]
        box = run.box(u0, u1, v0, v1, z0, z1)
        p = Panel(id=pid, name=name, role=role, material=self.mat[mkey], thickness=float(mat["thickness"]), box=box,
                  thin=run.axis(thin), face=+1, grain=None, edges={run.face(k): v for k, v in edges.items()},
                  group=group)
        p.meta["module"] = module
        cut = [run.box(*c) for c in cut_local]
        if cut:
            p.meta["cuts"] = cut
        s = self.add(pid, name, kind or ("back" if mkey == "back" else "carcass"), mkey, box, module, cut)
        s.panel = p
        if lshape is not None:
            self.k.lpanels.append((p, lshape))
        self.k.panels.append(p)
        return s

    def facade(self, run: Run, m: Module, name, kind, u0, u1, z0, z1, v0, hinge=None, mkey="facade") -> Facade:
        box = run.box(u0, u1, v0, v0 + self.tf, z0, z1)
        sid = f"{m.id}_f{len(m.facades) + 1}"
        s = self.add(sid, f"{m.id} {name}", "facade" if kind not in ("filler", "end", "corner", "side", "strip")
                     else "filler", mkey, box, m.id, run=run.name, hinge=hinge, plane_v=v0 + self.tf)
        n = hinge_count(z1 - z0, self.hinge_table) if hinge else 0
        f = Facade(m.id, name, kind, round(u1 - u0, 1), round(z1 - z0, 1), s, hinge, n)
        m.facades.append(f)
        if n:
            m.hw["hinge"] += n
            if self.opening == "push":
                m.hw["tipon_door"] += next(int(q) for hmax, q in self.push["tipon_per_door"] if z1 - z0 <= hmax)
        return f

    # ---------- корпуса ----------
    def lower_carcass(self, run: Run, m: Module, u0, w, back=True, front_rail=True, back_rail=None,
                      shelves=0, shelf_fixed=False, c_notches=(), low_rail_h=100, rails_edge=False, back_cut=(),
                      front_from=None):
        """Корпус нижнего: дно, боковины, царги (без крыши), задняя ХДФ или планка жёсткости, полки.
        gola: в боковинах выборка под профиль L, передняя царга на ребро за профилем.
        push: выборки нет, царги плашмя; rails_edge — обе царги на ребро (под мойкой: чаша проходит между ними)."""
        t, D, tb, kc = self.t, self.D, self.tb, self.kc
        zb, zt = self.zp, self.zc
        gl = kc["gola_L"]
        gola = self.opening == "gola"
        v0 = tb
        notch = ([(D - gl["depth"], D, zt - gl["height"], zt)] if gola else []) + list(c_notches)
        back_role = "joint" if back else "hidden"
        mid = m.id
        self.panel(run, f"{mid}_bottom", "Дно нижнего", "bottom", "carcass", u0, u0 + w, v0, D, zb, zb + t, "z",
                   {"+v": "visible", "-v": back_role, "-u": "hidden", "+u": "hidden"}, mid)
        for sd, a in (("L", u0), ("R", u0 + w - t)):
            self.panel(run, f"{mid}_side_{sd}", "Боковина нижнего", "side", "carcass", a, a + t, v0, D, zb + t, zt,
                       "u", {"+v": "visible", "-v": back_role, "-z": "joint", "+z": "hidden"}, mid,
                       cut_local=[(a, a + t, n[0], n[1], n[2], n[3]) for n in notch])
        m.hw["confirmat"] += 2 * 3
        brw = back_rail if back_rail is not None else kc["rail_width"]
        reh = float(self.push.get("rail_edge_h", kc["rail_width"]))
        if rails_edge and not gola:
            self.panel(run, f"{mid}_rail_back", "Царга (на ребро)", "rail", "carcass", u0 + t, u0 + w - t, v0, v0 + t,
                       zt - reh, zt, "v", {"-z": "hidden"}, mid)
        else:
            self.panel(run, f"{mid}_rail_back", "Царга", "rail", "carcass", u0 + t, u0 + w - t, v0, v0 + brw,
                       zt - t, zt, "z", {"+v": "hidden"}, mid)
        m.hw["confirmat"] += 4
        if front_rail:
            if gola:
                vr = D - gl["depth"]
                self.panel(run, f"{mid}_rail_front", "Царга", "rail", "carcass", u0 + t, u0 + w - t,
                           vr - t, vr, zt - kc["rail_width"], zt, "v", {"-z": "hidden"}, mid)
            elif rails_edge:
                fa = front_from if front_from is not None else u0 + t      # от стойки (угловой под мойку)
                self.panel(run, f"{mid}_rail_front", "Царга (на ребро)", "rail", "carcass", fa, u0 + w - t,
                           D - t, D, zt - reh, zt, "v", {"-z": "hidden", "+v": "visible"}, mid)
            else:
                self.panel(run, f"{mid}_rail_front", "Царга", "rail", "carcass", u0 + t, u0 + w - t,
                           D - kc["rail_width"], D, zt - t, zt, "z", {"+v": "visible", "-v": "hidden"}, mid)
            m.hw["confirmat"] += 4
        if back:
            bi = kc["back_inset"]
            self.panel(run, f"{mid}_back", "Задняя стенка нижнего", "back", "back", u0 + bi, u0 + w - bi, 0, tb,
                       zb + bi, zt - bi, "v", {}, mid, group="back", cut_local=back_cut)
            m.hw["hdf_screw"] += int(round(2 * (w + zt - zb) / self.shop["back"]["fastener_pitch"]))
        else:
            self.panel(run, f"{mid}_rail_low", "Планка задняя нижняя (жёсткость)", "rail", "carcass", u0 + t,
                       u0 + w - t, v0, v0 + t, zb + t, zb + t + low_rail_h, "v", {"+z": "hidden"}, mid)
            m.hw["confirmat"] += 4
        top_free = zt - (gl["height"] if gola else (reh if rails_edge else t))
        if shelves:
            iz0, iz1 = zb + t, top_free
            gap = (iz1 - iz0 - shelves * t) / (shelves + 1)
            for i in range(1, shelves + 1):
                z = round(iz0 + i * gap + (i - 1) * t)
                if shelf_fixed:
                    a, b, role, nm = u0 + t, u0 + w - t, "joint", "Полка неподвижная"
                    m.hw["confirmat"] += 4
                else:
                    g = kc["shelf_side_gap"]
                    a, b, role, nm = u0 + t + g, u0 + w - t - g, "hidden", "Полка"
                    m.hw["shelf_pin"] += 4
                self.panel(run, f"{mid}_shelf{i}", nm, "shelf", "carcass", a, b, v0 + kc["shelf_back_gap"],
                           D - kc["shelf_front_setback"], z, z + t, "z",
                           {"+v": "visible", "-v": "hidden", "-u": role, "+u": role}, mid)
        legs = self.kc["legs"]
        nl = legs["per_wide"] if w >= legs["wide_from"] else legs["per_module"]
        m.hw["leg"] += nl
        m.hw["plinth_clip"] += nl // 2
        m.hw["worktop_fix"] += self.kc["worktop_fix_per_module"]
        m.carcass = (w, zt - zb, D)

    def upper_carcass(self, run: Run, m: Module, u0, w, z0, z1, bottom=True, shelves=(), back_cut=(), fixed=(),
                      mdf_side=None):
        """Корпус верхнего. mdf_side L/R — видимая боковина из фасадного МДФ (заказывается с фасадами, в раскрой ЛДСП
        не идёт): ширина модуля та же, внутри на 2 мм уже."""
        t, Du, tb, kc = self.t, self.Du, self.tb, self.kc
        v0 = tb
        mid = m.id
        tl = self.tf if mdf_side == "L" else t
        tr = self.tf if mdf_side == "R" else t
        for sd, a, th in (("L", u0, tl), ("R", u0 + w - tr, tr)):
            if mdf_side == sd:
                s = self.add(f"{mid}_side_{sd}", f"{mid} Боковина видимая (МДФ в цвет фасадов)", "filler", "facade",
                             run.box(a, a + th, v0, Du, z0, z1), mid)
                m.facades.append(Facade(mid, "Боковина видимая (МДФ, крашеная с двух сторон)", "side", Du - v0, z1 - z0,
                                        s))
                continue
            self.panel(run, f"{mid}_side_{sd}", "Боковина верхнего", "side", "carcass", a, a + t, v0, Du, z0, z1, "u",
                       {"+v": "visible", "-v": "joint", "-z": "visible", "+z": "hidden"}, mid)
        self.panel(run, f"{mid}_top", "Крыша верхнего", "top", "carcass", u0 + tl, u0 + w - tr, v0, Du, z1 - t, z1, "z",
                   {"+v": "visible", "-v": "joint", "-u": "joint", "+u": "joint"}, mid)
        m.hw["confirmat"] += 4
        if bottom:
            self.panel(run, f"{mid}_bottom", "Дно верхнего", "bottom", "carcass", u0 + tl, u0 + w - tr, v0, Du, z0,
                       z0 + t, "z", {"+v": "visible", "-v": "joint", "-u": "joint", "+u": "joint"}, mid)
            m.hw["confirmat"] += 4
        bi = kc["back_inset"]
        self.panel(run, f"{mid}_back", "Задняя стенка верхнего", "back", "back", u0 + bi, u0 + w - bi, 0, tb,
                   z0 + bi, z1 - bi, "v", {}, mid, group="back", cut_local=back_cut)
        m.hw["hdf_screw"] += int(round(2 * (w + z1 - z0) / self.shop["back"]["fastener_pitch"]))
        g = kc["shelf_side_gap"]
        for i, z in enumerate(shelves, 1):
            self.panel(run, f"{mid}_shelf{i}", "Полка верхнего", "shelf", "carcass", u0 + tl + g, u0 + w - tr - g,
                       v0 + kc["shelf_back_gap"], Du - kc["shelf_front_setback"], z, z + t, "z",
                       {"+v": "visible", "-v": "hidden", "-u": "hidden", "+u": "hidden"}, mid)
            m.hw["shelf_pin"] += 4
        for i, (z, cut) in enumerate(fixed, 1):
            self.panel(run, f"{mid}_fshelf{i}", "Полка неподвижная верхнего", "shelf", "carcass", u0 + tl, u0 + w - tr,
                       v0, Du, z, z + t, "z", {"+v": "visible", "-v": "joint", "-u": "joint", "+u": "joint"}, mid,
                       cut_local=cut)
            m.hw["confirmat"] += 4
        m.hw["hanger"] += self.kc["hangers"]["per_cabinet"]
        m.carcass = (w, z1 - z0, Du)

    @staticmethod
    def even_shelves(z0, z1, n, t):
        gap = (z1 - z0 - n * t) / (n + 1)
        return [round(z0 + i * gap + (i - 1) * t) for i in range(1, n + 1)]

    # ---------- нижние модули ----------
    def lower(self, run: Run, spec: dict, u0: float) -> Module:
        typ, w, mid = spec["type"], float(spec["width"]), spec["id"]
        m = Module(mid, typ, run.name, u0, u0 + w, self.zp, self.zc, None)
        self.k.modules.append(m)
        g2, D, fz0, fz1 = self.g2, self.D, self.fz0, self.fz1
        ap = self.cfg["appliances"]
        if typ == "corner_blind":
            blind = float(spec["blind"])
            self.lower_carcass(run, m, u0, w, back=True, shelves=spec.get("shelves", 1), shelf_fixed=True)
            self.facade(run, m, "Дверь", "door", u0 + blind + g2, u0 + w - g2, fz0, fz1, D, hinge=spec.get("hinge", "far"))
            m.inside = (f"глухая часть {blind:.0f} мм у угла (за ней ряд A), полка неподвижная "
                        f"{w - 2 * self.t:.0f} мм; дверь открывается от угла")
            m.notes.append("полка длинная — неподвижная, на конфирматах (съёмная прогнётся)")
        elif typ == "sink":
            self.lower_carcass(run, m, u0, w, back=False)
            self.facade(run, m, "Дверь", "door", u0 + g2, u0 + w - g2, fz0, fz1, D, hinge=spec.get("hinge", "corner"))
            m.inside = "без задней стенки (трубы), мойка сверху, сифон; вывод воды внутри"
            self.sink(run, m, ap["sink"])
            m.hw["sink_tray"] += 1
        elif typ == "cargo":
            self.lower_carcass(run, m, u0, w, back=True)
            self.facade(run, m, "Фасад карго", "cargo", u0 + g2, u0 + w - g2, fz0, fz1, D)
            m.inside = "карго-бутылочница выдвижная с доводчиком, 2 корзины"
            m.hw["cargo"] += 1
        elif typ == "corner_sink":
            self.corner_sink(run, m, spec, u0, w, ap)
        elif typ == "doors":
            n = int(spec.get("doors", 2 if w >= 600 else 1))
            self.lower_carcass(run, m, u0, w, back=True, shelves=int(spec.get("shelves", 1)))
            if n == 1:
                self.facade(run, m, "Дверь", "door", u0 + g2, u0 + w - g2, fz0, fz1, D, hinge=spec.get("hinge", "far"))
            elif n == 2:
                um = u0 + w / 2
                self.facade(run, m, "Дверь левая" if run.name == "A" else "Дверь у угла", "door", u0 + g2, um - g2,
                            fz0, fz1, D, hinge="corner")
                self.facade(run, m, "Дверь правая" if run.name == "A" else "Дверь дальняя", "door", um + g2,
                            u0 + w - g2, fz0, fz1, D, hinge="far")
            else:
                raise KitchenError(f"{mid}: doors 1 или 2")
            ns = int(spec.get("shelves", 1))
            m.inside = (f"{n} двер{'ь' if n == 1 else 'и'}, {ns} полк{'а' if ns == 1 else 'и'} на полкодержателях"
                        + (f"; {spec['note']}" if spec.get("note") else ""))
        elif typ == "oven":
            gl = self.kc["gola_L"]
            oven = ap["oven"]
            if self.opening == "gola":
                oz1 = self.zc - gl["height"]               # верх ниши духовки — низ профиля L
                oz0 = oz1 - float(oven["h"])
            else:                                          # ниша от полки до низа столешницы (по инструкции духовки)
                oz0 = self.zc - float(oven.get("niche_h", oven["h"]))
                oz1 = oz0 + float(oven["h"])
            sz0 = oz0 - self.t
            self.lower_carcass(run, m, u0, w, back=False, front_rail=False, back_rail=self.kc["rail_width_hob"],
                               low_rail_h=min(100, sz0 - self.zp - self.t))
            self.panel(run, f"{mid}_oven_shelf", "Полка под духовку", "shelf", "carcass", u0 + self.t,
                       u0 + w - self.t, self.tb, D, sz0, oz0, "z",
                       {"+v": "visible", "-v": "hidden", "-u": "joint", "+u": "joint"}, mid)
            m.hw["confirmat"] += 6
            space = sz0 - (self.zp + self.t)
            dr = self.kc["drawer"]
            if space >= dr["min_space"]:
                self.facade(run, m, "Фасад ящика под духовкой", "drawer", u0 + g2, u0 + w - g2, fz0, oz0 - 2, D)
                m.hw["drawer"] += 1
                if self.opening == "push":
                    m.hw["tipon_drawer"] += 1
                    self.drawer_boxes(run, m, u0, w, [(fz0, oz0 - 2)], [], zmax=sz0)
                m.inside = f"духовка в нише {oven['h']} мм под варкой, под ней низкий ящик"
                if self.opening == "push":
                    m.inside += f" (внутри по высоте {space:.0f} мм — только низкий ящик)"
            else:
                self.facade(run, m, "Фальш-панель под духовкой (на клипсах)", "panel", u0 + g2, u0 + w - g2, fz0,
                            oz0 - 2, D)
                m.hw["panel_clip"] += 2
                m.inside = (f"духовка в нише {oven['h']} мм (Z {oz0:.0f}..{oz1:.0f}) под варкой; под полкой духовки "
                            f"{space:.0f} мм — ящик не встаёт, там съёмная фальш-панель и место под розетку")
                self.k.notes.append(
                    f"{mid}: низкий ящик под духовкой не помещается — под полкой духовки {space:.0f} мм, а ящику на "
                    f"металлических боковинах нужно ≥ {dr['min_space']} мм. Поставлена съёмная фальш-панель "
                    f"{w - 2 * g2:.0f}×{oz0 - 2 - fz0:.0f}.")
            self.oven(run, m, oven, oz0, oz1)
            self.hob(run, m, ap["hob"])
        elif typ == "dishwasher":
            self.facade(run, m, "Фасад посудомойки", "dw", u0 + g2, u0 + w - g2, fz0, fz1, D)
            m.inside = f"встраиваемая ПММ {w / 10:.0f}, ниша по высоте {self.zc:.0f} мм (от пола до столешницы)"
            m.carcass = None
            self.dishwasher(run, m, ap["dishwasher"])
            m.hw["dw_kit"] += 1
        elif typ == "drawers" and self.opening == "push":
            gap = float(self.push.get("drawer_gap", self.kc["facade_gap"]))
            field = fz1 - fz0
            n = len(spec.get("fronts_ratio") or spec["drawers"])
            if spec.get("fronts_ratio"):
                r = [float(x) for x in spec["fronts_ratio"]]
                total = field - gap * (n - 1)
                hs = [float(int(total * x / sum(r))) for x in r[:-1]]
                hs.append(total - sum(hs))                     # остаток — нижнему
            else:
                hs = [float(x) for x in spec["drawers"]]
            if abs(sum(hs) + gap * (n - 1) - field) > 0.5:
                raise KitchenError(f"{mid}: фасады ящиков {hs} + зазоры {gap} = {sum(hs) + gap * (n - 1):.0f}, а поле "
                                   f"фасадов {field:.0f}")
            z, fronts = fz1, []
            for h in hs:
                fronts.append((z - h, z))
                z -= h + gap
            self.lower_carcass(run, m, u0, w, back=True)
            for i, (a, b2) in enumerate(fronts, 1):
                self.facade(run, m, f"Фасад ящика {i} (сверху)", "drawer", u0 + g2, u0 + w - g2, a, b2, D)
            self.drawer_boxes(run, m, u0, w, fronts, [])
            m.hw["drawer"] += n
            m.hw["tipon_drawer"] += n
            m.inside = (f"{n} ящика с плавным закрыванием, открывание нажатием; фасады "
                        + " / ".join(f"{h:.0f}" for h in hs) + f" (зазор {gap:.0f})")
        elif typ == "drawers":
            gc = self.kc["gola_C"]
            hs = [float(x) for x in spec["drawers"]]
            total = sum(hs) + gc["gap"] * (len(hs) - 1)
            if abs(total - (fz1 - fz0)) > 0.5:
                raise KitchenError(f"{mid}: фасады ящиков {hs} + профили C = {total:.0f}, а поле фасадов "
                                   f"{fz1 - fz0:.0f}")
            z = fz1
            fronts, cz = [], []
            for i, h in enumerate(hs):
                fronts.append((z - h, z))
                z = z - h
                if i < len(hs) - 1:
                    cz.append((z - gc["gap"], z))
                    z -= gc["gap"]
            notches = []
            for a, b in cz:
                mid_z = (a + b) / 2
                notches.append((D - gc["depth"], D, mid_z - gc["height"] / 2, mid_z + gc["height"] / 2))
            self.lower_carcass(run, m, u0, w, back=True, c_notches=notches)
            for i, (a, b) in enumerate(fronts, 1):
                self.facade(run, m, f"Фасад ящика {i} (сверху)", "drawer", u0 + g2, u0 + w - g2, a, b, D)
            for i, (n, (a, b)) in enumerate(zip(notches, cz), 1):
                self.add(f"{mid}_golaC{i}", f"{mid} профиль Gola C", "gola", "gola",
                         run.box(u0, u0 + w, n[0], n[1], n[2], n[3]), mid, run=run.name, profile="C")
            self.drawer_boxes(run, m, u0, w, fronts, notches)
            m.hw["drawer"] += len(hs)
            m.inside = f"{len(hs)} ящика с доводчиком, между фасадами профиль Gola C"
        elif typ == "filler":
            self.facade(run, m, "Планка доборная", "filler", u0 + g2 - self.g2, u0 + w, self.fz0, self.fz1, D)
            m.inside = "планка МДФ на уголках к соседнему корпусу: дверь соседа не цепляет холодильник"
            m.z0, m.z1 = self.fz0, self.fz1
            m.hw["filler_bracket"] += 2
        elif typ == "fridge":
            self.fridge(run, m, ap["fridge"])
            m.carcass = None
            m.inside = "отдельностоящий, на своих ножках"
            m.z0, m.z1 = 0.0, float(ap["fridge"]["h"])
        else:
            raise KitchenError(f"{mid}: неизвестный тип нижнего модуля {typ!r}")
        return m

    def drawer_boxes(self, run, m, u0, w, fronts, notches, zmax=None):
        t, D, dr = self.t, self.D, self.kc["drawer"]
        iw = w - 2 * t
        bw, bl = iw - dr["bottom_w_minus"], dr["runner"] - dr["bottom_l_minus"]
        backw = iw - dr["back_w_minus"]
        ua = u0 + t + (iw - bw) / 2
        v1 = D - self.tb
        for i, (fa, fb) in enumerate(fronts, 1):
            below = [n[3] for n in notches if n[3] <= fb]
            zmin = max([self.zp + t + dr["bottom_clear"], fa + dr["bottom_clear"]] +
                       [z + dr["above_profile"] for z in below if z > fa - 40])
            bh = next(h for fh, h in dr["back_h_by_facade"] if fb - fa <= fh)
            if zmax is not None:                       # над ящиком полка (духовка): задняя стенка ниже
                bh = min(bh, zmax - 6 - zmin - t)
            self.panel(run, f"{m.id}_dr{i}_bottom", "Дно ящика", "drawer_bottom", "carcass", ua, ua + bw, v1 - bl, v1,
                       zmin, zmin + t, "z", {}, m.id)
            ub = u0 + t + (iw - backw) / 2
            self.panel(run, f"{m.id}_dr{i}_back", "Задняя стенка ящика", "drawer_back", "carcass", ub, ub + backw,
                       v1 - bl, v1 - bl + t, zmin + t, zmin + t + bh, "v", {"+z": "hidden"}, m.id)

    # ---------- техника ----------
    def corner_sink(self, run: Run, m: Module, spec: dict, u0: float, w: float, ap: dict):
        """Угловой нижний под мойку в ряду A (ряд B пристыкован к его глухой части).
        Видимая часть начинается от плоскости фасадов ряда B; у угла — доборная планка (дверь не цепляет фасад
        соседнего ряда), за ней стойка под петли левой двери; две двери; мойка по центру дверей."""
        t, D, g2, tf = self.t, self.D, self.g2, self.tf
        other = D + tf                                      # плоскость фасадов перпендикулярного ряда
        filler = float(spec.get("filler", 50))
        fu = u0 + other + filler                            # начало поля дверей
        if fu + 2 * 200 > u0 + w:
            raise KitchenError(f"{m.id}: на двери остаётся {u0 + w - fu:.0f} мм")
        pd = float(spec.get("post_depth", 100))
        pipe = spec.get("pipe_cut")                          # вырез в ХДФ под трубы: [u0, u1, z0, z1] от угла
        back_cut = [(pipe[0], pipe[1], -1, self.tb + 1, pipe[2], pipe[3])] if pipe else []
        # стойка на всю высоту (до столешницы), передняя царга — от стойки вправо: над глухой частью столешница
        # лежит на боковине у стены и на стойке
        self.lower_carcass(run, m, u0, w, back=True, rails_edge=True, back_cut=back_cut, front_from=fu + t)
        self.panel(run, f"{m.id}_post", "Стойка под петли", "post", "carcass", fu, fu + t, D - pd, D, self.zp + t,
                   self.zc, "u", {"+v": "visible", "-v": "hidden", "-z": "joint", "+z": "hidden"}, m.id)
        m.hw["confirmat"] += 4
        n = int(spec.get("doors", 2))
        um = (fu + u0 + w) / 2
        if n == 2:
            self.facade(run, m, "Дверь у угла (петли на стойке)", "door", fu + g2, um - g2, self.fz0, self.fz1, D,
                        hinge="corner")
            self.facade(run, m, "Дверь правая", "door", um + g2, u0 + w - g2, self.fz0, self.fz1, D, hinge="far")
        else:
            self.facade(run, m, "Дверь", "door", fu + g2, u0 + w - g2, self.fz0, self.fz1, D, hinge="far")
        self.k.geo["corner_sink"] = {"module": m.id, "fu": fu, "filler": filler, "zone": (fu + t, u0 + w - t)}
        sp = dict(ap["sink"])
        if sp.get("center", "auto") == "auto":
            sp["center"] = um
        self.sink(run, m, sp)
        m.hw["sink_tray"] += 1
        m.inside = (f"одна коробка {w:.0f}: глухая часть {other:.0f} у угла (перед ней ряд B), доборная планка "
                    f"{filler:.0f}, стойка под петли, {n} двери по {(u0 + w - fu) / n - 2 * g2:.0f}; царги на ребро — "
                    f"чаша мойки между ними; в ХДФ вырез под трубы; мойка по центру дверей (X {um:.0f})")

    def sink(self, run, m, sp):
        zw, zc = self.zw, self.zc
        uc = float(sp["center"])
        v1 = self.Dw - float(sp.get("from_front", self.kc["worktop"]["sink_from_front"]))
        v0 = v1 - float(sp["d"])
        u0, u1 = uc - sp["w"] / 2, uc + sp["w"] / 2
        r = sp["rim"]
        mr, mb, mf = sp.get("mat", "steel"), sp.get("mat_bowl", "steel_dark"), sp.get("faucet_mat", "chrome")
        rim = run.box(u0, u1, v0, v1, zw, zw + 2)
        hole = run.box(u0 + r, u1 - r, v0 + r, v1 - r, zc - 1, zw + 3)
        bz = zw - float(sp["bowl"])
        self.add("sink_rim", "Мойка (борт)", "appliance", mr, rim, m.id, cut=[hole])
        self.add("sink_bowl", "Мойка (чаша)", "appliance", mb,
                 run.box(u0 + r, u1 - r, v0 + r, v1 - r, bz, bz + 1), m.id)
        walls = [(u0 + r, u0 + r + 1, v0 + r, v1 - r), (u1 - r - 1, u1 - r, v0 + r, v1 - r),
                 (u0 + r + 1, u1 - r - 1, v0 + r, v0 + r + 1), (u0 + r + 1, u1 - r - 1, v1 - r - 1, v1 - r)]
        for i, (a, b, c, d) in enumerate(walls):
            self.add(f"sink_wall{i}", "Мойка (стенка)", "appliance", mr, run.box(a, b, c, d, bz + 1, zc), m.id)
        self.k.appl["sink"] = self.solid_by("sink_rim")
        self.k.geo["sink_hole"] = run.box(u0 + r, u1 - r, v0 + r, v1 - r, zc, zw)
        self.k.geo["sink_bowl_z"] = bz
        self.k.geo["sink_box"] = run.box(u0, u1, v0, v1, bz, zw)
        fv = v0 - float(sp.get("faucet_back", 45))
        fh = float(sp.get("faucet_h", 300))
        self.add("faucet", "Смеситель", "appliance", mf, run.box(uc - 22, uc + 22, fv - 22, fv + 22, zw, zw + fh),
                 m.id, shape="cyl_z")
        self.add("faucet_spout", "Излив смесителя", "appliance", mf,
                 run.box(uc - 12, uc + 12, fv - 10, fv + 190, zw + fh, zw + fh + 24), m.id)
        if sp.get("spout_down"):                        # излив «гусак»: опускается к мойке
            self.add("faucet_tip", "Излив смесителя (конец)", "appliance", mf,
                     run.box(uc - 12, uc + 12, fv + 166, fv + 190, zw + fh - 70, zw + fh), m.id)

    def hob(self, run, m, hp):
        uc = (m.u0 + m.u1) / 2
        v1 = self.Dw - self.kc["worktop"]["hob_from_front"]
        v0 = v1 - float(hp["d"])
        cw, cd = hp["cutout"]
        vc = (v0 + v1) / 2
        self.add("hob", "Варочная панель", "appliance", "black_glass",
                 run.box(uc - hp["w"] / 2, uc + hp["w"] / 2, v0, v1, self.zw, self.zw + 6), m.id)
        body = run.box(uc - cw / 2 + 10, uc + cw / 2 - 10, vc - cd / 2 + 10, vc + cd / 2 - 10, self.zc - hp["body_h"],
                       self.zc)
        self.add("hob_body", "Варочная панель (корпус под столешницей)", "appliance", "dark", body, m.id)
        self.k.appl["hob"] = self.solid_by("hob")
        self.k.geo["hob_hole"] = run.box(uc - cw / 2, uc + cw / 2, vc - cd / 2, vc + cd / 2, self.zc, self.zw)
        self.k.geo["hob_top"] = self.zw + 6
        if hp.get("type") == "gas":
            # газовая: 4 горелки и две чугунные решётки; верх решёток — опорная поверхность посуды
            gh = float(hp.get("grate_h", 30))
            zg = self.zw + 6
            hw2 = hp["w"] / 2
            for i, (du, dv, rr) in enumerate(((-140, -110, 50), (140, -110, 38), (-140, 120, 38), (140, 120, 50))):
                self.add(f"hob_burner{i}", "Горелка", "appliance", "dark",
                         run.box(uc + du - rr, uc + du + rr, vc + dv - rr, vc + dv + rr, zg, zg + 14), m.id,
                         shape="cyl_z")
            for j, (a, b2) in enumerate(((uc - hw2 + 15, uc - 4), (uc + 4, uc + hw2 - 15))):
                for nm, bx in (("l", (a, a + 10, v0 + 15, v1 - 15)), ("r", (b2 - 10, b2, v0 + 15, v1 - 15)),
                               ("f", (a, b2, v1 - 25, v1 - 15)), ("b", (a, b2, v0 + 15, v0 + 25)),
                               ("m", (a, b2, vc - 5, vc + 5)), ("x", ((a + b2) / 2 - 5, (a + b2) / 2 + 5, v0 + 15,
                                                                    v1 - 15))):
                    self.add(f"hob_grate{j}{nm}", "Решётка варочной панели", "appliance", "cast_iron",
                             run.box(bx[0], bx[1], bx[2], bx[3], zg + gh - 10, zg + gh), m.id, part_of=f"grate{j}")
                self.add(f"hob_grate{j}_feet", "Решётка (опоры)", "appliance", "cast_iron",
                         run.box(a, a + 10, v0 + 15, v0 + 25, zg, zg + gh - 10), m.id, part_of=f"grate{j}")
            self.k.geo["hob_top"] = zg + gh

    def oven(self, run, m, op, z0, z1):
        g2, D = self.g2, self.D
        self.add("oven_front", "Духовой шкаф (лицевая панель)", "appliance", "black_glass",
                 run.box(m.u0 + g2, m.u1 - g2, D, D + self.tf, z0, z1), m.id)
        body_v0 = D + self.tf - float(op["d"])
        self.add("oven_body", "Духовой шкаф (корпус)", "appliance", "dark",
                 run.box(m.u0 + 21, m.u1 - 21, body_v0, D, z0 + 6, z1 - float(op.get("body_top_drop", 4))), m.id)
        if op.get("handle"):
            hz = z1 - 70
            self.add("oven_handle", "Духовой шкаф (ручка)", "appliance", "chrome",
                     run.box(m.u0 + 60, m.u1 - 60, D + self.tf, D + self.tf + 30, hz - 12, hz + 12), m.id)
        self.k.appl["oven"] = self.solid_by("oven_body")
        self.k.geo["oven_back_v"] = body_v0
        self.k.geo["oven_z"] = (z0, z1)

    def dishwasher(self, run, m, dp):
        self.add("dw_base", "Посудомойка (цоколь)", "appliance", "dark",
                 run.box(m.u0 + 2, m.u1 - 2, 10, self.D - 60, 0, self.zp), m.id)
        gl = self.kc["gola_L"]
        if self.opening == "gola":
            vb = self.D - gl["depth"]                  # бак ПММ уходит за профиль, дверь — ниже профиля
            dz = self.zc - gl["height"] - 2
        else:
            vb = self.D - float(dp.get("door_t", 22))  # внутренняя дверь ПММ, на неё вешается фасад
            dz = self.zc - 5
        self.add("dw_body", "Посудомойка (корпус)", "appliance", "steel",
                 run.box(m.u0 + 2, m.u1 - 2, 10, vb - 2, self.zp, self.zc - 5), m.id)
        self.add("dw_door", "Посудомойка (дверь)", "appliance", "steel",
                 run.box(m.u0 + 2, m.u1 - 2, vb - 2, self.D - 2, self.zp, dz), m.id)
        self.k.appl["dw"] = self.solid_by("dw_body")
        self.k.geo["dw_niche_h"] = self.zc
        self.k.geo["dw_door_top"] = dz

    def fridge(self, run, m, fp):
        v0 = float(fp["wall_gap"])
        v1 = v0 + float(fp["d"])
        u0, u1 = m.u0, m.u0 + float(fp["w"])
        H = float(fp["h"])
        dv = 25
        mat = fp.get("mat", "white_steel")
        sp = float(fp.get("split", 707))               # шов между дверью холодильной и морозильной камер
        self.add("fridge", "Холодильник", "appliance", mat, run.box(u0, u1, v0, v1 - dv, 0, H), m.id)
        self.add("fridge_door_top", "Холодильник (дверь)", "appliance", mat,
                 run.box(u0 + 2, u1 - 2, v1 - dv, v1, sp + 5, H - 5), m.id)
        self.add("fridge_door_bot", "Холодильник (дверь морозилки)", "appliance", mat,
                 run.box(u0 + 2, u1 - 2, v1 - dv, v1, 15, sp), m.id)
        if fp.get("handles", True):
            hu = u0 + 30 if fp.get("hinge", "far") == "far" else u1 - 50
            for nm, a, b in (("top", 1050, 1450), ("bot", 420, 640)):
                self.add(f"fridge_handle_{nm}", "Холодильник (ручка)", "appliance", "chrome",
                         run.box(hu, hu + 20, v1, v1 + 30, a, b), m.id)
        if fp.get("dispenser"):
            dz0, dz1 = fp["dispenser"]
            uc = (u0 + u1) / 2
            self.add("fridge_dispenser", "Холодильник (диспенсер)", "appliance", "black_glass",
                     run.box(uc - 60, uc + 60, v1, v1 + 4, dz0, dz1), m.id)
        self.k.appl["fridge"] = self.solid_by("fridge")
        self.k.geo["fridge"] = {"u0": u0, "u1": u1, "v1": v1, "hinge": fp.get("hinge", "far"), "run": run.name}

    def solid_by(self, sid):
        return self.k.solid(sid)

    # ---------- верхние ----------
    def upper(self, run: Run, spec: dict, u0: float) -> Module:
        typ, w, mid = spec["type"], float(spec["width"]), spec["id"]
        hp = self.cfg["appliances"].get("hood", {})
        tele = typ == "hood" and hp.get("type") == "telescopic"
        z0 = self.hz0 if typ == "hood" else self.uz0
        m = Module(mid, typ, run.name, u0, u0 + w, z0, self.uz1, None, level="верхний")
        self.k.modules.append(m)
        g2, Du = self.g2, self.Du
        fz0 = z0 - self.udrop
        t = self.t
        if typ in ("shelves", "dryer"):
            if typ == "dryer":
                shelves = [round(self.uz1 - t - 280)]
                m.hw["dryer"] += 1
                m.inside = "сушилка для посуды 2 уровня с поддоном, сверху 1 полка"
            else:
                n = int(spec.get("shelves", 2))
                shelves = self.even_shelves(z0 + t, self.uz1 - t, n, t)
                m.inside = f"{n} полки на полкодержателях"
            self.upper_carcass(run, m, u0, w, z0, self.uz1, shelves=shelves, mdf_side=spec.get("mdf_side"))
            if spec.get("mdf_side"):
                m.inside += f"; боковина {'справа' if spec['mdf_side'] == 'R' else 'слева'} из МДФ в цвет фасадов " \
                            f"(видна{(' — ' + spec['side_note']) if spec.get('side_note') else ''})"
            self.facade(run, m, "Дверь", "door", u0 + g2, u0 + w - g2, fz0, self.ufz1, Du, hinge=spec.get("hinge", "far"))
        elif typ == "corner_blind_u":
            blind = float(spec["blind"])
            n = int(spec.get("shelves", 2))
            shelves = self.even_shelves(z0 + t, self.uz1 - t, n, t)
            self.upper_carcass(run, m, u0, w, z0, self.uz1, shelves=shelves)
            self.facade(run, m, "Дверь", "door", u0 + blind + g2, u0 + w - g2, fz0, self.ufz1, Du,
                        hinge=spec.get("hinge", "far"))
            m.inside = (f"глухая часть {blind:.0f} у угла (перед ней ряд B), {n} полки во всю ширину "
                        f"{w - 2 * t - 2:.0f}; дверь открывается от угла")
        elif typ == "microwave":
            self.microwave(run, m, spec, u0, w, z0, fz0)
        elif typ == "hood":
            zs = z0 + float(hp["h"]) + 20
            duct_r = float(hp["duct"]) / 2
            uc = u0 + w / 2
            dv0 = Du - float(hp["duct_from_front"]) - duct_r if hp.get("duct_from_front") else 100.0
            vent = next((p for p in self.cfg["room"]["points"] if p["id"] == "vent"), None)
            zv = float(vent["z"]) if vent else self.uz1 - 100
            back_cut = [(uc - duct_r - 5, uc + duct_r + 5, -1, self.tb + 1, zv - duct_r - 5, zv + duct_r + 5)]
            shelf_cut = [(uc - duct_r - 10, uc + duct_r + 10, dv0 - 10, dv0 + 2 * duct_r + 10, zs - 1, zs + t + 1)]
            zc0 = z0 + float(hp.get("below", 0)) if tele else z0   # корпус вытяжки выступает под дно шкафа
            self.upper_carcass(run, m, u0, w, zc0, self.uz1, bottom=False, back_cut=back_cut, fixed=[(zs, shelf_cut)])
            if tele:
                # телескопическая: корпус вытяжки в шкафу без дна, низ — по линии фасадов; выдвижной экран под дверью
                vh = float(hp.get("visor_h", 30))
                self.facade(run, m, "Дверь (над экраном вытяжки)", "door", u0 + g2, u0 + w - g2, z0 + vh + 2,
                            self.ufz1, Du, hinge=spec.get("hinge", "far"))
                bw = float(hp.get("body_w", w - 2 * t))
                bd = float(hp.get("body_d", Du - 12))
                self.add("hood", "Вытяжка встраиваемая телескопическая", "appliance", "steel",
                         run.box(uc - bw / 2, uc + bw / 2, Du - 2 - bd, Du - 2, z0, z0 + float(hp["h"])), mid)
                self.k.geo["hood_cabinet_z0"] = zc0
                self.add("hood_visor", "Вытяжка (выдвижной экран)", "appliance", "steel_dark",
                         run.box(u0 + g2, u0 + w - g2, Du, Du + self.tf, z0, z0 + vh), mid)
                m.z0 = z0
            else:
                self.facade(run, m, "Дверь", "door", u0 + g2, u0 + w - g2, fz0, self.ufz1, Du,
                            hinge=spec.get("hinge", "far"))
                self.add("hood", "Вытяжка встраиваемая", "appliance", "steel",
                         run.box(u0 + t, u0 + w - t, 10, Du - 10, z0, z0 + float(hp["h"])), mid)
            self.add("duct_v", "Воздуховод", "appliance", "duct",
                     run.box(uc - duct_r, uc + duct_r, dv0, dv0 + 2 * duct_r, z0 + float(hp["h"]), zv + duct_r), mid)
            self.add("duct_h", "Воздуховод (к выводу)", "appliance", "duct",
                     run.box(uc - duct_r, uc + duct_r, self.tb, dv0, zv - duct_r, zv + duct_r), mid)
            self.k.appl["hood"] = self.solid_by("hood")
            if tele:
                m.inside = (f"встраиваемая телескопическая вытяжка {hp['w']}: шкаф без дна, низ вытяжки Z {z0:.0f} "
                            f"(по линии фасадов, на {hp.get('below', 0)} ниже боковин), выдвижной экран "
                            f"{hp.get('visor_h', 30)} под дверью; над ней полка с вырезом, воздуховод Ø{hp['duct']} к "
                            f"выводу на Z {zv:.0f}")
            else:
                m.inside = (f"встраиваемая вытяжка {hp['w']} внизу шкафа (низ Z {z0:.0f}), над ней полка с вырезом, "
                            f"воздуховод Ø{hp['duct']} к выводу на Z {zv:.0f}; подсветка — своя у вытяжки")
        elif typ == "corner_l":
            self.corner_l(m)
        elif typ == "filler":
            m.z0, m.z1 = fz0, self.ufz1
            self.facade(run, m, "Планка доборная", "filler", u0, u0 + w, fz0, self.ufz1, Du)
            m.inside = "планка МДФ на уголках к соседнему корпусу"
            m.hw["filler_bracket"] += 2
        else:
            raise KitchenError(f"{mid}: неизвестный тип верхнего модуля {typ!r}")
        return m

    def microwave(self, run: Run, m: Module, spec: dict, u0: float, w: float, z0: float, fz0: float):
        """Шкаф с нишей под встраиваемую СВЧ внизу: дно корпуса — пол ниши, над нишей неподвижная полка, выше двери.
        Рамка СВЧ стоит перед корпусом в плоскости фасадов, её низ — по линии фасадов соседей."""
        t, Du, g2, tb = self.t, self.Du, self.g2, self.tb
        mw = self.cfg["appliances"]["microwave"]
        nh = float(mw["niche_h"])                         # высота ниши (от дна до полки)
        zf = z0 + t + nh                                  # низ неподвижной полки
        n_up = int(spec.get("shelves", 1))
        ups = self.even_shelves(zf + t, self.uz1 - t, n_up, t) if n_up else []
        vcut = mw.get("back_cut")                        # вентиляция: вырез в ХДФ в зоне ниши (по инструкции СВЧ)
        back_cut = [(u0 + t, u0 + w - t, -1, tb + 1, z0 + t, zf)] if vcut else []
        self.upper_carcass(run, m, u0, w, z0, self.uz1, shelves=ups, fixed=[(zf, [])], back_cut=back_cut)
        fh, fw_, fd = float(mw["front_h"]), float(mw["front_w"]), float(mw.get("front_t", 20))
        uc = u0 + w / 2
        fb = z0 + t - float(mw.get("front_below", 0))       # рамка ниже пола ниши (по чертежу СВЧ)
        if fb - fz0 > 4:                                     # планка под рамкой: линия низа как у дверей, прячет LED
            self.facade(run, m, "Планка под СВЧ", "strip", u0 + g2, u0 + w - g2, fz0, fb - 2, Du)
        self.add("mw_front", "СВЧ встраиваемая (рамка)", "appliance", "black_glass",
                 run.box(uc - fw_ / 2, uc + fw_ / 2, Du, Du + fd, fb, fb + fh), m.id)
        bw, bh, bd = (float(x) for x in mw["body"])
        self.add("mw_body", "СВЧ встраиваемая (корпус)", "appliance", "dark",
                 run.box(uc - bw / 2, uc + bw / 2, Du - bd, Du, z0 + t, z0 + t + bh), m.id)
        self.k.appl["mw"] = self.solid_by("mw_body")
        self.k.geo["mw"] = {"module": m.id, "niche": (w - 2 * t, nh, Du - (0 if vcut else tb)), "front_top": fb + fh,
                            "zf": zf}
        n = int(spec.get("doors", 2))
        dz0 = fb + fh + 2 * g2
        if n == 2:
            um = u0 + w / 2
            self.facade(run, m, "Дверь над СВЧ (у угла)", "door", u0 + g2, um - g2, dz0, self.ufz1, Du, hinge="corner")
            self.facade(run, m, "Дверь над СВЧ (дальняя)", "door", um + g2, u0 + w - g2, dz0, self.ufz1, Du,
                        hinge="far")
        else:
            self.facade(run, m, "Дверь над СВЧ", "door", u0 + g2, u0 + w - g2, dz0, self.ufz1, Du,
                        hinge=spec.get("hinge", "far"))
        m.inside = (f"ниша под встраиваемую СВЧ {w - 2 * t:.0f}×{nh:.0f} (глубина {Du - (0 if vcut else tb):.0f}) на дне "
                    f"шкафа, над ней неподвижная полка; выше {n} двер{'и' if n > 1 else 'ь'} и {n_up} полка; рамка СВЧ "
                    f"{fw_:.0f}×{fh:.0f} — в плоскости фасадов" + ("; в ХДФ вырез в зоне ниши (вентиляция)" if vcut else ""))

    def corner_l(self, m: Module):
        """Г-образный верхний 600×600 в углу A/B: две плечи глубиной Du, складная дверь «гармошка»."""
        t, Du, tb, kc = self.t, self.Du, self.tb, self.kc
        W = m.u1 - m.u0
        z0, z1 = self.uz0, self.uz1
        A, B = Run("A"), Run("B")
        mid = m.id
        # боковины на концах плеч
        self.panel(A, f"{mid}_side_A", "Боковина верхнего", "side", "carcass", W - t, W, tb, Du, z0, z1, "u",
                   {"+v": "visible", "-v": "joint", "-z": "visible", "+z": "hidden"}, mid)
        self.panel(B, f"{mid}_side_B", "Боковина верхнего", "side", "carcass", W - t, W, tb, Du, z0, z1, "u",
                   {"+v": "visible", "-v": "joint", "-z": "visible", "+z": "hidden"}, mid)
        notch = lambda a, b: (Du, W - t, Du, W - t, a, b)  # noqa: E731 — вырез Г: внутренний угол
        lo_edge = 2 * (W - t - Du)
        for nm, role, a in (("Дно/крыша Г-образная", "bottom", z0), ("Дно/крыша Г-образная", "top", z1 - t)):
            self.panel(A, f"{mid}_{role}", nm, role, "carcass", tb, W - t, tb, W - t, a, a + t, "z", {}, mid,
                       cut_local=[notch(a - 1, a + t + 1)], lshape=lo_edge)
        m.hw["confirmat"] += 8
        sh = self.even_shelves(z0 + t, z1 - t, 2, t)
        sv = kc["shelf_front_setback"]
        for i, z in enumerate(sh, 1):
            self.panel(A, f"{mid}_shelf{i}", "Полка Г-образная", "shelf", "carcass", tb + 1, W - t - 1, tb + 1,
                       W - t - 1, z, z + t, "z", {}, mid,
                       cut_local=[(Du - sv, W, Du - sv, W, z - 1, z + t + 1)], lshape=2 * (W - t - 1 - (Du - sv)))
            m.hw["shelf_pin"] += 5
        bi = kc["back_inset"]
        self.panel(A, f"{mid}_back_A", "Задняя стенка верхнего (плечо A)", "back", "back", tb, W - bi, 0, tb, z0 + bi,
                   z1 - bi, "v", {}, mid, group="back")
        self.panel(B, f"{mid}_back_B", "Задняя стенка верхнего (плечо B)", "back", "back", 0, W - bi, 0, tb, z0 + bi,
                   z1 - bi, "v", {}, mid, group="back")
        m.hw["hdf_screw"] += int(round(4 * (W + z1 - z0) / self.shop["back"]["fastener_pitch"]))
        m.hw["hanger"] += 2
        m.hw["wall_bracket"] += 2
        g2 = self.g2
        fz0 = z0 - kc["upper_facade_drop"]
        # створка B (на боковине плеча B) и створка A (на створке B, петля «гармошка»)
        fb = self.facade(B, m, "Створка «гармошки» (на боковине)", "leaf", Du, W - g2, fz0, self.ufz1, Du, hinge="far")
        fa = self.facade(A, m, "Створка «гармошки» (на створке)", "leaf", Du + self.tf + 2 * g2, W - g2, fz0,
                         self.ufz1, Du)
        fa.hinges = fb.hinges
        m.hw["bifold_hinge"] += fb.hinges
        m.carcass = (W, z1 - z0, Du)
        m.inside = "2 Г-образные полки; створки складываются «гармошкой», открываются целиком от угла"


def _upper_end_panel(b: _B, k: Kitchen, run: Run, last: Module, mid: str):
    """Торцевая панель МДФ на видимый торец верхнего ряда.
    За доборной планкой (последний модуль — filler) — панель-возврат внутри ряда, за планкой: сумма ряда не меняется
    и панель не залезает на холодильник. Иначе — снаружи ряда, как у нижних (ряд длиннее на толщину панели)."""
    tf, Du = b.tf, b.Du
    z0 = min(f.solid.box.lo[2] for f in last.facades) if last.facades else b.uz0 - b.udrop
    z1 = b.uz1
    cs = b.cfg["heights"].get("ceiling_strip")
    if cs:                                   # планка до потолка: торцевая панель тоже до потолка (закрывает торец планки)
        z1 = float(b.cfg["room"]["height"]) - float(cs.get("gap", 2))
    if last.type == "filler":
        u0, u1, v1, where = last.u1 - tf, last.u1, Du, "за доборной планкой (возврат)"
    else:
        u0, u1, v1, where = last.u1, last.u1 + tf, Du + tf, "снаружи ряда"
    # низ панели ниже корпуса (свес фасадов) — там фартук у стены: панель отступает от стены на толщину фартука
    ap_t = float(b.shop["kitchen_materials"][b.mat["apron"]]["thickness"])
    v0 = ap_t if z0 < b.uz0 else 0.0
    m = Module(mid, "end_panel", run.name, u0, u1, z0, z1, None, level="верхний")
    k.modules.append(m)
    s = b.add(f"end_panel_{mid}", "Панель торцевая верхних", "filler", "facade", run.box(u0, u1, v0, v1, z0, z1), mid)
    m.facades.append(Facade(mid, "Панель торцевая верхних", "end", v1 - v0, z1 - z0, s))
    m.inside = f"МДФ 18 в цвет фасадов на видимый торец {last.id}, {where}" + (" (до потолка)" if cs else "")
    m.hw["confirmat"] += 4


def _mirror_box(b: Box, a: float) -> Box:
    return Box.of(a - b.hi[0], a - b.lo[0], b.lo[1], b.hi[1], b.lo[2], b.hi[2])


def build(cfg: dict, shop: dict) -> Kitchen:
    b = _B(cfg, shop)
    k = b.k
    room = cfg["room"]
    A, B = Run("A"), Run("B")
    corner = cfg["kitchen"].get("corner", "AB")
    if corner not in ("AB", "AC"):
        raise KitchenError("kitchen.corner: AB или AC")

    # ---- нижние ряды ----
    def lower_run(run, rc):
        """Модули ряда подряд от start. Холодильник с in_run: false ставится через gap и длину ряда не меняет."""
        u = float(rc.get("start", 0))
        for spec in rc["modules"]:
            if spec["type"] == "fridge" and spec.get("in_run") is False:
                b.lower(run, spec, u + float(spec.get("gap", 0))).in_run = False
                continue
            b.lower(run, spec, u)
            u += float(spec["width"])
        return u

    lbc = cfg.get("lower_b", [])
    lb = lbc if isinstance(lbc, dict) else {"start": 0, "modules": lbc}
    la = cfg["lower_a"]
    k.runs["lower_b"] = lower_run(B, lb)
    b_start = float(lb.get("start", 0))
    a_start = float(la.get("start", 0))
    a_end = k.runs["lower_a"] = lower_run(A, la)
    b_end = k.runs["lower_b"]
    D, tf = b.D, b.tf
    # угловая планка: щель между фасадами ряда, занимающего угол, и началом перпендикулярного ряда
    if b.corner_owner == "B" and a_start > D:
        m = Module("У", "corner_filler", "угол", D, a_start, b.fz0, b.fz1, None)
        k.modules.append(m)
        s1 = b.add("corner_strip_A", "Планка угловая (по ряду A)", "filler", "facade",
                   Box.of(D, a_start, D, D + tf, b.fz0, b.fz1), "У")
        m.facades.append(Facade("У", "Планка угловая (ряд A)", "corner", a_start - D, b.fz1 - b.fz0, s1))
        if a_start > D + tf:
            s2 = b.add("corner_strip_B", "Планка угловая (по ряду B)", "filler", "facade",
                       Box.of(D, D + tf, D + tf, a_start, b.fz0, b.fz1), "У")
            m.facades.append(Facade("У", "Планка угловая (ряд B)", "corner", a_start - D - tf, b.fz1 - b.fz0, s2))
        m.inside = "Г-планка МДФ закрывает щель в углу между рядами (за ней глухая часть Н1)"
        m.hw["filler_bracket"] += 2
    elif b.corner_owner == "A" and "corner_sink" in k.geo:
        cs = k.geo["corner_sink"]
        fu = cs["fu"]
        m = Module("У", "corner_filler", "угол", D, fu, b.fz0, b.fz1, None)
        k.modules.append(m)
        s1 = b.add("corner_strip_A", "Планка угловая (по ряду A)", "filler", "facade",
                   Box.of(D, fu, D, D + tf, b.fz0, b.fz1), "У")
        m.facades.append(Facade("У", "Планка угловая доборная (ряд A)", "corner", fu - D, b.fz1 - b.fz0, s1))
        txt = f"Г-планка МДФ в углу: по ряду A {fu - D:.0f} (видно {fu - D - tf:.0f})"
        if b_start > D + tf + 0.5:
            s2 = b.add("corner_strip_B", "Планка угловая (по ряду B)", "filler", "facade",
                       Box.of(D, D + tf, D + tf, b_start, b.fz0, b.fz1), "У")
            m.facades.append(Facade("У", "Планка угловая (ряд B)", "corner", b_start - D - tf, b.fz1 - b.fz0, s2))
            txt += f", по ряду B {b_start - D - tf:.0f} — до фасада {lb['modules'][0]['id']}"
        m.inside = txt + f"; дверь {cs['module']} у угла не цепляет фасад ряда B"
        m.hw["filler_bracket"] += 2
    # торцевые панели нижних (снаружи ряда, до пола — закрывают цоколь)
    x_top = a_end
    if la.get("end_panel"):
        m = Module("Т", "end_panel", "A", a_end, a_end + tf, 0, b.zc, None)
        k.modules.append(m)
        s = b.add("end_panel", "Панель торцевая", "filler", "facade", Box.of(a_end, a_end + tf, 0, D + tf, 0, b.zc), "Т")
        m.facades.append(Facade("Т", "Панель торцевая", "end", D + tf, b.zc, s))
        m.inside = "МДФ в цвет фасадов на открытый торец, до пола (закрывает цоколь), столешница сверху"
        m.hw["confirmat"] += 4
        x_top = a_end + tf
    y_top_b = b_end
    if lb.get("end_panel"):
        m = Module("Т1", "end_panel", "B", b_end, b_end + tf, 0, b.zc, None)
        k.modules.append(m)
        s = b.add("end_panel_B", "Панель торцевая", "filler", "facade", Box.of(0, D + tf, b_end, b_end + tf, 0, b.zc),
                  "Т1")
        m.facades.append(Facade("Т1", "Панель торцевая", "end", D + tf, b.zc, s))
        m.inside = "МДФ в цвет фасадов на открытый торец ряда B, до пола (закрывает цоколь), столешница сверху"
        m.hw["confirmat"] += 4
        y_top_b = b_end + tf
    # ---- верхние ----
    ua = cfg["upper_a"]
    ub = cfg.get("upper_b") or {"start": 0, "modules": []}
    for run, rc, key, mid in ((A, ua, "upper_a", "Т2"), (B, ub, "upper_b", "Т3")):
        u = float(rc.get("start", 0))
        last = None
        for spec in rc["modules"]:
            last = b.upper(run, spec, u)
            u += float(spec["width"])
        k.runs[key] = u
        if rc.get("end_panel") and last is not None:
            _upper_end_panel(b, k, run, last, mid)

    # ---- столешница ----
    zc, zw, Dw = b.zc, b.zw, b.Dw
    cuts = [c for c in (k.geo.get("sink_hole"), k.geo.get("hob_hole")) if c is not None]
    k.geo["worktop_holes"] = cuts
    b.add("worktop_A", "Столешница (кусок A)", "worktop", "worktop", Box.of(0, x_top, 0, Dw, zc, zw), cut=cuts,
          grain="x")
    wb_end = max((m.u1 for m in k.modules if m.run == "B" and m.level == "нижний" and m.type != "fridge"),
                 default=Dw)
    if lb.get("worktop_end"):                      # длина столешницы по B задана в конфиге
        wb_end = float(lb["worktop_end"])
    if wb_end > Dw:
        b.add("worktop_B", "Столешница (кусок B)", "worktop", "worktop", Box.of(0, Dw, Dw, wb_end, zc, zw), grain="y")
    k.geo["worktop_B_end"] = wb_end
    k.geo["x_top"] = x_top
    # ---- фартук ----
    ap_t = float(shop["kitchen_materials"][cfg["materials"]["apron"]]["thickness"])
    win = room["window"]
    if win.get("wall", "A") == "A":
        xa_end = min(float(win["x0"]), x_top) if win["x0"] >= k.runs["upper_a"] else k.runs["upper_a"]
    else:
        xa_end = x_top
    hood = next((m for m in k.modules if m.type == "hood"), None)
    if hood is not None and hood.run == "A" and b.hz0 < b.uz0:
        # шкаф вытяжки ниже соседних (по линии фасадов): фартук под ним кончается на низе вытяжки
        b.add("apron_A", "Фартук (стена A)", "apron", "apron", Box.of(0, hood.u0, 0, ap_t, zw, b.uz0))
        b.add("apron_A_hob", "Фартук (стена A, над варкой)", "apron", "apron", Box.of(hood.u0, hood.u1, 0, ap_t, zw,
                                                                                      b.hz0))
        b.add("apron_A2", "Фартук (стена A)", "apron", "apron", Box.of(hood.u1, xa_end, 0, ap_t, zw, b.uz0))
    else:
        b.add("apron_A", "Фартук (стена A)", "apron", "apron", Box.of(0, xa_end, 0, ap_t, zw, b.uz0))
    if hood is not None and hood.run == "A" and b.hz0 > b.uz0:
        b.add("apron_A_hood", "Фартук над варкой (до вытяжки)", "apron", "apron",
              Box.of(hood.u0, hood.u1, 0, ap_t, b.uz0, b.hz0))
    b.add("apron_B", "Фартук (стена B)", "apron", "apron", Box.of(0, ap_t, ap_t, wb_end, zw, b.uz0))
    k.geo["apron"] = {"A": xa_end, "B": wb_end, "z": (zw, b.uz0)}
    # ---- цоколь ----
    kc = b.kc
    pv1 = D + tf - kc["plinth_setback"]
    pv0 = pv1 - kc["plinth_t"]
    b.add("plinth_A", "Цоколь (ряд A)", "plinth", "plinth", Box.of(pv0, a_end, pv0, pv1, 0, b.zp))
    b_plinth_end = max((m.u1 for m in k.modules if m.run == "B" and m.level == "нижний"
                        and m.type not in ("fridge", "end_panel")), default=pv1)
    b.add("plinth_B", "Цоколь (ряд B)", "plinth", "plinth", Box.of(pv0, pv1, pv1, b_plinth_end, 0, b.zp))
    k.geo["plinth"] = {"A": a_end - pv0, "B": b_plinth_end - pv1}
    # ---- профиль Gola L ----
    if b.opening == "gola":
        gl = kc["gola_L"]
        gv0, gv1, gz0 = D - gl["depth"], D, zc - gl["height"]
        b.add("gola_L_A", "Профиль Gola L (ряд A)", "gola", "gola", Box.of(D, a_end, gv0, gv1, gz0, zc), profile="L")
        b.add("gola_L_B", "Профиль Gola L (ряд B)", "gola", "gola", Box.of(gv0, gv1, D, wb_end, gz0, zc), profile="L")
        k.geo["gola_L"] = {"A": a_end - D, "B": wb_end - D}
    # ---- LED под верхними: участками под шкафами с полками/СВЧ (под вытяжкой — свой свет) ----
    led = kc["led"]
    lv = b.Du - led["y_from_front"]
    led_runs, led_segs = {}, {}
    lit = ("shelves", "dryer", "corner_l", "corner_blind_u", "microwave")
    for run, rname in ((A, "A"), (B, "B")):
        ivs = sorted((max(m.u0, b.Du + tf), m.u1) for m in k.modules if m.level == "верхний" and m.type in lit
                     and (m.run == rname or m.type == "corner_l"))
        segs = []
        for u0_, u1_ in ivs:
            if u1_ <= u0_:
                continue
            if segs and u0_ <= segs[-1][1] + 0.5:
                segs[-1][1] = max(segs[-1][1], u1_)
            else:
                segs.append([u0_, u1_])
        for i, (s0, s1) in enumerate(segs):
            sid = f"led_{rname}" if i == 0 else f"led_{rname}{i + 1}"
            b.add(sid, f"LED-профиль под верхними (ряд {rname})", "led", "led",
                  run.box(s0, s1, lv - 8, lv + 8, b.uz0 - 9, b.uz0))
        if segs:
            led_runs[rname] = sum(s1 - s0 for s0, s1 in segs)
            led_segs[rname] = [(s0, s1) for s0, s1 in segs]
    k.geo["led"] = led_runs
    k.geo["led_segs"] = led_segs
    # ---- планка до потолка (зазор над верхними) ----
    cs = cfg["heights"].get("ceiling_strip")
    if cs:
        H = float(room["height"])
        z1s = H - float(cs.get("gap", 2))
        Du = b.Du
        m = Module("П", "ceiling_strip", "угол", 0, 0, b.uz1, z1s, None, level="верхний")
        k.modules.append(m)
        up_b = [x for x in k.modules if x.level == "верхний" and x.run == "B" and x.type not in ("end_panel",)]
        up_a = [x for x in k.modules if x.level == "верхний" and x.run == "A" and x.type not in ("end_panel",)]
        a0 = Du + tf if up_b else 0.0
        if up_a:
            s1 = b.add("ceiling_strip_A", "Планка до потолка (ряд A)", "filler", "facade",
                       Box.of(a0, k.runs["upper_a"], Du, Du + tf, b.uz1, z1s), "П")
            m.facades.append(Facade("П", "Планка до потолка (ряд A)", "strip", k.runs["upper_a"] - a0, z1s - b.uz1, s1))
        if up_b:
            s2 = b.add("ceiling_strip_B", "Планка до потолка (ряд B)", "filler", "facade",
                       Box.of(Du, Du + tf, Du if up_a else 0.0, k.runs["upper_b"], b.uz1, z1s), "П")
            m.facades.append(Facade("П", "Планка до потолка (ряд B)", "strip", k.runs["upper_b"] - (Du if up_a else 0),
                                    z1s - b.uz1, s2))
        m.inside = (f"МДФ в цвет фасадов, в плоскости дверей, {z1s - b.uz1:.0f} мм (зазор до потолка "
                    f"{H - b.uz1:.0f}, {cs.get('gap', 2)} мм на подгонку по месту); крепление уголками к крышам шкафов")
        m.hw["filler_bracket"] += 2 * len(m.facades) + int((k.runs.get("upper_a", 0) + k.runs.get("upper_b", 0)) // 600)
        k.geo["ceiling_strip"] = z1s - b.uz1

    # ---- помещение ----
    _room(b, k)

    # ---- зеркало для угла A/C ----
    if corner == "AC":
        a = float(room["a"])
        for s in k.solids:
            if s.kind in ("room", "window", "door", "point", "wall"):
                continue
            s.box = _mirror_box(s.box, a)
            s.cut = [_mirror_box(c, a) for c in s.cut]
            if s.panel is not None:
                s.panel.box = s.box
                s.panel.edges = {(("+" if f[0] == "-" else "-") + f[1]) if f[1] == "x" else f: r
                                 for f, r in s.panel.edges.items()}
            s.meta["mirrored"] = True
        for key in ("sink_hole", "hob_hole", "sink_box"):
            if key in k.geo:
                k.geo[key] = _mirror_box(k.geo[key], a)
        k.geo["worktop_holes"] = [_mirror_box(c, a) for c in k.geo["worktop_holes"]]
        for m in k.modules:
            if m.run == "A":
                m.u0, m.u1 = a - m.u1, a - m.u0
        k.geo["mirrored"] = True
        k.notes.append("Угол A/C: мебель отзеркалена по X (x -> a - x), коммуникации и окно остались на месте.")

    mats = shop_mats = b.shop["materials"]
    used = {p.material for p in k.panels}
    k.product = Product(id=cfg["kitchen"]["id"], name=cfg["kitchen"]["name"], prefix=cfg["kitchen"].get("prefix", "K"),
                        qty=1, size=(float(room["a"]), float(room["b"]), float(room["height"])), panels=k.panels,
                        materials={m: shop_mats[m] for m in used}, shop=b.shop, params=cfg)
    del mats
    return k


def _room(b: _B, k: Kitchen):
    room = k.cfg["room"]
    a, bb, H, w = (float(room[x]) for x in ("a", "b", "height", "wall"))
    win = room["window"]
    wall_w = win.get("wall", "A")
    if wall_w == "A":
        wx0, wx1 = float(win["x0"]), float(win["x0"]) + float(win["width"])
    elif wall_w == "C":
        wx0, wx1 = float(win["y0"]), float(win["y0"]) + float(win["width"])   # вдоль стены C — по Y
    else:
        raise KitchenError("room.window.wall: A или C")
    wz0, wz1 = float(win["z0"]), float(win["z0"]) + float(win["height"])
    dr = room["door"]
    if dr["from_corner"] == "AB":
        dy0 = float(dr["offset"])
    elif dr["from_corner"] == "BD":
        dy0 = bb - float(dr["offset"]) - float(dr["width"])
    else:
        raise KitchenError("room.door.from_corner: AB или BD")
    dy1, dz1 = dy0 + float(dr["width"]), float(dr["height"])
    k.geo["window"] = Box.of(wx0, wx1, -w, 0, wz0, wz1) if wall_w == "A" else Box.of(a, a + w, wx0, wx1, wz0, wz1)
    k.geo["window_wall"] = wall_w
    k.geo["door"] = Box.of(-w, 0, dy0, dy1, 0, dz1)
    k.geo["room"] = Box.of(0, a, 0, bb, 0, H)
    add = b.add
    add("floor", "Пол", "room", "floor", Box.of(-w, a + w, -w, bb + w, -40, 0))
    fy0, fy1, fw = -w / 2 - 35, -w / 2 + 35, 60
    if wall_w == "A":
        # стена A с окном
        add("wall_A_l", "Стена A", "wall", "wall", Box.of(-w, wx0, -w, 0, 0, H), wall="A")
        add("wall_A_r", "Стена A", "wall", "wall", Box.of(wx1, a + w, -w, 0, 0, H), wall="A")
        add("wall_A_b", "Стена A (под окном)", "wall", "wall", Box.of(wx0, wx1, -w, 0, 0, wz0 - 20), wall="A")
        add("wall_A_s", "Стена A (под рамой)", "wall", "wall", Box.of(wx0, wx1, -w, -w / 2 + 35, wz0 - 20, wz0),
            wall="A")
        add("wall_A_t", "Стена A (над окном)", "wall", "wall", Box.of(wx0, wx1, -w, 0, wz1, H), wall="A")
    else:
        add("wall_A", "Стена A", "wall", "wall", Box.of(-w, a + w, -w, 0, 0, H), wall="A")
    # стена B с дверью
    add("wall_B_1", "Стена B", "wall", "wall", Box.of(-w, 0, 0, dy0, 0, H), wall="B")
    add("wall_B_2", "Стена B", "wall", "wall", Box.of(-w, 0, dy1, bb + w, 0, H), wall="B")
    add("wall_B_t", "Стена B (над дверью)", "wall", "wall", Box.of(-w, 0, dy0, dy1, dz1, H), wall="B")
    if wall_w == "A":
        add("wall_C", "Стена C", "wall", "wall", Box.of(a, a + w, 0, bb + w, 0, H), wall="C")
    else:
        # стена C с окном: p — вдоль стены (Y), q — вглубь стены от комнаты
        cb = lambda p0, p1, q0, q1, z0, z1: Box.of(a + q0, a + q1, p0, p1, z0, z1)  # noqa: E731
        add("wall_C_l", "Стена C", "wall", "wall", cb(0, wx0, 0, w, 0, H), wall="C")
        add("wall_C_r", "Стена C", "wall", "wall", cb(wx1, bb + w, 0, w, 0, H), wall="C")
        add("wall_C_b", "Стена C (под окном)", "wall", "wall", cb(wx0, wx1, 0, w, 0, wz0 - 20), wall="C")
        add("wall_C_s", "Стена C (под рамой)", "wall", "wall", cb(wx0, wx1, w / 2 - 35, w, wz0 - 20, wz0), wall="C")
        add("wall_C_t", "Стена C (над окном)", "wall", "wall", cb(wx0, wx1, 0, w, wz1, H), wall="C")
    add("wall_D", "Стена D", "wall", "wall", Box.of(0, a, bb, bb + w, 0, H), wall="D")
    # окно: рама, стекло, подоконник
    if wall_w == "A":
        for nm, bx in (("l", Box.of(wx0, wx0 + fw, fy0, fy1, wz0, wz1)), ("r", Box.of(wx1 - fw, wx1, fy0, fy1, wz0, wz1)),
                       ("b", Box.of(wx0 + fw, wx1 - fw, fy0, fy1, wz0, wz0 + fw)),
                       ("t", Box.of(wx0 + fw, wx1 - fw, fy0, fy1, wz1 - fw, wz1)),
                       ("m", Box.of((wx0 + wx1) / 2 - fw / 2, (wx0 + wx1) / 2 + fw / 2, fy0, fy1, wz0 + fw, wz1 - fw))):
            add(f"window_frame_{nm}", "Окно (рама)", "window", "window_frame", bx)
        add("window_glass", "Окно (стекло)", "window", "glass",
            Box.of(wx0 + fw, wx1 - fw, -w / 2 - 3, -w / 2 + 3, wz0 + fw, wz1 - fw))
        add("window_sill", "Подоконник", "window", "sill", Box.of(wx0, wx1, fy1, 0, wz0 - 20, wz0))
    else:
        q0, q1 = w / 2 - 35, w / 2 + 35
        for nm, (p0, p1, z0, z1) in (("l", (wx0, wx0 + fw, wz0, wz1)), ("r", (wx1 - fw, wx1, wz0, wz1)),
                                     ("b", (wx0 + fw, wx1 - fw, wz0, wz0 + fw)), ("t", (wx0 + fw, wx1 - fw, wz1 - fw, wz1)),
                                     ("m", ((wx0 + wx1) / 2 - fw / 2, (wx0 + wx1) / 2 + fw / 2, wz0 + fw, wz1 - fw))):
            add(f"window_frame_{nm}", "Окно (рама)", "window", "window_frame", cb(p0, p1, q0, q1, z0, z1), wall="C")
        add("window_glass", "Окно (стекло)", "window", "glass", cb(wx0 + fw, wx1 - fw, w / 2 - 3, w / 2 + 3,
                                                                    wz0 + fw, wz1 - fw), wall="C")
        add("window_sill", "Подоконник", "window", "sill", Box.of(a - float(win.get("sill_out", 0)), a + q0, wx0, wx1,
                                                                    wz0 - 20, wz0), wall="C")
    for i, c in enumerate(room.get("decor", [])):   # шторы и т.п. — только для картинки
        add(f"decor_{i}", c.get("name", "Декор"), "room", c.get("mat", "curtain"), Box.of(*c["box"]), wall=c.get("wall"))
    # дверь: полотно в проёме и наличник
    add("door_leaf", "Дверь (полотно)", "door", "door", Box.of(-w / 2 - 20, -w / 2 + 20, dy0 + 10, dy1 - 10, 0, dz1 - 10))
    for nm, bx in (("1", Box.of(0, 10, dy0 - 70, dy0, 0, dz1 + 70)), ("2", Box.of(0, 10, dy1, dy1 + 70, 0, dz1 + 70)),
                   ("t", Box.of(0, 10, dy0, dy1, dz1, dz1 + 70))):
        add(f"door_casing_{nm}", "Наличник", "door", "door_frame", bx)
    # точки коммуникаций
    colors = {"water": "point_water", "vent": "point_vent", "gas": "point_gas"}
    for p in room["points"]:
        r = float(p.get("d", 80)) / 2
        z = float(p["z"])
        if p["wall"] == "A":
            pt, bx = (float(p["pos"]), 0.0, z), Box.of(p["pos"] - r, p["pos"] + r, 0, 4, z - r, z + r)
        elif p["wall"] == "B":
            pt, bx = (0.0, float(p["pos"]), z), Box.of(0, 4, p["pos"] - r, p["pos"] + r, z - r, z + r)
        else:
            raise KitchenError(f"точка {p['id']}: стена A или B")
        k.points.append({**p, "pt": pt, "box": bx})
        col = colors.get(p.get("kind", p["id"]), colors.get(p["id"], "point_power"))
        add(f"pt_{p['id']}", p["name"], "point", col, bx, point=p["id"])
