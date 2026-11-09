# Cashflow Planner

A lifetime cashflow forecasting tool for UK financial planning, built for
Footes Financial Planning UK. It is in early development. This first part is the
**calculation engine**. It has no user interface and can be tested on its own.

> Forecasts are illustrations based on assumptions, not guarantees.

## What the engine does

`cashflow_engine.project(plan)` turns a client plan into a year-by-year forecast
in today's terms. Each year runs from one birthday to the next, and the first
year is the part-year up to the next birthday.

Each year, in this order:

1. Ongoing charges come off each pot, based on its opening value. One-off
   charges, such as an initial advice fee, come off too.
2. Contributions go in. They come either from the client's cashflow or from
   outside it, for example from an employer.
3. Planned withdrawals come out. Each pot has a tax rate, and withdrawals are
   grossed up for it.
4. Income minus expenses gives a surplus or a shortfall. A shortfall is drawn
   from pots in the plan's **withdrawal order**, and anything left unfunded
   becomes an overdraft. A surplus first pays off any overdraft, and a chosen
   share of the rest is saved.
5. Pots grow at their real rate, which is the growth rate minus inflation.

The forecast reports, for each year and each pot: opening value, charges,
contributions, withdrawals, tax, growth and closing value. It also reports when
each pot runs out and when total assets run out.

Scenarios (`Scenario`, `long_term_care`) work on a copy of the baseline plan,
so the baseline is never changed. A scenario can override assumptions or pot
rates, add or remove items, or change the withdrawal order.

## Checked against Voyant

`tests/test_voyant_baseline.py` rebuilds a real Voyant "Current Situation"
forecast, anonymised. The engine matches every one of its 44 yearly rows to
within £1. The behaviour this confirmed:

- Real rates are additive. For example, 5% growth with 2% inflation gives 3%.
- Charges are taken on the opening value, before withdrawals and growth.
- In the part-year, amounts and growth are scaled by the fraction of the year.
- Pension withdrawals are grossed up at the pot's flat tax rate.
- Once every pot is empty, the shortfall builds up as an interest-free
  overdraft. In real terms it shrinks by the rate of inflation each year.

## Running it

```bash
pip install -e ".[dev]"
pytest
python -m cashflow_engine examples/voyant_baseline.json          # print the table
python -m cashflow_engine examples/voyant_baseline.json --csv out.csv
```

## Client data

Real client data must never be committed. The `data/` and `clients/` folders
and `*.db` files are git-ignored. Test cases use anonymised figures only.

## Not done yet

- Tax using UK bands (personal allowance, income bands, 25% tax-free cash
  rules, CGT on GIAs, ISA allowances). At the moment each pot has a flat tax
  rate, as Voyant's default does.
- Monthly calculation steps. The engine is annual for now, which matches
  Voyant's year-by-year table.
- Returns that vary year to year, such as a fund's model returns.
- Client records, input screens and fact-find import (step 2).
- PDF and Excel reports (step 3).
