# First, build the application in the /workspace directory
FROM ghcr.io/astral-sh/uv:bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Configure the Python directory so it is consistent
ENV UV_PYTHON_INSTALL_DIR=/python

# Only use the managed Python version
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install 3.14

WORKDIR /workspace
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy scripts and run them first to cache the downloads
COPY update_htmx.sh /workspace/
COPY update_editorjs.sh /workspace/
COPY update_cropper.sh /workspace/
RUN chmod +x update_htmx.sh update_editorjs.sh update_cropper.sh && ./update_htmx.sh && ./update_editorjs.sh && ./update_cropper.sh

# Copy project files
COPY pyproject.toml /workspace/
COPY uv.lock /workspace/
COPY alembic.ini /workspace/
COPY alembic /workspace/alembic
COPY app /workspace/app
COPY start.sh /workspace/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Then, use a final image without uv
FROM debian:bookworm-slim

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# Install runtime dependencies (e.g., for SSL, requests)
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy the Python version
COPY --from=builder /python /python

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /workspace /workspace

# Place executables in the environment at the front of the path
ENV PATH="/workspace/.venv/bin:$PATH"

# Use the non-root user to run our application
USER nonroot

# Trust X-Forwarded-For/-Proto only from the reverse proxy on a private (docker)
# network, so rate limits see the visitor's IP instead of the proxy's. Override
# with FORWARDED_ALLOW_IPS in .env when the proxy runs elsewhere.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

# Use /workspace as the working directory
WORKDIR /workspace

# Expose port 3005
EXPOSE 3005

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3005/health', timeout=4)"]

# Run the application
CMD ["./start.sh"]
