FROM python:3.12-slim

WORKDIR /iris_analysis

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY iris_analysis /iris_analysis/

ENV PYTHONUNBUFFERED=1
EXPOSE 80