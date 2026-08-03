#!/usr/bin/env python3
"""Read and display UC1 OMOP database contents."""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

LOCAL_DATASET_HOST = os.environ['LOCAL_DATASET_HOST']
LOCAL_DATASET_PORT = int(os.environ['LOCAL_DATASET_PORT'])
DATASET_NAME = os.environ['DATASET_NAME']
DATASET_USERNAME = os.environ['DATASET_USERNAME']
DATASET_PASSWORD = os.environ['DATASET_PASSWORD']

try:
    conn = psycopg2.connect(
        host=LOCAL_DATASET_HOST,
        port=LOCAL_DATASET_PORT,
        user=DATASET_USERNAME,
        password=DATASET_PASSWORD,
        dbname=DATASET_NAME
    )
except psycopg2.Error as e:
    print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
    sys.exit(1)

cursor = conn.cursor(cursor_factory=RealDictCursor)

tables = ['person', 'visit_occurrence', 'procedure_occurrence', 'condition_occurrence']

print("\n" + "="*80)
print("UC1 OMOP Database Summary")
print("="*80)

for table in tables:
    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
    count = cursor.fetchone()['count']
    print(f"{table:<30} {count:>8} rows")

print("\n" + "="*80)
print("Sample Data (first 5 rows per table)")
print("="*80)

for table in tables:
    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
    count = cursor.fetchone()['count']

    if count == 0:
        print(f"\n{table}: (empty)")
        continue

    print(f"\n{table}:")
    cursor.execute(f"SELECT * FROM {table} LIMIT 5")
    rows = cursor.fetchall()

    if rows:
        all_headers = list(rows[0].keys())

        non_null_cols = {}
        for row in rows:
            for col in all_headers:
                if row[col] is not None:
                    non_null_cols[col] = True

        headers = [h for h in all_headers if h in non_null_cols]
        col_widths = [max(len(h), 12) for h in headers]

        header_row = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
        print(f"  {header_row}")
        print("  " + "-" * (len(header_row) + 2))

        for row in rows:
            formatted = " | ".join(
                f"{str(row[h]):<{w}}"
                for h, w in zip(headers, col_widths)
            )
            print(f"  {formatted}")

conn.close()
print("\n" + "="*80 + "\n")
