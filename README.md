# Cashflow Planner

A lifetime cashflow forecasting tool for UK financial planning, built for
Footes Financial Planning UK. It is in early development.

The code is in four separate parts, so the calculations can be tested on
their own:

| Part | What it does |
|---|---|
| `cashflow_engine` | The forecast calculations. It has no user interface. |
| `fact_find_import` | Reads CashCalc fact-find PDFs into a draft plan. |
| `client_store` | Encrypted client records, with saved versions and an audit trail. |
| `webapp` | The adviser's screens. It runs in the browser, on this computer only. |

## Starting the app

You need Python 3.11 or later. Install it once, from the project folder:

```bash
python -m pip install -e .
```

Then start the app each time with:

```bash
python -m webapp
```

The app opens at http://127.0.0.1:8765. The first time, you choose a
passphrase. It encrypts every client record. Records are kept in
`~/CashflowPlanner/clients.db`, which you can change with the `CASHFLOW_DB`
environment variable. The app only accepts connections from this computer.
Nothing about a client is sent anywhere.

What the app does:
- **Import a fact find:** upload a CashCalc PDF, then check what was read and
  fill in anything that was missing, such as the date of birth. You also set
  the starting growth and charge assumptions.
- **Edit a plan:** change pots, income, expenditure, contributions, planned
  withdrawals, one-off charges and the withdrawal order. The forecast,
  charts and year-by-year table update as you type. Sliders change inflation
  and all growth rates. Click a year to see each pot's figures for that year.
- **Scenarios:** save any edited plan as a named scenario. There are also
  one-click scenarios for care costs, inflation at 4% and returns 2% lower.
  A scenario never changes the baseline.
- **Compare scenarios:** see every scenario's total savings on one chart.
- **Audit trail:** every save is kept as a new version. Each entry records
  what changed, your note, and the effect on savings at the end of the plan.

## The calculation engine

> Forecasts are illustrations based on assumptions, not guarantees.

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
- Reading Intelligent Office fact finds.
- Changes to the baseline aren't carried into existing scenarios. Each
  scenario is a separate copy.
- PDF and Excel reports (step 3).
