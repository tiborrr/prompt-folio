from typing import ClassVar, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Passwords that must never protect a production /manage
INSECURE_ADMIN_PASSWORDS = {"", "secret", "change_this_to_a_secure_password"}


class Settings(BaseSettings):
    environment: str = "PROD"
    admin_password: str = ""
    mistral_api_key: str = ""
    recaptcha_client_side_key: str = ""
    recaptcha_server_side_key: str = ""
    ntfy_topic: str = ""
    sqlite_url: str = "sqlite+aiosqlite:///private/sessions.db"
    app_domain: str = "localhost"

    # Remote MCP server (/mcp) so Claude can read and update the profile.
    # PUBLIC_URL is the https origin the app is reached on; it defaults to
    # https://APP_DOMAIN (http://localhost:3005 in DEV/TEST).
    mcp_enabled: bool = True
    public_url: str = ""
    # OAuth clients may only redirect to these hosts (loopback is always allowed,
    # for Claude Code and the MCP Inspector). "*.example.com" also allows the
    # subdomains; "*" allows any https host (the owner still approves every
    # client on /oauth/consent).
    mcp_allowed_redirect_hosts: str = (
        "claude.ai,claude.com,*.cursor.com,cursor.sh,chatgpt.com,*.openai.com,"
        "*.grok.com,*.x.ai,*.mistral.ai,*.perplexity.ai,vscode.dev,*.github.com"
    )

    # Public, read-only MCP server at /mcp/public for anyone's AI agent: reads
    # the public profile and (if enabled) asks the AI assistant, rate limited.
    public_mcp_enabled: bool = True
    public_ask_enabled: bool = True
    public_ask_rate_limit: str = "10/hour"  # per client
    public_ask_daily_limit: str = "200/day"  # all clients together

    # Default UI configuration for new deployments
    default_owner_name: str = "Tibor"
    default_owner_pronouns: str = "their"
    default_color_shadow_grey: str = "#1e1e24"
    default_color_sweet_salmon: str = "#fb9f89"
    default_color_khaki_beige: str = "#c4af9a"
    default_color_muted_teal: str = "#81ae9d"
    default_color_seaweed: str = "#21a179"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def _require_admin_password(self) -> Self:
        if not self.is_dev and self.admin_password.strip() in INSECURE_ADMIN_PASSWORDS:
            msg = "ADMIN_PASSWORD must be set to a strong, non-default value outside DEV/TEST."
            raise ValueError(msg)
        return self

    @property
    def is_dev(self) -> bool:
        return self.environment in {"DEV", "TEST"}

    @property
    def base_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        if self.is_dev or self.app_domain in {"", "localhost"}:
            return "http://localhost:3005"
        return f"https://{self.app_domain}"

    @property
    def secure_cookie(self) -> bool:
        return not self.is_dev

    @property
    def cookie_prefix(self) -> str:
        return "" if self.is_dev else "__Secure-"

    @property
    def cookie_domain(self) -> str | None:
        if self.is_dev or self.app_domain in {None, "localhost", ""}:
            return None
        return self.app_domain


settings = Settings()
