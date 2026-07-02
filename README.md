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

Prompt Folio includes a smart, interactive deployment script. It automates building the Docker image locally, pushing it to your registry, and syncing everything to your remote server via SSH.

### How to Deploy

You don't need to manually configure anything to get started. Just run:

```bash
./deploy.sh
```

**What the script does:**
1. **Interactive Setup:** If this is your first time deploying, the script will automatically pause and ask you for any missing configuration (like your server IP, Docker registry, and port). 
2. **Auto-Save:** It saves your answers to the `.env` file so you never have to type them again.
3. **Build & Push:** It builds the Docker image locally and pushes it to your registry.
4. **Sync & Run:** It connects via SSH to your `REMOTE_HOST`, syncs your configuration, and starts the container using `docker compose`.
5. **Registry Cleanup:** It automatically cleans up old Docker images from your registry (keeping only the last 3 tags) to save space.

**Note:** Ensure you have SSH access to your `REMOTE_HOST` (e.g. using SSH keys) and permissions to write to the `REMOTE_PATH`. The application container is configured to run securely as a non-root user.

## Security
- The admin dashboard is protected via an HTTPOnly, Secure, SameSite=Strict cookie.
- Passwords are safe against timing attacks.
- Docker containers run as a non-root user.
