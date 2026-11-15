from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    app_name: str = "EVRIS Core"
    version: str = "0.1.0"

    ollama_url: str = "http://127.0.0.1:11434"

    # Dual-Model configuration (Fast for quick answers, Pro for complex tasks)
    fast_model: str = "qwen2.5:3b"
    pro_model: str = "qwen2.5:7b"

    # Routing mode: "auto" (complexity classifier), "fast", or "pro"
    routing_mode: str = "auto"

    # Minimum free RAM (GB) required if the Pro model is not yet loaded in memory
    pro_min_free_ram_gb: float = 3.0

    # Allows simulating the Pro node being offline/unavailable for testing refusal
    pro_enabled: bool = True

    db_path: str = str(DATA_DIR / "evris_memory.db")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
