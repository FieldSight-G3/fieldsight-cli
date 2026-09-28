# Supply a base image pinned to its sha256 digest at build time.
ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE} AS builder

ARG PYTHON_BASE_IMAGE
RUN case "$PYTHON_BASE_IMAGE" in *@sha256:*) :;; *) echo 'PYTHON_BASE_IMAGE must include a sha256 digest' >&2; exit 1;; esac
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG PYTHON_BASE_IMAGE
RUN case "$PYTHON_BASE_IMAGE" in *@sha256:*) :;; *) echo 'PYTHON_BASE_IMAGE must include a sha256 digest' >&2; exit 1;; esac
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels fieldsight \
    && rm -rf /wheels \
    && useradd --create-home --uid 10001 fieldsight
USER 10001
WORKDIR /home/fieldsight
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "fieldsight.tool_runtime:create_production_app()"]
