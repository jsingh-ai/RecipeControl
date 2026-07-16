FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
ARG VITE_API_URL=/api
ARG VITE_ENABLE_LIVE_MODE=false
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_ENABLE_LIVE_MODE=${VITE_ENABLE_LIVE_MODE}
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -qO- http://127.0.0.1/health >/dev/null || exit 1
