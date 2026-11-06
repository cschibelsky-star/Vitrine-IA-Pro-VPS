FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py bridge.py oauth_provider.py healthcheck.py ./
ENV PORT=8765 AVELLO_CALLS_ENABLED=false
RUN mkdir -p /data && chown 65532:65532 /data
USER 65532:65532
EXPOSE 8765
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--no-access-log"]

