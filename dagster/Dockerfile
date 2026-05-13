FROM python:3.12-slim

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# setup the dagster home directory
ENV DAGSTER_HOME=/opt/dagster/home
WORKDIR $DAGSTER_HOME

# Install locked third-party deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME"

# Copy package source (uses .dockerignore to limit scope)
COPY --chown=${USERNAME}:${USERNAME} . .

# Install package code in editable mode
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
USER ${USER_UID}
EXPOSE 80
