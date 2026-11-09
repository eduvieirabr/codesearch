FROM docker.io/library/python:3.13-slim AS build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.7
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM build AS test
RUN uv sync --frozen --no-editable --python /usr/local/bin/python
COPY tests ./tests
COPY scripts ./scripts
CMD ["/app/.venv/bin/pytest", "-q"]

FROM docker.io/library/python:3.13-slim
RUN groupadd --gid 10001 codesearch && useradd --uid 10001 --gid 10001 --create-home codesearch \
    && mkdir -p /data /workspace && chown 10001:10001 /data /workspace
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODESEARCH_WORKSPACE=/workspace \
    CODESEARCH_DATA_DIR=/data
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
ENTRYPOINT ["codesearch"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8090"]
