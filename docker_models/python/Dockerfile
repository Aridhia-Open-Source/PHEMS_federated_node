FROM python:3.12-slim

RUN pip install dagster-pipes

COPY entrypoint.py .
COPY main.py .

ENV PYTHONUNBUFFERED=1

ENTRYPOINT [ "python3", "entrypoint.py" ]

