FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    git \
    zip \
    curl \
    ca-certificates \
    github-cli

WORKDIR /app

COPY main.sh .

RUN chmod +x /app/main.sh

ENTRYPOINT ["/bin/bash", "/app/main.sh"]