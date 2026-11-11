# ---- Frontend ----
FROM node:20-slim AS build
WORKDIR /app

# H5.1 / S2-27: `npm ci`, not `npm install`.
#
# `npm install` is allowed to update package-lock.json to satisfy the manifest,
# so a build could quietly resolve a different tree from the one committed and
# tested — the same reproducibility hole H1.2 closed on the Python side. `npm ci`
# installs the lock exactly and fails if the two disagree, which is what a build
# should do. `--legacy-peer-deps` stays: React 19 with antd 6 and react-leaflet 5
# needs it, and it is what the repository's own install instructions use.
COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . ./
RUN npm run build

# ---------- runtime ----------
# nginx-unprivileged rather than nginx:alpine. The stock image starts its master
# process as root, and root is not needed to serve static files. This one runs
# as uid 101 throughout and listens on 8080, because a non-root process cannot
# bind a port below 1024.
#
# The published port is unchanged — docker-compose maps 3001 to this container,
# so only the container-side port moved from 80 to 8080. nginx.conf listens on
# 8080 to match; changing one without the other makes the frontend unreachable,
# which is exactly the S1-26 defect H1.10 had to fix.
FROM nginxinc/nginx-unprivileged:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# The base image already sets this, but stating it is not redundant: it
# survives a base-image change, and it is what a reader — or an image scanner
# looking for a root runtime — actually checks.
USER 101

EXPOSE 8080

# Static files, so liveness is simply "is nginx answering". wget is in the
# alpine base; curl is not, and adding a package to check a healthcheck would be
# its own small irony.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:8080/ || exit 1
