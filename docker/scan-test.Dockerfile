# Development scanner harness, separate from production packaging (stage 6).
FROM python@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir httpx==0.28.1 'jsonschema[format]==4.26.0'
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
