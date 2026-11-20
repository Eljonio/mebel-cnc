"""3D-просмотр: model.json из той же модели + собранный three.js в один HTML (открывается файлом, без сервера)."""
from __future__ import annotations

import html
import json
import os

from .config import ROOT
from .model import Product
from .parts import EDGE_NAMES, Part, fmt

BUNDLE = os.path.join(ROOT, "viewer", "dist", "viewer.bundle.js")
TEMPLATE = os.path.join(ROOT, "viewer", "template.html")


def model_json(prod: Product, parts: list[Part]) -> dict:
    no_of = {}
    for p in parts:
        for _, pid, _copy in p.instances:
            no_of[pid] = p
    panels = []
    for p in prod.panels:
        part = no_of[p.id]
        d = {"id": p.id, "name": p.name, "no": part.no, "group": p.group, "lo": list(p.box.lo), "hi": list(p.box.hi),
             "color": prod.materials[p.material]["color_3d"], "t": p.thickness,
             "material": prod.materials[p.material]["name"],
             "size": f"{fmt(part.L)}×{fmt(part.W)}", "saw": f"{fmt(part.L_saw)}×{fmt(part.W_saw)}",
             "edges": {e: part.edges[e] for e in EDGE_NAMES}, "holes": len(p.holes)}
        if p.role == "door":
            d["door"] = {"hinge_side": p.meta["hinge_side"], "pivot_x": p.meta["pivot_x"],
                         "handle": p.meta.get("handle"), "hinges": p.meta.get("hinges")}
        panels.append(d)
    holes = [{"panel": h.panel, "p": list(h.p), "dir": list(h.dir), "d": h.d, "depth": h.depth, "kind": h.kind}
             for h in prod.holes]
    table = [{"no": p.no, "name": p.name, "qty": p.qty, "L": p.L, "W": p.W, "Ls": p.L_saw, "Ws": p.W_saw,
              "t": p.t, "edges": {e: p.edges[e] for e in EDGE_NAMES}, "holes": len(p.holes),
              "material": prod.materials[p.material]["name"], "grain": p.grain} for p in parts]
    return {"id": prod.id, "title": prod.name, "size": list(prod.size), "panels": panels, "holes": holes,
            "parts": table}


def bundle_js() -> str:
    if not os.path.exists(BUNDLE):
        raise RuntimeError("нет viewer/dist/viewer.bundle.js — соберите: npm install && npm run build")
    with open(BUNDLE, encoding="utf-8") as f:
        return f.read()


def safe_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_viewer(path: str, model: dict) -> str:
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    out = (tpl.replace("__TITLE__", html.escape(model["title"]))
              .replace("__MODEL__", safe_json(model))
              .replace("__BUNDLE__", bundle_js().replace("</script", "<\\/script")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path
