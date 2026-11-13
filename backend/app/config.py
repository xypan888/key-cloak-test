from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    keycloak_issuer: str = "http://localhost:8080/realms/replatform"
    keycloak_internal_url: str = "http://keycloak:8080"
    keycloak_client_secret: SecretStr
    rvm_api_key: SecretStr
    greenu_base_url: str
    greenu_api_key: SecretStr
    greenu_merchant: str = "GreenAI"
    greenu_timeout_seconds: float = 10
    deposit_db: str = "/data/deposits.sqlite3"

    @property
    def token_url(self):
        return self.keycloak_internal_url.rstrip("/") + "/realms/replatform/protocol/openid-connect/token"

    @property
    def jwks_url(self):
        return self.keycloak_internal_url.rstrip("/") + "/realms/replatform/protocol/openid-connect/certs"


@lru_cache
def settings():
    return Settings()
