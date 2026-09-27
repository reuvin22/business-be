from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Each value can be overridden in the .env file or as an environment variable."""

    app_name: str = "My Business API"

    # Firebase service account key. Used to check login tokens and to read/write Firestore.
    # Give EITHER the path to the key file, OR the whole key file contents (JSON text).
    # The JSON option is handy on hosting platforms: paste the key into one environment variable.
    firebase_credentials_path: str = "firebase-service-account.json"
    firebase_credentials_json: str = ""

    # Comma-separated list of frontend URLs that are allowed to call this API
    cors_origins: str = "http://localhost:5173"

    # Comma-separated emails of platform admins. Admins review business verifications
    # and manage the shared product categories.
    admin_emails: str = ""

    # Redis cache, e.g. redis://default:password@host:port. Leave empty to run without a cache.
    # Put the API server in the same region as Redis, or cache calls cross the ocean too.
    redis_url: str = ""
    # Cached data expires after this many seconds, even if nothing changed (a safety net).
    cache_ttl_seconds: int = 600

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [email.strip().lower() for email in self.admin_emails.split(",") if email.strip()]


settings = Settings()
