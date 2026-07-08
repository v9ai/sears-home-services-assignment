# Minimal skeleton image — deployment-deliverables replaces this with a hardened
# multi-stage Next.js build (COORDINATION.md §3).
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
