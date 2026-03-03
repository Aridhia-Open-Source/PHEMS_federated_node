FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    git \
    zip \
    curl \
    ca-certificates

RUN curl -fsSL https://github.com/cli/cli/releases/latest/download/gh_$(uname -m).apk -o gh.apk \
    && apk add --allow-untrusted gh.apk \
    && rm gh.apk

WORKDIR /app

COPY main.sh .

RUN chmod +x /app/main.sh

ENTRYPOINT ["/bin/bash", "/app/main.sh"]