"""Постпроцессор: операции (не зависят от станка) -> программа под конкретную систему ЧПУ.

СЕЙЧАС G-CODE НЕ ВЫДАЁТСЯ: модель станка, система ЧПУ, ноль и инструмент неизвестны.
Любой вызов generate() без подтверждённого профиля — ошибка MachineNotConfigured.
Когда станок известен: заполнить profiles/<станок>.yaml по шаблону _template.yaml, написать класс-наследник
под диалект (NcStudio / Syntec / DSP / ...), проверить на симуляторе, первый рез — холостой проход с оператором.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from ..cutmap import place_xy
from ..dxf_out import part_ops, header_meta

PROFILES = os.path.join(os.path.dirname(__file__), "profiles")

REQUIRED = {
    "model": "модель станка (табличка)",
    "controller": "система ЧПУ (NcStudio/Weihong, Syntec, DSP-пульт, Biesse/Homag...)",
    "file_format": "что ест станок: расширение и пример файла с флешки",
    "work_area": "рабочее поле X×Y×Z, мм",
    "zero": "где ноль: угол стола/листа, Z=0 по столу или по верху листа",
    "tools": "инструмент: номер, тип, диаметр, обороты, подача",
    "tool_change": "смена инструмента: автомат (ATC) или вручную",
    "drill_unit": "сверлильная голова: вертикальные сверла, есть ли горизонтальные",
    "spoilboard": "жертвенный стол: насколько можно проходить ниже листа",
}


class MachineNotConfigured(RuntimeError):
    pass


@dataclass
class MachineProfile:
    status: str = "not_set"          # not_set / draft / confirmed (confirmed — только после сверки со станком и холостого прохода)
    data: dict = field(default_factory=dict)
    path: str = ""

    @classmethod
    def load(cls, name: str = "none") -> "MachineProfile":
        path = os.path.join(PROFILES, f"{name}.yaml")
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        return cls(status=d.get("status", "not_set"), data=d, path=path)

    def missing(self) -> list[str]:
        return [f"{k} — {v}" for k, v in REQUIRED.items() if not self.data.get(k)]


def sheet_operations(sheet, product_title: str, material: dict) -> dict:
    """Операции листа в координатах листа: что сверлить, где паз, какой контур резать. Без станка, без скоростей."""
    drills, edge_drills, grooves, contours = [], [], [], []
    for pl in sheet.placements:
        ops = part_ops(pl.part)
        tf = (lambda x, y, pl=pl: place_xy(pl, x, y))
        tag = f"{pl.part.no}"
        for c in ops["circles"]:
            x, y = tf(*c["c"])
            drills.append({"part": tag, "x": round(x, 3), "y": round(y, 3), "d": c["d"], "depth": c["depth"],
                           "through": c["through"], "face": c["face"], "kind": c["kind"]})
        for ln in ops["lines"]:
            a, b = tf(*ln["a"]), tf(*ln["b"])
            edge_drills.append({"part": tag, "from": [round(v, 3) for v in a], "to": [round(v, 3) for v in b],
                                "d": ln["d"], "z_from_top": ln["z"], "kind": ln["kind"],
                                "note": "в торец: горизонтальный узел или кондуктор"})
        for g in ops["grooves"]:
            a, b = tf(*g["a"]), tf(*g["b"])
            grooves.append({"part": tag, "from": [round(v, 3) for v in a], "to": [round(v, 3) for v in b],
                            "width": g["width"], "depth": g["depth"], "stopped": g["stopped"]})
        L, W = ops["contour"]
        pts = [tf(0, 0), tf(L, 0), tf(L, W), tf(0, W)]
        contours.append({"part": tag, "points": [[round(x, 3), round(y, 3)] for x, y in pts],
                         "area": round(pl.w * pl.h, 1), "thickness": material["thickness"]})
    # порядок, как принято: сначала сверление, потом пазы, потом контуры — мелкие детали первыми
    contours.sort(key=lambda c: c["area"])
    drills.sort(key=lambda d: (d["d"], d["x"], d["y"]))
    return {"header": header_meta(product_title, material, {"Лист": sheet.index}), "units": "mm",
            "sheet": {"L": sheet.L, "W": sheet.W, "trim": sheet.trim, "kerf": sheet.kerf},
            "drills": drills, "edge_drills": edge_drills, "grooves": grooves, "contours": contours}


class PostProcessor:
    """Базовый класс. Наследник под диалект переопределяет emit(). Здесь — только охрана."""

    dialect = "abstract"

    def __init__(self, profile: MachineProfile):
        self.profile = profile

    def generate(self, operations: dict) -> str:
        if self.profile.status != "confirmed":
            miss = self.profile.missing()
            raise MachineNotConfigured(
                "Станок не задан — G-code не делаем. Нужно узнать:\n  - " + "\n  - ".join(miss or ["подтвердить профиль"]))
        return self.emit(operations)

    def emit(self, operations: dict) -> str:  # pragma: no cover — появится вместе со станком
        raise NotImplementedError("диалект станка ещё не написан")
