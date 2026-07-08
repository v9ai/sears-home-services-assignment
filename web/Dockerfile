# syntax=docker/dockerfile:1
#
# Multi-stage build for the Next.js frontend (web). Reused verbatim by both
# Docker Compose (local) and Cloudflare Containers (hosted, see wrangler.web.toml) —
# per tech-stack.md "Hosting (Cloudflare Containers)": no separate build path.

# ---- deps: install once, cached across code-only changes ------------------------
FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json ./
RUN npm install

# ---- builder: production build ---------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `public/` is optional in the skeleton; guarantee it exists so the runtime stage's
# COPY --from=builder below never fails on a missing path.
RUN mkdir -p ./public
RUN npm run build

# ---- prod-deps: production-only node_modules for the runtime image --------------
FROM node:20-alpine AS prod-deps

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

# ---- runtime: slim, non-root ------------------------------------------------------
FROM node:20-alpine AS runtime

RUN addgroup -S -g 1001 nodejs \
    && adduser -S -u 1001 -G nodejs nextjs \
    && apk add --no-cache wget

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=prod-deps --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/package.json /app/next.config.mjs ./

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD wget -q --spider http://localhost:3000/ || exit 1

CMD ["npm", "run", "start"]
