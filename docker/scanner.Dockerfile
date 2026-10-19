# Inputs are prepared and hash-checked by scripts/build_scanner.py.
FROM python@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
COPY debs/ /tmp/debs/
RUN dpkg -i /tmp/debs/*.deb && rm -rf /tmp/debs
COPY wheels/ /tmp/wheels/
RUN pip install --no-index --no-deps /tmp/wheels/*.whl \
    && pip check && rm -rf /tmp/wheels
COPY engine/ /opt/ru-llm-scanner/engine/
COPY inventory.json /opt/ru-llm-scanner/build-inventory.json
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp TMPDIR=/tmp
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["ru-llm-scanner"]
