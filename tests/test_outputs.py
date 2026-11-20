"""Раскрой, DXF (запись + обратное чтение), Excel, постпроцессор — на полном конвейере."""
import os

import ezdxf
import pytest
from openpyxl import load_workbook

from mebel import nesting
from mebel.nesting import Placement, Sheet, guillotine_ok
from mebel.pipeline import run
from mebel.post import MachineNotConfigured, MachineProfile, PostProcessor

from conftest import PENAL, TUMBA


@pytest.fixture(scope="module")
def tumba_run(tmp_path_factory):
    return run([TUMBA], str(tmp_path_factory.mktemp("tumba")), viewer=False)


@pytest.fixture(scope="module")
def order_run(tmp_path_factory):
    return run([TUMBA, PENAL], str(tmp_path_factory.mktemp("order")), viewer=False)


def test_pipeline_no_errors(tumba_run, order_run):
    assert tumba_run["summary"]["errors"] == []
    assert order_run["summary"]["errors"] == []


def test_nesting_honest(order_run):
    for r in order_run["results"]:
        assert nesting.verify(r, order_run["parts"], order_run["shop"]) == []
        for s in r.sheets:
            assert guillotine_ok(s)
            for pl in s.placements:
                assert not (pl.part.grain and pl.rotated)


def test_guillotine_checker_rejects_pinwheel():
    """Вертушка из 4 деталей — классический не-гильотинный раскрой. Проверка должна сказать «нет»."""
    class P:
        pass
    s = Sheet("x", 1, 1000, 1000, 0, 4)
    for x, y, w, h in [(0, 0, 600, 396), (604, 0, 396, 600), (400, 604, 600, 396), (0, 400, 396, 600)]:
        s.placements.append(Placement(P(), ("a", "b", 1), x, y, w, h, False))
    assert not guillotine_ok(s)
    s.placements = s.placements[:2]
    assert guillotine_ok(s)


def test_kerf_respected(tumba_run, tmp_path):
    shop = dict(tumba_run["shop"])
    shop["cutting"] = dict(shop["cutting"], kerf=12)
    r = nesting.nest(tumba_run["parts"], shop, "ldsp16")
    assert nesting.verify(r, tumba_run["parts"], shop) == []


def test_dxf_hinge_cups_independent(tumba_run):
    """Независимо от сверки конвейера: чашки петель левой двери в DXF там, где посчитано руками.
    Петля 100 мм от торцов двери 620 -> 100 и 520 по чистовому; кромка 2 мм -> 98 и 518 по пильному.
    Центр 22 мм от края петель -> 20 по пильному. Ø35, глубина 13."""
    path = [f for f in tumba_run["summary"]["files"]["dxf_parts"] if os.path.basename(f).startswith("T-08")][0]
    doc = ezdxf.readfile(path)
    cups = sorted((round(e.dxf.center.x, 3), round(e.dxf.center.y, 3), e.dxf.radius)
                  for e in doc.modelspace().query('CIRCLE[layer=="DRILL_V_D35_Z13"]'))
    assert cups == [(98.0, 20.0, 17.5), (518.0, 20.0, 17.5)]
    cont = doc.modelspace().query('LWPOLYLINE[layer=="CONTOUR"]')[0]
    xs = [p[0] for p in cont.get_points("xy")]
    ys = [p[1] for p in cont.get_points("xy")]
    assert (max(xs), max(ys)) == (616, 393)
    assert doc.header["$INSUNITS"] == 4
    props = dict(doc.header.custom_vars)
    assert "НЕ ЗАДАН" in props["Станок"] and props["Толщина, мм"] == "16"


def test_dxf_tamper_is_caught(tumba_run, tmp_path):
    """Сверка DXF не формальная: сдвинутое отверстие ловится."""
    from mebel.dxf_out import verify_part_dxf
    p = [x for x in tumba_run["parts"] if x.no == "T-01"][0]
    src = [f for f in tumba_run["summary"]["files"]["dxf_parts"] if os.path.basename(f).startswith("T-01")][0]
    doc = ezdxf.readfile(src)
    c = doc.modelspace().query('CIRCLE[layer=="DRILL_V_D15_Z13"]')[0]
    c.dxf.center = (c.dxf.center.x + 0.5, c.dxf.center.y)
    bad = str(tmp_path / "bad.dxf")
    doc.saveas(bad)
    assert verify_part_dxf(p, src) == []
    assert verify_part_dxf(p, bad)


def test_xlsx_edges_by_hand(tumba_run):
    """Кромка тумбы руками: 2 мм — боковины 2×704, крышка 800+447+447, дно 768, полка 766, двери 2×2×(620+397)
    = 8704 мм; 0,4 мм — низ боковин 2×431, цоколь 768, полка 766+2×419 = 3234 мм."""
    wb = load_workbook(tumba_run["summary"]["files"]["xlsx"], read_only=True)
    rows = {r[0]: r for r in wb["Кромка"].iter_rows(min_row=2, values_only=True)}
    assert rows["Кромка 2 мм"][3] == pytest.approx(8.704)
    assert rows["Кромка 0.4 мм"][3] == pytest.approx(3.234)
    hw = {r[0]: r[1] for r in wb["Фурнитура"].iter_rows(min_row=2, values_only=True)}
    assert hw["Конфирмат 7×50"] == 2 * 3 + 2 * 1 + 4   # дно, цоколь к боковинам, дно к цоколю
    assert hw["Петля накладная 110° + планка 0 мм"] == 4
    assert hw["Полкодержатель Ø5"] == 4


def test_postprocessor_refuses_without_machine(tumba_run):
    with pytest.raises(MachineNotConfigured):
        PostProcessor(MachineProfile.load("none")).generate({"drills": []})
    out = tumba_run["summary"]["out"]
    gcode_ext = (".nc", ".tap", ".gcode", ".ngc", ".cnc", ".mpr", ".bpp", ".xxl")
    for root, _, files in os.walk(out):
        assert not [f for f in files if f.lower().endswith(gcode_ext)], "файл для станка без станка"


def test_ops_match_dxf(tumba_run):
    """Операции листа (вход будущего постпроцессора) = отверстия в DXF листа."""
    import json
    op = json.load(open(tumba_run["summary"]["files"]["ops"][0], encoding="utf-8"))
    sheet_dxf = tumba_run["summary"]["files"]["dxf_sheets"][0]
    doc = ezdxf.readfile(sheet_dxf)
    n_circles = len(doc.modelspace().query("CIRCLE"))
    assert len(op["drills"]) == n_circles
    assert op["header"]["Станок"].startswith("НЕ ЗАДАН")
