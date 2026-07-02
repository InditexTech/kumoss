FROM node:18-alpine AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /build/dist /public/user_portal/dist

COPY favicon /public/favicon
