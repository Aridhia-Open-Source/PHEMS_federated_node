#!/usr/bin/env python3
"""Generate a self-contained OMOP CDM v5.4 schema + synthetic dataset SQL file
that exercises the whole UC3 dose-interference pipeline
(uc3-dose-interference-model: src/lib/data/main.R then src/main.jl).

The DDL is generated from omopgenerics' own 5.4 field specification
(`omopgenerics:::fieldsTables[["5.4"]]`, exported to omop54_fields.csv) so the
column names/types are exactly what CDMConnector validates against - the same
spec the UC1 seed uses.

The data is fully deterministic (no RNG) and built backwards from what the
pipeline needs:

  * a vocabulary the R stage can actually search. UC3 does not carry a codelist:
    it discovers concepts at run time with CodelistGenerator (getCandidateCodes on
    keywords, getDescendants on LOINC hierarchy roots, getDrugIngredientCodes on
    ingredient names), so concept *names* here are what makes the pipeline find
    anything. Every codelist it builds must come back non-empty - newCodelist()
    errors on an empty element - which is why the excluded-by-design concepts and
    the Wilate/Haemate P products below are all present.

  * a haemophilia A cohort of children (conceptCohort + requireDemographics
    ageRange 0-18), each with FVIII activity measurements, weight, height, blood
    group and factor VIII administrations.

  * at least one (person, occasion) group shaped the way the julia stage needs:
    two FVIII one-stage-assay measurements 6 hours apart on a decaying profile,
    with a weight measurement inside the same occasion. That combination is what
    main.jl picks up and runs the MCMC on.

Usage:  python3 uc3_seed.py omop54_fields.csv > uc3_synthetic_cdm.sql
"""

import csv
import sys
from datetime import date, datetime, timedelta

CDM_SCHEMA = "cdm"
WRITE_SCHEMA = "results"

# ---------------------------------------------------------------- DDL -------

TYPE_MAP = {
    "integer": "integer",
    "bigint": "bigint",
    "float": "double precision",
    "date": "date",
    "datetime": "timestamp",
    "varchar(max)": "text",
    "logical": "boolean",
}


def sql_type(t):
    t = t.strip().lower()
    if t in TYPE_MAP:
        return TYPE_MAP[t]
    if t.startswith("varchar"):
        return t
    raise SystemExit(f"unmapped datatype: {t}")


def emit_ddl(fields_csv):
    rows = list(csv.DictReader(open(fields_csv)))
    tables = {}
    for r in rows:
        cols = tables.setdefault(r["cdm_table_name"], [])
        # the spec lists some fields twice (once per `type`), e.g. cohort
        if any(c["cdm_field_name"] == r["cdm_field_name"] for c in cols):
            continue
        cols.append(r)

    out = []
    out.append("-- =====================================================================")
    out.append("-- OMOP CDM v5.4 schema (generated from the omopgenerics field spec)")
    out.append("-- =====================================================================")
    out.append(f"DROP SCHEMA IF EXISTS {CDM_SCHEMA} CASCADE;")
    out.append(f"DROP SCHEMA IF EXISTS {WRITE_SCHEMA} CASCADE;")
    out.append(f"CREATE SCHEMA {CDM_SCHEMA};")
    out.append(f"CREATE SCHEMA {WRITE_SCHEMA};")
    out.append("")
    for table, cols in tables.items():
        defs = []
        for c in cols:
            null = " NOT NULL" if c["is_required"] == "TRUE" else ""
            defs.append(f'    "{c["cdm_field_name"]}" {sql_type(c["cdm_datatype"])}{null}')
        out.append(f"CREATE TABLE {CDM_SCHEMA}.{table} (")
        out.append(",\n".join(defs))
        out.append(");")
        out.append("")
    return "\n".join(out), sorted(tables)


# --------------------------------------------------------- vocabulary -------

# Conditions. cohort_concept_ids() searches Condition with
#   keywords c("factor VIII", "hemophilia")
#   exclude  c("actor IX", "actor XI", "arthropathy", "hemarthrosis",
#              "Hemorrhagic", "Willebrand", "multiple factor")
# and then drops names matching "emophilia B" / "factor V deficiency".
HAEM_A_PARENT = 55011
HAEM_A_SEVERITIES = {
    4051333: "Severe hereditary factor VIII deficiency disease",
    4051334: "Moderate hereditary factor VIII deficiency disease",
    4051335: "Mild hereditary factor VIII deficiency disease",
}
# Matched by the keywords, then thrown out again by the exclusions. They exist so
# the seed exercises the filtering rather than only the happy path: a person whose
# only record is one of these must not end up in the cohort.
EXCLUDED_CONDITIONS = {
    4239884: "Hemophilia B (hereditary factor IX deficiency disease)",
    4102493: "Arthropathy due to hemophilia",
    4344283: "von Willebrand disease with factor VIII deficiency",
}

# Measurements. measurement_concept_ids() searches Measurement with
#   keywords c("factor VIII", "von Willebrand activity", "von Willebrand antigen",
#              "desmopressin", "emicizumab")
#   exclude  c("mutation", "gene", "pathology")
# Downstream, get_fviii_act_concept_ids() keeps the lab codes whose names carry
# none of "overall" / "Willebrand" / "inhib", and process.jl then splits those into
# the chromogenic assay (name contains "chro") and the one-stage assay (the rest).
FVIII_OSA = 3013721      # one-stage assay -> `osa` in the julia stage
FVIII_CSA = 3034426      # chromogenic assay -> `csa`
VWF_ANTIGEN = 3002335
VWF_ACTIVITY = 3020813
LAB_CONCEPTS = {
    FVIII_OSA: "Coagulation factor VIII activity actual/normal in Platelet poor plasma by Coagulation assay",
    FVIII_CSA: "Coagulation factor VIII activity actual/normal in Platelet poor plasma by Chromogenic method",
    3010266: "Coagulation factor VIII inhibitor titer in Platelet poor plasma",
    3000724: "Coagulation factor VIII overall activity in Platelet poor plasma",
    VWF_ANTIGEN: "von Willebrand factor (vWf) antigen actual/normal in Platelet poor plasma",
    VWF_ACTIVITY: "von Willebrand factor (vWf) activity actual/normal in Platelet poor plasma",
}
FVIII_INHIBITOR = 3010266
# Excluded by the "mutation"/"gene" terms.
EXCLUDED_MEASUREMENTS = {
    3007111: "Factor VIII gene mutation analysis in Blood",
}

# LOINC hierarchy roots the R code walks with getDescendants(). Names of the
# descendants matter: weight/height drop anything matching "amputation", and blood
# group keeps only names containing "ABO".
WEIGHT_ROOT = 1003901
HEIGHT_ROOT = 1002881
BLOOD_GROUP_ROOT = 40782958
HIERARCHY_ROOTS = {
    WEIGHT_ROOT: "Body weight measurements",
    HEIGHT_ROOT: "Body height measurements",
    BLOOD_GROUP_ROOT: "Blood group measurements",
}
BODY_WEIGHT = 3025315
BODY_HEIGHT = 3036277
BLOOD_GROUP = 3005156
HIERARCHY_DESCENDANTS = {
    WEIGHT_ROOT: {
        BODY_WEIGHT: "Body weight",
        3013762: "Body weight measured after amputation",   # dropped by the R filter
    },
    HEIGHT_ROOT: {
        BODY_HEIGHT: "Body height",
        3036278: "Body height measured after amputation",   # dropped by the R filter
    },
    BLOOD_GROUP_ROOT: {
        BLOOD_GROUP: "ABO group [Type] in Blood",
        3005157: "Rh [Type] in Blood",                      # no "ABO", dropped
    },
}

# Drug ingredients, named exactly as drug_exposure_concept_ids() asks
# getDrugIngredientCodes() for them. Each needs at least one descendant product,
# or its codelist comes back empty and newCodelist() errors.
INGREDIENTS = {
    1517070: "Desmopressin",
    1301025: "Factor VIII",
    1759842: "Emicizumab",
    35604205: "efmoroctocog alfa",
    35604206: "damoctocog alfa pegol",
    35604207: "rurioctocog alfa pegol",
    35604208: "efanesoctocog alfa",
    35604209: "turoctocog alfa pegol",
}
# Found by keyword instead, via getCandidateCodes(keywords = c("Wilate", "Haemate P")).
FUSION_PRODUCTS = {
    45000101: "Wilate 500 UNT Injection",
    45000102: "Haemate P 1000 UNT Injection",
}

ROUTE_IV = 4171047
TYPE_CONCEPT = 32817          # "EHR"
GENDER = {8507: "MALE", 8532: "FEMALE"}
RACE_CONCEPT = 8527           # "White"
ETHNICITY_CONCEPT = 38003564  # "Not Hispanic or Latino"
CDM_VERSION_CONCEPT = 756265  # "CDM Version 5.4"


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.isoformat(sep=' ')}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def insert(table, cols, rows):
    if not rows:
        return ""
    out = [f"INSERT INTO {CDM_SCHEMA}.{table} ({', '.join(cols)}) VALUES"]
    vals = [f"  ({', '.join(q(v) for v in r)})" for r in rows]
    out.append(",\n".join(vals) + ";")
    return "\n".join(out) + "\n"


def ingredient_products():
    """{product_concept_id: (name, ingredient_concept_id)} - one product per ingredient."""
    products = {}
    for n, (ing_id, ing_name) in enumerate(sorted(INGREDIENTS.items())):
        products[45000001 + n] = (f"{ing_name} 250 UNT Injection", ing_id)
    return products


PRODUCTS = ingredient_products()
# The products the synthetic administrations use, in a stable order.
DOSED_PRODUCTS = sorted(PRODUCTS) + sorted(FUSION_PRODUCTS)


def build_concepts():
    """Return {concept_id: (name, domain, vocabulary, concept_class, standard)}."""
    c = {}

    def add(cid, name, domain, vocab, cclass, standard="S"):
        c[cid] = (name, domain, vocab, cclass, standard)

    add(HAEM_A_PARENT, "Hereditary factor VIII deficiency disease",
        "Condition", "SNOMED", "Clinical Finding")
    for cid, name in HAEM_A_SEVERITIES.items():
        add(cid, name, "Condition", "SNOMED", "Clinical Finding")
    for cid, name in EXCLUDED_CONDITIONS.items():
        add(cid, name, "Condition", "SNOMED", "Clinical Finding")

    for cid, name in LAB_CONCEPTS.items():
        add(cid, name, "Measurement", "LOINC", "Lab Test")
    for cid, name in EXCLUDED_MEASUREMENTS.items():
        add(cid, name, "Measurement", "LOINC", "Lab Test")
    for cid, name in HIERARCHY_ROOTS.items():
        # Classification concepts: searchable ancestors, never coded against.
        add(cid, name, "Measurement", "LOINC", "LOINC Hierarchy", "C")
    for root, descendants in HIERARCHY_DESCENDANTS.items():
        cclass = "Clinical Observation" if root != BLOOD_GROUP_ROOT else "Lab Test"
        for cid, name in descendants.items():
            add(cid, name, "Measurement", "LOINC", cclass)

    for cid, name in INGREDIENTS.items():
        add(cid, name, "Drug", "RxNorm", "Ingredient")
    for cid, (name, _) in PRODUCTS.items():
        add(cid, name, "Drug", "RxNorm", "Clinical Drug")
    for cid, name in FUSION_PRODUCTS.items():
        add(cid, name, "Drug", "RxNorm", "Clinical Drug")

    add(ROUTE_IV, "Intravenous", "Route", "SNOMED", "Qualifier Value")
    for cid, name in GENDER.items():
        add(cid, name, "Gender", "Gender", "Gender")
    add(RACE_CONCEPT, "White", "Race", "Race", "Race")
    add(ETHNICITY_CONCEPT, "Not Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity")
    add(TYPE_CONCEPT, "EHR", "Type Concept", "Type Concept", "Type Concept")
    add(CDM_VERSION_CONCEPT, "CDM Version 5.4", "Metadata", "Metadata", "CDM")
    add(0, "No matching concept", "Metadata", "None", "Undefined", None)
    return c


def concept_ancestor_rows(concepts):
    """Every concept is its own ancestor, plus the hierarchies the R code walks."""
    rows = [(cid, cid, 0, 0) for cid in sorted(concepts) if cid != 0]
    for root, descendants in HIERARCHY_DESCENDANTS.items():
        rows += [(root, cid, 1, 1) for cid in sorted(descendants)]
    # getCandidateCodes(includeDescendants = TRUE) on the haemophilia A parent.
    rows += [(HAEM_A_PARENT, cid, 1, 1) for cid in sorted(HAEM_A_SEVERITIES)]
    # getDrugIngredientCodes() resolves each ingredient to its products this way.
    rows += [(ing, cid, 1, 1) for cid, (_, ing) in sorted(PRODUCTS.items())]
    return rows


def emit_vocabulary(concepts):
    out = ["-- ---------------------------------------------------------------------",
           "-- Vocabulary tables",
           "-- ---------------------------------------------------------------------"]

    domains = sorted({v[1] for v in concepts.values()})
    out.append(insert("domain", ["domain_id", "domain_name", "domain_concept_id"],
                      [(d, d, 5000 + i) for i, d in enumerate(domains)]))

    classes = sorted({v[3] for v in concepts.values()})
    out.append(insert("concept_class",
                      ["concept_class_id", "concept_class_name", "concept_class_concept_id"],
                      [(k, k, 5100 + i) for i, k in enumerate(classes)]))

    vocabs = sorted({v[2] for v in concepts.values()})
    vrows = [(v, v, "synthetic", "SYNTHETIC v1.0", 5200 + i) for i, v in enumerate(vocabs)]
    # The CDM vocabulary version is read from vocabulary_id = 'None'.
    if "None" not in vocabs:
        vrows.append(("None", "OMOP Standardized Vocabularies", "synthetic",
                      "SYNTHETIC v1.0", 5299))
    out.append(insert("vocabulary", ["vocabulary_id", "vocabulary_name", "vocabulary_reference",
                                     "vocabulary_version", "vocabulary_concept_id"], vrows))

    out.append(insert("relationship",
                      ["relationship_id", "relationship_name", "is_hierarchical",
                       "defines_ancestry", "reverse_relationship_id", "relationship_concept_id"],
                      [("Subsumes", "Subsumes", "1", "1", "Is a", 5300),
                       ("Is a", "Is a", "1", "1", "Subsumes", 5301),
                       ("Maps to", "Maps to", "0", "0", "Mapped from", 5302),
                       ("Mapped from", "Mapped from", "0", "0", "Maps to", 5303)]))

    vs, ve = date(1970, 1, 1), date(2099, 12, 31)
    crows = []
    for cid, (name, domain, vocab, cclass, standard) in sorted(concepts.items()):
        crows.append((cid, name, domain, vocab, cclass, standard, f"SYN-{cid}", vs, ve, None))
    out.append(insert("concept", ["concept_id", "concept_name", "domain_id", "vocabulary_id",
                                  "concept_class_id", "standard_concept", "concept_code",
                                  "valid_start_date", "valid_end_date", "invalid_reason"], crows))

    out.append(insert("concept_ancestor", ["ancestor_concept_id", "descendant_concept_id",
                                           "min_levels_of_separation",
                                           "max_levels_of_separation"],
                      concept_ancestor_rows(concepts)))

    # "Maps to" self-mappings keep CodelistGenerator's standard/non-standard
    # lookups happy without introducing extra codes.
    rrows = [(cid, cid, "Maps to", vs, ve, None) for cid in sorted(concepts)
             if cid != 0 and concepts[cid][4] == "S"]
    out.append(insert("concept_relationship", ["concept_id_1", "concept_id_2", "relationship_id",
                                               "valid_start_date", "valid_end_date",
                                               "invalid_reason"], rrows))

    # searchInSynonyms = TRUE: give every concept its own name as a synonym.
    srows = [(cid, concepts[cid][0], 4180186) for cid in sorted(concepts) if cid != 0]
    out.append(insert("concept_synonym",
                      ["concept_id", "concept_synonym_name", "language_concept_id"], srows))

    out.append(insert("cdm_source",
                      ["cdm_source_name", "cdm_source_abbreviation", "cdm_holder",
                       "source_description", "source_release_date", "cdm_release_date",
                       "cdm_version", "cdm_version_concept_id", "vocabulary_version"],
                      [("Synthetic Haemophilia Test CDM", "SYNTH", "UC3 test data",
                        "Deterministic synthetic data for the UC3 dose interference pipeline",
                        date(2025, 1, 1), date(2025, 1, 1), "5.4", CDM_VERSION_CONCEPT,
                        "SYNTHETIC v1.0")]))
    return "\n".join(out)


# ------------------------------------------------------------- patients -----

N_COHORT = 30            # haemophilia A children, all fully instrumented
N_OCCASIONS = 3          # clinical visits per patient
OCCASION_GAP_DAYS = 60   # >> the 3-day window create_occasions! splits on
FIRST_OCCASION = date(2023, 1, 9)
OBS_END = date(2025, 12, 31)

BLOOD_GROUPS = ["O", "A", "B", "AB"]


def _person(pid, birth_date, gender):
    return (pid, gender, birth_date.year, birth_date.month, birth_date.day,
            RACE_CONCEPT, ETHNICITY_CONCEPT, f"SYN-{pid}")


def emit_patients():
    persons, obs, conds, meas, drugs = [], [], [], [], []
    co_id = mo_id = de_id = 0

    def measurement(pid, concept, when, value, unit=None, source_value=None):
        nonlocal mo_id
        mo_id += 1
        meas.append((mo_id, pid, concept, when.date(), when, TYPE_CONCEPT,
                     value, unit, source_value))

    def administration(pid, product, when, amount):
        nonlocal de_id
        de_id += 1
        drugs.append((de_id, pid, product, when.date(), when,
                      when.date(), when + timedelta(minutes=30), TYPE_CONCEPT,
                      amount, ROUTE_IV, "iu"))

    def condition(pid, concept, when):
        nonlocal co_id
        co_id += 1
        conds.append((co_id, pid, concept, when, when, TYPE_CONCEPT))

    severities = sorted(HAEM_A_SEVERITIES)

    for pid in range(1, N_COHORT + 1):
        i = pid
        # 8-15 years old over the measurement window, so requireDemographics'
        # ageRange = c(0, 18) keeps everyone.
        birth_date = date(2010 + (i % 6), 1 + (i % 12), 1 + (i % 28))
        persons.append(_person(pid, birth_date, 8532 if i % 10 == 0 else 8507))
        obs.append((pid, pid, birth_date, OBS_END, TYPE_CONCEPT))

        # Diagnosis in infancy: the cohort entry, comfortably inside the study
        # period (t0 = 1990-01-01) and before any measurement.
        diagnosis = date(birth_date.year + 1, birth_date.month, birth_date.day)
        condition(pid, severities[i % len(severities)], diagnosis)
        if i % 4 == 0:
            condition(pid, HAEM_A_PARENT, diagnosis + timedelta(days=30))
        # Comorbidities that the keyword exclusions must throw away.
        if i % 5 == 0:
            condition(pid, 4102493, diagnosis + timedelta(days=400))

        # One blood group record per patient; process.jl reads it from
        # value_source_value and only cares whether it starts with "O".
        first_occasion = FIRST_OCCASION + timedelta(days=i % 20)
        measurement(pid, BLOOD_GROUP, datetime.combine(first_occasion, datetime.min.time())
                    + timedelta(hours=8), None, None, BLOOD_GROUPS[i % 4])

        weight_kg = 20 + (i % 30)
        height_cm = 120 + (i % 40)

        for occasion in range(N_OCCASIONS):
            day = first_occasion + timedelta(days=OCCASION_GAP_DAYS * occasion)
            midnight = datetime.combine(day, datetime.min.time())

            # A dose the evening before and one first thing in the morning: the
            # timing the julia stage tries to recover. Its amount is inferred, so
            # what matters here is only that the administrations exist and fall in
            # this occasion.
            product = DOSED_PRODUCTS[(i + occasion) % len(DOSED_PRODUCTS)]
            administration(pid, product, midnight - timedelta(hours=4), 500 + 250 * (i % 4))
            administration(pid, product, midnight + timedelta(hours=7), 500 + 250 * (i % 4))

            # Two FVIII one-stage measurements, 6 hours apart on a decaying
            # profile. create_priors_inbetween_observations() reads that as "no
            # dose in between", which keeps the model to a single set of priors.
            trough = 0.80 + 0.05 * (i % 5)          # IU/mL
            osa_1 = midnight + timedelta(hours=9)
            osa_2 = midnight + timedelta(hours=15)
            measurement(pid, FVIII_OSA, osa_1, round(trough, 3), "iu/ml", str(round(trough, 3)))
            measurement(pid, FVIII_OSA, osa_2, round(trough / 2, 3), "iu/ml",
                        str(round(trough / 2, 3)))

            # Chromogenic assay alongside the second sample, at the same instant:
            # merge_osa_csa_rows! folds the pair into one row, so it does not read
            # as an extra measurement occasion.
            if i % 3 == 0:
                measurement(pid, FVIII_CSA, osa_2, round(trough / 2 + 0.02, 3), "iu/ml",
                            str(round(trough / 2 + 0.02, 3)))

            # Weight/height between the two samples, so they land in this
            # occasion: main.jl only models a group that has a weight.
            measurement(pid, BODY_WEIGHT, midnight + timedelta(hours=9, minutes=30),
                        weight_kg + occasion, "kg", str(weight_kg + occasion))
            measurement(pid, BODY_HEIGHT, midnight + timedelta(hours=9, minutes=35),
                        height_cm + occasion, "cm", str(height_cm + occasion))

            if i % 2 == 0:
                measurement(pid, VWF_ANTIGEN, midnight + timedelta(hours=9, minutes=10),
                            1.05, "iu/ml", "1.05")
                measurement(pid, VWF_ACTIVITY, midnight + timedelta(hours=9, minutes=15),
                            0.95, "iu/ml", "0.95")
            if i % 7 == 0:
                measurement(pid, FVIII_INHIBITOR, midnight + timedelta(hours=9, minutes=20),
                            0.4, "[bu]", "<0.6")

    # --- people the pipeline is expected to drop --------------------------------
    # Only haemophilia B: the keyword exclusions mean no cohort entry at all.
    for pid in range(N_COHORT + 1, N_COHORT + 4):
        birth_date = date(2012, 3, pid % 28 + 1)
        persons.append(_person(pid, birth_date, 8507))
        obs.append((pid, pid, birth_date, OBS_END, TYPE_CONCEPT))
        condition(pid, 4239884, date(birth_date.year + 1, 6, 1))
        measurement(pid, BODY_WEIGHT, datetime(2023, 6, 1, 10), 30, "kg", "30")

    # In the cohort, but no FVIII:act measurement - run_query() reports these as
    # dropped person ids.
    for pid in range(N_COHORT + 4, N_COHORT + 6):
        birth_date = date(2013, 5, pid % 28 + 1)
        persons.append(_person(pid, birth_date, 8507))
        obs.append((pid, pid, birth_date, OBS_END, TYPE_CONCEPT))
        condition(pid, severities[0], date(birth_date.year + 1, 6, 1))
        measurement(pid, BODY_WEIGHT, datetime(2023, 6, 1, 10), 28, "kg", "28")
        measurement(pid, BODY_HEIGHT, datetime(2023, 6, 1, 10, 5), 130, "cm", "130")
        measurement(pid, 3007111, datetime(2023, 6, 1, 10, 10), None, None, "detected")

    out = ["-- ---------------------------------------------------------------------",
           f"-- Clinical data: {len(persons)} people "
           f"({N_COHORT} in the haemophilia A cohort x {N_OCCASIONS} occasions)",
           "-- ---------------------------------------------------------------------"]
    out.append(insert("person", ["person_id", "gender_concept_id", "year_of_birth",
                                 "month_of_birth", "day_of_birth", "race_concept_id",
                                 "ethnicity_concept_id", "person_source_value"], persons))
    out.append(insert("observation_period",
                      ["observation_period_id", "person_id", "observation_period_start_date",
                       "observation_period_end_date", "period_type_concept_id"], obs))
    out.append(insert("condition_occurrence",
                      ["condition_occurrence_id", "person_id", "condition_concept_id",
                       "condition_start_date", "condition_end_date",
                       "condition_type_concept_id"], conds))
    out.append(insert("measurement",
                      ["measurement_id", "person_id", "measurement_concept_id",
                       "measurement_date", "measurement_datetime",
                       "measurement_type_concept_id", "value_as_number",
                       "unit_source_value", "value_source_value"], meas))
    out.append(insert("drug_exposure",
                      ["drug_exposure_id", "person_id", "drug_concept_id",
                       "drug_exposure_start_date", "drug_exposure_start_datetime",
                       "drug_exposure_end_date", "drug_exposure_end_datetime",
                       "drug_type_concept_id", "quantity", "route_concept_id",
                       "dose_unit_source_value"], drugs))
    return "\n".join(out)


def main():
    fields_csv = sys.argv[1] if len(sys.argv) > 1 else "omop54_fields.csv"
    ddl, _ = emit_ddl(fields_csv)
    print("-- Generated by dev.db/uc3_seed.py -- do not edit by hand.")
    print(ddl)
    print(emit_vocabulary(build_concepts()))
    print(emit_patients())
    for table in ("person", "observation_period", "condition_occurrence",
                  "measurement", "drug_exposure", "concept", "concept_ancestor"):
        print(f"ANALYZE {CDM_SCHEMA}.{table};")


if __name__ == "__main__":
    main()
