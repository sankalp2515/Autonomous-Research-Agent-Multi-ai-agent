# Veriscope frontend: build the Vite bundle, serve it with an UNPRIVILEGED
# nginx, and proxy /api to the backend. One image for compose and Cloud Run;
# nginx.conf is a template filled from env at start-up (PORT, API_UPSTREAM,
# API_HOST).
#
# Auth is optional: pass VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY as build
# args to enable sign-in. Both are public by design (the anon key is a client
# identifier, not a secret), which is why build-time baking is acceptable.
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_ANON_KEY=""
ARG VITE_SENTRY_DSN=""
ARG VITE_RELEASE="dev"
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_SENTRY_DSN=$VITE_SENTRY_DSN \
    VITE_RELEASE=$VITE_RELEASE

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# nginx-unprivileged runs as uid 101 and cannot bind below 1024, so the
# container never needs root (and listens on 8080, Cloud Run's default).
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV PORT=8080 \
    API_UPSTREAM=http://api:8000 \
    API_HOST=api
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/livez" || exit 1
