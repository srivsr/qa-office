FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install && \
    npm uninstall @clerk/nextjs @clerk/clerk-react @clerk/backend @clerk/shared @clerk/types 2>/dev/null || true

COPY . .

RUN npm run build

EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
