# The bundle is architecture-independent, so build it natively instead of
# under emulation when publishing multi-arch images.
FROM --platform=$BUILDPLATFORM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80 AS builder

COPY ./client/web /public

WORKDIR /public

RUN  npm ci && npm run build

FROM nginx@sha256:165ddde8751e75a1c907d24ef10d9f6deb08b57e0fe56caf67512486aff76d82

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /public/dist /public/dist

COPY ./client/web/favicon /public/favicon

