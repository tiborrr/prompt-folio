# Prompt Folio

Prompt Folio is a modern, AI-powered portfolio and context management system designed for fast interactions and elegant UI. It uses FastAPI for the backend, HTMX for reactive frontend components, and SQLite for lightweight, fast data storage. The chat interface is powered by Mistral AI.

## Features
- **AI Chat Assistant**: Talk to the portfolio owner's AI representative.
- **Admin Dashboard**: Manage your UI theme, settings, session context, and AI intents.
- **Real-time Notifications**: Get notified via SSE when an admin takes over the chat.
- **Lightweight & Fast**: Built with FastAPI, HTMX, and modern CSS. No heavy frontend frameworks.

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker & Docker Compose
- A remote server for deployment with SSH access

## Local Development

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in your details (like `MISTRAL_API_KEY`).
3. Run the development server:
   ```bash
   uv run fastapi dev app/main.py --port 3005
   ```
4. Access the app at `http://localhost:3005`.
5. Access the admin dashboard at `http://localhost:3005/manage`.

## Deployment

Prompt Folio includes an automated deployment script that builds the Docker image locally, pushes it to your registry, and syncs the configuration to your remote server via SSH.

### 1. Configure `.env`
All deployment configurations are managed directly in your `.env` file. You do not need to edit the deployment script manually.

1. Copy the example file if you haven't already:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and configure your deployment settings at the bottom of the file:
   ```env
   # The remote SSH host where the application will be deployed (e.g., your server alias in ~/.ssh/config)
   REMOTE_HOST=your_production_ssh_host

   # The absolute path on the remote host where the application will reside
   REMOTE_PATH=/opt/prompt-folio
   ```

### 2. Run the Deployment Script
Once your `.env` file is configured, simply run:
```bash
./deploy.sh
```

The script will:
1. Build the Docker image locally.
2. Push it to the container registry.
3. SSH into `REMOTE_HOST` and create `REMOTE_PATH`.
4. Sync `docker-compose.yml`.
5. Pull the new image on the remote server and start the container using `docker compose`.

**Note:** Ensure you have SSH access to `REMOTE_HOST` and permissions to write to `REMOTE_PATH`. The application container runs securely as a non-root user.

## Security
- The admin dashboard is protected via an HTTPOnly, Secure, SameSite=Strict cookie.
- Passwords are safe against timing attacks.
- Docker containers run as a non-root user.
