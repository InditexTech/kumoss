FROM node:23

WORKDIR /app

COPY . /app

RUN npm install

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
