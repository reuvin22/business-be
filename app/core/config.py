from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Each value can be overridden in the .env file or as an environment variable."""

    app_name: str = "SIRIS API (Supplier Inventory & Retail Integration System)"

    # Firebase service account key. Used to check login tokens and to read/write Firestore.
    # Give EITHER the path to the key file, OR the whole key file contents (JSON text).
    # The JSON option is handy on hosting platforms: paste the key into one environment variable.
    firebase_credentials_path: str = "firebase-service-account.json"
    firebase_credentials_json: str = ""
    # Firebase Realtime Database (live chat). Firebase Console > Realtime Database > the address at the top.
    firebase_database_url: str = "https://my-business-5bcad-default-rtdb.asia-southeast1.firebasedatabase.app"

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
    # Earlier public addresses of the same files (comma-separated), still accepted as "uploaded to SIRIS"
    r2_old_public_urls: str = ""
    # A second bucket with NO public access, for permits, IDs, and legal documents. They are opened with
    # links that expire after a few minutes, given only to the business's team and platform admins.
    r2_private_bucket: str = ""

    # Xendit (online payments in the selling app: e-wallets, cards, bank transfer).
    # Dashboard > Settings > Developers > API keys (secret key, with "Money-in" write permission),
    # and Settings > Developers > Webhooks (the verification token).
    xendit_secret_key: str = ""
    xendit_webhook_token: str = ""

    # The interactive API docs (/docs, /redoc, /openapi.json). Off unless turned on: in production they would
    # show everyone a map of every route. Set API_DOCS=true on your own computer.
    api_docs: bool = False
    # The detailed health pages (/api/health/r2, /cache, /encryption) need ?token=<this>. Empty = they are off.
    # (/api/health itself stays open: the hosting platform checks it.)
    health_token: str = ""

    # Encrypts confidential data at rest (Firestore fields, the Redis cache, chat messages). 32 random bytes
    # as base64; see app/core/crypto.py. Required. NEVER lose or change it: data encrypted with it cannot be
    # read without it. Make one with:
    #   python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
    data_encryption_key: str = ""
    # After changing the key: the earlier key(s), comma-separated, so old data can still be read until
    # `python -m app.scripts.encrypt_existing --apply` has re-encrypted it (see app/core/crypto.py)
    data_encryption_old_keys: str = ""

    @property
    def xendit_configured(self) -> bool:
        return bool(self.xendit_secret_key.strip())

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
