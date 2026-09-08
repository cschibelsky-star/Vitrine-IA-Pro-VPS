FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose git openssh-client bash
WORKDIR /app
COPY super-connector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY super-connector/main_v2.py /app/main.py
COPY super-connector/registry /app/registry-schema
EXPOSE 8000
CMD ["python", "/app/main.py"]
