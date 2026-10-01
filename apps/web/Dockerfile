# Next.js console — multi-stage, standalone output.
# Build context is the repo root; the app lives in apps/web.
FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile


FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable pnpm && pnpm build


FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Runtime configuration — set on `docker run` / compose / K8s, never at build
# time, so this one image serves every deployment (no ENV defaults baked in):
#   SYNAPSE_API_URL           API origin as browsers reach it (required outside
#                             localhost; falls back to http://localhost:8000)
#   SYNAPSE_API_INTERNAL_URL  API origin as this server reaches it, for the
#                             GET /v1/branding fetch (defaults to SYNAPSE_API_URL)
# Branding (name, logo, colours) comes from the API at runtime. Probe /healthz.
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
