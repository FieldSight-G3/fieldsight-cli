# The AgentCore Runtime image: the LangGraph workflow behind /invocations and /ping on :8080.
# AgentCore Runtime runs linux/arm64 containers, so build with --platform linux/arm64.
# Supply a base image pinned to its sha256 digest at build time (a multi-arch index digest covers arm64).
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE} AS builder

ARG PYTHON_BASE_IMAGE
RUN case "$PYTHON_BASE_IMAGE" in *@sha256:*) :;; *) echo 'PYTHON_BASE_IMAGE must include a sha256 digest' >&2; exit 1;; esac
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
COPY deploy/runtime/runtime-requirements.txt ./
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels . -r runtime-requirements.txt

FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG PYTHON_BASE_IMAGE
RUN case "$PYTHON_BASE_IMAGE" in *@sha256:*) :;; *) echo 'PYTHON_BASE_IMAGE must include a sha256 digest' >&2; exit 1;; esac
COPY --from=builder /wheels /wheels
COPY deploy/runtime/runtime-requirements.txt /tmp/runtime-requirements.txt
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels fieldsight -r /tmp/runtime-requirements.txt \
    && rm -rf /wheels /tmp/runtime-requirements.txt \
    && useradd --create-home --uid 10001 fieldsight
# retrieval reads the corpus manifest (the letters of interpretation a chunk can cite) at runtime
COPY corpus/sources.json /home/fieldsight/corpus/sources.json
ENV FIELDSIGHT_CORPUS_SOURCES=/home/fieldsight/corpus/sources.json
USER 10001
WORKDIR /home/fieldsight
EXPOSE 8080
CMD ["python", "-m", "fieldsight.services.agent_runtime"]
