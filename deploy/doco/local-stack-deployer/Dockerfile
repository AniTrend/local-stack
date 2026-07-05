FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git bash docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
