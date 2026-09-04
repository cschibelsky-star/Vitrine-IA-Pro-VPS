FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VITRINE_OPS_API_VERSION=0.1.0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY ops-api/requirements.txt /app/ops-api/requirements.txt
RUN pip install --no-cache-dir -r /app/ops-api/requirements.txt

COPY project-manager /app/project-manager
COPY project-manager/manifests /app/project-manifests
COPY ops-api /app/ops-api

WORKDIR /app/ops-api

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
