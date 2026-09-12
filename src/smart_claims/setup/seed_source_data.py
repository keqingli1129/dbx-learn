"""Seed the simulated operational database: source.customer, source.policy, source.claim.

Stands in for the transcript's SQL Server. These are ordinary Delta tables with Change Data Feed
enabled, so Phase 5 can replay real inserts, updates and deletes through Auto CDC instead of us
hand-writing a change log and then "verifying" the records we ourselves fabricated (research R4).

STRUCTURE: every generator below is pure Python and imports no Spark, so the data shape can be
checked offline against `smart_claims.lib` before any deploy. Spark is imported lazily inside
`main()`. Debugging a serverless job by redeploying is a slow loop; catching a wrong date format
in a unit test is not.

Run as a job task:
    spark_python_task:
      python_file: ../src/smart_claims/setup/seed_source_data.py
      parameters: ["--catalog", "...", "--source-schema", "..."]
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
from typing import Any, Final

from smart_claims.lib.cleaning import DATE_FORMATS
from smart_claims.lib.severity import SEVERITY_DOMAIN

# Table shapes as DDL strings rather than pyspark StructTypes -- a StructType would drag pyspark
# into module scope and make this file unimportable offline.
CUSTOMER_DDL: Final[str] = """
    customer_id STRING, name STRING, date_of_birth STRING, address STRING,
    email STRING, phone STRING, city STRING, state STRING, zip STRING
"""
POLICY_DDL: Final[str] = """
    policy_no STRING, customer_id STRING, chassis_no STRING,
    sum_insured DECIMAL(12,2), premium DECIMAL(10,2),
    pol_eff_date STRING, pol_expiry_date STRING, pol_issue_date STRING,
    model STRING, make STRING, model_year INT
"""
CLAIM_DDL: Final[str] = """
    claim_no STRING, policy_no STRING, claim_date STRING, incident_date STRING,
    incident_hour INT, incident_type STRING, collision_type STRING, incident_severity STRING,
    incident_city STRING, incident_state STRING, total_claim_amount DECIMAL(12,2),
    num_vehicles_involved INT, driver_license_issue_date STRING
"""

# Generated from stdlib `random`, not Faker: Faker is absent from the serverless base image
# (research R1) and would have to be declared as a job dependency purely to make up names nobody
# reads. The shapes below are what the cleaning functions actually care about.
FIRST_NAMES: Final[tuple[str, ...]] = (
    "Ada", "Grace", "Alan", "Edsger", "Barbara", "Ken", "Margaret", "Linus", "Radia", "Tim",
    "Jean", "Frances", "Donald", "Leslie", "Katherine", "Shafi", "Vint", "Hedy", "Anita", "Bjarne",
)
LAST_NAMES: Final[tuple[str, ...]] = (
    "Lovelace", "Hopper", "Turing", "Dijkstra", "Liskov", "Thompson", "Hamilton", "Torvalds",
    "Perlman", "Berners-Lee", "Bartik", "Allen", "Knuth", "Lamport", "Johnson", "Goldwasser",
    "Cerf", "Lamarr", "Borg", "Stroustrup",
)
# Compound surnames are deliberate: split_name() absorbs middle tokens into the surname, and the
# seed data should exercise that rather than only ever producing two clean tokens.
SURNAME_PREFIXES: Final[tuple[str, ...]] = ("", "", "", "", "", "van der ", "de ", "von ")

STREETS: Final[tuple[str, ...]] = (
    "Elm St", "Oak Ave", "Maple Dr", "Cedar Ln", "Birch Rd", "Pine Way", "Willow Ct", "Ash Blvd",
)
CITIES: Final[tuple[str, ...]] = (
    ("Munich", "BY"), ("Berlin", "BE"), ("Hamburg", "HH"), ("Cologne", "NW"),
    ("Frankfurt", "HE"), ("Stuttgart", "BW"), ("Leipzig", "SN"), ("Bremen", "HB"),
)
MAKES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("Volkswagen", ("Golf", "Passat", "Tiguan")),
    ("BMW", ("3 Series", "X3", "5 Series")),
    ("Audi", ("A3", "A4", "Q5")),
    ("Mercedes", ("C-Class", "E-Class", "GLC")),
)
INCIDENT_TYPES: Final[tuple[str, ...]] = (
    "Single Vehicle Collision", "Multi-vehicle Collision", "Parked Car", "Vehicle Theft",
)
COLLISION_TYPES: Final[tuple[str, ...]] = ("Front Collision", "Rear Collision", "Side Collision")


def _fmt(value: dt.date | dt.datetime, key: str) -> str:
    """Render a date using the SAME pattern table the cleaning functions parse with.

    Sourcing both sides from `DATE_FORMATS` is what guarantees the seed data and the silver
    transformation cannot disagree about a column's format -- the ambiguity that makes
    "03/04/2026" mean two different days (see tests/unit/test_cleaning.py).
    """
    return value.strftime(DATE_FORMATS[key].python)


def _messy_address(street_no: int, street: str, rng: random.Random) -> str:
    """An address with inconsistent casing and spacing, as an operational system would hold it.

    normalize_address() exists to canonicalise exactly this.
    """
    raw = f"{street_no} {street}"
    style = rng.randrange(4)
    if style == 0:
        return raw.lower()
    if style == 1:
        return raw.upper()
    if style == 2:
        return raw.replace(" ", "   ")
    return f"  {raw} "


def make_customers(count: int, rng: random.Random) -> list[dict[str, Any]]:
    """Customers with a COMBINED name column, exactly as the transcript's source system has it."""
    rows = []
    for i in range(count):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(SURNAME_PREFIXES) + rng.choice(LAST_NAMES)
        city, state = rng.choice(CITIES)
        dob = dt.date(rng.randrange(1955, 2005), rng.randrange(1, 13), rng.randrange(1, 29))
        rows.append({
            "customer_id": f"CUST-{i:06d}",
            "name": f"{first} {last}",                       # split_name() splits this
            "date_of_birth": _fmt(dob, "US_SLASH"),
            "address": _messy_address(rng.randrange(1, 400), rng.choice(STREETS), rng),
            "email": f"{first.lower()}.{last.split()[-1].lower()}{i}@example.invalid",
            "phone": f"+49-{rng.randrange(100, 999)}-{rng.randrange(1000000, 9999999)}",
            "city": city, "state": state, "zip": f"{rng.randrange(10000, 99999)}",
        })
    return rows


def make_policies(customers: list[dict], count: int, rng: random.Random) -> list[dict[str, Any]]:
    """Policies, each owned by an existing customer. `chassis_no` is what telematics joins on."""
    rows = []
    for i in range(count):
        owner = customers[i % len(customers)]
        make, models = rng.choice(MAKES)
        eff = dt.date(rng.randrange(2023, 2026), rng.randrange(1, 13), rng.randrange(1, 29))
        rows.append({
            "policy_no": f"POL-{i:06d}",
            "customer_id": owner["customer_id"],
            "chassis_no": f"WVWZZZ{i:011d}",
            "sum_insured": float(rng.choice((25_000, 50_000, 75_000, 100_000))),
            "premium": float(rng.randrange(400, 2_400)),
            "pol_eff_date": _fmt(eff, "ISO_DASH"),
            "pol_expiry_date": _fmt(eff + dt.timedelta(days=365), "ISO_DASH"),
            "pol_issue_date": _fmt(eff - dt.timedelta(days=rng.randrange(1, 30)), "EU_DASH"),
            "model": rng.choice(models), "make": make,
            "model_year": rng.randrange(2015, 2026),
        })
    return rows


def make_claims(policies: list[dict], count: int, rng: random.Random) -> list[dict[str, Any]]:
    """Claims against existing policies, with the customer's self-assessed severity."""
    rows = []
    for i in range(count):
        policy = policies[i % len(policies)]
        incident = dt.date(2026, rng.randrange(1, 10), rng.randrange(1, 29))
        claim_ts = dt.datetime.combine(
            incident + dt.timedelta(days=rng.randrange(0, 5)),
            dt.time(rng.randrange(8, 18), rng.randrange(0, 60)),
        )
        city, state = rng.choice(CITIES)
        rows.append({
            "claim_no": f"CLM-{i:06d}",
            "policy_no": policy["policy_no"],
            "claim_date": _fmt(claim_ts, "ISO_DATETIME"),
            "incident_date": _fmt(incident, "US_SLASH"),
            "incident_hour": rng.randrange(0, 24),
            "incident_type": rng.choice(INCIDENT_TYPES),
            "collision_type": rng.choice(COLLISION_TYPES),
            "incident_severity": rng.choice(SEVERITY_DOMAIN),
            "incident_city": city, "incident_state": state,
            "total_claim_amount": float(rng.randrange(500, 90_000)),
            "num_vehicles_involved": rng.randrange(1, 5),
            # A FOURTH date format, and the one that makes format-sniffing dangerous: this is
            # dd/MM/yyyy while incident_date above is MM/dd/yyyy.
            "driver_license_issue_date": _fmt(
                dt.date(rng.randrange(1990, 2024), rng.randrange(1, 13), rng.randrange(1, 29)),
                "EU_SLASH",
            ),
        })
    return rows


def generate(customers: int, policies: int, claims: int, seed: int) -> dict[str, list[dict]]:
    """Generate all three tables. Deterministic for a given seed, so runs are reproducible."""
    rng = random.Random(seed)
    customer_rows = make_customers(customers, rng)
    policy_rows = make_policies(customer_rows, policies, rng)
    claim_rows = make_claims(policy_rows, claims, rng)
    return {"customer": customer_rows, "policy": policy_rows, "claim": claim_rows}


def main() -> None:
    # Spark is imported HERE, not at module scope, so the generators above stay importable and
    # testable without a Spark session (Constitution II).
    from pyspark.sql import SparkSession

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--source-schema", required=True,
                        help="RESOLVED schema name; development mode renames it (research R13)")
    parser.add_argument("--customers", type=int, default=1000)
    parser.add_argument("--policies", type=int, default=1200)
    parser.add_argument("--claims", type=int, default=1300)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args()

    spark = SparkSession.builder.getOrCreate()
    data = generate(args.customers, args.policies, args.claims, args.seed)
    ddl = {"customer": CUSTOMER_DDL, "policy": POLICY_DDL, "claim": CLAIM_DDL}

    for table, rows in data.items():
        fq = f"`{args.catalog}`.`{args.source_schema}`.`{table}`"
        spark.createDataFrame(rows, schema=ddl[table]).createOrReplaceTempView(f"_seed_{table}")
        # CTAS with TBLPROPERTIES so both properties hold from version 0. Enabling Change Data
        # Feed after creation would start the feed at the version where it was turned on, and
        # Phase 5 replays changes from the beginning.
        spark.sql(f"""
            CREATE OR REPLACE TABLE {fq}
            TBLPROPERTIES (
                delta.enableChangeDataFeed = true,
                delta.enableRowTracking    = true
            )
            AS SELECT * FROM _seed_{table}
        """)
        print(f"wrote {len(rows):>5} rows to {fq}")


if __name__ == "__main__":
    main()
