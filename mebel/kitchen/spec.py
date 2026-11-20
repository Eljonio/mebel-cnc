"""Кухня: таблица модулей, фасады, спецификация материалов и фурнитуры (без цен), техника, допущения."""
from __future__ import annotations

import math
from collections import Counter

from .. import nesting
from ..parts import EDGE_NAMES, detailing, edge_str, fmt
from ..xlsx_out import edge_totals
from .layout import TYPE_RU, Kitchen

HW_NAMES = {
    "confirmat": ("Конфирмат 7×50", "шт", "сборка корпусов (оценка: по 2–3 на стык)"),
    "shelf_pin": ("Полкодержатель Ø5", "шт", "съёмные полки"),
    "hdf_screw": ("Саморез 3,5×16 для ХДФ (или гвоздь)", "шт", "задние стенки, шаг ~120"),
    "leg": ("Опора регулируемая 100 мм (95–130)", "шт", "нижние корпуса: 4 на корпус, 6 на широкий"),
    "plinth_clip": ("Клипса крепления цоколя к опоре", "шт", "передние опоры"),
    "worktop_fix": ("Крепление столешницы (саморез 4×30 через царгу / уголок)", "шт", "4 на корпус"),
    "hanger": ("Навес регулируемый скрытый для верхних", "шт", "2 на шкаф"),
    "wall_bracket": ("Уголок крепления к стене (угловой верхний)", "шт", "В1"),
    "filler_bracket": ("Уголок крепления доборной планки", "шт", "планки"),
    "panel_clip": ("Клипса для съёмной фальш-панели", "шт", "под духовкой"),
    "sink_tray": ("Поддон алюминиевый в шкаф под мойку 600", "шт", "защита дна от протечек"),
    "dw_kit": ("Комплект монтажа фасада ПММ (идёт с ПММ) + планка-пароотвод под столешницу", "компл", "Н5"),
}


def module_rows(k: Kitchen) -> list[dict]:
    rows = []
    order = {"A": 1, "B": 0, "угол": 2}
    for m in sorted(k.modules, key=lambda m: (m.level != "нижний", order.get(m.run, 3), m.u0)):
        axis = "X" if m.run == "A" else "Y"
        if m.type in ("corner_filler",):
            pos = "угол X/Y 560..600" if m.u1 <= 600 else f"угол, X {fmt(m.u0)}..{fmt(m.u1)}"
        elif m.type == "ceiling_strip":
            pos = "над верхними, вдоль A и B"
        elif m.type == "corner_l":
            pos = f"X 0..{fmt(m.u1)} и Y 0..{fmt(m.u1)}"
        else:
            pos = f"{axis} {fmt(m.u0)}..{fmt(m.u1)}"
        fac = Counter()
        for f in m.facades:
            fac[(f.name, f.w, f.h, f.hinges)] += 1
        flist = "; ".join(f"{n} {fmt(w)}×{fmt(h)}" + (f" ×{q}" if q > 1 else "") +
                          (f" ({hc} петли)" if hc and "гармошки» (на створке" not in n else "") +
                          (f" ({hc} петли-гармошка)" if hc and "гармошки» (на створке" in n else "")
                          for (n, w, h, hc), q in fac.items())
        rows.append({
            "id": m.id, "type": TYPE_RU.get(m.type, {"corner_filler": "планка угловая", "end_panel":
                                                    "панель торцевая"}.get(m.type, m.type)),
            "level": m.level, "run": m.run, "pos": pos, "z": f"{fmt(m.z0)}..{fmt(m.z1)}",
            "carcass": (f"{fmt(m.carcass[0])}×{fmt(m.carcass[1])}×{fmt(m.carcass[2])}" if m.carcass else "—"),
            "facades": flist or "—", "n_fac": len(m.facades), "inside": m.inside,
            "hinges": sum(f.hinges for f in m.facades if "на створке" not in f.name),
        })
    return rows


def facade_rows(k: Kitchen) -> list[dict]:
    rows = []
    for m in k.modules:
        for f in m.facades:
            rows.append({"module": m.id, "name": f.name, "w": f.w, "h": f.h, "area": f.w * f.h / 1e6,
                         "hinge": {"corner": "со стороны угла", "far": "от угла"}.get(f.hinge, "—") if f.hinge else "—",
                         "hinges": f.hinges, "kind": f.kind})
    return rows


def worktop_info(k: Kitchen) -> dict:
    sh = k.shop
    wt = k.kind("worktop")
    pieces = [(s.name, max(s.box.size[0], s.box.size[1]), min(s.box.size[0], s.box.size[1])) for s in wt]
    lens = sorted(sh["kitchen_materials"][k.cfg["materials"]["worktop"]]["lengths"])
    saw = sh["kitchen"]["worktop"]["saw"]
    need = sum(p[1] for p in pieces) + saw * (len(pieces) - 1)
    if need <= lens[-1]:
        blanks = f"1 заготовка {lens[-1]}×600 (нужно {fmt(need)} мм с пропилом)"
    else:
        blanks = f"{len(pieces)} заготовки: " + ", ".join(
            str(next(L for L in lens if L >= p[1])) + "×600" for p in pieces)
    return {"pieces": pieces, "blanks": blanks, "joints": max(0, len(pieces) - 1), "end_strips": 2}


def material_spec(k: Kitchen, parts, nest_results) -> list[tuple]:
    """(раздел, позиция, кол-во, ед., примечание)."""
    if k.geo.get("opening") == "push":
        return _material_spec_push(k, parts, nest_results)
    sh = k.shop
    mats = sh["materials"]
    cm, bm, fm = (k.cfg["materials"][x] for x in ("carcass", "back", "facade"))
    rows = []
    by_mat = {r.material: r for r in nest_results}
    for key in (cm, bm):
        area = sum(p.L * p.W * p.qty for p in parts if p.material == key) / 1e6
        r = by_mat.get(key)
        n = len(r.sheets) if r else 0
        util = ", ".join(f"{s.util * 100:.0f}%" for s in r.sheets) if r else ""
        L, W = mats[key]["sheet"]
        rows.append(("Плита", mats[key]["name"], round(area, 2), "м² деталей",
                     f"листов {L}×{W}: {n} (заполнение {util}); раскрой с пропилом {sh['cutting']['kerf']} и обрезкой "
                     f"{sh['cutting']['trim']} — карта раскроя в папке cutmap"))
        rows.append(("Плита", f"  листов {mats[key]['kind']} {L}×{W}", n, "лист", "по раскрою"))
    frs = facade_rows(k)
    area = sum(r["area"] for r in frs)
    kinds = Counter(r["kind"] for r in frs)
    ru = {"door": "двери", "leaf": "створки «гармошки»", "drawer": "фасады ящиков", "dw": "фасад ПММ",
          "cargo": "фасад карго", "panel": "фальш-панель", "filler": "доборные планки", "corner": "угловые планки",
          "end": "торцевая панель"}
    rows.append(("Фасады", mats[fm]["name"], round(area, 2), "м²",
                 f"{len(frs)} шт: " + ", ".join(f"{ru.get(kk, kk)} {v}" for kk, v in kinds.items()) +
                 "; фрезеровки нет (гладкие), кромки нет — покраска по кругу; размеры — лист «Фасады»"))
    wt = worktop_info(k)
    rows.append(("Столешница", mats[k.cfg["materials"]["worktop"]]["name"], len(wt["pieces"]), "кусок",
                 "; ".join(f"{n} {fmt(L)}×{fmt(W)}" for n, L, W in wt["pieces"]) + f"; {wt['blanks']}"))
    ks = sh["kitchen"]["worktop"]
    rows.append(("Столешница", ks["joint_strip"], wt["joints"], "шт", "стык кусков A и B в углу (Y=600)"))
    rows.append(("Столешница", ks["end_strip"], wt["end_strips"], "шт",
                 f"открытые торцы: X={fmt(k.geo['x_top'])} (над торцевой панелью) и Y={fmt(k.geo['worktop_B_end'])} "
                 "(у холодильника)"))
    ap_t = k.solid("apron_B").box.size[0]
    wall_len = (k.geo["apron"]["A"] + k.geo["apron"]["B"] - ap_t + 6) / 1000
    rows.append(("Столешница", ks["wall_strip"], round(wall_len, 2), "м",
                 "стык столешницы со стеной/фартуком; + уголок внутренний 1, заглушки 2; под окном — герметик к подоконнику"))
    rows.append(("Столешница", "Вырез под мойку (по шаблону мойки) и под варку 560×490 (по паспорту), "
                 "торцы вырезов — герметик", 2, "выреза", "делается в цеху или на месте"))
    rows.append(("Столешница", "Герметик силиконовый санитарный / для торцов", 2, "туба",
                 "вырезы, стык, примыкания"))
    ap = k.kind("apron")
    rows.append(("Фартук", mats[k.cfg["materials"]["apron"]]["name"], round(sum(s.box.size[0 if s.box.size[0] > 10 else 1]
                                                                               * s.box.size[2] for s in ap) / 1e6, 2),
                 "м²", "; ".join(f"{s.name} {fmt(max(s.box.size[0], s.box.size[1]))}×{fmt(s.box.size[2])}" for s in ap)
                 + "; под окном фартука нет"))
    # кромка
    et = edge_totals(parts, sh)
    for e in et:
        rows.append(("Кромка", f"Кромка ПВХ {fmt(e['thickness'])}×{sh['edges']['tape_width'].get(str(int(e['width'])), '')} "
                     f"мм ({e['material'].split('(')[0].strip()})", round(e["m_allow"], 2), "м",
                     f"чистыми {e['m']:.2f} м, отрезков {e['pieces']}, запас {sh['edges']['piece_allowance']} мм на отрезок"))
    lm = sum(v for _, v in k.lpanels) / 1000
    if lm:
        rows.append(("Кромка", "Кромка ПВХ 2 мм на Г-детали углового верхнего (внутренний угол)", round(lm + 0.2, 2),
                     "м", f"чистыми {lm:.2f} м: передние кромки Г-образных дна, крыши и полок В1"))
    # цоколь
    pl = k.geo["plinth"]
    plen = (pl["A"] + pl["B"]) / 1000
    bar = sh["kitchen"]["plinth"]["bar"]
    rows.append(("Цоколь", sh["kitchen"]["plinth"]["name"], round(plen, 2), "м",
                 f"ряд A {fmt(pl['A'])} + ряд B {fmt(pl['B'])}; хлыстов {bar / 1000:g} м: "
                 f"{math.ceil(plen * 1000 / bar)}; подрезать под ПММ по паспорту"))
    rows.append(("Цоколь", "Угол внутренний 90° для цоколя", 1, "шт", "стык рядов A и B"))
    rows.append(("Цоколь", "Заглушка торцевая цоколя", 1, "шт", "конец ряда B у холодильника (конец A закрыт торцевой панелью)"))
    rows.append(("Цоколь", "Уплотнитель цоколя (к полу)", round(plen, 2), "м", "по желанию"))
    # профили Gola
    kc = sh["kitchen"]
    gL = k.geo["gola_L"]
    lL = (gL["A"] + gL["B"]) / 1000
    golaC = [s for s in k.kind("gola") if s.meta.get("profile") == "C"]
    lC = sum(max(s.box.size[0], s.box.size[1]) for s in golaC) / 1000
    rows.append(("Профиль Gola", kc["gola_L"]["name"], round(lL, 2), "м",
                 f"ряд A {fmt(gL['A'])} + ряд B {fmt(gL['B'])}; хлыстов {kc['gola_L']['bar'] / 1000:g} м: "
                 f"{math.ceil(lL * 1000 / kc['gola_L']['bar'])}; угол внутренний 1, заглушка 1 (у холодильника)"))
    if golaC:
        rows.append(("Профиль Gola", kc["gola_C"]["name"], round(lC, 2), "м",
                     f"{len(golaC)} отрезка по {fmt(max(golaC[0].box.size[0], golaC[0].box.size[1]))} (Н6); "
                     f"заглушки {len(golaC)} (со стороны ПММ)"))
    rows.append(("Профиль Gola", "Крепёж профилей (уголки, саморезы) + выборка в боковинах под профиль", 1, "компл",
                 f"вырез {kc['gola_L']['depth']}×{kc['gola_L']['height']} в передне-верхнем углу боковин нижних"))
    # LED
    led = k.geo["led"]
    lled = sum(led.values()) / 1000
    lk = kc["led"]
    watt = lled * lk["watt_per_m"]
    psu = max(15, math.ceil(watt * lk["psu_margin"] / 15) * 15)
    rows.append(("Подсветка", lk["name_profile"], round(lled, 2), "м",
                 " + ".join(f"ряд {r} {fmt(v)}" for r, v in led.items()) +
                 f"; хлыстов {lk['profile_bar'] / 1000:g} м: {math.ceil(lled * 1000 / lk['profile_bar'])}; заглушки "
                 f"{2 * len(led)}, крепёж"))
    rows.append(("Подсветка", lk["name_strip"], round(lled, 2), "м", f"катушка {lk['strip_reel'] / 1000:g} м: 1 "
                 f"(нужно {lled:.2f} м, мощность ~{watt:.0f} Вт)"))
    rows.append(("Подсветка", f"Блок питания 24 В {psu} Вт (запас ×{lk['psu_margin']})", 1, "шт",
                 "прячется в шкафу верхних или над ними; нужна розетка/вывод (в ТЗ нет)"))
    rows.append(("Подсветка", "Выключатель бесконтактный (взмах руки) в профиль или клавишный", 1, "шт", ""))
    rows.append(("Подсветка", "Провод 2×0,75 + коннекторы", 5, "м", "соединение рядов A и B через угловой В1"))
    # фурнитура
    hw = Counter()
    for m in k.modules:
        hw.update(m.hw)
    hw.update(k.hw)
    n_fac = Counter(f.kind for m in k.modules for f in m.facades)
    rows.append(("Фурнитура", kc["hinges_note"], hw["hinge"], "шт",
                 "двери нижних — 2, верхних 918 мм — 3, шкаф вытяжки 818 — 2 (таблица петель в shop.yaml)"))
    if hw["bifold_hinge"]:
        rows.append(("Фурнитура", kc["bifold_hinge"], hw["bifold_hinge"], "шт", "угловой верхний В1: створка к створке"))
    if hw["drawer"]:
        rows.append(("Фурнитура", kc["drawer"]["system"], hw["drawer"], "компл",
                     f"Н6: {n_fac['drawer']} ящика; дно и задняя стенка из ЛДСП — в деталях"))
    if hw["cargo"]:
        rows.append(("Фурнитура", "Карго-бутылочница 300 с доводчиком, 2 корзины, крепление фасада", hw["cargo"],
                     "шт", "Н3"))
    if hw["dryer"]:
        rows.append(("Фурнитура", "Сушилка для посуды в шкаф 600, 2 уровня, с поддоном", hw["dryer"], "шт", "В2"))
    rows.append(("Фурнитура", "Шина монтажная для навесов", round(k.runs["upper_a"] / 1000 + (
        k.runs["upper_b"] - min((m.u0 for m in k.modules if m.run == "B" and m.level == "верхний"), default=0)) / 1000,
        2), "м", "вдоль A и B, дюбель 8×60 через ~300 мм"))
    rows.append(("Фурнитура", "Дюбель 8×60 + шуруп (шина, уголки, ПММ)", 20, "шт", "оценка"))
    n_join = 0
    for run in ("A", "B"):
        for lvl in ("нижний", "верхний"):
            mods = sorted((m for m in k.modules if m.run == run and m.level == lvl and m.carcass), key=lambda m: m.u0)
            n_join += sum(1 for a, b in zip(mods, mods[1:]) if abs(a.u1 - b.u0) < 0.5)
    rows.append(("Фурнитура", "Стяжка межсекционная", n_join * kc["ties_per_joint"], "шт",
                 f"{n_join} стыков соседних корпусов × {kc['ties_per_joint']}"))
    for key, (name, unit, note) in HW_NAMES.items():
        if hw[key]:
            rows.append(("Фурнитура", name, hw[key], unit, note))
    rows.append(("Фурнитура", "Заглушка конфирмата в цвет корпуса (светло-серая)", 10, "шт",
                 "видимые места крепежа (торцы закрыты панелями МДФ — по месту)"))
    return rows


def appliance_rows(k: Kitchen) -> list[tuple]:
    ap = k.cfg["appliances"]
    if k.cfg.get("share"):
        return _appliance_rows_order(k)
    return [
        ("Холодильник отдельностоящий", f"{ap['fridge']['w']}×{ap['fridge']['h']}×{ap['fridge']['d']}",
         f"Y 1200..1800, {ap['fridge']['wall_gap']} от стены; дверь навешена от угла (петли со стороны прохода)"),
        ("Духовой шкаф встраиваемый", f"{ap['oven']['w']}×{ap['oven']['h']}×{ap['oven']['d']}",
         "в Н4 под варкой; ниша 600 от полки до профиля Gola; нужна своя розетка 16 А (в ТЗ нет)"),
        ("Варочная панель индукционная", f"{ap['hob']['w']}×{ap['hob']['d']}, вырез {ap['hob']['cutout'][0]}×"
         f"{ap['hob']['cutout'][1]}", "центр X 1800; подключение 32 А / клеммы — по паспорту"),
        ("Посудомойка встраиваемая", f"{ap['dishwasher']['w']}", "Н5, полный фасад 598×730; до сифона мойки ~1,8 м — удлинитель слива или отдельный отвод"),
        ("Мойка врезная + смеситель + сифон", f"{ap['sink']['w']}×{ap['sink']['d']}", "центр X 900, 80 от переднего края"),
        ("Вытяжка встраиваемая", f"{ap['hood']['w']}", f"в В4, низ на 1600; воздуховод Ø{ap['hood']['duct']} ~0,8 м + "
         "колено + обратный клапан; розетка над шкафом (в ТЗ нет)"),
    ]


def _appliance_rows_order(k: Kitchen) -> list[tuple]:
    """Техника проекта по эскизу: размеры из конфига, место — из модели, что учесть — из раздела share.appliances."""
    ap, g = k.cfg["appliances"], k.geo
    notes = k.cfg["share"].get("appliances", {})
    mod = {x: k.module(k.appl[x].module).id for x in ("oven", "dw", "mw", "hood", "sink", "fridge") if x in k.appl}
    fr = ap["fridge"]
    hb = ap["hob"]
    mw = ap["microwave"]
    rows = [
        ("Холодильник отдельностоящий", f"{fr['w']}×{fr['h']}×{fr['d']}",
         f"справа от кухни, X {fmt(k.appl['fridge'].box.lo[0])}..{fmt(k.appl['fridge'].box.hi[0])}, {fr['wall_gap']} от "
         f"стены. " + notes.get("fridge", "")),
        ("Варочная панель газовая, 4 конфорки", f"{hb['w']}×{hb['d']}, вырез {hb['cutout'][0]}×{hb['cutout'][1]}",
         f"над {mod['oven']}, центр X {fmt((k.appl['hob'].box.lo[0] + k.appl['hob'].box.hi[0]) / 2)}. " +
         notes.get("hob", "")),
        ("Духовой шкаф встраиваемый", f"{ap['oven']['w']}×{ap['oven']['h']}×{ap['oven']['d']}",
         f"{mod['oven']}, ниша Z {fmt(g['oven_z'][0])}..{fmt(g['oven_z'][1])}. " + notes.get("oven", "")),
        ("Посудомойка встраиваемая 45", f"{ap['dishwasher']['w']}, ниша {fmt(g['dw_niche_h'])}",
         f"{mod['dw']}. " + notes.get("dw", "")),
        ("СВЧ встраиваемая 60 (для навесного шкафа)", f"рамка {mw['front_w']}×{mw['front_h']}",
         f"{mod['mw']}, ниша {'×'.join(fmt(x) for x in g['mw']['niche'])}. " + notes.get("mw", "")),
        ("Вытяжка встраиваемая телескопическая 60", f"{ap['hood']['w']}",
         f"{mod['hood']}, низ Z {fmt(k.appl['hood'].box.lo[2])}. " + notes.get("hood", "")),
        ("Мойка врезная + смеситель", f"{ap['sink']['w']}×{ap['sink']['d']}",
         f"{mod['sink']}, по центру дверей X {fmt((g['sink_box'].lo[0] + g['sink_box'].hi[0]) / 2)}, "
         f"{ap['sink'].get('from_front', 50)} от края столешницы. " + notes.get("sink", "")),
    ]
    return rows


def assumptions(k: Kitchen) -> list[tuple]:
    """(что, значение, почему) — решения, принятые без подтверждения (ждут сверки)."""
    if k.cfg.get("assumptions"):
        return [tuple(x) for x in k.cfg["assumptions"]]
    g = k.geo
    kc = k.shop["kitchen"]
    return [
        ("Дверь", "проём Y 2200..3000 (от угла B/D)", "с Y 100..900 нижние вдоль A перекрывают дверь; параметр room.door"),
        ("Высота корпуса нижних", "762 (цоколь 100 + 762 + столешница 38 = 900)", "720+100+38=858 ≠ 900 подоконника"),
        ("Верхние вдоль A", "2100 вместо 2400", "окно начинается с X 2200, 100 мм до откоса"),
        ("Высота верхних", "Z 1500..2400, корпус 900; шкаф вытяжки 1600..2400", "в ТЗ не задано; 700 над индукцией"),
        ("Глубина корпуса нижних", f"{g['D']:.0f} + фасад {g['tf']:.0f} = 578, свес столешницы 22",
         "600 по ТЗ со столешницей"),
        ("Н1", "корпус 1150 + доборная планка 50 (не 1200 одним корпусом)",
         "иначе дверь Н1 при открытии упирается в бок холодильника (холодильник глубже на 122 мм)"),
        ("В5", "корпус 550 + планка 50", "то же: дверь верхнего упирается в холодильник (он до 2000)"),
        ("Н4", "под духовкой съёмная фальш-панель 598×102 вместо ящика",
         "под полкой духовки 72 мм, ящику на металлических боковинах нужно ≥ 90"),
        ("Духовка", "ниша Z 204..804: верх духовки — по низу профиля Gola L", "профиль занимает 58 мм под столешницей"),
        ("Мойка", "передний край в 80 мм от края столешницы (центр X 900)", "позади фасада профиль Gola, чаше нужен зазор"),
        ("Торец X=3000", "торцевая панель МДФ 18 снаружи, ряд A с ней 3018, столешница до 3018", "модули стандартные 300"),
        ("Торцы верхних", "МДФ 18: у В4 снаружи (верхние A с панелью 2118, до откоса 82); над холодильником — возврат "
         "за планкой F2", "серая ЛДСП на видимом торце не смотрится; на холодильник панель выходить не может"),
        ("Фасады", f"МДФ 18, зазор {kc['facade_gap']} мм; нижние 730 (Z 100..830), верхние 918 (Z 1480..2398)",
         "верх нижних на 32 ниже столешницы под профиль; верхние на 20 ниже корпуса под LED"),
        ("Ящики Н6", "фасады 176 / 245 / 245, между ними профиль C (щель 32)", "сумма 730 по полю фасадов"),
        ("Угловой верхний В1", "Г-образный, складная дверь «гармошка» 267 + 247", "угол открывается целиком"),
        ("Задние стенки", "ХДФ 3 накладная; у мойки и духовки нет (трубы, вентиляция) — вместо неё планка жёсткости", ""),
        ("Царги", "нижние без крыши: задняя царга 100 (у варки 40), передняя на ребро за профилем", ""),
        ("Цоколь", f"ПВХ/алюминий 100, утоплен на {kc['plinth_setback']} от фасадов, опоры 95–130", ""),
        ("Розетка холодильника", "Y 1500 (центр холодильника), Z 300", "Y в ТЗ не задан"),
        ("Фартук", "стеновая панель 6 мм, Z 900..1500, над варкой до 1600; A до X 2200, B до Y 1200", ""),
        ("Цвета", "фасады — пример RAL 1015, корпус — пример Egger U708, столешница — пример Egger H3303",
         "подобрать по каталогам поставщиков"),
        ("Цеховые числа", "пропил 4, обрезка 10, лист 2800×2070, кромка 2/0,4", "shop/shop.yaml — допущения до сверки с цехом"),
    ]


def parts_rows(k: Kitchen, parts) -> list[tuple]:
    rows = []
    mats = k.shop["materials"]
    lids = {p.id for p, _ in k.lpanels}
    for p in parts:
        mods = sorted({pid.split("_")[0] for _, pid, _ in p.instances})
        lflag = " (Г-образная, вырез по месту/на ЧПУ)" if any(pid in lids for _, pid, _ in p.instances) else ""
        rows.append((p.no, p.name + lflag, ", ".join(mods), mats[p.material]["kind"] + f" {fmt(p.t)}", p.qty,
                     fmt(p.L), fmt(p.W), fmt(p.L_saw), fmt(p.W_saw), edge_str({e: p.edges[e] for e in EDGE_NAMES})))
    return rows


def compute(k: Kitchen):
    parts = detailing([k.product])
    results = []
    for m in sorted({p.material for p in parts}, key=lambda x: -k.shop["materials"][x]["thickness"]):
        results.append(nesting.nest(parts, k.shop, m))
    errs = []
    for r in results:
        errs += nesting.verify(r, parts, k.shop)
    return parts, results, errs


FAC_RU = {"door": "двери", "leaf": "створки «гармошки»", "drawer": "фасады ящиков", "dw": "фасад ПММ", "cargo": "фасад карго",
          "panel": "фальш-панель", "filler": "доборные планки", "corner": "угловые планки", "end": "торцевые панели",
          "side": "видимые боковины", "strip": "планки до потолка"}


def _mods_with(k: Kitchen, key: str) -> str:
    return ", ".join(m.id for m in k.modules if m.hw.get(key))


def _material_spec_push(k: Kitchen, parts, nest_results) -> list[tuple]:
    """Спецификация варианта без ручек (открывание нажатием): те же разделы, тексты — из модели."""
    sh = k.shop
    mats = sh["materials"]
    kc = sh["kitchen"]
    pk = kc["push"]
    cm, bm, fm = (k.cfg["materials"][x] for x in ("carcass", "back", "facade"))
    rows = []
    by_mat = {r.material: r for r in nest_results}
    for key in (cm, bm):
        area = sum(p.L * p.W * p.qty for p in parts if p.material == key) / 1e6
        r = by_mat.get(key)
        n = len(r.sheets) if r else 0
        util = ", ".join(f"{s.util * 100:.0f}%" for s in r.sheets) if r else ""
        L, W = mats[key]["sheet"]
        rows.append(("Плита", mats[key]["name"], round(area, 2), "м² деталей",
                     f"листов {L}×{W}: {n} (заполнение {util}); раскрой с пропилом {sh['cutting']['kerf']} и обрезкой "
                     f"{sh['cutting']['trim']}"))
        rows.append(("Плита", f"  листов {mats[key]['kind']} {L}×{W}", n, "лист", "по раскрою"))
    frs = facade_rows(k)
    area = sum(r["area"] for r in frs)
    kinds = Counter(r["kind"] for r in frs)
    g = k.geo
    pl = g["plinth"]
    plen = (pl["A"] + pl["B"]) / 1000
    ph = g["zp"] - 2
    rows.append(("Фасады", mats[fm]["name"], round(area + plen * ph / 1000, 2), "м²",
                 f"{len(frs)} шт: " + ", ".join(f"{FAC_RU.get(kk, kk)} {v}" for kk, v in kinds.items()) +
                 f"; + цоколь {plen:.2f} м × {ph:.0f}. Гладкие, без фрезеровки и ручек, покраска по кругу; видимые "
                 "боковины и торцы — с двух сторон; размеры — в таблице фасадов"))
    wt = worktop_info(k)
    rows.append(("Столешница", mats[k.cfg["materials"]["worktop"]]["name"], len(wt["pieces"]), "кусок",
                 "; ".join(f"{n} {fmt(L)}×{fmt(W)}" for n, L, W in wt["pieces"]) + f"; {wt['blanks']}"))
    ks = kc["worktop"]
    rows.append(("Столешница", "Соединение кусков в углу: «евро-запил» на ЧПУ + стяжки (на однотонной столешнице планка "
                 "заметна) или планка соединительная", wt["joints"], "стык", "стык A и B в углу (Y=600)"))
    rows.append(("Столешница", "Кромка торцевая в цвет столешницы (ABS 2 мм) или планка торцевая", 2, "торца",
                 f"открытые торцы: X={fmt(g['x_top'])} (у холодильника) и Y={fmt(g['worktop_B_end'])} (над торцевой "
                 "панелью ряда B)"))
    rows.append(("Столешница", ks["wall_strip"], round((g["apron"]["A"] + g["apron"]["B"]) / 1000, 2), "м",
                 "стык столешницы со стеной/фартуком; + уголок внутренний 1, заглушки 2"))
    hp = k.cfg["appliances"]["hob"]
    rows.append(("Столешница", f"Вырез под мойку (по шаблону мойки) и под газовую панель "
                 f"{hp['cutout'][0]}×{hp['cutout'][1]} (по паспорту), торцы вырезов — герметик", 2, "выреза",
                 "делается в цеху (ЧПУ) или на месте"))
    rows.append(("Столешница", "Герметик силиконовый санитарный / для торцов", 2, "туба", "вырезы, стык, примыкания"))
    ap = k.kind("apron")
    rows.append(("Фартук", mats[k.cfg["materials"]["apron"]]["name"],
                 round(sum(max(s.box.size[0], s.box.size[1]) * s.box.size[2] for s in ap) / 1e6, 2), "м²",
                 "; ".join(f"{s.name} {fmt(max(s.box.size[0], s.box.size[1]))}×{fmt(s.box.size[2])}" for s in ap) +
                 "; вырезы под розетки — по месту"))
    et = edge_totals(parts, sh)
    for e in et:
        rows.append(("Кромка", f"Кромка ПВХ {fmt(e['thickness'])}×{sh['edges']['tape_width'].get(str(int(e['width'])), '')} "
                     f"мм ({e['material'].split('(')[0].strip()})", round(e["m_allow"], 2), "м",
                     f"чистыми {e['m']:.2f} м, отрезков {e['pieces']}, запас {sh['edges']['piece_allowance']} мм на отрезок"))
    rows.append(("Цоколь", f"Цоколь МДФ 18 в цвет фасадов, высота {ph:.0f} (в списке фасадов)", round(plen, 2), "м",
                 f"ряд A {fmt(pl['A'])} + ряд B {fmt(pl['B'])}; у ПММ подрезать по паспорту ПММ"))
    hw = Counter()
    for m in k.modules:
        hw.update(m.hw)
    hw.update(k.hw)
    rows.append(("Цоколь", "Клипса крепления цоколя к опоре", hw["plinth_clip"], "шт", "передние опоры"))
    rows.append(("Цоколь", "Уплотнитель цоколя к полу (прозрачный)", round(plen, 2), "м", ""))
    if g.get("ceiling_strip"):
        lc = sum(max(s.box.size[0], s.box.size[1]) for s in k.solids if s.id.startswith("ceiling_strip"))
        rows.append(("Планка до потолка", f"МДФ в цвет фасадов, высота {g['ceiling_strip']:.0f} (в списке фасадов)",
                     round(lc / 1000, 2), "м", "крепление уголками к крышам шкафов; подгонка по потолку на месте"))
    led = g["led"]
    lled = sum(led.values()) / 1000
    lk = kc["led"]
    watt = lled * lk["watt_per_m"]
    psu = max(15, math.ceil(watt * lk["psu_margin"] / 15) * 15)
    nseg = sum(len(v) for v in g.get("led_segs", {}).values())
    rows.append(("Подсветка", lk["name_profile"], round(lled, 2), "м",
                 "; ".join(f"ряд {r} " + " + ".join(f"{fmt(b - a)}" for a, b in v) for r, v in g["led_segs"].items()) +
                 f" (под вытяжкой — свой свет вытяжки); хлыстов {lk['profile_bar'] / 1000:g} м: "
                 f"{math.ceil(lled * 1000 / lk['profile_bar'])}; заглушки {2 * nseg}"))
    rows.append(("Подсветка", lk["name_strip"], round(lled, 2), "м", f"катушка {lk['strip_reel'] / 1000:g} м: "
                 f"{math.ceil(lled * 1000 / lk['strip_reel'])} (нужно {lled:.2f} м, ~{watt:.0f} Вт)"))
    rows.append(("Подсветка", f"Блок питания 24 В {psu} Вт (запас ×{lk['psu_margin']})", 1, "шт",
                 "в шкафу вытяжки, розетка там же"))
    rows.append(("Подсветка", "Выключатель бесконтактный (взмах руки) в профиль или клавишный", 1, "шт", ""))
    rows.append(("Подсветка", "Провод 2×0,75 + коннекторы", 6, "м", "между участками через шкафы, по крышам"))
    hz = Counter((f.h, f.hinges) for m in k.modules for f in m.facades if f.hinges)
    brk = ", ".join(f"{q} дв. {fmt(h)} мм × {n}" for (h, n), q in sorted(hz.items()))
    rows.append(("Фурнитура", pk["hinge_name"], hw["hinge"], "шт", f"{brk} (по высоте двери, таблица петель)"))
    hmax = max((f.h for m in k.modules for f in m.facades if f.hinges), default=0)
    rows.append(("Фурнитура", pk["door_name"], hw["tipon_door"], "шт",
                 f"по 1 на дверь (самая высокая дверь {fmt(hmax)} мм — короткий TIP-ON до ~1300); ставится у края "
                 "двери против петель"))
    if hw["drawer"]:
        rows.append(("Фурнитура", kc["drawer"]["system"], hw["drawer"], "компл",
                     f"{_mods_with(k, 'drawer')}: дно и задняя стенка ящиков из ЛДСП — входят в листы ЛДСП"))
        rows.append(("Фурнитура", pk["drawer_name"], hw["tipon_drawer"], "компл", "на каждый ящик"))
    rows.append(("Фурнитура", "Шина монтажная для навесов", round((k.runs["upper_a"] + k.runs["upper_b"] -
                 min((m.u0 for m in k.modules if m.run == "B" and m.level == "верхний"), default=0)) / 1000, 2), "м",
                 "вдоль A и B, дюбель 8×60 через ~300 мм"))
    rows.append(("Фурнитура", "Дюбель 8×60 + шуруп (шина, уголки, планки)", 30, "шт", "оценка"))
    n_join = 0
    for run in ("A", "B"):
        for lvl in ("нижний", "верхний"):
            mods = sorted((m for m in k.modules if m.run == run and m.level == lvl and m.carcass), key=lambda m: m.u0)
            n_join += sum(1 for a, b in zip(mods, mods[1:]) if abs(a.u1 - b.u0) < 0.5)
    rows.append(("Фурнитура", "Стяжка межсекционная", n_join * kc["ties_per_joint"], "шт",
                 f"{n_join} стыков соседних корпусов × {kc['ties_per_joint']}"))
    names = {**HW_NAMES, "sink_tray": ("Поддон алюминиевый в шкаф под мойку", "шт", "защита дна от протечек"),
             "dw_kit": ("Комплект монтажа фасада ПММ (идёт с ПММ) + планка-пароотвод под столешницу", "компл", ""),
             "wall_bracket": ("Уголок крепления к стене", "шт", "")}
    if k.drill_stats:                        # присадка посчитана — конфирматы точным числом
        hw["confirmat"] = k.drill_stats["confirmat"]
        names["confirmat"] = ("Конфирмат 7×50", "шт", "по присадке (точно)")
    for key, (name, unit, note) in names.items():
        if hw[key]:
            mods = "" if key == "confirmat" and k.drill_stats else _mods_with(k, key)
            rows.append(("Фурнитура", name, hw[key], unit, "; ".join(x for x in (note, mods) if x)))
    rows.append(("Фурнитура", "Заглушка конфирмата в цвет корпуса", 10, "шт", "видимые места крепежа — по месту"))
    gas = k.cfg.get("gas", {})
    rows.append(("Газ (делает газовая служба)", "Кран шаровой газовый перед варочной + гибкая подводка с сертификатом",
                 1, "компл", f"кран в {gas.get('valve_module', 'шкафу рядом с варкой')}, отверстие Ø40 в боковине; длина "
                 f"подводки ≤ {gas.get('hose_max', 1500) / 1000:.1f} м (сверить с газовой службой)"))
    return rows
