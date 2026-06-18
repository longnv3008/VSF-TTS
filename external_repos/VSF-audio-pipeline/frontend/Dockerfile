FROM node:20-alpine

WORKDIR /app

RUN corepack enable

COPY frontend/package.json /app/package.json
RUN yarn install

COPY frontend /app

CMD ["yarn", "dev", "--host", "0.0.0.0", "--port", "5173"]
