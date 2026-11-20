"""Сцена кухни для картинок: одна и та же модель -> three.js (html) и Blender (рендеры, .blend, .glb)."""
from __future__ import annotations

import math

from .layout import Kitchen, box_minus

MATS = {
    "facade": {"color": "#ddcdb2", "rough": 0.62, "metal": 0.0},
    "carcass": {"color": "#c9cbca", "rough": 0.55, "metal": 0.0},
    "back": {"color": "#d9dad8", "rough": 0.7, "metal": 0.0},
    "worktop": {"color": "#bf9a6c", "rough": 0.5, "metal": 0.0, "wood": True},
    "apron": {"color": "#ece3d3", "rough": 0.3, "metal": 0.0},
    "plinth": {"color": "#8e9195", "rough": 0.5, "metal": 0.1},
    "gola": {"color": "#a7aaae", "rough": 0.35, "metal": 0.85},
    "led": {"color": "#fff1d6", "rough": 0.5, "metal": 0.0, "emissive": 6.0},
    "steel": {"color": "#c9ccd0", "rough": 0.28, "metal": 1.0},
    "steel_dark": {"color": "#8d9196", "rough": 0.35, "metal": 1.0},
    "chrome": {"color": "#e6e8ea", "rough": 0.12, "metal": 1.0},
    "black_glass": {"color": "#0f1012", "rough": 0.06, "metal": 0.0},
    "dark": {"color": "#2a2c30", "rough": 0.5, "metal": 0.2},
    "white_steel": {"color": "#eceded", "rough": 0.25, "metal": 0.15},
    "duct": {"color": "#b9bcbf", "rough": 0.4, "metal": 0.6},
    "wall": {"color": "#f1eee8", "rough": 0.9, "metal": 0.0},
    "floor": {"color": "#d6cec2", "rough": 0.55, "metal": 0.0, "tiles": True},
    "window_frame": {"color": "#f6f6f4", "rough": 0.4, "metal": 0.0},
    "glass": {"color": "#d4e6f0", "rough": 0.03, "metal": 0.0, "opacity": 0.18},
    "sill": {"color": "#f6f6f4", "rough": 0.35, "metal": 0.0},
    "door": {"color": "#e7e1d6", "rough": 0.5, "metal": 0.0},
    "door_frame": {"color": "#f2f0ea", "rough": 0.5, "metal": 0.0},
    "point_water": {"color": "#2563eb", "rough": 0.5, "metal": 0.0},
    "point_power": {"color": "#dc2626", "rough": 0.5, "metal": 0.0},
    "point_vent": {"color": "#374151", "rough": 0.5, "metal": 0.0},
    "point_gas": {"color": "#ca8a04", "rough": 0.5, "metal": 0.0},
    "granite_black": {"color": "#141416", "rough": 0.45, "metal": 0.0},
    "faucet_black": {"color": "#18181a", "rough": 0.35, "metal": 0.6},
    "cast_iron": {"color": "#1b1b1d", "rough": 0.6, "metal": 0.4},
    "steel_fridge": {"color": "#6f6c68", "rough": 0.32, "metal": 0.75},
    "curtain": {"color": "#b9b2a6", "rough": 0.95, "metal": 0.0},
}


POINT_MAT = {"water": "point_water", "vent": "point_vent", "gas": "point_gas"}


def mats_for(k: Kitchen) -> dict:
    """Цвета картинки: базовые + раздел look конфига (цвета материалов). Без look — как раньше."""
    out = {key: dict(v) for key, v in MATS.items()}
    look = k.cfg.get("look") or {}
    for key in ("facade", "carcass", "worktop", "apron", "plinth"):
        if look.get(key):
            out[key]["color"] = look[key]
    if look.get("worktop_wood") is False:
        out["worktop"].pop("wood", None)
        out["worktop"]["rough"] = 0.7
    return out


def _bird(a, b, pitch, dist, lens, clip):
    tx, ty, tz = a * 0.36, b * 0.36, 600.0
    hx, hy = a - tx, b - ty
    n = math.hypot(hx, hy)
    c, s_ = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    pos = [tx + hx / n * dist * c, ty + hy / n * dist * c, tz + dist * s_]
    return {"pos": [round(v) for v in pos], "target": [tx, ty, tz], "lens": lens, "hide": [], "clip": clip,
            "clip_kinds": ["wall", "window", "door"], "clip_drop": ["door_leaf"],
            "title": f"Общий вид сверху (из угла C/D, {pitch}° к полу, стены срезаны на {clip})"}


def cameras(k: Kitchen) -> dict:
    a, b, H = (float(k.cfg["room"][x]) for x in ("a", "b", "height"))
    extra = {key: dict(v) for key, v in (k.cfg.get("cameras") or {}).items()}
    return {**_std_cameras(k, a, b, H), **extra}


def _std_cameras(k: Kitchen, a, b, H) -> dict:
    return {
        # оси помещения; hide — что прятать на этом виде
        "front": {"pos": [a / 2, b + 650, 1350], "target": [a / 2, 0, 1250], "lens": 26, "hide": ["D"],
                  "title": "Вид спереди (на стену A)"},
        "angle": {"pos": [a + 950, b + 1150, 2350], "target": [1250, 650, 950], "lens": 27, "hide": ["C", "D"],
                  "title": "Вид под углом (из угла C/D на угол A/B)"},
        # общий вид сверху: из угла C/D, ~60° к полу, стены/окно/дверь срезаны на 1500 — видно проёмы и шкафы
        "top": _bird(a, b, pitch=58, dist=7000, lens=28, clip=1500),
    }


def scene_json(k: Kitchen) -> dict:
    solids = []
    for s in k.solids:
        boxes = box_minus(s.box, s.cut) if s.cut else [s.box]
        solids.append({"id": s.id, "name": s.name, "kind": s.kind, "mat": s.mat, "module": s.module,
                       "shape": s.shape, "grain": s.meta.get("grain"), "wall": s.meta.get("wall"),
                       "boxes": [[*bx.lo, *bx.hi] for bx in boxes],
                       "size": [round(v, 1) for v in s.box.size]})
    labels = []
    for m in k.modules:
        if m.type in ("corner_filler", "end_panel", "filler", "ceiling_strip"):
            continue
        uc = (m.u0 + m.u1) / 2
        if m.type == "corner_l":
            pos = [170, 170, (m.z0 + m.z1) / 2]
        elif m.type == "fridge":
            pos = [720, uc, 1500] if m.run == "B" else [uc, 720, 1500]
        else:
            front = (k.geo["D"] if m.level == "нижний" else k.geo["Du"]) + k.geo["tf"] + 30
            z = (m.z0 + m.z1) / 2
            pos = [uc, front, z] if m.run == "A" else [front, uc, z]
        labels.append({"text": m.id, "pos": pos})
    points = [{"id": p["id"], "name": p["name"], "pos": list(p["pt"]),
               "color": MATS[POINT_MAT.get(p.get("kind", p["id"]), POINT_MAT.get(p["id"], "point_power"))]["color"]}
              for p in k.points]
    return {"title": k.cfg["kitchen"]["name"], "room": {x: k.cfg["room"][x] for x in ("a", "b", "height", "wall")},
            "mats": mats_for(k), "solids": solids, "labels": labels, "points": points, "cameras": cameras(k),
            **({"render": k.cfg["render"]} if k.cfg.get("render") else {})}
