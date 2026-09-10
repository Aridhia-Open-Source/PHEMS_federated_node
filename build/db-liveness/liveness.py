"""
Database liveness check for task pods.
"""
import os
import sys
import time

import pyodbc


def check() -> int:
    connection_string = os.environ["CONNECTION_STRING"]
    retries = int(os.environ.get("DB_LIVENESS_RETRIES", "5"))
    backoff = int(os.environ.get("DB_LIVENESS_BACKOFF", "30"))
    timeout = int(os.environ.get("DB_LIVENESS_TIMEOUT", "30"))

    for attempt in range(retries):
        if attempt:
            wait = backoff * attempt
            print(f"Waiting {wait}s before attempt {attempt + 1}", flush=True)
            time.sleep(wait)
        try:
            connection = pyodbc.connect(connection_string, timeout=timeout)
            connection.cursor().execute("SELECT 1")
            connection.close()
            print(f"Database responded on attempt {attempt + 1}", flush=True)
            return 0
        except Exception as exc:  # any driver error here just means try again
            print(
                f"Attempt {attempt + 1}/{retries} failed: {exc}",
                file=sys.stderr,
                flush=True
            )

    print("Database still unreachable, giving up", file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(check())
