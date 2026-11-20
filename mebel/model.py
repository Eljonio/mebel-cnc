"""Модель изделия: панели в 3D, отверстия и пазы в глобальных координатах."""
from __future__ import annotations

from dataclasses import dataclass, field

from .geom import Box

FACES = ("-x", "+x", "-y", "+y", "-z", "+z")


def face_key(axis: int, sign: int) -> str:
    return ("-" if sign < 0 else "+") + "xyz"[axis]


@dataclass
class Hole:
    panel: str                 # id панели
    p: tuple                   # точка входа сверла на поверхности панели (глобально)
    dir: tuple                 # куда идёт сверло (единичный осевой вектор)
    d: float                   # диаметр
    depth: float               # глубина (для сквозного = толщина)
    kind: str                  # confirmat_face / confirmat_edge / minifix_cam / ... / handle
    joint: str                 # id соединения: отверстия одного соединения могут пересекаться
    through: bool = False

    @property
    def end(self):
        return tuple(a + b * self.depth for a, b in zip(self.p, self.dir))


@dataclass
class Groove:
    panel: str
    box: Box                   # вынутый материал (глобально)
    width: float
    depth: float
    kind: str = "back_groove"
    stopped: bool = False      # глухой паз (не выходит на торцы) — только фрезой


@dataclass
class Panel:
    id: str
    name: str
    role: str                  # side_left, side_right, top, bottom, shelf, shelf_fixed, plinth, door, back
    material: str              # ключ материала из shop.yaml
    thickness: float
    box: Box
    thin: int                  # ось толщины
    face: int                  # +1/-1: какая пласть обрабатывается (смотрит вверх на станке)
    grain: int | None          # глобальная ось текстуры (None — без текстуры)
    edges: dict = field(default_factory=dict)   # грань ('-y' и т.п.) -> роль торца: visible/hidden/joint/none
    group: str = "carcass"     # carcass / facade / back
    holes: list = field(default_factory=list)
    grooves: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)    # для дверей: сторона петель, ось поворота


@dataclass
class Product:
    id: str
    name: str
    prefix: str
    qty: int
    size: tuple                # (W, D, H)
    panels: list
    materials: dict            # ключ -> описание материала
    shop: dict
    params: dict
    notes: list = field(default_factory=list)       # что решил генератор (пропущенные отверстия и т.п.)
    chains: list = field(default_factory=list)      # размерные цепочки для проверки
    facade_field: dict = field(default_factory=dict)
    hardware: list = field(default_factory=list)    # фурнитура без отверстий (заглушки, гвозди)
    meta: dict = field(default_factory=dict)

    def panel(self, pid: str) -> Panel:
        for p in self.panels:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def by_role(self, role: str) -> list:
        return [p for p in self.panels if p.role == role]

    @property
    def holes(self):
        return [h for p in self.panels for h in p.holes]
