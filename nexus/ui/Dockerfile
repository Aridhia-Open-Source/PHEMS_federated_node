FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Unprivileged nginx listens on 8080 and runs as non-root (the chart's nonRootSC).
# NEXUS_API_URL is substituted into the config at start by the image's envsubst templates.
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV NEXUS_API_URL=http://nexus-api:5000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html/nexus-ui
EXPOSE 8080
