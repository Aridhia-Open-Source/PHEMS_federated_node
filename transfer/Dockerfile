FROM alpine:3.19

# Install required tools
RUN apk add --no-cache \
    bash \
    git \
    zip \
    curl \
    ca-certificates

# Install GitHub CLI
RUN curl -fsSL https://github.com/cli/cli/releases/latest/download/gh_$(uname -m).apk -o gh.apk \
    && apk add --allow-untrusted gh.apk \
    && rm gh.apk

# Set working directory
WORKDIR /app

# Copy transfer script
COPY github_push.sh .

# Make executable
RUN chmod +x /app/github_push.sh

# Entrypoint
ENTRYPOINT ["/bin/bash", "/app/github_push.sh"]