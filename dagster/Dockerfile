FROM python:3.12-slim

ENV DAGSTER_HOME=/opt/dagster/home/
WORKDIR $DAGSTER_HOME

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY iris_analysis .
COPY dagster.yaml .

ENV PYTHONUNBUFFERED=1
EXPOSE 80
