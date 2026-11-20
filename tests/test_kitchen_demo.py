"""Демо-кухня (kuhnya-demo.yaml, синтетический пример): без ручек, газ, открывание у угла и у холодильника, СВЧ,
розетки, PDF с эскизом-референсом, присадка и DXF."""
import copy
import os
import re

import pytest

from mebel.config import ROOT, load_shop, load_yaml
from mebel.kitchen import checks
from mebel.kitchen.layout import build

CFG = os.path.join(ROOT, "products", "kuhnya-demo.yaml")


@pytest.fixture(scope="module")
def base():
    return load_yaml(CFG)


@pytest.fixture(scope="module")
def shop():
    return load_shop()


def found(cfg, shop, check=None, level=("error",)):
    k = build(cfg, shop)
    return [x for x in checks.run_all(k) if x.level in level and (check is None or x.check == check)]


def mod(cfg, mid):
    for key in ("lower_a", "lower_b", "upper_a", "upper_b"):
        for m in cfg[key]["modules"]:
            if m["id"] == mid:
                return m
    raise KeyError(mid)


def test_sizes_as_configured(base, shop):
    k = build(base, shop)
    assert not checks.errors(checks.run_all(k))
    assert k.runs == {"lower_b": 1550, "lower_a": 3200, "upper_a": 3200, "upper_b": 1550}
    assert k.geo["zw"] == 880 and k.geo["worktop_B_end"] == 1570
    assert k.solid("end_panel_B").box.hi[1] == 1568                 # 1550 + торец 18
    fr = k.appl["fridge"].box
    assert fr.lo[0] >= 3200 and fr.size[0] == 600                  # холодильник за мебелью, в длину ряда не входит
    hood = k.module("В5")
    assert (hood.u0, hood.u1) == (1850, 2450) == (k.module("Н3").u0, k.module("Н3").u1)   # вытяжка над варкой
    ups = [f.solid.box.lo[2] for m in k.modules if m.level == "верхний" and m.type == "shelves" for f in m.facades]
    assert min(ups) == 1500 and k.geo["uz1"] == 2520               # верхние 1500..2520 = 1020 до планки


def test_gas_hood_is_critical_not_error(base, shop):
    c = found(base, shop, "газ", ("critical",))
    assert len(c) == 1 and "НЕ ХВАТАЕТ 66" in c[0].text and "индукция" in c[0].text   # 650 − (1500 − 916)
    cfg = copy.deepcopy(base)
    cfg["heights"]["hood_bottom"] = 1570                          # поднять шкаф вытяжки на 70
    assert not found(cfg, shop, "газ", ("critical", "error"))
    cfg = copy.deepcopy(base)
    cfg["kitchen"]["hob"] = "induction"
    assert not found(cfg, shop, "газ", ("critical", "error"))


def test_corner_door_needs_filler(base, shop):
    cfg = copy.deepcopy(base)
    mod(cfg, "Н1")["filler"] = 0
    e = found(cfg, shop, "открывание дверей")
    assert e and any("посудомойки" in x.text for x in e)


@pytest.mark.parametrize("mid", ["Н5", "В7"])
def test_door_hinged_at_fridge_hits_it(base, shop, mid):
    cfg = copy.deepcopy(base)
    mod(cfg, mid)["hinge"] = "far"
    e = found(cfg, shop, "открывание дверей")
    assert e and any("Холодильник" in x.text for x in e)


def test_microwave_niche(base, shop):
    k = build(base, shop)
    assert k.geo["mw"]["niche"] == (568, 363, 332)
    cfg = copy.deepcopy(base)
    cfg["appliances"]["microwave"]["niche_h"] = 400
    assert found(cfg, shop, "СВЧ")


def test_gas_valve_and_sockets(base, shop):
    cfg = copy.deepcopy(base)
    next(p for p in cfg["room"]["points"] if p["id"] == "gas")["pos"] = 1550      # за ящиками Н2
    assert found(cfg, shop, "газ", ("critical",))
    cfg = copy.deepcopy(base)
    p = next(p for p in cfg["room"]["points"] if p["id"] == "pw_dw")
    p["wall"], p["pos"] = "B", 800                                               # за посудомойкой
    assert found(cfg, shop, "розетки", ("warn",))
    cfg = copy.deepcopy(base)
    next(p for p in cfg["room"]["points"] if p["id"] == "pw_oven")["pos"] = 2430  # за духовкой, но вне зоны
    assert found(cfg, shop, "розетки", ("warn",))


def test_oven_drawers_strip(base, shop):
    k = build(base, shop)
    assert k.geo["oven_z"] == (242, 837)                       # ниша 600 до низа столешницы, фасад 595
    hs = sorted(f.h for f in k.module("Н2").facades)
    assert hs == [177, 177, 357] and sum(hs) + 2 * 3 == 717     # 1 : 1 : 2, зазор 3 (TIP-ON BLUMOTION ≥ 2,5)
    assert k.geo["ceiling_strip"] == 78                    # 2600 − 2520 − зазор 2
    assert k.solid("end_panel_Т3").box.hi[2] == 2598            # торец верхних до потолка


def test_share_pdf_text(base, shop, tmp_path):
    from PIL import Image

    from mebel.kitchen import spec
    from mebel.kitchen.share import FORBIDDEN
    from mebel.kitchen.share_order import build_html
    (tmp_path / "renders").mkdir()
    for v in ("photo", "angle", "front"):
        Image.new("RGB", (64, 40), "white").save(tmp_path / "renders" / f"preview_{v}.png")
    src = tmp_path / "photo.jpeg"
    Image.new("RGB", (64, 40), "white").save(src)
    k = build(base, shop)
    parts, res, _ = spec.compute(k)
    doc = build_html(k, parts, res, checks.run_all(k), str(tmp_path), str(tmp_path), str(src))
    text = re.sub(r"data:[^\"]+", "", doc).lower()
    assert not [w for w in FORBIDDEN if w in text]
    for must in ("Важно до заказа", "Чем проект отличается от эскиза", "Вопросы и замер", "Деталировка", "Фасады МДФ",
                 "наш проект с того", "НЕ ХВАТАЕТ 66"):
        assert must in doc, must


def test_photo_camera(base, shop):
    from mebel.kitchen.scene import scene_json
    sc = scene_json(build(base, shop))
    c = sc["cameras"]["photo"]
    assert c["pos"][2] == 1600 and c["fov_h"] == pytest.approx(70) and "D" in c["hide"]


def test_tz_parts_fixed_split(shop):
    """ТЗ-кухня: детали с разными вырезами больше не сливаются в одну позицию (боковины Н6, полка шкафа вытяжки)."""
    from mebel.kitchen import spec
    k = build(load_yaml(os.path.join(ROOT, "products", "kuhnya-g.yaml")), shop)
    parts, _, _ = spec.compute(k)
    sides = [p for p in parts if p.name == "Боковина нижнего" and any(i[1].startswith("Н6") for i in p.instances)]
    assert len(sides) == 1 and sides[0].qty == 2 and len(sides[0].detail.cuts) == 3
    assert sum(p.qty for p in parts) == 70


def test_drilling_and_dxf(base, shop, tmp_path):
    """Второй этап: присадка без ошибок, чашка и планка петли на одной оси, DXF прочитаны обратно и сверены."""
    from mebel import checks as core
    from mebel.kitchen import drilling
    from mebel.kitchen.__main__ import run
    k = build(base, shop)
    st = drilling.drill(k)
    f = core.check_holes(k.product) + core.check_joints(k.product) + drilling.check(k)
    assert not [x for x in f if x.level == "error"], [x.text for x in f if x.level == "error"]
    doors = [fa for m in k.modules for fa in m.facades if fa.hinges]
    assert st["hinge"] == sum(fa.hinges for fa in doors) and not st["notes"]
    for fa in doors:                                            # петли от краёв двери 100, кроме шкафа вытяжки
        zs = [z - fa.solid.box.lo[2] for z in fa.solid.meta["hinges_z"]]
        if fa.module != "В5":
            assert zs[0] == 100 and abs(fa.h - zs[-1] - 100) < 0.5, (fa.module, zs)
    hood = k.appl["hood"].box
    assert min(k.module("В5").facades[0].solid.meta["hinges_z"]) - 40 >= hood.hi[2]   # петли выше корпуса вытяжки
    post = k.solid("Н1_post").box
    assert post.hi[2] == k.geo["zc"]                            # стойка на всю высоту
    res = run(CFG, str(tmp_path), render=False, share=False)    # strict: при расхождении DXF — SystemExit
    d = tmp_path / "dxf"
    assert len(list((d / "parts").glob("*.dxf"))) == len(res["parts"])
    assert list((d / "fasady").glob("*.dxf")) and (d / "README.txt").exists()
