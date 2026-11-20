# Prompt Folio

Prompt Folio is a modern, open-source, AI-powered portfolio and context management system designed for fast interactions and an elegant user experience. It uses FastAPI for the backend, HTMX for reactive frontend components, and SQLite for lightweight, fast data storage. The chat interface is powered by Mistral AI.

## Features
- **AI Chat Assistant**: Talk to an AI representative that is context-aware and trained on your personal history, resume, and side projects.
- **Dynamic Context Engine**: Upload source documents (PDFs, Markdown) which are parsed and securely stored in SQLite. Rebuild your AI's context on the fly using a rich text editor (EditorJS).
- **Admin Dashboard**: Manage your UI theme, settings, session context, and AI intents.
- **Human Takeover**: Get notified via SSE when an admin takes over the chat. The AI pauses, allowing you to chat directly with visitors.
- **Integrations**: Built-in support for invisible ReCAPTCHA v3 and external analytics.
- **Lightweight & Fast**: Built with FastAPI, HTMX, and modern CSS (glassmorphism UI). No heavy frontend frameworks.

## MCP server: let Claude read and update your profile

The app serves a remote [MCP](https://modelcontextprotocol.io) server at `/mcp` (streamable HTTP), so Claude can read your profile and keep it up to date.

**Tools**

| Tool | What it does |
|---|---|
| `get_profile` | Name, pronouns, meeting link and the profile as Markdown (with its section headings) |
| `update_profile` | Replace the whole profile with new Markdown |
| `update_profile_section` | Replace the text under one heading, or add a new section |
| `update_owner_details` | Change name, pronouns or meeting link |
| `list_source_documents`, `read_source_document` | Read the uploaded CVs and notes |
| `list_profile_revisions`, `restore_profile_revision` | Undo a change: every write keeps the previous version (last 50) |

The profile is stored as Editor.js JSON; the tools convert it to Markdown and back, so the `/manage` editor keeps working.

**Authentication** is OAuth 2.1 with dynamic client registration, served by the app itself (`/.well-known/oauth-authorization-server`, `/authorize`, `/token`, `/register`). When a client connects, you log in with the `/manage` password on `/oauth/consent` and approve it. Tokens are stored hashed; access tokens last an hour and refresh tokens 90 days (rotated on use). Clients may only redirect to the hosts in `MCP_ALLOWED_REDIRECT_HOSTS` (default `claude.ai,claude.com`) or to loopback.

**Connect Claude**

1. Make sure `PUBLIC_URL` (or `APP_DOMAIN`) is the https address the app is reachable on.
2. claude.ai: *Settings > Connectors > Add custom connector*, URL `https://<your domain>/mcp`. Leave the OAuth client ID and secret empty.
3. Claude Code: `claude mcp add --transport http prompt-folio https://<your domain>/mcp`, then `/mcp` to log in.
4. Approve the request on the consent page that opens.

## Prerequisites

- Python 3.14+
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
3. **Publish** (`main` only): pushes the image with the commit SHA and `latest` tags to the registry.
4. **Deploy** (`main` only): connects over SSH with a deploy key that the server pins to `scripts/deploy_remote.sh` (forced command). The script accepts only a commit SHA, pulls that tag, waits for the container healthcheck and rolls back to the previously deployed tag if it does not become healthy.
5. **Deploy status:** opens a `deploy-failure` issue when `main` was not deployed and closes it after the next successful deploy.

`.github/workflows/dependency-audit.yml` runs `uv audit` daily and opens a `dependency-advisory` issue when a new advisory hits the locked dependencies.

### Secrets (environment `production`)

All secrets live in the GitHub environment `production`, which only accepts jobs running on `main`. Pull request runs cannot read them.

| Secret | Purpose |
|---|---|
| `REGISTRY_HOST`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` | Push access to the Docker registry |
| `PROD_SSH_KEY` | Private deploy key; the server only lets it run the deploy script |
| `PROD_SSH_KNOWN_HOSTS` | The server's host key (`ssh-keyscan` output), so CI never trusts an unknown host |
| `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_PORT` (optional, default 22) | SSH target |

Set them with `gh secret set NAME --env production`; `gh` then asks for the value without echoing it.

### Server setup

The server uses one generic script for every app: `scripts/deploy_remote.sh`, installed as `/usr/local/bin/deploy-app` (owned by root). A dedicated `deploy` user runs it; each app has its own deploy key, pinned in `/home/deploy/.ssh/authorized_keys` to that app only:

```
command="/usr/local/bin/deploy-app prompt-folio",restrict ssh-ed25519 AAAA... deploy@prompt-folio
```

The app lives in `/home/deploy/deployments/prompt-folio` with `docker-compose.yml` (image tag `${IMAGE_TAG}`), the production `.env` and `private/` (owned by uid 999, the container user). CI does not copy files to the server: a change to `docker-compose.yml` or the script has to be copied by hand. Membership of the `docker` group is effectively root, so the forced command is what limits the key.

The script also handles multi-service stacks (used by the other apps on the server): only services whose image tag is `${IMAGE_TAG}` are pulled and recreated; databases, Keycloak and other services are only started when missing, and one-shot init containers that exit with code 0 count as healthy.

## Manual deployment

`./deploy.sh` remains as a fallback. It runs the tests, builds and pushes a `v<timestamp>` image from your machine, syncs the compose file over SSH and starts it. On first use it asks for missing settings (`REMOTE_HOST`, `REMOTE_PATH`, registry, port) and saves them to `.env`. Its registry cleanup keeps the last 3 `v<timestamp>` tags and never touches the commit-SHA tags pushed by CI.

## Security
- The admin dashboard is protected via an HTTPOnly, Secure, SameSite=Strict cookie.
- Passwords are safe against timing attacks.
- Docker containers run as a non-root user.
- Forms and endpoints are protected against spam via ReCAPTCHA v3 integration.
