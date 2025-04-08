FROM python:3.12

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# hadolint ignore=DL3013,DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt install -y unixodbc \
    && pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir \
        pyodbc mariadb "sqlglot[rs]"

WORKDIR /app
COPY connector.py /app/

USER ${USER_UID}
ENTRYPOINT [ "python3", "connector.py" ]
