FROM python:3.12-slim

# PYTHONUNBUFFERED=1 is load-bearing: without it python buffers stdout, the
# container log file on the node stays empty, and the DaemonSet log agent has
# nothing to ship. Logs must leave the process immediately.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    OTEL_SERVICE_NAME=api \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

# Run as a non-root user: nothing here needs privileges.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
