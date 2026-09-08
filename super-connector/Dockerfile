FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose git openssh-client bash
WORKDIR /app
COPY super-connector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY super-connector/main.py /app/main.py
COPY super-connector/emergency_executor.py /app/emergency_executor.py
COPY super-connector/registry /app/registry
ENV SUPER_REGISTRY_ROOT=/app/registry/projects \
    SUPER_LEGACY_V5_REGISTRY_ROOT=/legacy-v5-manifests \
    SUPER_PHP_RUNNER_IMAGE=vitrine-core-hml-app:latest
EXPOSE 8000
CMD ["python", "/app/main.py"]
