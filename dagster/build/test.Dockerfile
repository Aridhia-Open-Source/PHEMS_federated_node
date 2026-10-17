# The Dagster image built from dagster/Dockerfile (run_tests.sh builds it first)
FROM dagster_fn_base

ENV PYTHONDONTWRITEBYTECODE=1

# Dev extras (pytest, pytest-mock, pylint)
RUN pip install --no-cache-dir -e ".[dev]"
