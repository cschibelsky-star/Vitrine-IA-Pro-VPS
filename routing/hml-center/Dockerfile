FROM python:3.12-alpine

WORKDIR /app
COPY app.py /app/app.py

RUN addgroup -S hml && adduser -S -G hml hml \
    && chown -R hml:hml /app

USER hml
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3).read()'

CMD ["python", "/app/app.py"]
