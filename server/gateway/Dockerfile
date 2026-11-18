FROM python:3.12-slim
WORKDIR /app
COPY protocol/ /app/protocol/
COPY server/gateway/ /app/server/gateway/
RUN pip install --no-cache-dir /app/server/gateway
ENV PYTHONPATH=/app/server/gateway \
    PI_DELTA_SCHEMA=/app/protocol/pi-delta-v1.schema.json \
    PI_DELTA_DB=/app/data/sessions.sqlite
RUN useradd --system --home-dir /app --user-group delta && mkdir -p /app/data && chown -R delta:delta /app/data
USER delta
WORKDIR /app/server/gateway
CMD ["python", "-m", "pi_delta"]
