# First, build the application in the /workspace directory
FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Configure the Python directory so it is consistent
ENV UV_PYTHON_INSTALL_DIR=/python

# Only use the managed Python version
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install 3.11

WORKDIR /workspace
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

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
COPY --from=builder --chown=python:python /python /python

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /workspace /workspace

# Place executables in the environment at the front of the path
ENV PATH="/workspace/.venv/bin:$PATH"

# Use the non-root user to run our application
USER nonroot

# Use /workspace as the working directory
WORKDIR /workspace

# Expose port 3005
EXPOSE 3005

# Run the application
CMD ["./start.sh"]
