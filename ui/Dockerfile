# A2A travel demo UI — build the SPA, serve with nginx:alpine.
# Runtime config: config.js (from ui/public) is replaced at deploy time by
# a ConfigMap volume mount; see k8s/travel-ui/README.md.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# nginx unprivileged image: listens 8080, runs as uid 101, writes nothing
# to its rootfs — matches the deployment's securityContext.
COPY --from=0 /app/dist /usr/share/nginx/html
# SPA fallback (/auth/callback is client-handled) + no-cache for config.js.
RUN printf '%s\n' \
  'server {' \
  '  listen 8080;' \
  '  root /usr/share/nginx/html;' \
  '  index index.html;' \
  '  location = /config.js { add_header Cache-Control "no-cache"; }' \
  '  location / { try_files $uri $uri/ /index.html; }' \
  '}' > /etc/nginx/conf.d/default.conf
EXPOSE 8080
