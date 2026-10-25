# One-shot frontend build for deploy/docker-compose.yml (build context: frontend/).
# Needs frontend/package.json, frontend/package-lock.json and an `npm run build` that writes
# dist/. The app must call the API with relative URLs (/api/...), since Caddy serves the SPA
# and /api on the same origin; no API base URL is baked in.
FROM node:22.20.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Tiny runtime stage: replace the contents of the shared volume (/out) with dist/, then exit.
FROM alpine:3.22
COPY --from=build /app/dist /dist
CMD ["sh", "-c", "test -f /dist/index.html && find /out -mindepth 1 -delete && cp -a /dist/. /out/ && echo 'frontend: dist copied'"]
