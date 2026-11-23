"""Settings, read from env vars (see .env.example). ENV picks the database: rideout_<env>."""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    env: Literal["dev", "staging", "prod", "test"] = "dev"
    git_sha: str = "local"

    mongodb_uri: str = "mongodb://localhost:27017"
    # Optional: keep the password out of MONGODB_URI. Put `<db_password>` in the URI and the password here.
    mongodb_password: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    anthropic_api_key: str = ""
    # Claude bills per token. The team said no paid models, so Claude is never called unless this is true.
    allow_paid_models: bool = False
    claude_fallback_model: str = "claude-sonnet-5-5"
    claude_judge_model: str = "claude-opus-5-5"
    # Optional: Claude through Amazon Bedrock. AWS keys come from the standard AWS_* env vars.
    claude_provider: Literal["anthropic", "bedrock"] = "anthropic"
    aws_region: str = "us-west-2"
    bedrock_fallback_model: str = ""  # Bedrock model ID for the Sonnet fallback (from the Bedrock console)
    bedrock_judge_model: str = ""  # Bedrock model ID for the Opus judge

    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_phone_number_id: str = ""
    elevenlabs_telephony: Literal["twilio", "sip-trunk"] = "twilio"  # how the number was imported
    firms_map_key: str = ""

    # Dialer. Real calls are paced at 1/s per number (Twilio default); stand-ins have no such limit.
    dial_rate_per_s: float = 1.0
    standin_rate_per_s: float = 2.0
    standin_concurrency: int = 20
    standin_turn_delay_s: float = 0.6  # pause between stand-in turns, so /calls looks like a call
    standin_use_models: bool = False  # stand-ins use the free rule interpreter; real calls use Gemini/Claude
    reach_ladder_scale: float = 1.0  # 0.1 = retries after 12 s / 30 s instead of 2 / 5 min (demo)
    public_api_url: str = "http://localhost:8000"
    internal_token: str = "dev-token-change-me"
    cors_origins: str = "*"  # comma-separated

    # Background workers (offer expiry, change streams). Off in tests.
    run_workers: bool = True
    offer_ttl_seconds: int = 120

    @property
    def mongo_url(self) -> str:
        """MONGODB_URI with `<db_password>` replaced by MONGODB_PASSWORD (URL-encoded)."""
        if self.mongodb_password and "<db_password>" in self.mongodb_uri:
            return self.mongodb_uri.replace("<db_password>", quote_plus(self.mongodb_password))
        return self.mongodb_uri

    @property
    def db_name(self) -> str:
        return f"rideout_{self.env}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
