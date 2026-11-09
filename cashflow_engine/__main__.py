"""Run a saved plan from the command line.

    python -m cashflow_engine plan.json            # prints the year-by-year table
    python -m cashflow_engine plan.json --csv out.csv
"""

import argparse
import sys

from .engine import project
from .export import write_csv
from .serialize import loads


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cashflow_engine")
    ap.add_argument("plan", help="plan JSON file")
    ap.add_argument("--csv", help="write the forecast to this CSV file")
    args = ap.parse_args(argv)
    with open(args.plan, encoding="utf-8") as fh:
        plan = loads(fh.read())
    forecast = project(plan)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            write_csv(forecast, fh)
        print(f"Wrote {len(forecast.rows)} years to {args.csv}")
        return 0
    print(f"{'Year':>5} {'Age':>4} {'Start':>12} {'Income':>10} {'Expenses':>10} {'Charges':>9} {'End':>12}")
    for r in forecast.rows:
        print(f"{r.year:>5} {r.age:>4} {r.savings_start:>12,.0f} {r.total_income:>10,.0f} "
              f"{r.total_expenses:>10,.0f} {r.total_charges:>9,.0f} {r.savings_end:>12,.0f}")
    print(f"Savings at age {forecast.final_age}: £{forecast.final_savings:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
