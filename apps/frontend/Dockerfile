# ---------- Build stage: make static files ----------
FROM node:20-alpine AS builder
WORKDIR /app

# Add bash because Alpine doesn't have it, and your npm scripts want /bin/bash
RUN apk add --no-cache bash

# Copy only package files first for better Docker cache
COPY apps/frontend/package*.json ./
RUN npm ci

# Copy the rest of your frontend source
COPY apps/frontend ./

# Remove any env files to prevent overriding production values
RUN rm -f .env .env.* || true

# Create production env file
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN printf "VITE_API_URL=%s\n" "$VITE_API_URL" > .env.production

# Build Vite -> outputs static files in /app/dist
RUN npm run build

# ---------- Run stage: serve files with Nginx ----------
FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
# (SPA fallback)
COPY infra/nginx/frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
