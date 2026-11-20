"""Деталировка: панель из 3D -> деталь в своих координатах.

Система координат детали (как смотрит оператор на станке):
  u (X детали) — вдоль текстуры (если текстуры нет — вдоль длинной стороны), это «длина»;
  n — нормаль обрабатываемой пласти (смотрит вверх, на шпиндель);
  v (Y детали) = n × u — «ширина». Ноль — левый нижний угол, если смотреть на обрабатываемую пласть.
Стороны кромки: Д1 (y=0) и Д2 (y=W) идут вдоль длины; Ш1 (x=0) и Ш2 (x=L) — вдоль ширины.
Чистовые координаты — от края готовой детали (с кромкой); пильные — от края выпиленной заготовки.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geom import axis_of, cross, dot, sub, unit
from .model import Panel, Product, face_key

EDGE_NAMES = ("Д1", "Д2", "Ш1", "Ш2")
KIND_RU = {
    "confirmat_face": "конфирмат (пласть)", "confirmat_edge": "конфирмат (торец)",
    "minifix_cam": "эксцентрик", "minifix_edge": "эксцентрик, канал в торец", "minifix_bolt": "шток эксцентрика",
    "dowel_face": "шкант (пласть)", "dowel_edge": "шкант (торец)", "hinge_cup": "чашка петли",
    "hinge_plate": "планка петли", "shelf_pin": "полкодержатель", "handle": "ручка",
}


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


@dataclass
class LocalHole:
    side: str            # "A" — обрабатываемая пласть, "B" — обратная пласть, "Д1"/"Д2"/"Ш1"/"Ш2" — торец
    x: float             # чистовые координаты: для пласти — центр; для торца — точка входа на торце
    y: float
    z: float             # для торца — глубина оси от пласти A; для пласти — 0
    d: float
    depth: float
    through: bool
    kind: str
    joint: str

    @property
    def is_edge(self) -> bool:
        return self.side not in ("A", "B")

    def key(self):
        return (self.side, round(self.x, 2), round(self.y, 2), round(self.z, 2), self.d, round(self.depth, 2),
                self.through, self.kind)


@dataclass
class LocalGroove:
    side: str            # "A"/"B"
    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    depth: float
    stopped: bool

    def key(self):
        return (self.side, round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2), self.width,
                self.depth, self.stopped)


@dataclass
class LocalCut:
    """Вырез (выборка) прямоугольником в чистовых координатах детали: через всю толщину или с пласти на глубину."""
    x0: float
    y0: float
    x1: float
    y1: float
    depth: float
    through: bool

    def key(self):
        return (round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2), round(self.depth, 2),
                self.through)


@dataclass
class Detail:
    """Одна физическая деталь (экземпляр панели) в своих координатах."""
    panel: Panel
    product_id: str
    L: float
    W: float
    t: float
    edges: dict          # "Д1" -> толщина кромки (0 — нет)
    grain: bool
    holes: list
    grooves: list
    sub: dict            # "Д1" -> сколько вычтено из размера на эту сторону
    material: str
    frame: dict = field(default_factory=dict)
    cuts: list = field(default_factory=list)

    @property
    def L_saw(self) -> float:
        return self.L - self.sub["Ш1"] - self.sub["Ш2"]

    @property
    def W_saw(self) -> float:
        return self.W - self.sub["Д1"] - self.sub["Д2"]

    def to_saw(self, x: float, y: float) -> tuple[float, float]:
        return x - self.sub["Ш1"], y - self.sub["Д1"]

    def signature(self):
        return (self.material, round(self.L, 2), round(self.W, 2), tuple(self.edges[e] for e in EDGE_NAMES),
                self.grain, tuple(sorted(h.key() for h in self.holes)), tuple(sorted(g.key() for g in self.grooves)),
                tuple(sorted(c.key() for c in self.cuts)))


@dataclass
class Part:
    """Позиция деталировки: одинаковые детали объединены, qty — на весь заказ."""
    no: str
    name: str
    qty: int
    detail: Detail
    instances: list      # [(product_id, panel_id, copy_no)]

    def __getattr__(self, item):
        return getattr(self.detail, item)


def local_frame(p: Panel) -> dict:
    n = unit(p.thin, p.face)
    in_plane = [a for a in range(3) if a != p.thin]
    if p.grain is not None:
        g = p.grain
    else:
        g = max(in_plane, key=lambda a: p.box.size[a])
    o = [a for a in in_plane if a != g][0]
    u = unit(g, +1)
    v = cross(n, u)
    v_axis, v_sign = axis_of(v)
    assert v_axis == o
    origin = [0.0, 0.0, 0.0]
    origin[g] = p.box.lo[g]
    origin[o] = p.box.lo[o] if v_sign > 0 else p.box.hi[o]
    origin[p.thin] = p.box.hi[p.thin] if p.face > 0 else p.box.lo[p.thin]
    return {"u": u, "v": v, "n": n, "origin": tuple(origin), "g": g, "o": o, "v_sign": v_sign}


def to_local(fr: dict, pt) -> tuple[float, float, float]:
    d = sub(pt, fr["origin"])
    return dot(d, fr["u"]), dot(d, fr["v"]), -dot(d, fr["n"])   # z — глубина от пласти A


def edge_name_of_face(fr: dict, fk: str) -> str | None:
    """Глобальная грань -> имя стороны детали."""
    axis, sign = "xyz".index(fk[1]), (1 if fk[0] == "+" else -1)
    if axis == fr["g"]:
        return "Ш1" if sign < 0 else "Ш2"
    if axis == fr["o"]:
        lo_is_d1 = fr["v_sign"] > 0
        return "Д1" if (sign < 0) == lo_is_d1 else "Д2"
    return None


def make_detail(p: Panel, prod: Product) -> Detail:
    shop = prod.shop
    fr = local_frame(p)
    L, W = p.box.size[fr["g"]], p.box.size[fr["o"]]
    by_role = shop["edges"]["by_role"]
    edges = {e: 0.0 for e in EDGE_NAMES}
    for fk, role in p.edges.items():
        en = edge_name_of_face(fr, fk)
        if en:
            edges[en] = float(by_role.get(role, 0) or 0)
    rule = {float(k): float(v) for k, v in shop["edges"]["subtract"].items()}
    premill = float(shop["edges"].get("premill", 0) or 0)
    subs = {e: (rule.get(th, th) - premill if th > 0 else 0.0) for e, th in edges.items()}

    holes = []
    for h in p.holes:
        x, y, z = to_local(fr, h.p)
        da = dot(h.dir, fr["n"])
        if abs(da) > 0.5:                              # отверстие в пласть
            if h.through:
                side = "A"
            else:
                side = "A" if da < 0 else "B"
            holes.append(LocalHole(side, x, y, 0.0, h.d, h.depth, h.through, h.kind, h.joint))
        else:                                          # отверстие в торец
            du, dv = dot(h.dir, fr["u"]), dot(h.dir, fr["v"])
            if du > 0.5:
                side = "Ш1"
            elif du < -0.5:
                side = "Ш2"
            elif dv > 0.5:
                side = "Д1"
            else:
                side = "Д2"
            holes.append(LocalHole(side, x, y, z, h.d, h.depth, False, h.kind, h.joint))

    grooves = []
    for g in p.grooves:
        a, b = to_local(fr, g.box.lo), to_local(fr, g.box.hi)
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        z0, z1 = sorted((a[2], b[2]))
        side = "A" if z0 < 1e-6 else "B"
        grooves.append(LocalGroove(side, x0, y0, x1, y1, g.width, g.depth, g.stopped))

    cuts = []
    for cb in p.meta.get("cuts", []):                  # вырезы: глобальные коробки -> прямоугольник в детали
        x = cb.intersect(p.box)
        if x is None:
            continue
        a, b = to_local(fr, x.lo), to_local(fr, x.hi)
        x0, x1 = max(min(a[0], b[0]), 0.0), min(max(a[0], b[0]), L)
        y0, y1 = max(min(a[1], b[1]), 0.0), min(max(a[1], b[1]), W)
        z0, z1 = sorted((a[2], b[2]))
        through = z1 - z0 >= p.thickness - 1e-6
        cuts.append(LocalCut(x0, y0, x1, y1, z1 - z0, through))

    mat = prod.materials[p.material]
    return Detail(panel=p, product_id=prod.id, L=L, W=W, t=p.thickness, edges=edges,
                  grain=bool(mat.get("grain")) and p.grain is not None, holes=holes, grooves=grooves, sub=subs,
                  material=p.material, frame=fr, cuts=cuts)


def detailing(products: list[Product]) -> list[Part]:
    """Деталировка заказа: одинаковые детали (размер, кромка, присадка) — одна позиция."""
    groups: dict = {}
    order = []
    for prod in products:
        for copy in range(1, prod.qty + 1):
            for p in prod.panels:
                d = make_detail(p, prod)
                sig = (prod.id if len(products) > 1 else "",) + d.signature()
                if sig not in groups:
                    groups[sig] = {"detail": d, "names": [], "inst": [], "prefix": prod.prefix}
                    order.append(sig)
                groups[sig]["names"].append(p.name)
                groups[sig]["inst"].append((prod.id, p.id, copy))
    parts = []
    counters: dict = {}
    for sig in order:
        g = groups[sig]
        pre = g["prefix"]
        counters[pre] = counters.get(pre, 0) + 1
        name = g["names"][0]
        parts.append(Part(no=f"{pre}-{counters[pre]:02d}", name=name, qty=len(g["inst"]), detail=g["detail"],
                          instances=g["inst"]))
    return parts


def edge_str(edges: dict) -> str:
    return " ".join(f"{e}:{fmt(edges[e]) if edges[e] else '—'}" for e in EDGE_NAMES)
