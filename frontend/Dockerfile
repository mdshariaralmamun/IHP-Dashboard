# Frontend image: Next.js 15 (output: 'standalone'), multi-stage build.

# ---- deps: install node_modules from the lockfile ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- builder: build the standalone production bundle ----
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
# .dockerignore excludes node_modules and .next, so this copies source only.
COPY . .
# API_URL is BAKED into the build: Next.js compiles the next.config rewrites
# (the /api/* -> backend proxy) into the standalone output. Leaving it unset
# here makes the container proxy to the dev fallback (localhost:8001) and
# every API call fails with ECONNREFUSED. Override with --build-arg if the
# backend is not reachable at this host name at runtime.
ARG API_URL=http://backend:8000
ENV API_URL=$API_URL
RUN npm run build

# ---- runner: minimal production image ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    API_URL=http://backend:8000

RUN addgroup -S nodejs && adduser -S nextjs -G nodejs

# Next.js standalone convention: the standalone output contains a minimal
# server.js plus its traced node_modules; static assets and public files
# must be copied alongside it.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
