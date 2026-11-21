# One container: the FastAPI app with its templates, static files, config and prompts.
# Built from a clean `git archive` of HEAD by deploy/deploy.sh, so ignored files never reach the image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LAFAZ_DB=/app/data/lafaz.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
# Everything else the app reads (lafaz/, config/, prompts/, templates/, static/); .dockerignore keeps keys,
# state, tests and docs out.
COPY . .
# The data folder exists in the image so a fresh named volume mounted on it is owned by the app user.
RUN useradd --system --uid 10001 --home-dir /app lafaz && mkdir -p /app/data && chown lafaz:lafaz /app/data
USER lafaz
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "lafaz.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
