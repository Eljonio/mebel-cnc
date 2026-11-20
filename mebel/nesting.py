"""Раскрой листов. Упаковка — rectpack (Apache-2.0), проверка результата — свой код.

Пропил: каждая деталь «раздувается» на ширину пропила, полезная зона листа — тоже (+пропил),
тогда между соседними деталями ровно пропил, а крайняя деталь не выходит за обрезку.
Текстура: деталь с текстурой кладётся длиной вдоль длины листа (2800) и не поворачивается.
Гильотина (форматно-раскроечный станок): каждый рез сквозной от края до края заготовки — проверяется отдельно.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import rectpack
from rectpack import guillotine, maxrects

from .parts import Part

SCALE = 10  # 0,1 мм -> целые

G_ALGOS = [guillotine.GuillotineBssfSas, guillotine.GuillotineBssfLas, guillotine.GuillotineBssfSlas,
           guillotine.GuillotineBssfLlas, guillotine.GuillotineBssfMaxas, guillotine.GuillotineBssfMinas,
           guillotine.GuillotineBlsfSas, guillotine.GuillotineBlsfLas, guillotine.GuillotineBafSas,
           guillotine.GuillotineBafLas, guillotine.GuillotineBafSlas, guillotine.GuillotineBafLlas]
M_ALGOS = [maxrects.MaxRectsBl, maxrects.MaxRectsBssf, maxrects.MaxRectsBaf, maxrects.MaxRectsBlsf]
SORTS = {"area": rectpack.SORT_AREA, "peri": rectpack.SORT_PERI, "diff": rectpack.SORT_DIFF,
         "sside": rectpack.SORT_SSIDE, "lside": rectpack.SORT_LSIDE, "ratio": rectpack.SORT_RATIO,
         "none": rectpack.SORT_NONE}


@dataclass
class Placement:
    part: Part
    instance: tuple       # (product_id, panel_id, copy)
    x: float              # левый нижний угол на листе, мм (от угла листа, с обрезкой)
    y: float
    w: float              # размер на листе (пильный)
    h: float
    rotated: bool         # True — длина детали идёт поперёк листа


@dataclass
class Sheet:
    material: str
    index: int
    L: float
    W: float
    trim: float
    kerf: float
    placements: list = field(default_factory=list)

    @property
    def parts_area(self) -> float:
        return sum(p.w * p.h for p in self.placements)

    @property
    def util(self) -> float:
        return self.parts_area / (self.L * self.W)


@dataclass
class NestResult:
    material: str
    sheets: list
    strategy: str
    tried: int


class NestError(ValueError):
    pass


def _instances(parts: list[Part], material: str):
    out = []
    for p in parts:
        if p.material != material:
            continue
        for inst in p.instances:
            out.append((p, inst))
    return out


def _run(items, orient, algo, sort, uL, uW, kerf, guillo):
    packer = rectpack.newPacker(mode=rectpack.PackingMode.Offline, bin_algo=rectpack.PackingBin.BFF,
                                pack_algo=algo, sort_algo=sort, rotation=False)
    kw = {"merge": False} if guillo else {}
    packer.add_bin(int(round((uL + kerf) * SCALE)), int(round((uW + kerf) * SCALE)), count=len(items), **kw)
    for i, ((p, _), rot) in enumerate(zip(items, orient)):
        w, h = (p.W_saw, p.L_saw) if rot else (p.L_saw, p.W_saw)
        packer.add_rect(int(round((w + kerf) * SCALE)), int(round((h + kerf) * SCALE)), rid=i)
    packer.pack()
    rects = packer.rect_list()
    if len(rects) != len(items):
        return None
    return rects


def nest(parts: list[Part], shop: dict, material: str) -> NestResult:
    mat = shop["materials"][material]
    cut = shop["cutting"]
    SL, SW = map(float, mat["sheet"])
    trim, kerf, guillo = float(cut["trim"]), float(cut["kerf"]), bool(cut.get("guillotine", True))
    uL, uW = SL - 2 * trim, SW - 2 * trim
    items = _instances(parts, material)
    if not items:
        return NestResult(material, [], "", 0)

    def fits(L, W):
        return L <= uL + 1e-6 and W <= uW + 1e-6

    # варианты ориентации: деталь с текстурой — только вдоль; без текстуры — как удобнее
    variants = {}
    for mode in ("long_x", "long_y", "fit"):
        orient = []
        for p, _ in items:
            if p.grain:
                if not fits(p.L_saw, p.W_saw):
                    raise NestError(f"{p.no} «{p.name}» {p.L_saw:g}×{p.W_saw:g} не влезает в лист вдоль текстуры")
                orient.append(False)
                continue
            can_x, can_y = fits(p.L_saw, p.W_saw), fits(p.W_saw, p.L_saw)
            if not (can_x or can_y):
                raise NestError(f"{p.no} «{p.name}» {p.L_saw:g}×{p.W_saw:g} не влезает в лист")
            long_along_x = p.L_saw >= p.W_saw
            want = {"long_x": not long_along_x, "long_y": long_along_x, "fit": False}[mode]
            if want and not can_y:
                want = False
            if not want and not can_x:
                want = True
            orient.append(want)
        variants[mode] = orient

    algos = G_ALGOS if guillo else G_ALGOS + M_ALGOS
    best, best_key, tried = None, None, 0
    for (mode, orient), algo, (sname, sort) in itertools.product(variants.items(), algos, SORTS.items()):
        tried += 1
        rects = _run(items, orient, algo, sort, uL, uW, kerf, guillo and algo in G_ALGOS)
        if rects is None:
            continue
        sheets = _to_sheets(rects, items, orient, material, SL, SW, trim, kerf)
        if guillo and not all(guillotine_ok(s) for s in sheets):
            continue
        n = len(sheets)
        last = min(s.parts_area for s in sheets)
        key = (n, last)  # меньше листов; при равенстве — больше делового остатка на последнем листе
        if best_key is None or key < best_key:
            best, best_key = (sheets, f"{mode}/{algo.__name__}/{sname}"), key
    if best is None:
        raise NestError("не удалось разложить детали")
    return NestResult(material, best[0], best[1], tried)


def _to_sheets(rects, items, orient, material, SL, SW, trim, kerf):
    sheets: dict = {}
    for b, x, y, w, h, rid in rects:
        p, inst = items[rid]
        rot = orient[rid]
        pw, phh = (p.W_saw, p.L_saw) if rot else (p.L_saw, p.W_saw)
        assert abs(w / SCALE - kerf - pw) < 0.05 and abs(h / SCALE - kerf - phh) < 0.05, "rectpack повернул деталь"
        s = sheets.setdefault(b, Sheet(material, 0, SL, SW, trim, kerf))
        s.placements.append(Placement(p, inst, trim + x / SCALE, trim + y / SCALE, pw, phh, rot))
    out = [sheets[k] for k in sorted(sheets)]
    out.sort(key=lambda s: -s.parts_area)
    for i, s in enumerate(out, 1):
        s.index = i
        s.placements.sort(key=lambda p: (p.y, p.x))
    return out


# ---------- проверки раскроя ----------
def guillotine_ok(sheet: Sheet) -> bool:
    rects = [(p.x, p.y, p.x + p.w, p.y + p.h) for p in sheet.placements]
    return _guillo(rects, sheet.kerf)


def _guillo(rects, kerf) -> bool:
    if len(rects) <= 1:
        return True
    for ax in (0, 1):
        for c in sorted(set(r[ax + 2] for r in rects)):
            left = [r for r in rects if r[ax + 2] <= c + 1e-6]
            right = [r for r in rects if r[ax] >= c + kerf - 1e-6]
            if left and right and len(left) + len(right) == len(rects):
                return _guillo(left, kerf) and _guillo(right, kerf)
    return False


def verify(res: NestResult, parts: list[Part], shop: dict) -> list[str]:
    """Пустой список — раскрой честный."""
    errs = []
    need = sorted((p.no, inst) for p, inst in _instances(parts, res.material))
    got = sorted((pl.part.no, pl.instance) for s in res.sheets for pl in s.placements)
    if need != got:
        errs.append(f"{res.material}: разложено {len(got)} из {len(need)} деталей")
    for s in res.sheets:
        lo, hiL, hiW = s.trim, s.L - s.trim, s.W - s.trim
        for pl in s.placements:
            if pl.x < lo - 1e-6 or pl.y < lo - 1e-6 or pl.x + pl.w > hiL + 1e-6 or pl.y + pl.h > hiW + 1e-6:
                errs.append(f"лист {s.index}: {pl.part.no} заходит в обрезку края")
            if pl.part.grain and pl.rotated:
                errs.append(f"лист {s.index}: {pl.part.no} повёрнута поперёк текстуры")
        for a, b in itertools.combinations(s.placements, 2):
            gap_x = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
            gap_y = max(b.y - (a.y + a.h), a.y - (b.y + b.h))
            if max(gap_x, gap_y) < s.kerf - 1e-6:
                errs.append(f"лист {s.index}: {a.part.no} и {b.part.no} ближе пропила ({max(gap_x, gap_y):.1f} мм)")
        if shop["cutting"].get("guillotine", True) and not guillotine_ok(s):
            errs.append(f"лист {s.index}: нет последовательности сквозных резов (не гильотина)")
    return errs
