# The bundle is architecture-independent, so build it natively instead of
# under emulation when publishing multi-arch images.
FROM --platform=$BUILDPLATFORM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80 AS builder

COPY ./client/web /public

WORKDIR /public

RUN  npm ci && npm run build

# Keep the tag next to the digest so the nginx version is visible in reviews
# and scans (the digest alone is what Docker resolves). 1.31.9 fixes the
# HTTP/2 CVE-2026-123007 "nginx2root" (affects 1.9.5-1.31.8).
FROM nginx:1.31.9@sha256:08f354a3b44c422021a5c0f5efb3e27f8f90236b5447d3bac4053f5f50ab6760

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /public/dist /public/dist

COPY ./client/web/favicon /public/favicon

