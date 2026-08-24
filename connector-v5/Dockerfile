FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose git
WORKDIR /app
COPY connector-v5/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY connector-v5/main.py /app/main.py
EXPOSE 8000
CMD ["python","/app/main.py"]
