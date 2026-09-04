FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose git openssh-client bash openssl
WORKDIR /app
COPY connector-v5/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY connector-v5/main.py /app/main.py
COPY connector-v5/main_ext.py /app/main_ext.py
COPY connector-v5/marketing_live_patch.py /app/marketing_live_patch.py
COPY connector-v5/production_publication.py /app/production_publication.py
EXPOSE 8000
CMD ["python","/app/main_ext.py"]
