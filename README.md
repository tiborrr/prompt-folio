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

Prompt Folio features an asynchronous test suite using `pytest`, `pytest-asyncio`, and Playwright for UI integration tests. Tests are run in parallel using `pytest-xdist`.

Run the same checks as CI (format, lint, typecheck, dependency audit, tests):
```bash
make install-static                    # pinned HTMX / Editor.js / Cropper.js files
uv run playwright install chromium     # browser for the UI tests
make validate
```

## CI/CD

`.github/workflows/ci.yml` runs on every pull request and every push to `main`:

1. **Validate:** `ruff format --check`, `ruff check`, `basedpyright`, `uv audit` and the full test suite (including Playwright).
2. **Image:** builds the Docker image, smoke-tests `/health` and `/`, and scans it with Trivy. A fixable CRITICAL/HIGH finding blocks the release; accepted findings go in `.trivyignore` with a reason.
3. **Push** (`main` only): tags the image with the commit SHA and `latest` and pushes it to the registry.
4. **Deploy** (`main` only): syncs `docker-compose.yml` and `scripts/deploy_remote.sh` to the server and runs the script, which pulls the SHA tag, waits for the container healthcheck and rolls back to the previously deployed tag if it does not become healthy.
5. **Deploy status:** opens a `deploy-failure` issue when `main` was not deployed and closes it after the next successful deploy.

`.github/workflows/dependency-audit.yml` runs `uv audit` daily and opens a `dependency-advisory` issue when a new advisory hits the locked dependencies.

### Repository secrets

| Secret | Purpose |
|---|---|
| `REGISTRY_HOST`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` | Push access to the Docker registry |
| `PROD_SSH_KEY` | Private key of a deploy key authorised on the server |
| `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_PORT` (optional, default 22) | SSH target |

The server deploys from `~/deployments/prompt-folio` of `PROD_SSH_USER`, must hold the production `.env` there, and must be logged in to the registry (`docker login`).

## Manual deployment

`./deploy.sh` remains as a fallback. It runs the tests, builds and pushes a `v<timestamp>` image from your machine, syncs the compose file over SSH and starts it. On first use it asks for missing settings (`REMOTE_HOST`, `REMOTE_PATH`, registry, port) and saves them to `.env`. Its registry cleanup keeps the last 3 `v<timestamp>` tags and never touches the commit-SHA tags pushed by CI.

## Security
- The admin dashboard is protected via an HTTPOnly, Secure, SameSite=Strict cookie.
- Passwords are safe against timing attacks.
- Docker containers run as a non-root user.
- Forms and endpoints are protected against spam via ReCAPTCHA v3 integration.
