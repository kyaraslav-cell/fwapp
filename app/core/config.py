from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    media_dir: Path
    ruleset_path: Path
    lake_config_path: Path
    host: str
    port: int


def get_settings() -> Settings:
    db_path = Path(os.environ.get("FISHLOG_DB_PATH", str(REPO_ROOT / "fishlog.db")))
    media_dir = Path(os.environ.get("FISHLOG_MEDIA_DIR", str(db_path.parent / "media")))
    return Settings(
        db_path=db_path,
        media_dir=media_dir,
        ruleset_path=CONFIG_DIR / "rules.v0.2.yaml",
        lake_config_path=CONFIG_DIR / "lakes" / "pomocnia.yaml",
        host=os.environ.get("FISHLOG_HOST", "0.0.0.0"),
        port=int(os.environ.get("FISHLOG_PORT", "8000")),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        loaded: dict[str, Any] = yaml.safe_load(f)
        return loaded


def load_lake_config() -> dict[str, Any]:
    return load_yaml(get_settings().lake_config_path)


def load_ruleset_yaml() -> dict[str, Any]:
    return load_yaml(get_settings().ruleset_path)
