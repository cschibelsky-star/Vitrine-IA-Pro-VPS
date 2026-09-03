FROM python:3.12-alpine

RUN addgroup -S -g 8871 breakglass && adduser -S -D -H -u 8871 -G breakglass breakglass
WORKDIR /app
COPY break-glass/app.py /app/app.py
USER breakglass
EXPOSE 8099
CMD ["python", "/app/app.py"]
