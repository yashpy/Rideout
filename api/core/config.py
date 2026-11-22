"""Settings, read from env vars (see .env.example). ENV picks the database: rideout_<env>."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    env: Literal["dev", "staging", "prod", "test"] = "dev"
    git_sha: str = "local"

    mongodb_uri: str = "mongodb://localhost:27017"
    tiger_database_url: str = ""

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
    tinyfish_api_key: str = ""

    # Dialer. Real calls are paced at 1/s per number (Twilio default); stand-ins have no such limit.
    dial_rate_per_s: float = 1.0
    standin_rate_per_s: float = 2.0
    standin_concurrency: int = 20
    standin_turn_delay_s: float = 0.6  # pause between stand-in turns, so /calls looks like a call
    standin_use_models: bool = False  # stand-ins use the free rule interpreter; real calls use Gemini/Claude
    reach_ladder_scale: float = 1.0  # 0.1 = retries after 12 s / 30 s instead of 2 / 5 min (demo)
    # TinyFish zone watcher. Fetch only: free up to 1,000 URLs/day; the cap keeps us under it.
    public_web_url: str = "http://localhost:3000"  # where TinyFish finds /drill (must be public)
    tinyfish_daily_cap: int = 800
    tinyfish_poll_s: float = 15.0
    tinyfish_arm_minutes: float = 30.0
    county_page_url: str = ""  # optional one-time read-only fetch for the pitch
    public_api_url: str = "http://localhost:8000"
    internal_token: str = "dev-token-change-me"
    cors_origins: str = "*"  # comma-separated

    # Background workers (offer expiry, change streams). Off in tests.
    run_workers: bool = True
    offer_ttl_seconds: int = 120

    @property
    def db_name(self) -> str:
        return f"rideout_{self.env}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
