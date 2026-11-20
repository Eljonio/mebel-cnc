"""Геометрия: коробки (панели), отрезки (оси отверстий), расстояния. Мм, глобальные оси X (ширина), Y (глубина, 0 — фронт), Z (вверх)."""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-6
AXES = "xyz"


def unit(axis: int, sign: int = 1) -> tuple[float, float, float]:
    v = [0.0, 0.0, 0.0]
    v[axis] = float(sign)
    return tuple(v)


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def axis_of(v) -> tuple[int, int]:
    """Для единичного вектора вдоль оси — (индекс оси, знак)."""
    for i, c in enumerate(v):
        if abs(c) > 0.5:
            return i, (1 if c > 0 else -1)
    raise ValueError(f"не осевой вектор {v}")


@dataclass(frozen=True)
class Box:
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    @staticmethod
    def of(x0, x1, y0, y1, z0, z1) -> "Box":
        return Box((min(x0, x1), min(y0, y1), min(z0, z1)), (max(x0, x1), max(y0, y1), max(z0, z1)))

    @property
    def size(self):
        return tuple(h - l for l, h in zip(self.lo, self.hi))

    def volume(self) -> float:
        s = self.size
        return s[0] * s[1] * s[2]

    def intersect(self, o: "Box") -> "Box | None":
        lo = tuple(max(a, b) for a, b in zip(self.lo, o.lo))
        hi = tuple(min(a, b) for a, b in zip(self.hi, o.hi))
        if all(h - l > EPS for l, h in zip(lo, hi)):
            return Box(lo, hi)
        return None

    def contains(self, o: "Box", tol: float = 1e-6) -> bool:
        return all(sl - tol <= ol and oh <= sh + tol for sl, sh, ol, oh in zip(self.lo, self.hi, o.lo, o.hi))

    def union(self, o: "Box") -> "Box":
        return Box(tuple(min(a, b) for a, b in zip(self.lo, o.lo)), tuple(max(a, b) for a, b in zip(self.hi, o.hi)))


def bbox(boxes) -> Box:
    boxes = list(boxes)
    out = boxes[0]
    for b in boxes[1:]:
        out = out.union(b)
    return out


def seg_seg_dist(p1, q1, p2, q2) -> float:
    """Кратчайшее расстояние между отрезками p1q1 и p2q2 (стандартный алгоритм, Ericson)."""
    d1, d2, r = sub(q1, p1), sub(q2, p2), sub(p1, p2)
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a <= EPS and e <= EPS:
        return math.dist(p1, p2)
    if a <= EPS:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = dot(d1, r)
        if e <= EPS:
            t, s = 0.0, min(max(-c / a, 0.0), 1.0)
        else:
            b = dot(d1, d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > EPS else 0.0
            t = (b * s + f) / e
            if t < 0:
                t, s = 0.0, min(max(-c / a, 0.0), 1.0)
            elif t > 1:
                t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    c1, c2 = add(p1, mul(d1, s)), add(p2, mul(d2, t))
    return math.dist(c1, c2)


def point_box_dist(p, box: Box) -> float:
    d = [max(l - c, 0.0, c - h) for c, l, h in zip(p, box.lo, box.hi)]
    return math.sqrt(sum(x * x for x in d))


def seg_box_dist(p, q, box: Box, step: float = 0.25) -> float:
    """Расстояние от отрезка до коробки — перебором точек (отрезки короткие, точности 0,25 мм хватает)."""
    n = max(1, int(math.dist(p, q) / step))
    return min(point_box_dist(add(p, mul(sub(q, p), i / n)), box) for i in range(n + 1))


def spread(a: float, b: float, offset: float, max_pitch: float) -> list[float]:
    """Точки крепежа на отрезке [a, b]: первая и последняя в offset от краёв, шаг не больше max_pitch."""
    length = b - a
    if length <= 2 * offset:
        return [round((a + b) / 2, 1)]
    span = length - 2 * offset
    n = math.ceil(span / max_pitch - 1e-9) + 1
    return [round(a + offset + span * i / (n - 1), 1) for i in range(n)]
