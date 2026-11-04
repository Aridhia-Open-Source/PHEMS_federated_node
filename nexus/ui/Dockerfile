FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
RUN npm run build

# Vite dev server for nexus.ui.devServer (chart) and Tilt, which syncs source into /app.
# Numeric user so the chart's runAsNonRoot can verify it; Vite writes its cache under /app.
FROM deps AS dev
COPY . .
RUN chown -R 1000:1000 /app
USER 1000
EXPOSE 5173
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]

# Unprivileged nginx listens on 8080 and runs as non-root (the chart's nonRootSC).
# NEXUS_API_URL is substituted into the config at start by the image's envsubst templates.
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV NEXUS_API_URL=http://nexus-api:5000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html/nexus-ui
EXPOSE 8080
