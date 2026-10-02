FROM node:26-alpine AS builder

COPY ./client/web /public

WORKDIR /public

RUN  npm ci && npm run build

FROM nginx@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /public/dist /public/dist

COPY ./client/web/favicon /public/favicon

