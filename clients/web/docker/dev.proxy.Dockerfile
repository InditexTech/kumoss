FROM nginx@sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx/local.nginx.conf /etc/nginx/conf.d/default.conf
COPY favicon /public/favicon
