# Prompt Folio

Prompt Folio is a modern, open-source, AI-powered portfolio and context management system designed for fast interactions and an elegant user experience. It uses FastAPI for the backend, HTMX for reactive frontend components, and SQLite for lightweight, fast data storage. The chat interface is powered by Mistral AI.

## Features
- **AI Chat Assistant**: Talk to an AI representative that is context-aware and trained on your personal history, resume, and side projects.
- **Dynamic Context Engine**: Upload source documents (PDFs, Markdown) which are parsed and securely stored in SQLite. Rebuild your AI's context on the fly using a rich text editor (EditorJS).
- **Admin Dashboard**: Manage your UI theme, settings, session context, and AI intents.
- **Human Takeover**: Get notified via SSE when an admin takes over the chat. The AI pauses, allowing you to chat directly with visitors.
- **Integrations**: Built-in support for invisible ReCAPTCHA v3 and external analytics.
- **Lightweight & Fast**: Built with FastAPI, HTMX, and modern CSS (glassmorphism UI). No heavy frontend frameworks.

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker & Docker Compose
- A remote server for deployment with SSH access

## Local Development

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in your details (like `MISTRAL_API_KEY`).
3. Install dependencies and run the development server:
   ```bash
   uv run fastapi dev app/main.py --port 3005
   ```
4. Access the app at `http://localhost:3005`.
5. Access the admin dashboard at `http://localhost:3005/manage`.

## Testing

Prompt Folio features a robust asynchronous test suite using `pytest`, `pytest-asyncio`, and Playwright for UI integration tests. Tests are run in parallel using `pytest-xdist`.

To run the test suite locally:
```bash
uv run pytest
```

## Deployment

Prompt Folio includes a smart, interactive deployment script. It automates testing, building the Docker image locally, pushing it to your registry, and syncing everything to your remote server via SSH.

### How to Deploy

You don't need to manually configure anything to get started. Just run:

```bash
./deploy.sh
```

**What the script does:**
1. **Automated Testing:** Runs `uv run pytest` and aborts deployment if any tests fail.
2. **Interactive Setup:** If this is your first time deploying, the script will automatically pause and ask you for any missing configuration (like your server IP, Docker registry, and port). 
3. **Auto-Save:** It saves your answers to the `.env` file so you never have to type them again.
4. **Build & Push:** It builds the Docker image locally and pushes it to your registry.
5. **Sync & Run:** It connects via SSH to your `REMOTE_HOST`, syncs your configuration, and starts the container using `docker compose`.
6. **Registry Cleanup:** It automatically cleans up old Docker images from your registry (keeping only the last 3 tags) to save space.

**Note:** Ensure you have SSH access to your `REMOTE_HOST` (e.g. using SSH keys) and permissions to write to the `REMOTE_PATH`. The application container is configured to run securely as a non-root user.

## Security
- The admin dashboard is protected via an HTTPOnly, Secure, SameSite=Strict cookie.
- Passwords are safe against timing attacks.
- Docker containers run as a non-root user.
- Forms and endpoints are protected against spam via ReCAPTCHA v3 integration.
