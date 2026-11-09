"""Anonymised test case rebuilt from a real Voyant report.

The figures (pots, expenses, assumptions and expected results) come from the
"Current Situation" forecast in a Voyant report. Names and identifiers are
removed. Date of birth is chosen so the first part-year matches the report
(80 days until the next birthday from a 19 Oct 2021 start).
"""

from datetime import date

from cashflow_engine import Assumptions, Expense, Frequency, Person, Plan, Pot, PotType

M, A = Frequency.MONTHLY, Frequency.ANNUAL

# (name, amount, frequency) – all from age 56 to 100 at assumed inflation.
BASELINE_EXPENSES = [
    ("Food / Housekeeping", 150, M), ("Council Tax", 1036, A), ("Fuel", 60, M),
    ("Holidays", 50, M), ("Socialising / Entertainment", 50, M), ("Motoring Insurance", 540, A),
    ("Motoring Maintenance", 510, A), ("Broadband / Landline / TV", 41, M),
    ("Birthdays / Christmas", 41, M), ("Gas", 35, M), ("Electricity", 35, M),
    ("Other expenses", 28, M), ("Dental", 17, M), ("Insurance", 170, A), ("TV Licence", 158, A),
    ("Motoring Tax", 145, A), ("Water", 122, A), ("Security", 9, M),
]


def voyant_baseline_plan() -> Plan:
    def pension(pid, name, value):
        return Pot(pid, name, PotType.PENSION, value, growth_rate=0.05, charge_rate=0.01, tax_rate=0.20)

    return Plan(
        name="Current situation",
        client=Person("Test Client A", date_of_birth=date(1965, 1, 7), retirement_age=60),
        start_date=date(2021, 10, 19),
        pots=[
            Pot("current", "Current account", PotType.CURRENT_ACCOUNT, 0, growth_rate=0.005),
            pension("pp1", "Personal pension 1", 120_000),
            pension("pp2", "Personal pension 2", 79_000),
            pension("wp1", "Workplace pension", 8_300),
            pension("pp3", "Personal pension 3", 69_000),
            Pot("isa", "ISA", PotType.ISA, 100_000, growth_rate=0.01),
        ],
        expenses=[Expense(n, amt, freq, start_age=56, end_age=100) for n, amt, freq in BASELINE_EXPENSES],
        withdrawal_order=["current", "pp1", "pp2", "wp1", "pp3", "isa"],
        assumptions=Assumptions(inflation=0.02, end_age=100),
    )


# Expected year-by-year results from the Voyant report, ages 56 to 99.
# (year, age, savings at start, expenses, charges, surplus/deficit, savings at end)
VOYANT_BASELINE_ROWS = [
    (2021, 56, 376300, 1945, 606, -1945, 374841), (2022, 57, 374841, 8873, 2751, -8873, 367838),
    (2023, 58, 367838, 8873, 2691, -8873, 360727), (2024, 59, 360727, 8873, 2629, -8873, 353504),
    (2025, 60, 353504, 8873, 2567, -8873, 346169), (2026, 61, 346169, 8873, 2503, -8873, 338718),
    (2027, 62, 338718, 8873, 2438, -8873, 331148), (2028, 63, 331148, 8873, 2372, -8873, 323458),
    (2029, 64, 323458, 8873, 2305, -8873, 315644), (2030, 65, 315644, 8873, 2236, -8873, 307703),
    (2031, 66, 307703, 8873, 2166, -8873, 299634), (2032, 67, 299634, 8873, 2094, -8873, 291433),
    (2033, 68, 291433, 8873, 2021, -8873, 283097), (2034, 69, 283097, 8873, 1947, -8873, 274623),
    (2035, 70, 274623, 8873, 1871, -8873, 266008), (2036, 71, 266008, 8873, 1793, -8873, 257250),
    (2037, 72, 257250, 8873, 1714, -8873, 248345), (2038, 73, 248345, 8873, 1634, -8873, 239290),
    (2039, 74, 239290, 8873, 1552, -8873, 230082), (2040, 75, 230082, 8873, 1468, -8873, 220718),
    (2041, 76, 220718, 8873, 1383, -8873, 211194), (2042, 77, 211194, 8873, 1296, -8873, 201506),
    (2043, 78, 201506, 8873, 1207, -8873, 191652), (2044, 79, 191652, 8873, 1117, -8873, 181628),
    (2045, 80, 181628, 8873, 1024, -8873, 171431), (2046, 81, 171431, 8873, 930, -8873, 161056),
    (2047, 82, 161056, 8873, 834, -8873, 150499), (2048, 83, 150499, 8873, 737, -8873, 139758),
    (2049, 84, 139758, 8873, 637, -8873, 128828), (2050, 85, 128828, 8873, 535, -8873, 117705),
    (2051, 86, 117705, 8873, 432, -8873, 106386), (2052, 87, 106386, 8873, 326, -8873, 94866),
    (2053, 88, 94866, 8873, 218, -8873, 83140), (2054, 89, 83140, 8873, 108, -8873, 71301),
    (2055, 90, 71301, 8873, 0, -8873, 61803), (2056, 91, 61803, 8873, 0, -8873, 52401),
    (2057, 92, 52401, 8873, 0, -8873, 43093), (2058, 93, 43093, 8873, 0, -8873, 33878),
    (2059, 94, 33878, 8873, 0, -8873, 24754), (2060, 95, 24754, 8873, 0, -8873, 15723),
    (2061, 96, 15723, 8873, 0, -8873, 6781), (2062, 97, 6781, 8873, 0, -8873, -2050),
    (2063, 98, -2050, 8873, 0, -8873, -10705), (2064, 99, -10705, 8873, 0, -8873, -19186),
]
