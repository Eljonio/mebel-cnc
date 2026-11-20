import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mebel.builder import build  # noqa: E402
from mebel.config import load_product, load_shop  # noqa: E402

TUMBA = os.path.join(ROOT, "products", "tumba-800.yaml")
PENAL = os.path.join(ROOT, "products", "penal-400.yaml")


@pytest.fixture
def shop():
    return load_shop()


@pytest.fixture
def tumba(shop):
    return build(load_product(TUMBA), shop)


@pytest.fixture
def penal(shop):
    return build(load_product(PENAL), shop)
