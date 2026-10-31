FROM rust:1-slim-trixie AS build
WORKDIR /build
COPY Cargo.toml Cargo.lock build.rs ./
COPY migrations ./migrations
COPY src ./src
# Backend and image-guard build in parallel: the shared registry is locked while in use,
# and each has its own target directory.
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=observatoire-backend-target,target=/build/target \
    cargo build --release --locked && cp target/release/observatoire /observatoire

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build /observatoire /app/observatoire
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 CMD ["/app/observatoire", "healthcheck"]
ENTRYPOINT ["/app/observatoire"]
