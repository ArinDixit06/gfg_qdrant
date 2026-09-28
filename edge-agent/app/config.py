"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Device identity
    device_id: str = "edge-device-01"
    device_name: str = "Edge Device 01"

    # Local edge agent
    edge_api_host: str = "127.0.0.1"
    edge_api_port: int = 8000
    shard_root: str = "./data"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_name: str = "content"
    vector_dim: int = 384

    # Cloud Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    collection_name: str = "edge-collection"
    server_shard_id: int = 0

    # Sync behavior
    connectivity_poll_seconds: float = 5.0
    push_interval_seconds: float = 10.0
    pull_interval_seconds: float = 20.0
    force_offline: bool = False

    # Metadata Postgres
    database_url: str = "postgresql://edge:edgepass@localhost:5432/edgememory"
    postgres_enabled: bool = True

    @property
    def mutable_shard_dir(self) -> str:
        return str(Path(self.shard_root) / self.device_id / "mutable")

    @property
    def immutable_shard_dir(self) -> str:
        return str(Path(self.shard_root) / self.device_id / "immutable")

    @property
    def models_dir(self) -> str:
        return str(Path(self.shard_root) / "models")


settings = Settings()
