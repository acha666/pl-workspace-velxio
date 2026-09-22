FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /tests
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY smoke.mjs ./
CMD ["node", "smoke.mjs", "blink"]
