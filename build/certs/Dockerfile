FROM alpine/k8s:1.29.4

ENV VENV_DIR=/usr/venv
ENV CERTBOT_FOLDER=/app/.secrets/certbot/

RUN apk update \
    && python3 -m venv "${VENV_DIR}" \
    && . "${VENV_DIR}"/bin/activate \
    && python3 -m pip install --no-cache-dir \
        certbot \
        pyopenssl \
        certbot-dns-azure \
        certbot-dns-route53

COPY --chmod=755 scripts/*.sh /app/scripts/

ENTRYPOINT [ "/app/scripts/azure.sh" ]
