# The Dagster image built from dagster/Dockerfile (run_tests.sh builds it first)
FROM dagster_fn_base

ENV PYTHONDONTWRITEBYTECODE=1

# Dev extras (pytest, pytest-mock, pylint) and the fncli extra (its tests run here too)
RUN pip install --no-cache-dir -e ".[dev,cli]"
