# ShockTrace web (Next.js standalone build).
# Build from the repository root:
#   docker build -f infrastructure/docker/web.Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 .
FROM node:22-alpine AS deps
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /web
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_MAP_STYLE_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_MAP_STYLE_URL=$NEXT_PUBLIC_MAP_STYLE_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S web && adduser -S web -G web
COPY --from=build --chown=web:web /web/.next/standalone ./
COPY --from=build --chown=web:web /web/.next/static ./.next/static
COPY --from=build --chown=web:web /web/public ./public
USER web
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
