"""python -m mebel products/tumba-800.yaml [products/penal-400.yaml ...] [-o out/имя]"""
import argparse
import os
import sys

from .config import ROOT
from .pipeline import CheckFailed, run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mebel", description="параметры изделия -> детали -> раскрой -> DXF -> Excel -> 3D")
    ap.add_argument("products", nargs="+", help="YAML изделий (несколько — один заказ, общий раскрой)")
    ap.add_argument("-o", "--out", help="папка результата (по умолчанию out/<id>)")
    ap.add_argument("--shop", help="цеховые параметры (по умолчанию shop/shop.yaml)")
    ap.add_argument("--no-viewer", action="store_true")
    a = ap.parse_args(argv)
    ids = [os.path.splitext(os.path.basename(p))[0] for p in a.products]
    out = a.out or os.path.join(ROOT, "out", ids[0] if len(ids) == 1 else "zakaz_" + "+".join(ids))
    try:
        res = run(a.products, out, a.shop, viewer=not a.no_viewer)
    except CheckFailed as e:
        print("ПРОВЕРКИ НЕ ПРОШЛИ — файлы не выданы:\n" + str(e), file=sys.stderr)
        return 2
    with open(os.path.join(out, "summary.txt"), encoding="utf-8") as f:
        print(f.read())
    print("Результат:", out)
    return 1 if res["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
