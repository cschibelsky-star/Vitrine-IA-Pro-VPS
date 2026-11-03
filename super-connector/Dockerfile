FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose git openssh-client bash
WORKDIR /app
COPY super-connector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY super-connector/main_v2.py /app/main.py
COPY super-connector/materialize_entrypoint.py /app/materialize_entrypoint.py
COPY super-connector/foundation_entrypoint.py /app/foundation_entrypoint.py
COPY super-connector/branding_entrypoint.py /app/branding_entrypoint.py
COPY super-connector/foundation /app/foundation
COPY super-connector/registry /app/registry-schema
COPY super-connector/capability-manifest.json /app/capability-manifest.json
EXPOSE 8000
CMD ["python", "/app/branding_entrypoint.py"]

# Preserve the deployed publication guard while correcting the HML registry binding.
FROM vitrine-publication-guard-super:20261010 AS hml_binding
COPY super-connector/foundation/recovery_ops.py /app/foundation/recovery_ops.py

# Review-only candidate: preserve the publication guard and stage the source
# catalog outside /app. Nothing here is registered as a live MCP tool.
# Promotion requires an explicit guard review and a separate approved deploy.
FROM hml_binding AS mcp_catalog_candidate
COPY super-connector/main_v2.py /opt/super-candidate/main.py
COPY super-connector/materialize_entrypoint.py /opt/super-candidate/materialize_entrypoint.py
COPY super-connector/foundation_entrypoint.py /opt/super-candidate/foundation_entrypoint.py
COPY super-connector/branding_entrypoint.py /opt/super-candidate/branding_entrypoint.py
COPY super-connector/foundation /opt/super-candidate/foundation
COPY super-connector/capability-manifest.json /opt/super-candidate/capability-manifest.json
RUN python -m compileall -q /opt/super-candidate
