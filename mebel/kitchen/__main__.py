"""python -m mebel.kitchen products/kuhnya-g.yaml [-o папка] [--render] [--samples 160]

Конфиг кухни -> проверки -> модули, фасады, спецификация, детали и предварительный раскрой -> xlsx, 3D html, сцена,
чертежи (план, развёртки), отчёт. С --render — ещё Blender: 3 рендера (Cycles на CPU), .blend и .glb.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

from .. import cutmap
from ..config import ROOT, load_shop, load_yaml
from . import checks, cnc, drawings, drilling, outputs, report, spec
from .layout import build
from .scene import scene_json

# Blender/Chrome — только программный рендер на CPU (Mesa/SwiftShader): дискретную видеокарту не трогаем
SAFE_ENV = {
    "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
    "__GLX_VENDOR_LIBRARY_NAME": "mesa",
    "VK_ICD_FILENAMES": "/usr/share/vulkan/icd.d/lvp_icd.json",
    "VK_DRIVER_FILES": "/usr/share/vulkan/icd.d/lvp_icd.json",
    "__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS": "/nonexistent",
    "CUDA_VISIBLE_DEVICES": "",
    "DISPLAY": "",
    "OIDN_DEVICE_CUDA": "0", "OIDN_DEVICE_SYCL": "0", "OIDN_DEVICE_HIP": "0", "OIDN_DEVICE_METAL": "0",
}


def out_dir(cfg: dict, out=None) -> str:
    """Папка результата: -o, иначе kitchen.out из конфига, иначе out/<id> в корне проекта (относительные — от корня)."""
    path = out or cfg["kitchen"].get("out") or os.path.join("out", cfg["kitchen"]["id"])
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) or out else os.path.join(ROOT, path)


def previews(out: str, cameras: dict) -> list[str]:
    """Быстрые картинки из 3D (three.js, программный рендер SwiftShader) — пока нет рендеров Blender."""
    done = []
    for v, c in cameras.items():
        w, h = c.get("res", (1920, 1200))
        png = os.path.join(out, "renders", f"preview_{v}.png")
        subprocess.run(["nice", "-n", "19", os.path.join(ROOT, "tools", "shot.sh"), os.path.join(out, "kuhnya_3d.html"),
                        png, str(w), str(h), f"?clean=1#{v}"], check=True, stdout=subprocess.DEVNULL, timeout=300)
        done.append(png)
    return done


def run(cfg_path, out=None, render=False, samples=160, strict=True, share=True, preview=False):
    shop = load_shop()
    cfg = load_yaml(cfg_path)
    out = out_dir(cfg, out)
    k = build(cfg, shop)
    drill = bool(cfg["kitchen"].get("drilling"))
    if drill:                                   # второй этап: присадка корпусов и фасадов
        k.drill_stats = drilling.drill(k)
    findings = checks.run_all(k)
    if drill:
        from .. import checks as core_checks
        findings += core_checks.check_holes(k.product) + core_checks.check_joints(k.product) + drilling.check(k)
    errs = checks.errors(findings)
    if errs and strict:
        raise SystemExit("ПРОВЕРКИ НЕ ПРОШЛИ — файлы не выданы:\n" + "\n".join(f"  {e.check}: {e.text}" for e in errs))
    parts, results, nest_errs = spec.compute(k)
    if nest_errs:
        raise SystemExit("раскрой не сошёлся: " + "; ".join(nest_errs))
    os.makedirs(out, exist_ok=True)
    if drill:
        cr = cnc.export(k, parts, results, out)
        if cr["errors"] and strict:
            raise SystemExit("DXF не сошлись с расчётом:\n" + "\n".join(cr["errors"]))
    for sub in ("model", "chertezhi", "spec", "raskroy", "renders"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    sc = scene_json(k)
    scene_path = os.path.join(out, "model", "scene.json")
    with open(scene_path, "w", encoding="utf-8") as f:
        json.dump(sc, f, ensure_ascii=False)
    outputs.write_html(os.path.join(out, "kuhnya_3d.html"), sc)
    xerr = outputs.write_xlsx(os.path.join(out, "spec", "kuhnya_specifikaciya.xlsx"), k, parts, results, findings)
    drawings.write(k, os.path.join(out, "chertezhi"))
    rdir = os.path.join(out, "raskroy")
    for f in os.listdir(rdir):
        os.remove(os.path.join(rdir, f))
    ctitle = k.cfg["kitchen"]["name"] + (" — корпуса, раскрой с присадкой (лист, пропил — сверить с цехом)" if drill
                                         else " — корпуса (предварительно)")
    cmats = k.shop["materials"]
    if drill:                                 # короткие имена материалов в шапке карты (длинные не влезают)
        cmats = {key: {**v, "name": v["name"].split("(")[0].strip()} for key, v in cmats.items()}
    cutmap.render(results, ctitle, cmats, rdir,
                  os.path.join(rdir, "raskroy.pdf"))
    with open(os.path.join(out, "proverki.txt"), "w", encoding="utf-8") as f:
        for x in findings:
            f.write(f"[{outputs.LEVEL_RU.get(x.level, x.level)}] {x.check}: {x.text}\n")
    if preview:
        previews(out, sc["cameras"])
    if render:
        blender = shutil.which("blender") or "blender"
        env = {**os.environ, **SAFE_ENV}
        cmd = [blender, "-b", "--factory-startup", "--python", os.path.join(ROOT, "tools", "kitchen_blender.py"), "--",
               scene_path, os.path.join(out, "renders"), "--samples", str(samples), "--views", ",".join(sc["cameras"])]
        if k.cfg.get("render"):                 # интерьерный рендер: денойз нодой композитора на CPU, все ядра
            cmd += ["--denoise", "--threads", str(os.cpu_count() or 4)]
        subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL)
        for name in ("kuhnya.blend", "kuhnya.glb"):
            src = os.path.join(out, "renders", name)
            if os.path.exists(src):
                shutil.move(src, os.path.join(out, "model", name))
    if k.cfg.get("share"):
        report.write_order(os.path.join(out, "ОТЧЁТ.md"), k, parts, results, findings, out)
    else:
        report.write(os.path.join(out, "ОТЧЁТ.md"), k, parts, results, findings, out)
    if share and k.cfg.get("share"):
        if os.path.exists(os.path.join(out, k.cfg["share"]["photo"])):
            from .share_order import build_pdf as build_order_pdf
            build_order_pdf(k, parts, results, findings, out, SAFE_ENV, cfg_path)
        else:
            print("PDF не собран: нет эскиза-референса", os.path.join(out, k.cfg["share"]["photo"]))
    elif share and all(os.path.exists(os.path.join(out, "renders", f"render_{v}.png")) for v in ("front", "angle", "top")):
        from .share import build_pdf
        build_pdf(k, parts, results, out, SAFE_ENV)
    return {"kitchen": k, "findings": findings, "parts": parts, "results": results, "xlsx_errors": xerr}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mebel.kitchen")
    ap.add_argument("config")
    ap.add_argument("-o", "--out", default=None, help="папка выхода (по умолчанию kitchen.out из конфига или out/<id>)")
    ap.add_argument("--render", action="store_true", help="рендеры Blender (CPU, несколько минут)")
    ap.add_argument("--preview", action="store_true", help="быстрые картинки из 3D (SwiftShader), без Blender")
    ap.add_argument("--samples", type=int, default=160)
    a = ap.parse_args(argv)
    res = run(a.config, a.out, a.render, a.samples, preview=a.preview)
    f = res["findings"]
    print(f"проверок: {len(f)}, ошибок {sum(x.level == 'error' for x in f)}, критично {sum(x.level == 'critical' for x in f)}, "
          f"внимание {sum(x.level == 'warn' for x in f)}")
    for r in res["results"]:
        print(r.material, "листов", len(r.sheets), [f"{s.util * 100:.0f}%" for s in r.sheets])
    if res["xlsx_errors"]:
        print("xlsx:", res["xlsx_errors"])
        return 1
    print("Результат:", out_dir(res["kitchen"].cfg, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
