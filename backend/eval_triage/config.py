"""Runtime configuration.

Every path and service location is configurable through environment variables.
Defaults bind to loopback and keep all evaluation data under ``.data/`` in the
repository so nothing touches another project's store.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVAL_TRIAGE_", extra="ignore")

    data_dir: Path = REPO_ROOT / ".data"
    api_host: str = "127.0.0.1"
    api_port: int = 8310
    allow_non_loopback: bool = False
    testing: bool = False

    # Durable job execution.
    lease_seconds: float = 60.0
    heartbeat_seconds: float = 10.0
    worker_poll_seconds: float = 0.5
    worker_slots: int = 4

    # MemoryAI bridge environment. Hugging Face runs offline so nothing is downloaded
    # implicitly; point TIKTOKEN_CACHE_DIR at an existing tokenizer cache when the
    # worker's temporary directory differs from the one MemoryAI used.
    memoryai_hf_offline: bool = True
    tiktoken_cache_dir: Path | None = None

    # Serve the built frontend from the API process when present.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    # MemoryAI bridge. The source path and interpreter are the user's project;
    # Eval Triage never installs into or modifies either.
    memoryai_source_path: Path = Field(
        default=REPO_ROOT.parent / "memoryai",
        validation_alias=AliasChoices("MEMORYAI_SOURCE_PATH", "EVAL_TRIAGE_MEMORYAI_SOURCE_PATH"),
    )
    memoryai_python: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("MEMORYAI_PYTHON", "EVAL_TRIAGE_MEMORYAI_PYTHON"),
    )

    @field_validator("data_dir", "frontend_dist", "memoryai_source_path", mode="after")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("api_host")
    @classmethod
    def _host(cls, value: str) -> str:
        return value.strip()

    def check_bind_host(self) -> None:
        if self.api_host not in LOOPBACK_HOSTS and not self.allow_non_loopback:
            raise ValueError(
                f"Refusing to bind {self.api_host}: Eval Triage has no authentication. "
                "Set EVAL_TRIAGE_ALLOW_NON_LOOPBACK=true only on a trusted network."
            )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "eval_triage.sqlite"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def memoryai_stores_dir(self) -> Path:
        return self.data_dir / "memoryai-stores"

    @property
    def resolved_memoryai_python(self) -> Path:
        if self.memoryai_python is not None:
            return self.memoryai_python.expanduser()
        return self.memoryai_source_path / ".venv" / "bin" / "python"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.artifacts_dir, self.memoryai_stores_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Forget cached settings (tests change environment variables)."""
    get_settings.cache_clear()
