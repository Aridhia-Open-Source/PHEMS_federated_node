ARG PYTHON_BASE_TAG=0.0.1
FROM ghcr.io/aridhia-open-source/python-base:${PYTHON_BASE_TAG}

WORKDIR /app

COPY liveness.py .

USER 1001

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "liveness.py"]
