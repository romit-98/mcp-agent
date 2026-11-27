"""Settings every server shares. Each server subclasses this with its own env prefix and port."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Subclass with `model_config = SettingsConfigDict(env_prefix="CRM_", extra="ignore")`."""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int
    dev_auth: bool = False  # trust the X-Dev-User header; off unless set, so it fails closed

    # Token validation (phase 5). Each server sets its own audience (its Keycloak client ID).
    oidc_issuer: str = "http://localhost:8180/realms/northstar"
    oidc_audience: str = ""  # empty = no tokens accepted (fails closed)
    oidc_jwks_url: str | None = None  # default: <issuer>/protocol/openid-connect/certs

    db_host: str = "localhost"
    db_port: int = 5433
    db_name: str = "northstar"
    db_user: str
    db_password: SecretStr  # no default: fail fast if missing; shows as ********** in logs
