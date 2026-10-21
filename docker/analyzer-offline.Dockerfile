# Source context and all inputs are verified before an offline build.
FROM __BASE__ AS scanner-analyzer
LABEL org.opencontainers.image.source="https://github.com/vovkins/ru-llm-scanner" \
      org.opencontainers.image.version="0.2.0" \
      org.opencontainers.image.description="Offline sensitive-data Analyzer for ru-llm-scanner"
COPY --chmod=u=rwX,go=rX offline/debs/ /tmp/debs/
RUN dpkg -i /tmp/debs/*.deb && rm -rf /tmp/debs
COPY --chmod=u=rwX,go=rX offline/wheels/ /tmp/wheels/
# Start with one clean package tree. Do not overlay new dist-info onto base pip.
RUN rm -rf /usr/local/lib/python3.11/site-packages \
    && mkdir /usr/local/lib/python3.11/site-packages \
    && PYTHONPATH=/tmp/wheels/pip-26.2.1-py3-none-any.whl \
       python -m pip install --no-index --no-deps /tmp/wheels/*.whl \
    && python -m pip check && rm -rf /tmp/wheels
WORKDIR /app
COPY --chmod=u=rwX,go=rX presidio/analyzer_server.py presidio/capacity.py presidio/entity_types.py ./
COPY --chmod=u=rwX,go=rX presidio/model_artifact.py presidio/result_merging.py presidio/text_chunking.py ./
COPY --chmod=u=rwX,go=rX presidio/real_model_smoke.py presidio/verify_cpu_runtime.py presidio/verify_gpu_runtime.py ./
COPY --chmod=u=rwX,go=rX presidio/recognizers/ ./recognizers/
COPY --chmod=u=rwX,go=rX presidio/ner/ ./ner/
COPY --chmod=u=rwX,go=rX offline/model/ /opt/models/ner_rus_bert-secret_detection/
COPY --chmod=u=rwX,go=rX scanner_build/probe_runtime.py /opt/scanner/probe_runtime.py
COPY --chmod=u=rwX,go=rX scanner_build/source-lock.json /opt/scanner/upstream.lock.json
COPY --chmod=u=rwX,go=rX litellm_guardrails/dictionary_policy.py /opt/scanner/dictionary_policy.py
COPY --chmod=u=rwX,go=rX litellm_guardrails/dictionary-substitutions.default.json /opt/scanner/dictionary.json
COPY --chmod=u=rwX,go=rX THIRD_PARTY_NOTICES.md /opt/scanner/THIRD_PARTY_NOTICES.md
COPY --chmod=u=rwX,go=rX distribution-licenses/ /opt/scanner/licenses/
COPY --chmod=u=rwX,go=rX offline/artifacts.lock.json /opt/scanner/offline-artifacts.lock.json
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1 \
    PRESIDIO_ANALYZER_DEVICE_PROFILE=cpu PRESIDIO_ANALYZER_GPU_PRECISION=fp32 \
    PRESIDIO_ANALYZER_NER_BATCH_SIZE=4 PRESIDIO_ANALYZER_WORKERS=1
# LOCKED_ANALYZER_ENVIRONMENT
RUN python verify_cpu_runtime.py \
    && python /opt/scanner/probe_runtime.py > /opt/scanner/build-provenance.json
EXPOSE 5001
CMD ["uvicorn", "analyzer_server:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "1"]

FROM scanner-analyzer AS analyzer-test
COPY --chmod=u=rwX,go=rX offline/test-wheels/ /tmp/test-wheels/
RUN python -m pip install --no-index --no-deps /tmp/test-wheels/*.whl \
    && python -m pip check && rm -rf /tmp/test-wheels
