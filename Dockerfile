# ---- build mbelib + shim ----
FROM python:3.13-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY native/ /src/native/
RUN /src/native/build.sh /out

# ---- web app (Listen and Manage pages) ----
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.13-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg tzdata icecast2 media-types \
    && rm -rf /var/lib/apt/lists/*
COPY --from=native /out/libhcmbe.so /usr/local/lib/libhcmbe.so
WORKDIR /app
# Dependencies first, in their own layer (faster-whisper alone is most of
# the image), so an ordinary hamcast update only changes the small layer
# below. The list comes from pyproject.toml, so it can't drift.
COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
print('\n'.join(p['dependencies'] + p['optional-dependencies']['whisper']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY README.md LICENSE ./
COPY hamcast/ hamcast/
COPY --from=web /src/hamcast/static/ hamcast/static/
RUN pip install --no-cache-dir --no-deps .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV HAMCAST_LIBHCMBE=/usr/local/lib/libhcmbe.so \
    HOME=/tmp \
    HF_HOME=/data/models/huggingface \
    PYTHONUNBUFFERED=1
# 8080 dashboard, 8000 bundled Icecast
EXPOSE 8080 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve", "--config", "/config/config.yaml"]
