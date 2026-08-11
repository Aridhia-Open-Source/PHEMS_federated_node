#!/usr/bin/env python3
"""Read back the UC3 OMOP database and check it can actually drive the pipeline.

Row counts alone say little for UC3: the R stage discovers its concepts by keyword
at run time, so a seed can be fully loaded and still leave every codelist empty.
This re-runs the same searches in SQL and then checks the one shape the julia stage
insists on - a (person, occasion) group with two FVIII one-stage measurements and a
weight - so a broken seed is visible without waiting on an R/julia run.
"""

import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, os.environ.get('SEED_ENV_FILE', 'uc3.env')))

LOCAL_DATASET_HOST = os.environ['LOCAL_DATASET_HOST']
LOCAL_DATASET_PORT = int(os.environ['LOCAL_DATASET_PORT'])
DATASET_NAME = os.environ['DATASET_NAME']
DATASET_USERNAME = os.environ['DATASET_USERNAME']
DATASET_PASSWORD = os.environ['DATASET_PASSWORD']
DATASET_SCHEMA = os.environ['DATASET_SCHEMA']

# The searches src/lib/data/concept_ids.R performs, as (label, domain, keywords,
# exclusions). Keywords match the way CodelistGenerator does: all words of a
# keyword present, in order, case insensitive.
KEYWORD_SEARCHES = [
    ("cohort (Condition)", "Condition",
     ["factor VIII", "hemophilia"],
     ["actor IX", "actor XI", "arthropathy", "hemarthrosis", "Hemorrhagic",
      "Willebrand", "multiple factor", "emophilia B", "factor V deficiency"]),
    ("lab (Measurement)", "Measurement",
     ["factor VIII", "von Willebrand activity", "von Willebrand antigen",
      "desmopressin", "emicizumab"],
     ["mutation", "gene", "pathology"]),
    ("Wilate/Haemate P (Drug)", "Drug", ["Wilate", "Haemate P"], []),
]

# getDescendants() roots, and the name filter the R code applies to the results.
DESCENDANT_SEARCHES = [
    ("weight", 1003901, "amputation"),
    ("height", 1002881, "amputation"),
    ("blood_group", 40782958, None),
]

INGREDIENTS = ["Desmopressin", "Factor VIII", "Emicizumab", "efmoroctocog alfa",
               "damoctocog alfa pegol", "rurioctocog alfa pegol",
               "efanesoctocog alfa", "turoctocog alfa pegol"]

FVIII_OSA = 3013721
BODY_WEIGHT = 3025315


def like_pattern(keyword):
    return "%" + "%".join(keyword.lower().split()) + "%"


def main():
    try:
        conn = psycopg2.connect(
            host=LOCAL_DATASET_HOST,
            port=LOCAL_DATASET_PORT,
            user=DATASET_USERNAME,
            password=DATASET_PASSWORD,
            dbname=DATASET_NAME,
        )
    except psycopg2.Error as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        return 1

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(f'SET search_path TO "{DATASET_SCHEMA}"')

    print("\n" + "=" * 78)
    print("UC3 OMOP Database Summary")
    print("=" * 78)
    for table in ('person', 'observation_period', 'condition_occurrence',
                  'measurement', 'drug_exposure', 'concept', 'concept_ancestor'):
        cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
        print(f"{table:<28} {cursor.fetchone()['count']:>8} rows")

    problems = []

    print("\n" + "=" * 78)
    print("Concept searches the R stage performs")
    print("=" * 78)
    for label, domain, keywords, exclusions in KEYWORD_SEARCHES:
        where = " OR ".join(["lower(concept_name) LIKE %s"] * len(keywords))
        params = [like_pattern(k) for k in keywords]
        sql = (f"SELECT concept_id, concept_name FROM concept "
               f"WHERE domain_id = %s AND standard_concept = 'S' AND ({where})")
        cursor.execute(sql, [domain] + params)
        rows = cursor.fetchall()
        kept = [r for r in rows
                if not any(x.lower() in r['concept_name'].lower() for x in exclusions)]
        print(f"\n{label}: {len(rows)} matched, {len(kept)} left after exclusions")
        for r in kept:
            print(f"  {r['concept_id']:>10}  {r['concept_name']}")
        if not kept:
            problems.append(f"{label} resolves to no concepts - newCodelist() will error")

    print("\n" + "=" * 78)
    print("Hierarchy walks (getDescendants)")
    print("=" * 78)
    for label, root, name_filter in DESCENDANT_SEARCHES:
        cursor.execute(
            "SELECT c.concept_id, c.concept_name FROM concept_ancestor a "
            "JOIN concept c ON c.concept_id = a.descendant_concept_id "
            "WHERE a.ancestor_concept_id = %s AND c.standard_concept = 'S'",
            (root,),
        )
        rows = cursor.fetchall()
        kept = [r for r in rows if not name_filter
                or name_filter.lower() not in r['concept_name'].lower()]
        if label == "blood_group":
            kept = [r for r in kept if "ABO" in r['concept_name']]
        print(f"\n{label} (root {root}): {len(rows)} descendants, {len(kept)} kept")
        for r in kept:
            print(f"  {r['concept_id']:>10}  {r['concept_name']}")
        if not kept:
            problems.append(f"{label} hierarchy resolves to no concepts")

    print("\n" + "=" * 78)
    print("Drug ingredients (getDrugIngredientCodes)")
    print("=" * 78)
    for name in INGREDIENTS:
        cursor.execute(
            "SELECT c.concept_id, COUNT(d.descendant_concept_id) AS products "
            "FROM concept c LEFT JOIN concept_ancestor d "
            "  ON d.ancestor_concept_id = c.concept_id AND d.min_levels_of_separation > 0 "
            "WHERE c.concept_class_id = 'Ingredient' AND lower(c.concept_name) = lower(%s) "
            "GROUP BY c.concept_id",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            print(f"  MISSING ingredient: {name}")
            problems.append(f"ingredient '{name}' not in the vocabulary")
        else:
            print(f"  {row['concept_id']:>10}  {name:<26} {row['products']} product(s)")
            if row['products'] == 0:
                problems.append(f"ingredient '{name}' has no descendant products")

    print("\n" + "=" * 78)
    print("Occasions the julia stage can model")
    print("=" * 78)
    # An "occasion" is a run of FVIII measurements no more than 3 days apart
    # (create_occasions! in src/lib/process.jl). The seed keeps occasions 60 days
    # apart, so grouping by measurement date is the same partition here.
    cursor.execute(
        "SELECT person_id, measurement_date, COUNT(*) AS osa "
        "FROM measurement WHERE measurement_concept_id = %s "
        "GROUP BY person_id, measurement_date HAVING COUNT(*) > 1 "
        "ORDER BY person_id, measurement_date",
        (FVIII_OSA,),
    )
    occasions = cursor.fetchall()
    cursor.execute(
        "SELECT DISTINCT person_id, measurement_date FROM measurement "
        "WHERE measurement_concept_id = %s", (BODY_WEIGHT,),
    )
    with_weight = {(r['person_id'], r['measurement_date']) for r in cursor.fetchall()}
    usable = [o for o in occasions if (o['person_id'], o['measurement_date']) in with_weight]
    print(f"  {len(occasions)} occasions with >1 FVIII one-stage measurement")
    print(f"  {len(usable)} of those also carry a weight measurement")
    for o in usable[:5]:
        print(f"    person {o['person_id']:>3}  {o['measurement_date']}  {o['osa']} measurements")
    if not usable:
        problems.append("no occasion has 2 FVIII measurements plus a weight - "
                        "main.jl has nothing to model")

    conn.close()

    print("\n" + "=" * 78)
    if problems:
        print("PROBLEMS")
        for p in problems:
            print(f"  - {p}")
        print("=" * 78 + "\n")
        return 1
    print("All pipeline prerequisites present.")
    print("=" * 78 + "\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
