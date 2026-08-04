#!/usr/bin/env python3
"""
Seed UC1 OMOP database with minimal synthetic data for testing.
Generates patients, visits, procedures, and conditions needed for cardiac benchmarking analysis.
"""

import sys
import argparse
import random
from datetime import date, timedelta
import psycopg2
from psycopg2.extras import execute_values


def connect_db(host, port, user, password, dbname):
    """Connect to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname
        )
        return conn
    except psycopg2.Error as e:
        print(f"ERROR: Failed to connect to database: {e}")
        sys.exit(1)


def seed_concepts(conn):
    """Insert required OMOP concepts for cardiac analysis."""
    cur = conn.cursor()

    # Visit type concepts
    visit_concepts = [
        (9201, 'Emergency Room', 'Visit'),
        (9202, 'Outpatient Visit', 'Visit'),
        (9203, 'Inpatient Hospital Stay', 'Visit'),
        (32037, 'Intensive Care Unit', 'Visit'),
    ]

    # Cardiac procedure concepts (simplified set for testing)
    procedure_concepts = [
        (2107359, 'Arterial Switch Operation', 'Procedure'),
        (4012932, 'Atrial Septal Defect Repair', 'Procedure'),
        (4031347, 'Norwood Procedure', 'Procedure'),
        (4019026, 'Coarctation of Aorta Repair', 'Procedure'),
        (4000619, 'Tetralogy of Fallot Repair', 'Procedure'),
        (4020370, 'Heart Transplant', 'Procedure'),
        (4018437, 'Fontan Procedure', 'Procedure'),
        (4019237, 'Glenn Procedure', 'Procedure'),
        (4017751, 'TAPVC Repair', 'Procedure'),
        (4019028, 'Vascular Ring Repair', 'Procedure'),
        (4018433, 'VSD Closure', 'Procedure'),
        (4017753, 'AVSD Repair', 'Procedure'),
    ]

    # Complication condition concepts
    condition_concepts = [
        (321042, 'Cardiac Arrest', 'Condition'),
        (4172822, 'Cardiac Arrest - Ventricular', 'Condition'),
        (4324124, 'Peritoneal Dialysis', 'Condition'),
        (607219, 'Cardiac Arrest - Asystole', 'Condition'),
        (439847, 'Intracranial Hemorrhage', 'Condition'),
        (4306136, 'Chylothorax', 'Condition'),
        (4308227, 'Necrotising Enterocolitis', 'Condition'),
        (4052536, 'Extracorporeal Membrane Oxygenation', 'Procedure'),
    ]

    # Gender concepts
    gender_concepts = [
        (8507, 'Male', 'Gender'),
        (8532, 'Female', 'Gender'),
    ]

    all_concepts = visit_concepts + procedure_concepts + condition_concepts + gender_concepts

    # Insert concepts with today's date as valid_start_date
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=999999)).isoformat()

    execute_values(
        cur,
        """
        INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id,
                           concept_class_id, standard_concept, concept_code,
                           valid_start_date, valid_end_date)
        VALUES %s
        ON CONFLICT (concept_id) DO NOTHING
        """,
        [
            (cid, name, domain, 'SNOMED', 'Clinical Finding', 'S',
             f"{cid:05d}", today, future)
            for cid, name, domain in all_concepts
        ]
    )

    # Insert self-referencing concept_ancestor rows (each concept is its own ancestor)
    execute_values(
        cur,
        """
        INSERT INTO concept_ancestor (ancestor_concept_id, descendant_concept_id,
                                     min_levels_of_separation, max_levels_of_separation)
        VALUES %s
        ON CONFLICT DO NOTHING
        """,
        [
            (cid, cid, 0, 0)
            for cid, _, _ in all_concepts
        ]
    )

    conn.commit()
    print(f"✓ Inserted {len(all_concepts)} concepts")
    cur.close()


def seed_patients(conn, num_patients=100):
    """Generate synthetic patients aged 0-17."""
    cur = conn.cursor()

    patients = []
    for pid in range(1, num_patients + 1):
        birth_year = 2006 + random.randint(0, 17)  # Ages 0-17 as of 2024
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        gender = random.choice([8507, 8532])  # Male or Female

        patients.append((
            pid,  # person_id
            gender,  # gender_concept_id
            birth_year,  # year_of_birth
            birth_month,  # month_of_birth
            birth_day,  # day_of_birth
            f"P{pid:06d}",  # person_source_value
        ))

    execute_values(
        cur,
        """
        INSERT INTO person (person_id, gender_concept_id, year_of_birth,
                          month_of_birth, day_of_birth, person_source_value)
        VALUES %s
        ON CONFLICT (person_id) DO NOTHING
        """,
        patients
    )

    conn.commit()
    print(f"✓ Inserted {num_patients} patients")
    cur.close()
    return num_patients


def seed_observation_periods(conn, num_patients):
    """Create observation periods for all patients."""
    cur = conn.cursor()

    obs_periods = []
    study_start = date(2019, 5, 1)
    today = date.today()

    for pid in range(1, num_patients + 1):
        # Each patient has observation period from study start to today
        obs_periods.append((
            pid,  # observation_period_id
            pid,  # person_id
            study_start.isoformat(),  # observation_period_start_date
            today.isoformat(),  # observation_period_end_date
        ))

    execute_values(
        cur,
        """
        INSERT INTO observation_period (observation_period_id, person_id,
                                       observation_period_start_date,
                                       observation_period_end_date)
        VALUES %s
        ON CONFLICT (observation_period_id) DO NOTHING
        """,
        obs_periods
    )

    conn.commit()
    print(f"✓ Inserted {num_patients} observation periods")
    cur.close()


def seed_visits(conn, num_patients):
    """Generate synthetic visits (admissions)."""
    cur = conn.cursor()

    visits = []
    visit_id = 1
    visit_types = [9201, 9202, 9203]  # ER, Outpatient, Inpatient
    study_start = date(2019, 5, 1)
    today = date.today()

    for pid in range(1, num_patients + 1):
        # 2-5 visits per patient
        num_visits = random.randint(2, 5)
        for _ in range(num_visits):
            visit_date = study_start + timedelta(days=random.randint(0, (today - study_start).days))
            visit_type = random.choice(visit_types)
            duration = random.randint(1, 30)
            end_date = visit_date + timedelta(days=duration)

            visits.append((
                visit_id,  # visit_occurrence_id
                pid,  # person_id
                visit_type,  # visit_concept_id
                visit_date.isoformat(),  # visit_start_date
                end_date.isoformat(),  # visit_end_date
                9201 if visit_type == 9201 else 9202,  # visit_type_concept_id
            ))
            visit_id += 1

    execute_values(
        cur,
        """
        INSERT INTO visit_occurrence (visit_occurrence_id, person_id, visit_concept_id,
                                     visit_start_date, visit_end_date, visit_type_concept_id)
        VALUES %s
        ON CONFLICT (visit_occurrence_id) DO NOTHING
        """,
        visits
    )

    conn.commit()
    print(f"✓ Inserted {visit_id - 1} visits")
    cur.close()
    return visit_id


def seed_procedures(conn, num_patients, next_visit_id):
    """Generate synthetic procedures (surgeries)."""
    cur = conn.cursor()

    procedures = []
    proc_id = 1
    cardiac_procedures = [
        2107359, 4012932, 4031347, 4019026, 4000619, 4020370,
        4018437, 4019237, 4017751, 4019028, 4018433, 4017753
    ]

    # Get all visits for random assignment
    cur.execute("SELECT visit_occurrence_id, person_id, visit_start_date FROM visit_occurrence")
    visits = cur.fetchall()

    for _ in range(num_patients * 2):  # ~2 procedures per patient on average
        if not visits:
            break
        visit_id, pid, visit_date = random.choice(visits)
        proc_date = visit_date
        proc_type = random.choice(cardiac_procedures)

        procedures.append((
            proc_id,  # procedure_occurrence_id
            pid,  # person_id
            proc_type,  # procedure_concept_id
            proc_date,  # procedure_date
            9201,  # procedure_type_concept_id
            visit_id,  # visit_occurrence_id
        ))
        proc_id += 1

    execute_values(
        cur,
        """
        INSERT INTO procedure_occurrence (procedure_occurrence_id, person_id,
                                         procedure_concept_id, procedure_date,
                                         procedure_type_concept_id, visit_occurrence_id)
        VALUES %s
        ON CONFLICT (procedure_occurrence_id) DO NOTHING
        """,
        procedures
    )

    conn.commit()
    print(f"✓ Inserted {proc_id - 1} procedures")
    cur.close()


def seed_conditions(conn, num_patients):
    """Generate synthetic conditions/complications."""
    cur = conn.cursor()

    conditions = []
    cond_id = 1
    complications = [321042, 4172822, 4324124, 607219, 439847, 4306136, 4308227, 4052536]

    # Get all visits for random assignment
    cur.execute("SELECT visit_occurrence_id, person_id, visit_start_date FROM visit_occurrence")
    visits = cur.fetchall()

    for _ in range(num_patients):  # ~1 condition per patient on average
        if not visits:
            break
        visit_id, pid, visit_date = random.choice(visits)
        cond_date = visit_date + timedelta(days=random.randint(0, 10))
        cond_type = random.choice(complications)

        conditions.append((
            cond_id,  # condition_occurrence_id
            pid,  # person_id
            cond_type,  # condition_concept_id
            cond_date,  # condition_start_date
            9201,  # condition_type_concept_id
            visit_id,  # visit_occurrence_id
        ))
        cond_id += 1

    execute_values(
        cur,
        """
        INSERT INTO condition_occurrence (condition_occurrence_id, person_id,
                                         condition_concept_id, condition_start_date,
                                         condition_type_concept_id, visit_occurrence_id)
        VALUES %s
        ON CONFLICT (condition_occurrence_id) DO NOTHING
        """,
        conditions
    )

    conn.commit()
    print(f"✓ Inserted {cond_id - 1} conditions")
    cur.close()


def main():
    parser = argparse.ArgumentParser(description='Seed UC1 OMOP database with synthetic data')
    parser.add_argument('--host', default='localhost', help='Database host')
    parser.add_argument('--port', type=int, default=5432, help='Database port')
    parser.add_argument('--user', default='uc1_omop_user', help='Database user')
    parser.add_argument('--password', required=True, help='Database password (REQUIRED)')
    parser.add_argument('--dbname', default='uc1_omop', help='Database name')
    parser.add_argument('--num-patients', type=int, default=100, help='Number of synthetic patients')

    args = parser.parse_args()

    # Validate required arguments
    if not args.password:
        print("ERROR: --password argument is required", file=sys.stderr)
        sys.exit(1)

    if args.num_patients <= 0:
        print(f"ERROR: --num-patients must be > 0, got {args.num_patients}", file=sys.stderr)
        sys.exit(1)

    if args.port <= 0 or args.port > 65535:
        print(f"ERROR: --port must be between 1-65535, got {args.port}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {args.host}:{args.port}/{args.dbname}...")
    conn = connect_db(args.host, args.port, args.user, args.password, args.dbname)

    try:
        print("\n=== Seeding UC1 OMOP Database ===\n")
        seed_concepts(conn)
        num_patients = seed_patients(conn, args.num_patients)
        seed_observation_periods(conn, num_patients)
        next_visit_id = seed_visits(conn, num_patients)
        seed_procedures(conn, num_patients, next_visit_id)
        seed_conditions(conn, num_patients)

        print("\n✓ UC1 OMOP database seeded successfully!")

    except psycopg2.Error as e:
        print(f"\nERROR during seeding: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
