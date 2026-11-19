# ---- build ----
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
# Сначала зависимости по lock-файлу (этот слой кэшируется, пока requirements.txt не меняется),
# потом сам пакет без зависимостей — версии берутся только из lock.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm /tmp/*.whl \
    && useradd --create-home --uid 1000 app
COPY config ./config
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "resto_analytics.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
