#!/bin/sh
set -e

# Run migrations
alembic upgrade head

# Run the FastAPI application using fastapi cli
exec fastapi run app/main.py --host 0.0.0.0 --port 3005
