"""Один файл «поделиться»: Кухня-проект.pdf (A4 альбомная) для цеха, клиента, коллег — открывается на телефоне.

Собирается из той же модели: HTML-страницы (рендеры JPEG ~1600 px, чертежи векторные SVG, таблицы) печатаются
headless Chrome в PDF (только программный рендер, видеокарту не трогаем). Внутреннего в тексте быть не должно —
проверяется списком запрещённых слов.
"""
from __future__ import annotations

import base64
import html
import io
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter

from PIL import Image

from ..parts import fmt
from . import drawings, spec
from .layout import TYPE_RU, Kitchen

# внутренние слова, которым не место во внешнем PDF (пути, имена файлов, служебные пометки)
FORBIDDEN = ["/home", "~/", "mebel-cnc", "коммит", "допущ", "shop.yaml", ".yaml", "папк", "scratch", "gpu"]

LEGEND = [
    ("Н1", "нижний угловой: глухая часть уходит в угол за ряд у окна, дверь открывается от угла"),
    ("Н2", "нижний под мойку"), ("Н3", "нижний 300 — выдвижная бутылочница (карго)"),
    ("Н4", "нижний под духовку, сверху варочная панель"), ("Н5", "встроенная посудомойка, полный фасад"),
    ("Н6", "нижний 300 с тремя ящиками"), ("ХЛ", "холодильник отдельностоящий"),
    ("F1, F2", "доборные планки 50 мм у холодильника (внизу и вверху): двери соседей не цепляют холодильник"),
    ("В1", "верхний угловой Г-образный, дверь складывается «гармошкой»"),
    ("В2", "верхний над мойкой, с сушилкой для посуды"), ("В3", "верхний 300 с полками"),
    ("В4", "верхний под встраиваемую вытяжку (ниже соседних)"), ("В5", "верхний над угловым Н1"),
    ("Т", "торцевые панели МДФ в цвет фасадов на открытых торцах"),
]
DECISIONS = [
    "Дверь — проём 800 у дальнего угла стены B (от угла с окном 2200–3000 мм): иначе нижние шкафы закрывают дверь.",
    "Столешница на высоте 900, вровень с подоконником: цоколь 100 + корпус 762 + столешница 38.",
    "Верхние шкафы вдоль стены с окном — 2100 мм (не 2400): дальше начинается окно; до откоса остаётся 82 мм "
    "с торцевой панелью.",
    "Верхние шкафы: низ 1500 (600 над столешницей), верх 2400; шкаф вытяжки с 1600 — 700 мм над варочной.",
    "У холодильника доборные планки 50 мм внизу и вверху: холодильник глубже шкафов, без планок двери упираются в него.",
    "Под духовкой — съёмная панель вместо ящика: ящик по высоте не помещается (остаётся 72 мм).",
]
CLARIFY = [
    "Розетка варочной панели (высота 300) попадает за корпус духовки — вилка не влезет. Перенести ниже (≈150, за "
    "съёмную панель) или в соседний шкаф.",
    "Есть ли батарея под окном? Под окном стоят посудомойка и ящики.",
    "Модели техники: посудомойка с дверью не выше 802 мм от пола (над ней профиль-ручка), духовка в нишу 600, "
    "вытяжка встраиваемая 600, холодильник 600 × 650.",
    "Розетки: в задании только варка и холодильник — нужны ещё духовка, посудомойка, вытяжка, подсветка и 2–3 над "
    "столешницей.",
    "Замеры на месте: длины стен и углы (90° или нет), выступает ли подоконник в комнату, точное положение воды, "
    "канализации и вентиляции, сторона открывания двери, ровность пола и высота потолка.",
    "Слив посудомойки — ~1,8 м до сифона: нужен удлинитель или отдельный отвод.",
]
CAPTIONS = {
    "plan": "План — вид сверху. Стена A с окном вверху листа, стена B с дверью слева. Сплошное — нижние шкафы, "
            "столешница и техника; фиолетовый пунктир — верхние шкафы. Размеры в мм, цветные точки — вода, розетки, "
            "вентиляция.",
    "razvertka_A": "Развёртка стены A — стена с окном, вид из комнаты. Клетчатое слева — ряд вдоль стены B в разрезе. "
                   "Слева — высоты от пола, снизу и сверху — ширины шкафов; пунктирный треугольник на двери — "
                   "вершиной к петлям.",
    "razvertka_B": "Развёртка стены B — стена с дверью, вид из комнаты. Клетчатое справа — ряд вдоль окна в разрезе. "
                   "Слева — высоты от пола, снизу — ширины; красная точка — розетка холодильника за ним.",
}


def _clean(t: str) -> str:
    t = re.sub(r"\s*—\s*карта раскроя в папке \w+", "", str(t))
    t = re.sub(r"\s*\(таблица петель в shop\.yaml\)", "", t)
    t = t.replace("(оценка: по 2–3 на стык)", "(по 2–3 на стык)").replace("в ТЗ нет", "в задании нет")
    t = t.replace("размеры — лист «Фасады»", "размеры — в таблице шкафов").replace("из ЛДСП — в деталях",
                                                                                   "из ЛДСП — входят в листы ЛДСП")
    return t


def _jpeg(path, width=1600, q=84) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _svg(path) -> str:
    with open(path, "rb") as f:
        return "data:image/svg+xml;base64," + base64.b64encode(f.read()).decode()


def _table(header, rows, cls=""):
    th = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    tb = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table>'


def module_rows(k: Kitchen):
    rows = []
    order = {"B": 0, "A": 1, "угол": 2}
    for m in sorted(k.modules, key=lambda m: (m.level != "нижний", order.get(m.run, 3), m.u0)):
        name = TYPE_RU.get(m.type, {"corner_filler": "планка угловая", "end_panel": "панель торцевая"}.get(m.type,
                                                                                                         m.type))
        c = Counter((f.name, f.w, f.h, f.hinges) for f in m.facades)
        fac = "; ".join(f"{n[0].lower() + n[1:]} {fmt(w)}×{fmt(h)} × {q}" + (f" ({hc} петли)" if hc and "на створке" not in n
                                                                  else "") for (n, w, h, hc), q in c.items())
        car = f"{fmt(m.carcass[0])}×{fmt(m.carcass[1])}×{fmt(m.carcass[2])}" if m.carcass else "—"
        axis = "X" if m.run == "A" else "Y"
        if m.type == "corner_l":
            where = "угол, по 600 на обе стены"
        elif m.type == "corner_filler":
            where = "угол"
        elif m.type == "ceiling_strip":
            where = "над верхними"
        else:
            where = f"{axis} {fmt(m.u0)}–{fmt(m.u1)}"
        rows.append((m.id, name, where, car, fac or "—"))
    return rows


CSS = """
@page { size: A4 landscape; margin: 8mm 9mm; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #fff; }
body { font-family: "DejaVu Sans", "Noto Sans", Arial, sans-serif; color: #16233b; font-size: 9.5pt; line-height: 1.35; }
.page { height: 193mm; break-after: page; display: flex; flex-direction: column; overflow: hidden; }
.flow { break-before: page; }
h1 { font-size: 24pt; margin: 0 0 2mm; font-weight: 700; letter-spacing: -0.2pt; }
h2 { font-size: 14pt; margin: 0 0 2.5mm; font-weight: 700; }
.sub { color: #475569; font-size: 10.5pt; margin-bottom: 3mm; }
.facts { display: flex; column-gap: 6mm; row-gap: 0.8mm; flex-wrap: wrap; margin: 0 0 1.6mm; font-size: 9.5pt; }
.facts b { font-weight: 700; }
.imgbox { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
.imgbox img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
.cap { font-size: 9.5pt; color: #334155; margin-top: 2mm; border-top: 0.3mm solid #cbd5e1; padding-top: 1.5mm; }
.planwrap { flex: 1; min-height: 0; display: flex; gap: 4mm; }
.planwrap .imgbox { flex: 1; }
.legend { width: 72mm; font-size: 8.3pt; line-height: 1.3; }
.legend dt { font-weight: 700; float: left; width: 12mm; }
.legend dd { margin: 0 0 1.4mm 12mm; }
.dots span { display: inline-block; width: 2.6mm; height: 2.6mm; border-radius: 50%; margin-right: 1.2mm;
  vertical-align: -0.3mm; }
table { width: 100%; border-collapse: collapse; font-size: 8.4pt; }
th { background: #16233b; color: #fff; text-align: left; font-weight: 700; padding: 1.4mm 1.8mm; }
td { padding: 1.2mm 1.8mm; border-bottom: 0.25mm solid #d6dbe3; vertical-align: top; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
td:first-child { white-space: nowrap; font-weight: 700; }
.num td:nth-child(3), .num td:nth-child(4) { white-space: nowrap; }
.cols { display: flex; gap: 8mm; }
.cols > div { flex: 1; }
ol, ul { margin: 0; padding-left: 5mm; }
li { margin-bottom: 1.6mm; }
.note { color: #475569; font-size: 8.5pt; margin-top: 2mm; }
.foot { margin-top: auto; color: #64748b; font-size: 8pt; }
"""


def build_html(k: Kitchen, parts, results, out_dir: str, tmp: str) -> str:
    rnd = os.path.join(out_dir, "renders")
    imgs = {v: _jpeg(os.path.join(rnd, f"render_{v}.png")) for v in ("angle", "front", "top")}
    svgs = {n: _svg(p) for n, p in drawings.write_svg(k, os.path.join(tmp, "svg")).items()}
    room = k.cfg["room"]
    fr = spec.facade_rows(k)
    n_carc = sum(1 for m in k.modules if m.carcass)
    ldsp = next((r for r in results if r.material == k.cfg["materials"]["carcass"]), None)
    mats = k.shop["materials"]
    P = []
    P.append(f"""<section class="page">
<h1>Кухня Г-образная — проект</h1>
<div class="sub">27.10.2026 · помещение {room['a']} × {room['b']} × {room['height']} мм</div>
<div class="facts"><span><b>Нижние:</b> вдоль стены с окном 3000, вдоль стены с дверью 1800 (с холодильником)</span>
<span><b>Верхние:</b> 2100 и 1200</span><span><b>Столешница:</b> на 900, вровень с подоконником</span></div>
<div class="facts"><span><b>Фасады</b> — МДФ матовый бежевый</span><span><b>Корпус</b> — ЛДСП светло-серая</span>
<span><b>Столешница</b> — под натуральный дуб</span><span><b>Ручки</b> — скрытый профиль</span>
<span><b>Подсветка</b> под верхними шкафами</span><span><b>Петли и ящики</b> — с доводчиками</span></div>
<div class="imgbox"><img src="{imgs['angle']}" alt="вид под углом"></div>
<div class="cap">Вид под углом из дальнего угла комнаты; две ближние стены срезаны, чтобы было видно кухню.</div>
</section>""")
    P.append(f"""<section class="page"><h2>Вид спереди — на стену с окном</h2>
<div class="imgbox"><img src="{imgs['front']}" alt="вид спереди"></div>
<div class="cap">Слева угол и холодильник, справа окно. Под окном — посудомойка и ящики, столешница вровень с подоконником.</div>
</section>""")
    P.append(f"""<section class="page"><h2>Общий вид сверху</h2>
<div class="imgbox"><img src="{imgs['top']}" alt="вид сверху"></div>
<div class="cap">Вид сверху под углом из дальнего угла, стены срезаны на высоте 1500: видно дверной проём, окно с
подоконником, холодильник и шкафы.</div></section>""")
    leg = "".join(f"<dt>{html.escape(a)}</dt><dd>{html.escape(b)}</dd>" for a, b in LEGEND)
    P.append(f"""<section class="page"><h2>План с размерами</h2>
<div class="planwrap"><div class="imgbox"><img src="{svgs['plan']}" alt="план"></div>
<div class="legend"><b>Обозначения</b><dl>{leg}</dl>
<div class="dots"><span style="background:#2563eb"></span>вода и канализация<br>
<span style="background:#dc2626"></span>розетки<br><span style="background:#374151"></span>вывод вентиляции</div>
<p class="note">Стена A — с окном, стена B — с дверью. Размеры в мм от угла между ними.</p></div></div>
<div class="cap">{html.escape(CAPTIONS['plan'])}</div></section>""")
    for key, title in (("razvertka_A", "Развёртка стены A (с окном)"), ("razvertka_B", "Развёртка стены B (с дверью)")):
        P.append(f"""<section class="page"><h2>{title}</h2>
<div class="imgbox"><img src="{svgs[key]}" alt="{title}"></div>
<div class="cap">{html.escape(CAPTIONS[key])}</div></section>""")
    P.append(f"""<section class="flow"><h2>Шкафы: корпуса и фасады</h2>
{_table(["№", "Что это", "Где, мм", "Корпус Ш×В×Г, мм", "Фасады Ш×В, мм × шт"], module_rows(k), "num")}
<p class="note">Всего {n_carc} корпусов, {len(fr)} фасадных деталей МДФ ({sum(r['area'] for r in fr):.2f} м²).
Нижние фасады 730 (от 100 до 830 от пола), верхние 918, шкаф вытяжки 818; зазор между фасадами 2 мм.
Глубина нижних 560 + фасад 18, столешница 600; верхних 332 + фасад 18. X — вдоль стены с окном от угла, Y — вдоль
стены с дверью от угла.</p></section>""")
    ms = [(a, _clean(b), c, d, _clean(e)) for a, b, c, d, e in spec.material_spec(k, parts, results)]
    P.append(f"""<section class="flow"><h2>Спецификация материалов и фурнитуры</h2>
{_table(["Раздел", "Позиция", "Кол-во", "Ед.", "Примечание"], ms)}
<p class="note">Цены не указаны. Количество листов ЛДСП ({len(ldsp.sheets) if ldsp else '—'} шт, лист
{mats[k.cfg['materials']['carcass']]['sheet'][0]}×{mats[k.cfg['materials']['carcass']]['sheet'][1]}) — по
предварительному раскрою. Марки и цвета — примеры, подобрать по каталогам поставщиков.</p></section>""")
    dec = "".join(f"<li>{html.escape(t)}</li>" for t in DECISIONS)
    cla = "".join(f"<li>{html.escape(t)}</li>" for t in CLARIFY)
    P.append(f"""<section class="flow"><h2>Техника (покупается отдельно)</h2>
{_table(["Что", "Размер, мм", "Где и что учесть"], [tuple(_clean(c) for c in r) for r in spec.appliance_rows(k)])}
<div class="cols" style="margin-top:6mm"><div><h2>Принятые решения по заданию</h2><ol>{dec}</ol></div>
<div><h2>Уточнить на объекте</h2><ul>{cla}</ul></div></div></section>""")
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Кухня Г-образная — проект</title>
<style>{CSS}</style></head><body>{''.join(P)}</body></html>"""
    low = re.sub(r"data:[^\"]+", "", doc).lower()
    bad = [w for w in FORBIDDEN if w in low]
    if bad:
        raise RuntimeError(f"во внешнем файле внутренние слова: {bad}")
    return doc


def build_pdf(k: Kitchen, parts, results, out_dir: str, safe_env: dict) -> str:
    dst = os.path.join(out_dir, "поделиться")
    os.makedirs(dst, exist_ok=True)
    pdf = os.path.join(dst, "Кухня-проект.pdf")
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "kuhnya.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(build_html(k, parts, results, out_dir, tmp))
        prof = os.path.join(tmp, "profile")
        tmp_pdf = os.path.join(tmp, "out.pdf")
        subprocess.run(["google-chrome", "--headless=new", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={prof}", "--disable-gpu", "--disable-vulkan", "--disable-features=Vulkan",
                        "--use-angle=swiftshader", "--host-resolver-rules=MAP * ~NOTFOUND",
                        "--no-pdf-header-footer", "--virtual-time-budget=8000", f"--print-to-pdf={tmp_pdf}",
                        "file://" + page], env={**os.environ, **safe_env}, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        shutil.move(tmp_pdf, pdf)
    return pdf
