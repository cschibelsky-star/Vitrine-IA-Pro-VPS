FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VITRINE_OPS_API_VERSION=0.1.0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
        openssh-client \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && docker --version \
    && docker compose version \
    && rm -rf /var/lib/apt/lists/*

COPY ops-api/requirements.txt /app/ops-api/requirements.txt
RUN pip install --no-cache-dir -r /app/ops-api/requirements.txt

COPY project-manager /app/project-manager
COPY project-manager/manifests /app/project-manifests
COPY ops-api /app/ops-api

WORKDIR /app/ops-api

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
