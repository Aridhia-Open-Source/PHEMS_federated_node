#!/usr/bin/env python3
"""Generate a self-contained OMOP CDM v5.4 schema + synthetic dataset SQL file
that exercises the whole UC1 cardiac benchmarking pipeline (CodeToRun.R).

The DDL is generated from omopgenerics' own 5.4 field specification
(`omopgenerics:::fieldsTables[["5.4"]]`, exported to fields54.csv) so the
column names/types are exactly what CDMConnector validates against.

The data is fully deterministic (no RNG): every cohort and every stratum the
R code builds gets comfortably more than min_cell_count = 5 patients, so
nothing important is suppressed out of the results.

Usage:  python3 generate_synthetic_cdm.py fields54.csv > omop_synthetic_cdm.sql
"""

import csv
import sys
from datetime import date, timedelta

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

# Required cardiac operations ("base cohort" ancestors) -- generate_codelists.R
MANUAL_OP_CONCEPT_IDS = [
    4336751, 4308136, 4196823, 4017751, 4187380, 44805913, 4199899, 4178479, 4018441, 4203153,
    4020520, 4323509, 44790415, 4018747, 44511291, 4019237, 4049734, 4021725, 44512017, 19025274,
    4137127, 4019929, 4049979, 40486525, 4020376, 4232476, 44789857, 44793133, 4020506, 42872796,
    4020508, 44790092, 44510968, 4293619, 4339184, 4296790, 4139214, 4144921, 44511949, 4020812,
    4019028, 4217615, 4052536,
]
ALL_OP_REMOVE_CONCEPTS = [4178623, 4338731, 43747361]
ECMO_CONCEPT_ID = 4052536

# Focus operation cohorts -- one entry per group, mirroring focus_ops_codelist.
# The representative code (first element) is what the synthetic procedures use;
# every other code is still created in `concept` so conceptCohort() resolves the
# full codelist without dropping unknown concepts.
FOCUS_OPS = {
    "Arterial switch operation": [
        4196823, 2107359, 2107360, 2107375, 2107376, 2107377, 2107378, 4019932, 4077745, 4122006,
        4217722, 4286184, 4328241, 40756865, 40756882, 44511408],
    "Atrial septal defect repair": [
        44805913, 2107271, 4012932, 4018430, 4020376, 4039864, 4054814, 4069636, 4146227, 4146733,
        4147581, 4147709, 4148834, 4150386, 4151156, 4186747, 4205155, 4219986, 4281072, 4325108,
        4337317, 4337440, 37151413, 44511434],
    "Norwood/ Sano Procedure - HLHS (Stage 1)": [
        44793133, 2107270, 4031347, 4050560, 4329367, 40482202, 40756929],
    "Coarctation of aorta": [
        4020812, 2107405, 4019026, 4019027, 4021743, 4049478, 4105220, 4158900, 4183605, 4327880,
        37311675, 44512011, 44512017],
    "Repair of Tetralogy of Fallot": [
        4308136, 2107305, 2107306, 4000619, 4017746, 4017748, 4019929, 4048531, 4105579, 4137534,
        4175022, 4184315, 4206483, 4265767, 4267710, 4286812, 4322960, 4326252, 4327798, 4338732,
        40488996, 44511398, 44790296],
    "Heart transplant": [
        4336751, 4020370, 4137127, 4187247, 4228489, 4337309, 44511390],
    "Truncus arterious repair": [
        4215602, 4036615, 4050113, 4225412, 4264274, 4264715, 4313301, 44511283],
    "Fontan procedure/ Total Cavopulmonary Connection/ TCPC": [
        44789857, 4018437, 4049087, 4050559, 4322710, 44789858],
    "Glenn/ BCPC": [
        4019237, 4050122, 4051948, 40482697, 40484186, 40484569, 40484605, 40485436, 40487665,
        40491942],
    "Total anomalous pulmonary venous connection/ TAPVC repair/ TAPVD": [
        4017751, 4018425, 4019934, 4019935, 4031920, 4083543, 4196951, 4221305, 4225140, 4239234,
        40479326, 40480161, 40480989, 40481027, 40481443, 40481446, 40482836, 40483226, 40485434,
        40485479, 44511413],
    "Vascular ring repair": [4019028],
    "VSD closure": [
        4199899, 2001471, 2001473, 4018433, 4020378, 4051041, 4213864, 4232394, 4232476, 4254234,
        4261388, 4307508, 4323071, 4323638, 4338300, 4338731, 40481831, 40487946, 44511443],
    "Atrioventricular septal defect repair": [
        4187380, 4017753, 4017862, 4018427, 4178577, 4200561, 4337443, 4338615, 37158840, 37158841,
        37158842, 37158844, 40486525, 40487051, 44511427, 44783044],
}

# Seizure concepts that must be discoverable by
# getCandidateCodes(keywords = "Seizure", domains = "Condition").
SEIZURE_CONCEPTS = {
    377091: "Seizure",
    4076779: "Febrile seizure",
    443454: "Generalized tonic-clonic seizure",
    4046219: "Acquired epileptic aphasia with seizure",  # explicitly excluded by the R code
}

# Complication concepts, keyed as in complications_codelist. Domain matters:
# conceptCohort() routes each concept to the clinical table for its domain.
CARDIAC_ARREST_IDS = [321042, 4172822, 4301015, 607219, 4173446, 4306984, 4311273, 607220,
                      761738, 317669, 4120088, 4128968, 764719, 4106274]
COMPLICATION_CONCEPTS = {
    # concept_id: (name, domain)
    4324124: ("Peritoneal dialysis", "Procedure"),
    4308227: ("Necrotizing enterocolitis", "Condition"),
    439847: ("Intracranial hemorrhage", "Condition"),
    4306136: ("Chylothorax", "Condition"),
}
for cid in CARDIAC_ARREST_IDS:
    COMPLICATION_CONCEPTS[cid] = ("Cardiac arrest", "Condition")

VISIT_CONCEPTS = {
    9201: "Inpatient Visit",
    9202: "Outpatient Visit",
    9203: "Emergency Room Visit",
    262: "Emergency Room and Inpatient Visit",
    32037: "Intensive care",
}

TYPE_CONCEPT = 32817          # "EHR"
GENDER = {8507: "MALE", 8532: "FEMALE"}
RACE_CONCEPT = 8527           # "White"
ETHNICITY_CONCEPT = 38003564  # "Not Hispanic or Latino"
CDM_VERSION_CONCEPT = 756265  # "CDM Version 5.4"

# The 7 complication groups the R code reports on, with the concept used in the
# synthetic data and the table it lands in.
COMPLICATION_ASSIGNMENT = [
    ("Extracorporeal membrane oxygenation", ECMO_CONCEPT_ID, "procedure"),
    ("Peritoneal dialysis", 4324124, "procedure"),
    ("Cardiac arrest", 321042, "condition"),
    ("Necrotising enterocolitis", 4308227, "condition"),
    ("Seizure", 377091, "condition"),
    ("Intracranial hemorrhage", 439847, "condition"),
    ("Chylothorax", 4306136, "condition"),
]


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
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


def build_concepts():
    """Return {concept_id: (name, domain, vocabulary, concept_class, standard)}."""
    c = {}

    def add(cid, name, domain, vocab, cclass, standard="S"):
        c[cid] = (name, domain, vocab, cclass, standard)

    # cardiac operations: the required-operation ancestors plus every focus-op code
    for i, cid in enumerate(MANUAL_OP_CONCEPT_IDS):
        add(cid, f"Cardiac operation {i + 1}", "Procedure", "SNOMED", "Procedure")
    add(ECMO_CONCEPT_ID, "Extracorporeal membrane oxygenation", "Procedure", "SNOMED", "Procedure")
    for group, ids in FOCUS_OPS.items():
        for n, cid in enumerate(ids):
            if cid not in c:
                add(cid, f"{group} - code {n + 1}", "Procedure", "SNOMED", "Procedure")
    # concepts the R code explicitly removes must still exist
    for cid in ALL_OP_REMOVE_CONCEPTS:
        if cid not in c:
            add(cid, f"Excluded cardiac procedure {cid}", "Procedure", "SNOMED", "Procedure")

    for cid, name in SEIZURE_CONCEPTS.items():
        add(cid, name, "Condition", "SNOMED", "Clinical Finding")
    for cid, (name, domain) in COMPLICATION_CONCEPTS.items():
        cclass = "Procedure" if domain == "Procedure" else "Clinical Finding"
        add(cid, name, domain, "SNOMED", cclass)
    for cid, name in VISIT_CONCEPTS.items():
        add(cid, name, "Visit", "Visit", "Visit")
    for cid, name in GENDER.items():
        add(cid, name, "Gender", "Gender", "Gender")
    add(RACE_CONCEPT, "White", "Race", "Race", "Race")
    add(ETHNICITY_CONCEPT, "Not Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity")
    add(TYPE_CONCEPT, "EHR", "Type Concept", "Type Concept", "Type Concept")
    add(CDM_VERSION_CONCEPT, "CDM Version 5.4", "Metadata", "Metadata", "CDM")
    add(0, "No matching concept", "Metadata", "None", "Undefined", None)
    return c


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
    vrows = []
    for i, v in enumerate(vocabs):
        vrows.append((v, v, "synthetic", "SYNTHETIC v1.0", 5200 + i))
    # OmopSketch reads the CDM vocabulary version from vocabulary_id = 'None'
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

    # Every concept is its own ancestor: getDescendants() then resolves each
    # required-operation code to itself, which is what the codelists expect.
    arows = [(cid, cid, 0, 0) for cid in sorted(concepts) if cid != 0]
    out.append(insert("concept_ancestor", ["ancestor_concept_id", "descendant_concept_id",
                                           "min_levels_of_separation",
                                           "max_levels_of_separation"], arows))

    # "Maps to" self-mappings keep CodelistGenerator's standard/non-standard
    # lookups happy without introducing extra codes.
    rrows = [(cid, cid, "Maps to", vs, ve, None) for cid in sorted(concepts)
             if cid != 0 and concepts[cid][4] == "S"]
    out.append(insert("concept_relationship", ["concept_id_1", "concept_id_2", "relationship_id",
                                               "valid_start_date", "valid_end_date",
                                               "invalid_reason"], rrows))

    srows = [(cid, concepts[cid][0], 4180186) for cid in sorted(concepts) if cid != 0]
    out.append(insert("concept_synonym",
                      ["concept_id", "concept_synonym_name", "language_concept_id"], srows))

    out.append(insert("cdm_source",
                      ["cdm_source_name", "cdm_source_abbreviation", "cdm_holder",
                       "source_description", "source_release_date", "cdm_release_date",
                       "cdm_version", "cdm_version_concept_id", "vocabulary_version"],
                      [("Synthetic Cardiac Test CDM", "SYNTH", "MVP-Code test data",
                        "Deterministic synthetic data for the UC1 cardiac benchmarking pipeline",
                        date(2025, 1, 1), date(2025, 1, 1), "5.4", CDM_VERSION_CONCEPT,
                        "SYNTHETIC v1.0")]))
    return "\n".join(out)


# ------------------------------------------------------------- patients -----

N_PER_OP_YEAR = 16          # patients per (operation, year) cell -> > min_cell_count
YEARS = [2020, 2021, 2022, 2023]
OBS_END = date(2024, 12, 31)


def emit_patients(concepts):
    groups = list(FOCUS_OPS.items())
    persons, obs, visits, vdetails, procs, conds, deaths = [], [], [], [], [], [], []

    pid = 0
    vo_id = 0
    vd_id = 0
    po_id = 0
    co_id = 0

    for year in YEARS:
        for g_index, (group, codes) in enumerate(groups):
            op_concept = codes[0]
            for k in range(N_PER_OP_YEAR):
                pid += 1
                i = pid  # single deterministic driver for all per-patient variation

                # --- index operation -------------------------------------------
                proc_date = date(year, 1 + (i % 12), 1 + (i % 28))
                age = i % 18                                    # 0..17 -> passes requireAge
                birth_date = proc_date - timedelta(days=age * 365 + 40)

                # --- admission containing the operation -------------------------
                adm_start = proc_date - timedelta(days=i % 5)
                adm_end = proc_date + timedelta(days=3 + (i % 18))

                # --- reoperation within 30 days (~11% of patients) ---------------
                reop_date = None
                if i % 9 == 0:
                    reop_date = proc_date + timedelta(days=5 + (i % 20))
                    adm_end = max(adm_end, reop_date + timedelta(days=2))

                # --- death within 30 days, in hospital (~5% of patients) --------
                death_date = None
                if i % 20 == 0:
                    death_date = proc_date + timedelta(days=8 + (i % 15))
                    adm_end = max(adm_end, death_date)
                    deaths.append((pid, death_date, TYPE_CONCEPT))

                persons.append((pid, 8507 if i % 2 else 8532, birth_date.year,
                                birth_date.month, birth_date.day, RACE_CONCEPT,
                                ETHNICITY_CONCEPT, f"SYN-{pid}"))
                obs.append((pid, pid, birth_date, OBS_END, TYPE_CONCEPT))

                vo_id += 1
                inpatient_vo = vo_id
                visits.append((inpatient_vo, pid, 9201, adm_start, adm_end, TYPE_CONCEPT))

                po_id += 1
                procs.append((po_id, pid, op_concept, proc_date, TYPE_CONCEPT, inpatient_vo))
                if reop_date:
                    po_id += 1
                    procs.append((po_id, pid, op_concept, reop_date, TYPE_CONCEPT, inpatient_vo))

                # --- outpatient follow-up (1/3 of patients) ---------------------
                if i % 3 == 0:
                    for offset in (40, 100):
                        d = proc_date + timedelta(days=offset)
                        vo_id += 1
                        visits.append((vo_id, pid, 9202, d, d, TYPE_CONCEPT))

                # --- ICU stay in visit_detail (half of patients) ----------------
                if i % 2 == 0:
                    icu_start = proc_date
                    icu_end = proc_date + timedelta(days=1 + (i % 6))
                    vd_id += 1
                    vdetails.append((vd_id, pid, 32037, icu_start, icu_end, TYPE_CONCEPT,
                                     inpatient_vo))
                    # ICU readmission: second stay starting the day after the first
                    # ends, so it falls in the (-2, -1) intersect window.
                    if i % 10 == 0:
                        re_start = icu_end + timedelta(days=1)
                        re_end = re_start + timedelta(days=2)
                        adm_end = max(adm_end, re_end)
                        vd_id += 1
                        vdetails.append((vd_id, pid, 32037, re_start, re_end, TYPE_CONCEPT,
                                         inpatient_vo))
                        # keep the admission covering the readmission
                        for idx in range(len(visits) - 1, -1, -1):
                            if visits[idx][0] == inpatient_vo:
                                v = list(visits[idx])
                                v[4] = max(v[4], re_end)
                                visits[idx] = tuple(v)
                                break

                # --- one complication per patient, 1-30 days post-op ------------
                cname, ccid, ctable = COMPLICATION_ASSIGNMENT[i % len(COMPLICATION_ASSIGNMENT)]
                comp_date = proc_date + timedelta(days=3 + (i % 20))
                if ctable == "procedure":
                    po_id += 1
                    procs.append((po_id, pid, ccid, comp_date, TYPE_CONCEPT, inpatient_vo))
                else:
                    co_id += 1
                    conds.append((co_id, pid, ccid, comp_date, comp_date, TYPE_CONCEPT,
                                  inpatient_vo))

    out = ["-- ---------------------------------------------------------------------",
           f"-- Clinical data: {pid} patients, {len(groups)} focus operations x {len(YEARS)} years",
           "-- ---------------------------------------------------------------------"]
    out.append(insert("person", ["person_id", "gender_concept_id", "year_of_birth",
                                 "month_of_birth", "day_of_birth", "race_concept_id",
                                 "ethnicity_concept_id", "person_source_value"], persons))
    out.append(insert("observation_period",
                      ["observation_period_id", "person_id", "observation_period_start_date",
                       "observation_period_end_date", "period_type_concept_id"], obs))
    out.append(insert("visit_occurrence",
                      ["visit_occurrence_id", "person_id", "visit_concept_id", "visit_start_date",
                       "visit_end_date", "visit_type_concept_id"], visits))
    out.append(insert("visit_detail",
                      ["visit_detail_id", "person_id", "visit_detail_concept_id",
                       "visit_detail_start_date", "visit_detail_end_date",
                       "visit_detail_type_concept_id", "visit_occurrence_id"], vdetails))
    out.append(insert("procedure_occurrence",
                      ["procedure_occurrence_id", "person_id", "procedure_concept_id",
                       "procedure_date", "procedure_type_concept_id", "visit_occurrence_id"],
                      procs))
    out.append(insert("condition_occurrence",
                      ["condition_occurrence_id", "person_id", "condition_concept_id",
                       "condition_start_date", "condition_end_date", "condition_type_concept_id",
                       "visit_occurrence_id"], conds))
    out.append(insert("death", ["person_id", "death_date", "death_type_concept_id"], deaths))
    return "\n".join(out)


def main():
    fields_csv = sys.argv[1] if len(sys.argv) > 1 else "fields54.csv"
    ddl, tables = emit_ddl(fields_csv)
    concepts = build_concepts()
    print("-- Generated by test_data/generate_synthetic_cdm.py -- do not edit by hand.")
    print(ddl)
    print(emit_vocabulary(concepts))
    print(emit_patients(concepts))
    print(f"\nANALYZE {CDM_SCHEMA}.person;")
    print(f"ANALYZE {CDM_SCHEMA}.visit_occurrence;")
    print(f"ANALYZE {CDM_SCHEMA}.procedure_occurrence;")
    print(f"ANALYZE {CDM_SCHEMA}.condition_occurrence;")


if __name__ == "__main__":
    main()
