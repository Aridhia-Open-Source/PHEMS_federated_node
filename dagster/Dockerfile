FROM python:3.12-slim

# setup the dagster home directory
ENV DAGSTER_HOME=/opt/dagster/home
WORKDIR $DAGSTER_HOME

# Install locked third-party deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package source (uses .dockerignore to limit scope)
COPY . .

# Install package code in editable mode
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 80
