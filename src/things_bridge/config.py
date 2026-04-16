"""Configuration loading for things-bridge."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _default_config_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "things-bridge")


@dataclass
class Config:
    config_dir: str = ""
    host: str = "127.0.0.1"
    port: int = 9200
    auth_url: str = "http://127.0.0.1:9100"
    osascript_path: str = "/usr/bin/osascript"
    request_timeout: float = 30.0
    log_path: str = ""

    def __post_init__(self):
        if not self.config_dir:
            self.config_dir = _default_config_dir()
        if not self.log_path:
            self.log_path = os.path.join(self.config_dir, "bridge.log")


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
        if k not in ("config_dir", "log_path")
    }
    with open(config_path, "w") as f:
        json.dump(serializable, f, indent=2)
        f.write("\n")

    return config
