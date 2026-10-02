from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Each value can be overridden in the .env file or as an environment variable."""

    app_name: str = "SIRIS API (Supplier Inventory & Retail Integration System)"

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
    # How long a cached entry lives. Changes already mark old entries as outdated, so this only
    # decides how long data stays cached while nothing changes (default: 1 day).
    cache_ttl_seconds: int = 86400

    # Cloudflare R2 (file storage for uploaded images). Find these in the Cloudflare dashboard:
    #   R2 > your bucket > Settings (public URL), and R2 > Manage API tokens (keys).
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    # The bucket's public address, e.g. https://pub-xxxx.r2.dev or https://images.yourdomain.com
    r2_public_url: str = ""
    # Top folder in the bucket that holds all of this API's images (product_img/, business_img/ go inside it)
    r2_root_folder: str = "business_api"

    @property
    def r2_configured(self) -> bool:
        return all([self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key, self.r2_bucket, self.r2_public_url])

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [email.strip().lower() for email in self.admin_emails.split(",") if email.strip()]


settings = Settings()
