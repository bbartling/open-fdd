from __future__ import annotations
import argparse
import json
from .algorithms import calculate, list_calculators
from .job import ECMJob

def main() -> None:
    parser = argparse.ArgumentParser(prog="open-fdd-ecm")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("calculators")

    calc = sub.add_parser("calc")
    calc.add_argument("name")
    calc.add_argument("--json", required=True)

    demo = sub.add_parser("demo")
    demo.add_argument("--out", default="Open_FDD_Demo_ECMs.xlsx")

    args = parser.parse_args()
    if args.command == "calculators":
        print("\n".join(list_calculators()))
    elif args.command == "calc":
        print(json.dumps(calculate(args.name, json.loads(args.json)), indent=2))
    elif args.command == "demo":
        path = (
            ECMJob("Open-FDD Demo", path=args.out)
            .set_global(area_ft2=85000, electric_rate=0.145, gas_rate=0.92)
            .add_ecm(
                "static_pressure_reset",
                fan_kw=55.9,
                hours=4100,
                baseline_speed=0.82,
                proposed_speed=0.67,
            )
            .save()
        )
        print(path)

if __name__ == "__main__":
    main()
