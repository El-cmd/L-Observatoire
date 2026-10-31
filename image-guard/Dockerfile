FROM rust:1-slim-trixie AS build
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    cargo build --release --locked && cp target/release/image-guard /image-guard

# No network access, no secrets, no volume: see compose.yaml.
FROM debian:trixie-slim
RUN groupadd --gid 10002 guard && useradd --uid 10002 --gid guard --no-create-home guard
COPY --from=build /image-guard /usr/local/bin/image-guard
USER 10002:10002
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 CMD ["/usr/local/bin/image-guard", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/image-guard"]
