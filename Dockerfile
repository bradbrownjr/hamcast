# ---- build mbelib + shim ----
FROM python:3.13-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY native/ /src/native/
RUN /src/native/build.sh /out

# ---- runtime ----
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=native /out/libhcmbe.so /usr/local/lib/libhcmbe.so
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY hamcast/ hamcast/
RUN pip install --no-cache-dir .
ENV HAMCAST_LIBHCMBE=/usr/local/lib/libhcmbe.so
ENTRYPOINT ["hamcast"]
