FROM node:24-alpine AS builder

COPY ./client/web /public

WORKDIR /public

RUN  npm ci && npm run build

FROM nginx@sha256:abe47724e466aeab9a345d8e46a221c2fa8953c7848bb4a3bd9976a7199f8cf2

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /public/dist /public/dist

COPY ./client/web/favicon /public/favicon

