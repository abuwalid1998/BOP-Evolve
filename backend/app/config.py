"""Runtime configuration.

All values come from environment variables (see `.env.example`). Production
secrets and connection strings must come from the bank's approved secrets
manager — never from a committed file.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    demo_mode: bool = True
    database_url: str = "postgresql+psycopg://bop_evolve:bop_evolve_local@db:5432/bop_evolve_dev"
    auth_mode: str = "mock"
    jwt_secret: str = "local-dev-only-change-me"
    session_ttl_minutes: int = 480
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Demo accounts created by the seed script share this password. It is a
    # documented, local-only demo value and must never be a real credential.
    demo_password: str = "Evolve#Demo2026"
    seed_on_start: bool = True

    worker_tick_seconds: int = 10

    # Privacy thresholds for aggregated team / branch views.
    privacy_min_group_employees: int = 3
    privacy_min_group_cases: int = 10

    # Employee-level simulation requires a separate approval and validation gate.
    employee_level_simulation_enabled: bool = False

    # Retention values are displayed for governance review; enforcement is out
    # of scope for the prototype.
    retention_cases_days: int = 1095
    retention_audit_days: int = 2555

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_safe_for_environment(self) -> None:
        """Refuse to start a mock-auth / demo build in a production environment."""
        if self.app_env.lower() == "production":
            if self.auth_mode == "mock" or self.demo_mode:
                raise RuntimeError(
                    "AUTH_MODE=mock and DEMO_MODE=true are not permitted when APP_ENV=production. "
                    "Configure the bank-approved SSO/OIDC provider first."
                )
            if self.jwt_secret == "local-dev-only-change-me":
                raise RuntimeError("JWT_SECRET must be provided by the secrets manager in production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
