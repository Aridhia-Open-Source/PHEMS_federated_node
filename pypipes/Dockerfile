FROM python:3.12-slim

ARG USER_UID=1001
ARG USER_GID=1001

RUN pip install dagster-pipes

COPY entrypoint.py .
COPY main.py .

# Runs non-root deliberately: this is the reference analytical image, so it is what
# exercises the artifacts volume being writable by a non-root uid.
RUN groupadd -g "${USER_GID}" pipes \
    && useradd -u "${USER_UID}" -g "${USER_GID}" -M -s /usr/sbin/nologin pipes
USER ${USER_UID}

ENTRYPOINT [ "python3", "entrypoint.py" ]

