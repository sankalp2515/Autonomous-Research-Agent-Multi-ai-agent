# Veriscope frontend — build the Vite bundle, serve it with nginx, and proxy
# /api to the backend container. Result: the whole app lives at ONE URL, so a
# reviewer runs `docker compose --profile app up` and opens http://localhost:8080.
#
# Auth is optional: pass VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY as build
# args to enable sign-in. Omit them (the default) for a zero-config open demo.
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_ANON_KEY=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
