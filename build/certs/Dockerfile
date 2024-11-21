FROM alpine/k8s:1.29.4

ENV VENV_DIR=/usr/venv
ENV CERTBOT_FOLDER=/app/.secrets/certbot
ENV RUNTIME_GRP=cert
ENV RUNTIME_USER=certuser
ENV USER_UID=1200
ENV USER_GID=1200

COPY requirements.txt /app/
WORKDIR /app

# hadolint detects pipenv as another invocation of pip
# And a file path is not found, most likely in the chown line
# hadolint ignore=SC1091
RUN apk update \
    && addgroup -g "${USER_GID}" "${RUNTIME_GRP}" \
    && adduser "${RUNTIME_USER}" -G "${RUNTIME_GRP}" -D -u "${USER_UID}" \
    && python3 -m venv "${VENV_DIR}" \
    && . "${VENV_DIR}"/bin/activate \
    && python3 -m pip install --no-cache-dir -r requirements.txt \
    && mkdir /etc/letsencrypt \
    && chown ${RUNTIME_USER}:${RUNTIME_GRP} -R /var/log /etc/letsencrypt /app

COPY --chown=${RUNTIME_USER}:${RUNTIME_USER} --chmod=755 scripts/*.sh /app/scripts/
USER ${USER_UID}

ENTRYPOINT [ "/app/scripts/azure.sh" ]
