FROM python:3.12-slim

RUN pip install dagster-pipes

COPY entrypoint.py .
COPY main.py .

ENTRYPOINT [ "python3", "entrypoint.py" ]

