ARG NODE_IMAGE=node:22-bookworm-slim
FROM ${NODE_IMAGE}

WORKDIR /app

COPY package*.json ./

# npm срывался посреди установки, но выходил с кодом 0 — образ уезжал без vite.
# npm ci ставит строго по лок-файлу; повтор с чистым кэшем закрывает срывы сети.
RUN npm config set fetch-retries 5 \
 && npm config set fetch-retry-mintimeout 20000 \
 && npm config set fetch-retry-maxtimeout 120000 \
 && (npm ci --include=dev --no-audit --no-fund \
     || (echo "Установка сорвалась, повтор с чистым кэшем" \
         && npm cache clean --force \
         && npm ci --include=dev --no-audit --no-fund))

# Тот же обрыв в следующий раз должен уронить сборку здесь, а не прод.
RUN test -x node_modules/.bin/vite

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
