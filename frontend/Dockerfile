FROM node:20-bookworm-slim
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund --include=optional
COPY . .
EXPOSE 5173
CMD ["npm","run","dev"]
