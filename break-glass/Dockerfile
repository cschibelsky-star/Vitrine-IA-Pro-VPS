FROM python:3.12-alpine

RUN addgroup -S breakglass && adduser -S -G breakglass breakglass
WORKDIR /app
COPY break-glass/app.py /app/app.py
USER breakglass
EXPOSE 8099
CMD ["python", "/app/app.py"]
