# Source context and all inputs are verified before an offline build.
FROM __BASE__ AS scanner-analyzer
COPY offline/debs/ /tmp/debs/
RUN dpkg -i /tmp/debs/*.deb && rm -rf /tmp/debs
COPY offline/wheels/ /tmp/wheels/
# Start with one clean package tree. Do not overlay new dist-info onto base pip.
RUN rm -rf /usr/local/lib/python3.11/site-packages \
    && mkdir /usr/local/lib/python3.11/site-packages \
    && PYTHONPATH=/tmp/wheels/pip-26.2.1-py3-none-any.whl \
       python -m pip install --no-index --no-deps /tmp/wheels/*.whl \
    && python -m pip check && rm -rf /tmp/wheels
WORKDIR /app
COPY presidio/analyzer_server.py presidio/capacity.py presidio/entity_types.py ./
COPY presidio/model_artifact.py presidio/result_merging.py presidio/text_chunking.py ./
COPY presidio/real_model_smoke.py presidio/verify_cpu_runtime.py presidio/verify_gpu_runtime.py ./
COPY presidio/recognizers/ ./recognizers/
COPY presidio/ner/ ./ner/
COPY offline/model/ /opt/models/ner_rus_bert-secret_detection/
COPY scanner_build/probe_runtime.py /opt/scanner/probe_runtime.py
COPY scanner_build/source-lock.json /opt/scanner/upstream.lock.json
COPY litellm_guardrails/dictionary_policy.py /opt/scanner/dictionary_policy.py
COPY litellm_guardrails/dictionary-substitutions.default.json /opt/scanner/dictionary.json
COPY THIRD_PARTY_NOTICES.md /opt/scanner/THIRD_PARTY_NOTICES.md
COPY offline/artifacts.lock.json /opt/scanner/offline-artifacts.lock.json
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
COPY offline/test-wheels/ /tmp/test-wheels/
RUN python -m pip install --no-index --no-deps /tmp/test-wheels/*.whl \
    && python -m pip check && rm -rf /tmp/test-wheels
