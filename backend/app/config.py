from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    app_name: str = "EVRIS Core"
    version: str = "0.1.0"

    ollama_url: str = "http://127.0.0.1:11434"

    # Multi-Model configuration (Qwen 3.5 — fast/pro + abliterated limitless tier)
    fast_model: str = "qwen3.5:4b"
    pro_model: str = "qwen3.5:9b"
    limitless_model: str = "huihui_ai/qwen3.5-abliterated:9b"

    # Routing mode: "auto" (complexity classifier), "fast", "pro", or "limitless"
    routing_mode: str = "auto"

    # Disable Ollama chain-of-thought tokens by default so CPU tool-calling stays responsive
    pro_thinking: bool = False

    # Minimum free RAM (GB) required if a 9B model (Pro / Limitless) is not yet loaded in memory
    pro_min_free_ram_gb: float = 5.5

    # Allows simulating the Pro node being offline/unavailable for testing refusal
    pro_enabled: bool = True

    db_path: str = str(DATA_DIR / "evris_memory.db")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
