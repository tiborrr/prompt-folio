from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "PROD"
    admin_password: str = "secret"
    mistral_api_key: str = ""
    recaptcha_client_side_key: str = ""
    recaptcha_server_side_key: str = ""
    ntfy_topic: str = ""
    sqlite_url: str = "sqlite+aiosqlite:///private/sessions.db"
    app_domain: str = "localhost"

    # Default UI configuration for new deployments
    default_owner_name: str = "Tibor"
    default_owner_pronouns: str = "their"
    default_color_shadow_grey: str = "#1e1e24"
    default_color_sweet_salmon: str = "#fb9f89"
    default_color_khaki_beige: str = "#c4af9a"
    default_color_muted_teal: str = "#81ae9d"
    default_color_seaweed: str = "#21a179"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
