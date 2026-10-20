# Inputs are prepared and hash-checked by scripts/build_scanner.py.
FROM python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
LABEL org.opencontainers.image.source="https://github.com/vovkins/ru-llm-scanner" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="Local sensitive-data scanner for Git repositories"
COPY debs/ /tmp/debs/
RUN dpkg -i /tmp/debs/*.deb && rm -rf /tmp/debs
COPY wheels/ /tmp/wheels/
COPY probe_runtime.py /tmp/probe_runtime.py
RUN pip install --no-index --no-deps /tmp/wheels/*.whl \
    && pip check \
    && PYTHONPATH=/tmp python -c "from probe_runtime import installed_packages, packaging_imports; packaging_imports(installed_packages())" \
    && rm -rf /tmp/wheels /tmp/probe_runtime.py /tmp/__pycache__
COPY engine/ /opt/ru-llm-scanner/engine/
COPY distribution-licenses/ /opt/ru-llm-scanner/licenses/
COPY inventory.json /opt/ru-llm-scanner/build-inventory.json
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp TMPDIR=/tmp
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["ru-llm-scanner"]
