"""Загрузка параметров: цех (shop.yaml) + изделие (products/*.yaml)."""
from __future__ import annotations

import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SHOP = os.path.join(ROOT, "shop", "shop.yaml")


def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_shop(path: str | None = None) -> dict:
    return load_yaml(path or DEFAULT_SHOP)


def load_product(path: str) -> dict:
    cfg = load_yaml(path)
    cfg.setdefault("construction", {})
    cfg["_path"] = os.path.abspath(path)
    return cfg
