FROM node:22-alpine

WORKDIR /app

COPY vps-ops-plugin/package.json ./package.json
RUN npm install --omit=dev

COPY vps-ops-plugin/server.js ./server.js

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8181

EXPOSE 8181

CMD ["node", "server.js"]
