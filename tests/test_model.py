"""Модель и проверки: на правильных изделиях — чисто; на сломанных — проверка обязана поймать."""
import copy
import random

import pytest

from mebel import checks as chk
from mebel.builder import BuildError, build
from mebel.config import load_product
from mebel.geom import Box
from mebel.model import Hole
from mebel.parts import detailing

from conftest import PENAL, TUMBA


def levels(findings, check=None):
    return [f.level for f in findings if check is None or f.check == check]


@pytest.mark.parametrize("fx", ["tumba", "penal"])
def test_reference_products_clean(fx, request):
    prod = request.getfixturevalue(fx)
    f = chk.run_all(prod)
    assert not chk.errors(f), [x.text for x in chk.errors(f)]
    for name in ("габарит", "цепочка", "пересечения", "зазоры фасадов", "отверстия", "крепёж", "петли", "лист"):
        assert "ok" in levels(f, name), name


def test_tumba_numbers(tumba):
    """Ручной расчёт тумбы — сверка с генератором."""
    parts = {p.no: p for p in detailing([tumba])}
    want = {  # № : (длина, ширина чистовые; длина, ширина пильные)
        "T-01": (704, 431, 704, 429), "T-02": (704, 431, 704, 429), "T-03": (800, 447, 796, 445),
        "T-04": (768, 431, 768, 429), "T-05": (768, 80, 768, 80), "T-06": (766, 419, 766, 417),
        "T-07": (796, 636, 796, 636), "T-08": (620, 397, 616, 393), "T-09": (620, 397, 616, 393),
    }
    for no, (L, W, Ls, Ws) in want.items():
        p = parts[no]
        assert (p.L, p.W, p.L_saw, p.W_saw) == (L, W, Ls, Ws), no
    # 800 = 16 + 768 + 16; 720 = 704 + 16; 450 = 16 + 431 + 3; двери 2 + 397 + 2 + 397 + 2 = 800
    assert 16 + 768 + 16 == 800 and 704 + 16 == 720 and 16 + 431 + 3 == 450 and 2 + 397 + 2 + 397 + 2 == 800


def test_hinge_counts(tumba, penal):
    assert [len(d.meta["hinges"]) for d in tumba.by_role("door")] == [2, 2]
    assert [len(d.meta["hinges"]) for d in penal.by_role("door")] == [4]


def test_mirror_sides_are_different_parts(tumba):
    """Левая и правая боковины — зеркальные, это разные детали (присадка на внутренней пласти)."""
    parts = detailing([tumba])
    sides = [p for p in parts if p.panel.role.startswith("side")]
    assert len(sides) == 2 and all(p.qty == 1 for p in sides)
    assert all(h.side != "B" for p in parts for h in p.holes), "вся присадка с одной пласти"


def test_identical_shelves_grouped(penal):
    parts = detailing([penal])
    sh = [p for p in parts if p.panel.role == "shelf"]
    assert len(sh) == 1 and sh[0].qty == 3


# ---------- проверки ловят ошибки ----------
def test_catch_overlap(tumba):
    b = tumba.panel("bottom")
    b.box = Box(tuple(v - (1 if i == 0 else 0) for i, v in enumerate(b.box.lo)), b.box.hi)
    assert "error" in levels(chk.check_overlaps(tumba))


def test_catch_size_and_chain(tumba):
    s = tumba.panel("side_right")
    s.box = Box(s.box.lo, (s.box.hi[0] + 1, s.box.hi[1], s.box.hi[2]))
    assert "error" in levels(chk.check_size(tumba))
    assert "error" in levels(chk.check_chains(tumba))


def test_catch_facade_gap(tumba):
    d = tumba.by_role("door")[1]
    d.box = Box((d.box.lo[0] + 1, d.box.lo[1], d.box.lo[2]), d.box.hi)
    assert "error" in levels(chk.check_facades(tumba))


def test_catch_hole_near_edge(tumba):
    s = tumba.panel("side_left")
    s.holes.append(Hole(s.id, (16, 16 + 3, 300), (-1, 0, 0), 5, 10, "test", "X1"))   # 3 мм от переднего края
    assert "error" in levels(chk.check_holes(tumba))


def test_catch_hole_collision(tumba):
    s = tumba.panel("side_left")
    h = next(h for h in s.holes if h.kind == "shelf_pin")
    s.holes.append(Hole(s.id, (h.p[0], h.p[1] + 6, h.p[2]), h.dir, 5, 10, "test", "X2"))
    assert "error" in levels(chk.check_holes(tumba))


def test_catch_blind_hole_breakthrough(tumba):
    d = tumba.by_role("door")[0]
    cup = next(h for h in d.holes if h.kind == "hinge_cup")
    cup.depth = 15.5
    assert "error" in levels(chk.check_holes(tumba))


def test_catch_misaligned_joint(tumba):
    b = tumba.panel("bottom")
    h = next(h for h in b.holes if h.kind == "confirmat_edge")
    h.p = (h.p[0], h.p[1] + 2, h.p[2])
    assert "error" in levels(chk.check_joints(tumba))


def test_catch_shelf_on_hinge(penal):
    d = penal.by_role("door")[0]
    z = d.meta["hinges"][1]
    s = next(p for p in penal.panels if p.role == "shelf")
    s.box = Box((s.box.lo[0], s.box.lo[1], z - 8), (s.box.hi[0], s.box.hi[1], z + 8))
    assert "error" in levels(chk.check_hinges(penal))


def test_catch_part_bigger_than_sheet(shop):
    """Лист 1830×1830 (бывает у поставщиков): боковина пенала 2000 вдоль текстуры не влезает."""
    shop = copy.deepcopy(shop)
    shop["materials"]["ldsp16"]["sheet"] = [1830, 1830]
    prod = build(load_product(PENAL), shop)
    f = chk.check_parts(detailing([prod]), shop)
    assert "error" in levels(f, "лист")


def test_build_refuses_bad_params(shop):
    cfg = load_product(TUMBA)
    cfg["construction"]["shelves"]["count"] = 9
    with pytest.raises(BuildError):
        build(cfg, shop)
    cfg = load_product(TUMBA)
    cfg["construction"]["doors"]["count"] = 3
    with pytest.raises(BuildError):
        build(cfg, shop)


# ---------- параметры работают, а не одна тумба ----------
def test_parameter_sweep(shop):
    rnd = random.Random(19102026)
    base = load_product(TUMBA)
    built = refused = 0
    for _ in range(160):
        cfg = copy.deepcopy(base)
        W = rnd.choice([300, 400, 500, 600, 800, 1000, 1200])
        H = rnd.choice([450, 720, 900, 1400, 2000, 2200])
        D = rnd.choice([300, 350, 450, 600])
        cfg["size"] = {"width": W, "depth": D, "height": H}
        c = cfg["construction"]
        c["top"] = rnd.choice(["overlay", "inset"])
        c["top_joint"] = rnd.choice(["minifix", "confirmat"])
        c["back"] = rnd.choice(["overlay", "groove"])
        c["plinth"] = rnd.choice([0, 60, 80, 100])
        n = rnd.randint(0, 5)
        c["shelves"] = {"count": n, "fixed": [rnd.randint(1, n)] if n and rnd.random() < 0.4 else []}
        c["doors"] = {"count": rnd.choice([0, 1] if W < 500 else [0, 1, 2]), "hinge_side": rnd.choice(["left", "right"])}
        try:
            prod = build(cfg, shop)
        except BuildError:
            refused += 1      # явный отказ с причиной — допустимо (полки не влезают, петля в полку)
            continue
        built += 1
        f = chk.run_all(prod)
        errs = [x.text for x in chk.errors(f) if x.check != "лист"]
        assert not errs, (cfg["size"], c, errs)
    assert built >= 120, (built, refused)
