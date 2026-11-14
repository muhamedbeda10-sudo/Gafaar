"""Runtime configuration. Secrets never live here: broker credentials are not used by this release."""
from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    data_dir: Path = Path(__file__).resolve().parent.parent / "var"
    initial_capital_egp: Decimal = Decimal("50000")
    seed_sample_data: bool = True
    sample_history_days: int = 520
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Live brokerage execution is a separate, future module. It is not implemented
    # and this flag exists only so the UI can state the fact explicitly.
    live_trading_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def get_settings() -> Settings:
    return Settings()
