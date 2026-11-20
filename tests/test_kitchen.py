"""Кухня: базовый конфиг собирается без ошибок, сломанные конфиги ловятся проверками."""
import copy
import os

import pytest
from openpyxl import load_workbook

from mebel.config import ROOT, load_shop, load_yaml
from mebel.kitchen import checks
from mebel.kitchen.__main__ import run
from mebel.kitchen.layout import KitchenError, build

CFG = os.path.join(ROOT, "products", "kuhnya-g.yaml")


@pytest.fixture(scope="module")
def base():
    return load_yaml(CFG)


@pytest.fixture(scope="module")
def shop():
    return load_shop()


def errs(cfg, shop, check=None):
    k = build(cfg, shop)
    e = checks.errors(checks.run_all(k))
    return [x for x in e if check is None or x.check == check]


def test_base_no_errors(base, shop):
    k = build(base, shop)
    f = checks.run_all(k)
    assert not checks.errors(f), [x.text for x in checks.errors(f)]
    assert k.runs == {"lower_b": 1800, "lower_a": 3000, "upper_a": 2100, "upper_b": 1200}
    names = {x.check for x in f}
    for c in ("сумма модулей", "высоты", "пересечения", "стены", "окно", "дверь", "мойка над водой",
              "варка под вентиляцией", "открывание дверей"):
        assert c in names


def test_heights_meet_sill(base, shop):
    k = build(base, shop)
    assert k.geo["zw"] == 900 == base["room"]["window"]["z0"]
    for s in k.kind("worktop"):
        assert s.box.hi[2] == 900 and s.box.lo[2] == 862


def test_module_sums_match_parts(base, shop):
    k = build(base, shop)
    low_a = [m for m in k.modules if m.run == "A" and m.level == "нижний" and m.type != "end_panel"]
    assert sum(m.width for m in low_a) + base["lower_a"]["start"] == 3000
    up_b = [m for m in k.modules if m.run == "B" and m.level == "верхний" and m.type != "end_panel"]
    assert sum(m.width for m in up_b) + base["upper_b"]["start"] == 1200


def test_door_as_in_tz_blocks_kitchen(base, shop):
    cfg = copy.deepcopy(base)
    cfg["room"]["door"]["from_corner"] = "AB"          # Y 100..900, как в ТЗ дословно
    e = errs(cfg, shop, "дверь")
    assert e and any("проёме двери" in x.text for x in e)


def test_upper_a_2400_hits_window(base, shop):
    cfg = copy.deepcopy(base)
    cfg["upper_a"]["modules"].append({"id": "В6", "type": "shelves", "width": 300, "shelves": 2, "hinge": "far"})
    assert errs(cfg, shop, "окно")
    assert errs(cfg, shop, "сумма модулей")


def test_sink_not_over_water(base, shop):
    cfg = copy.deepcopy(base)
    next(p for p in cfg["room"]["points"] if p["id"] == "water")["pos"] = 1350
    assert errs(cfg, shop, "мойка над водой")


def test_hob_not_under_vent(base, shop):
    cfg = copy.deepcopy(base)
    next(p for p in cfg["room"]["points"] if p["id"] == "vent")["pos"] = 1200
    assert errs(cfg, shop, "варка под вентиляцией")


def test_without_filler_door_hits_fridge(base, shop):
    cfg = copy.deepcopy(base)
    cfg["lower_b"] = [{"id": "Н1", "type": "corner_blind", "width": 1200, "blind": 600, "shelves": 1, "hinge": "far"},
                      {"id": "ХЛ", "type": "fridge", "width": 600}]
    e = errs(cfg, shop, "открывание дверей")
    assert e and "Холодильник" in e[0].text


def test_height_720_mismatch(base, shop):
    cfg = copy.deepcopy(base)
    cfg["heights"]["lower_carcass"] = 720
    cfg["lower_a"]["modules"][-1]["drawers"] = [176, 224, 224]   # поле фасадов стало 688
    assert errs(cfg, shop, "высоты")


def test_drawer_fronts_must_fill_field(base, shop):
    cfg = copy.deepcopy(base)
    cfg["lower_a"]["modules"][-1]["drawers"] = [176, 245, 200]
    with pytest.raises(KitchenError):
        build(cfg, shop)


def test_overlap_caught(base, shop):
    cfg = copy.deepcopy(base)
    cfg["lower_a"]["start"] = 540                        # ряд A въезжает в угловой Н1 на 20 мм
    cfg["lower_a"]["modules"][0]["width"] = 660
    assert errs(cfg, shop, "пересечения")


def test_corner_ac_switch_builds(base, shop):
    cfg = copy.deepcopy(base)
    cfg["kitchen"]["corner"] = "AC"
    cfg["room"]["door"]["from_corner"] = "AB"
    k = build(cfg, shop)
    e = checks.errors(checks.run_all(k))
    assert not [x for x in e if x.check == "дверь"]   # дверь как в ТЗ — кухне в углу A/C не мешает
    assert [x for x in e if x.check == "мойка над водой"]   # но вода у угла A/B — честно падает
    assert all(s.box.lo[0] >= -0.01 for s in k.solids if s.kind not in checks.ROOM_KINDS)


def test_outputs(tmp_path):
    res = run(CFG, str(tmp_path), render=False)
    assert not res["xlsx_errors"]
    for p in ("kuhnya_3d.html", "model/scene.json", "spec/kuhnya_specifikaciya.xlsx", "chertezhi/plan.png",
              "chertezhi/razvertka_A.png", "chertezhi/razvertka_B.png", "chertezhi/chertezhi.pdf", "ОТЧЁТ.md",
              "raskroy/raskroy.pdf"):
        assert (tmp_path / p).stat().st_size > 1000, p
    wb = load_workbook(tmp_path / "spec/kuhnya_specifikaciya.xlsx", read_only=True)
    assert {"Модули", "Фасады", "Спецификация", "Техника (отдельно)", "Детали ЛДСП и ХДФ", "Проверки",
            "Допущения"} <= set(wb.sheetnames)
    ldsp = next(r for r in res["results"] if r.material == "ldsp16_grey")
    area = sum(p.L * p.W * p.qty for p in res["parts"] if p.material == "ldsp16_grey") / 1e6
    L, W = res["kitchen"].shop["materials"]["ldsp16_grey"]["sheet"]
    assert len(ldsp.sheets) >= area / (L * W / 1e6)


def test_upper_end_panels(base, shop):
    k = build(base, shop)
    t2, t3 = k.solid("end_panel_Т2"), k.solid("end_panel_Т3")
    assert t2.mat == t3.mat == "facade"
    win = k.geo["window"]
    assert win.lo[0] - t2.box.hi[0] >= 50                       # до откоса окна после панели
    fr = k.appl["fridge"]
    assert t3.box.hi[1] <= fr.box.lo[1] + 1e-6                 # панель над холодильником не выходит на него
    assert k.runs["upper_a"] == 2100 and k.runs["upper_b"] == 1200
    assert not checks.errors(checks.run_all(k))


def test_share_html_has_no_internal_words(base, shop, tmp_path):
    from PIL import Image

    from mebel.kitchen import spec
    from mebel.kitchen.share import FORBIDDEN, build_html
    (tmp_path / "renders").mkdir()
    for v in ("front", "angle", "top"):
        Image.new("RGB", (64, 40), "white").save(tmp_path / "renders" / f"render_{v}.png")
    k = build(base, shop)
    parts, res, _ = spec.compute(k)
    doc = build_html(k, parts, res, str(tmp_path), str(tmp_path))
    import re
    text = re.sub(r"data:[^\"]+", "", doc).lower()
    assert not [w for w in FORBIDDEN if w in text]
    for must in ("Кухня Г-образная — проект", "27.10.2026", "4200 × 3100 × 2700", "Принятые решения", "Уточнить на объекте",
                 "Обозначения", "Развёртка стены A", "Развёртка стены B", "Спецификация", "Техника"):
        assert must in doc, must
