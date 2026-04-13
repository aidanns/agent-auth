"""Configuration loading for agent-auth."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _default_config_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "agent-auth")


@dataclass
class Config:
    config_dir: str = ""
    db_path: str = ""
    host: str = "127.0.0.1"
    port: int = 9100
    access_token_ttl: int = 900
    refresh_token_ttl: int = 28800
    notification_plugin: str = "terminal"
    notification_plugin_config: dict = field(default_factory=dict)
    log_path: str = ""

    def __post_init__(self):
        if not self.config_dir:
            self.config_dir = _default_config_dir()
        if not self.db_path:
            self.db_path = os.path.join(self.config_dir, "tokens.db")
        if not self.log_path:
            self.log_path = os.path.join(self.config_dir, "audit.log")


def load_config(config_dir: str | None = None) -> Config:
    """Load configuration from disk, creating defaults if absent."""
    config_dir = config_dir or _default_config_dir()
    config_path = os.path.join(config_dir, "config.json")

    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        data["config_dir"] = config_dir
        return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})

    config = Config(config_dir=config_dir)
    Path(config_dir).mkdir(parents=True, exist_ok=True)

    serializable = {
        k: v for k, v in asdict(config).items()
        if k not in ("config_dir", "db_path", "log_path")
    }
    with open(config_path, "w") as f:
        json.dump(serializable, f, indent=2)
        f.write("\n")

    return config
