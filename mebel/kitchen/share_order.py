"""Один файл наружу для проекта по эскизу (фото или рендер с размерами): <share.file> (A4 альбомная) — клиенту,
в цех, фасадному цеху.

Страницы: эскиз рядом с нашим видом с того же места; вид под углом и спереди; план; развёртки; таблица
шкафов (корпуса и фасады); список фасадов; деталировка ЛДСП/ХДФ с кромкой; спецификация и техника; ❗ критично;
отличия от эскиза; вопросы на замер. Всё из той же модели. Тексты решений и вопросов — из раздела share конфига.
Картинки: рендеры Blender (renders/render_*.png), а пока их нет — быстрые снимки 3D (renders/preview_*.png).
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
from .layout import Kitchen
from .share import CSS, FORBIDDEN, _clean, _jpeg, _svg, _table, module_rows

ORDER_CSS = CSS + """
.hero { width: 100%; height: 128mm; object-fit: cover; display: block; border-radius: 1.2mm; }
.herorow { display: flex; gap: 5mm; margin-top: 3mm; height: 52mm; }
.herorow img { height: 52mm; width: auto; display: block; border-radius: 1mm; }
.herorow .txt { flex: 1; font-size: 8.3pt; color: #334155; display: flex; flex-direction: column; gap: 1.2mm; }
.herorow .txt b { color: #16233b; }
h1.small { font-size: 17pt; margin: 0 0 2mm; }
.fullimg { flex: 1; min-height: 0; display: flex; align-items: flex-start; justify-content: center; }
.fullimg img { width: 100%; max-height: 100%; object-fit: contain; display: block; border-radius: 1.2mm; }
.cap1 { font-size: 9pt; color: #334155; margin-top: 1.5mm; }
.pair { flex: 1; min-height: 0; display: flex; gap: 4mm; }
.pair figure { flex: 1; margin: 0; display: flex; flex-direction: column; min-width: 0; }
.pair figure .imgbox { flex: 1; }
.pair figcaption { font-size: 9pt; color: #334155; margin-top: 1.5mm; text-align: center; font-weight: 700; }
.crit { border-left: 2.2mm solid #dc2626; padding: 1.5mm 3mm; background: #fef2f2; margin-bottom: 2.5mm;
  break-inside: avoid; }
.crit b { color: #b91c1c; }
.small table { font-size: 7.6pt; }
.legend { width: 80mm; }
.legend dt { width: 17mm; }
.legend dd { margin-left: 17mm; }
table.tight { font-size: 7.8pt; }
table.tight td, table.tight th { padding: 0.75mm 1.6mm; }
ol { padding-left: 7mm; }
.small td, .small th { padding: 0.55mm 1.4mm; }
.dots2 { columns: 2; font-size: 8.2pt; margin-top: 2mm; }
.dots2 div { break-inside: avoid; margin-bottom: 0.8mm; }
.dots2 span { display: inline-block; width: 3.4mm; height: 3.4mm; border-radius: 50%; color: #fff; font-size: 6.5pt;
  text-align: center; line-height: 3.4mm; margin-right: 1.2mm; font-weight: 700; }
"""


def _img(out_dir: str, view: str):
    for name in (f"render_{view}.png", f"preview_{view}.png"):
        p = os.path.join(out_dir, "renders", name)
        if os.path.exists(p):
            return p
    return None


def _trimmed(path: str, width=1800, q=86) -> str:
    """Картинка для PDF: прозрачное — на белый, пустые поля по краям (почти однотонные) — обрезать."""
    import numpy as np
    im = Image.open(path)
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im = im.convert("RGB")
    a = np.asarray(im).astype(int)
    edge = a[0, 0]
    diff = np.abs(a - edge).sum(axis=2) > 24
    rows, cols = np.where(diff.any(axis=1))[0], np.where(diff.any(axis=0))[0]
    if len(rows) and len(cols):
        pad = 6
        box = (max(cols[0] - pad, 0), max(rows[0] - pad, 0), min(cols[-1] + pad + 1, im.width),
               min(rows[-1] + pad + 1, im.height))
        if (box[2] - box[0]) * (box[3] - box[1]) < 0.97 * im.width * im.height:
            im = im.crop(box)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def hinge_side_front(run: str, hinge: str) -> str:
    """Сторона петель, если смотреть на дверь спереди: ряд A — X растёт вправо, ряд B — Y растёт влево."""
    lo = hinge == "corner"
    return ("слева" if lo else "справа") if run == "A" else ("справа" if lo else "слева")


def _num_key(mid: str):
    m = re.match(r"([^\d]+)(\d*)", mid)
    pre, n = m.group(1), int(m.group(2) or 0)
    return ({"Н": 0, "ХЛ": 1, "У": 2, "Т": 3, "В": 4, "П": 5}.get(pre, 6), n)


def order_module_rows(k: Kitchen):
    rows = module_rows(k)
    return sorted(rows, key=lambda r: _num_key(r[0]))


def facade_order_rows(k: Kitchen):
    """Список фасадов для фасадного цеха: одинаковые детали — одной строкой, модули через запятую."""
    groups, order = {}, []
    for m in k.modules:
        for f in m.facades:
            side = hinge_side_front(m.run, f.hinge) if f.hinge else ""
            hz = f.solid.meta.get("hinges_z")
            axes = ", ".join(fmt(z - f.solid.box.lo[2]) for z in hz) if hz else ""
            key = (f.name, f.w, f.h, side, f.hinges, axes)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(m.id)
    rows = []
    order.sort(key=lambda kk: _num_key(groups[kk][0]))
    for key in order:
        name, w, h, side, hn, axes = key
        mods = groups[key]
        rows.append((", ".join(dict.fromkeys(mods)), name, fmt(w), fmt(h), len(mods),
                     f"{hn} ({side}){': ' + axes if axes else ''}" if hn else "—"))
    return rows


def build_html(k: Kitchen, parts, results, findings, out_dir: str, tmp: str, src_photo: str) -> str:
    sh = k.cfg["share"]
    svgs = {n: _svg(p) for n, p in drawings.write_svg(k, os.path.join(tmp, "svg")).items()}
    room = k.cfg["room"]
    g = k.geo
    P = []
    photo = _jpeg(src_photo, 900)
    ours = _img(out_dir, "photo")
    facts = "".join(f"<span>{html.escape(t)}</span>" for t in sh["facts"])
    P.append(f"""<section class="page">
<h1 class="small">{html.escape(sh['title'])}</h1>
<img class="hero" src="{_trimmed(ours) if ours else ''}" alt="проект">
<div class="herorow"><img src="{photo}" alt="эскиз">
<div class="txt"><div><b>Слева — эскиз</b> (фото или рендер с размерами); <b>сверху — наш проект с того
же места</b>, построенный из модели, по которой режем детали.</div>
<div class="facts" style="margin:0">{facts}</div>
<div>{html.escape(sh['photo_caption'])}</div>
<div style="color:#64748b">{html.escape(sh['date'])} · потолок {room['height']} мм</div></div></div></section>""")
    for view, title, cap in (("angle", "От двери на кухню", sh["views_caption"]),
                             ("front", "Спереди, на длинную стену", sh["views_caption"]),
                             ("top", "Сверху: план (верхние шкафы и стены выше 1,5 м убраны)",
                              "Вид сверху без верхних шкафов: столешница, мойка, газовая панель, холодильник, пол.")):
        im = _img(out_dir, view)
        if not im:
            continue
        P.append(f"""<section class="page"><h2>{title}</h2>
<div class="fullimg"><img src="{_trimmed(im)}" alt="{title}"></div>
<div class="cap1">{html.escape(cap)}</div></section>""")
    leg = "".join(f"<dt>{html.escape(a_)}</dt><dd>{html.escape(b_)}</dd>" for a_, b_ in sh["legend"])
    pts = "".join(f'<div><span style="background:{c}">{i}</span>{html.escape(nm)} — {html.escape(pos)}</div>'
                  for i, nm, pos, c in drawings.points_legend(k))
    P.append(f"""<section class="page"><h2>План с размерами</h2>
<div class="planwrap"><div class="imgbox"><img src="{svgs['plan']}" alt="план"></div>
<div class="legend"><b>Обозначения</b><dl>{leg}</dl>
<p class="note">Стена A — длинная (с холодильником), стена B — левая. X — вдоль A от угла, Y — вдоль B от угла.</p></div>
</div><div class="dots2">{pts}</div>
<div class="cap">План, вид сверху: сплошное — нижние, столешница, техника; пунктир — верхние. Точки воды, газа, розеток
и вентиляции на эскизе не даны — расставлены по смыслу, место сверить с электриком и газовой службой.</div></section>""")
    for key, title, cap in (("razvertka_A", "Развёртка стены A (длинная)", sh["cap_A"]),
                            ("razvertka_B", "Развёртка стены B (левая)", sh["cap_B"])):
        P.append(f"""<section class="page"><h2>{title}</h2>
<div class="imgbox"><img src="{svgs[key]}" alt="{title}"></div>
<div class="cap">{html.escape(cap)}</div></section>""")
    fr = spec.facade_rows(k)
    n_carc = sum(1 for m in k.modules if m.carcass)
    P.append(f"""<section class="flow"><h2>Шкафы: корпуса и фасады</h2>
{_table(["№", "Что это", "Где, мм", "Корпус Ш×В×Г, мм", "Фасады Ш×В, мм × шт"], order_module_rows(k), "num tight")}
<p class="note">{n_carc} корпусов, {len(fr)} деталей МДФ ({sum(r['area'] for r in fr):.2f} м²). {html.escape(sh['modules_note'])}</p>
</section>""")
    P.append(f"""<section class="flow"><h2>Фасады МДФ — список для фасадного цеха</h2>
{_table(["Модуль", "Деталь", "Ширина", "Высота", "Шт", "Петли (вид спереди): оси от низа, мм"], facade_order_rows(k), "num tight")}
<p class="note">{html.escape(sh['facades_note'])} Плюс цоколь МДФ в цвет фасадов: {fmt(g['plinth']['A'] + g['plinth']['B'])} мм
длины, высота {fmt(g['zp'] - 2)}.</p></section>""")
    pr = spec.parts_rows(k, parts)
    P.append(f"""<section class="flow small"><h2>Деталировка корпусов (ЛДСП 16, ХДФ 3) с кромкой</h2>
<p class="note" style="margin:0 0 2mm">Длина — вдоль длинной стороны. Чистовой размер — готовая деталь с кромкой, пильный —
до кромления (вычтена кромка 2 мм). Кромка: Д1, Д2 — длинные стороны, Ш1, Ш2 — короткие; 2 — ПВХ 2 мм, 0,4 — ПВХ 0,4 мм,
— без кромки. Левые и правые боковины — разные детали (зеркальная сверловка). Сверловка — в файлах деталей для станка.</p>
{_table(["№", "Деталь", "Модули", "Материал", "Шт", "Длина", "Ширина", "Пил. длина", "Пил. ширина", "Кромка"], pr, "num")}
</section>""")
    ms = [(a_, _clean(b_), c, d, _clean(e)) for a_, b_, c, d, e in spec.material_spec(k, parts, results)]
    P.append(f"""<section class="flow"><h2>Спецификация материалов и фурнитуры</h2>
{_table(["Раздел", "Позиция", "Кол-во", "Ед.", "Примечание"], ms)}
<p class="note">Цены не указаны. Листы — по раскрою. Марки и цвета — примеры, подобрать по каталогам поставщиков.</p>
</section>""")
    P.append(f"""<section class="flow"><h2>Техника (покупается отдельно)</h2>
{_table(["Что", "Размер, мм", "Где и что учесть"], [tuple(_clean(c) for c in r) for r in spec.appliance_rows(k)])}
</section>""")
    crit = [f.text for f in findings if f.level == "critical"] + list(sh.get("critical", []))
    cr = "".join(f'<div class="crit"><b>❗</b> {html.escape(t)}</div>' for t in crit)
    dev = sh["deviations"]
    P.append(f"""<section class="flow"><h2>❗ Важно до заказа</h2>{cr}
<h2 style="margin-top:5mm">Чем проект отличается от эскиза и почему</h2>
{_table(["На эскизе", "В проекте", "Почему"], dev)}</section>""")
    qs = "".join(f"<li>{html.escape(t)}</li>" for t in sh["questions"])
    P.append(f"""<section class="flow"><h2>Вопросы и замер на объекте</h2><ol>{qs}</ol></section>""")
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{html.escape(sh['title'])}</title>
<style>{ORDER_CSS}</style></head><body>{''.join(P)}</body></html>"""
    low = (re.sub(r"data:[^\"]+", "", doc) + "\n" + drawings.figure_texts(k)).lower()
    bad = [w for w in FORBIDDEN if w in low]
    if bad:
        raise RuntimeError(f"во внешнем файле внутренние слова: {bad}")
    return doc


def build_pdf(k: Kitchen, parts, results, findings, out_dir: str, safe_env: dict, cfg_path: str) -> str:
    sh = k.cfg["share"]
    src = os.path.join(out_dir, sh["photo"])
    dst = os.path.join(out_dir, "поделиться")
    os.makedirs(dst, exist_ok=True)
    pdf = os.path.join(dst, sh["file"])
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "kuhnya.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(build_html(k, parts, results, findings, out_dir, tmp, src))
        prof = os.path.join(tmp, "profile")
        tmp_pdf = os.path.join(tmp, "out.pdf")
        subprocess.run(["nice", "-n", "19", "google-chrome", "--headless=new", "--no-first-run",
                        "--no-default-browser-check", f"--user-data-dir={prof}", "--disable-gpu", "--disable-vulkan",
                        "--disable-features=Vulkan", "--use-angle=swiftshader", "--host-resolver-rules=MAP * ~NOTFOUND",
                        "--no-pdf-header-footer", "--virtual-time-budget=8000", f"--print-to-pdf={tmp_pdf}",
                        "file://" + page], env={**os.environ, **safe_env}, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240)
        shutil.move(tmp_pdf, pdf)
    return pdf
