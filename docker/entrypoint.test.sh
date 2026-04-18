#!/usr/bin/env bash

# Render a config.json from env overrides and start agent-auth serve.
# Used only by the integration-test Docker image — do not ship in
# production.

set -euo pipefail

config_dir="${XDG_CONFIG_HOME}/agent-auth"
config_path="${config_dir}/config.json"
mkdir -p "${config_dir}"

# Delegate JSON rendering to python so typos or exotic env values can
# never produce a silently malformed config file.
python3 - "${config_path}" <<'PY'
import json
import os
import sys

config = {
    "host": os.environ.get("AGENT_AUTH_HOST", "0.0.0.0"),
    "port": int(os.environ.get("AGENT_AUTH_PORT", "9100")),
    "access_token_ttl_seconds": int(os.environ.get("AGENT_AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")),
    "refresh_token_ttl_seconds": int(os.environ.get("AGENT_AUTH_REFRESH_TOKEN_TTL_SECONDS", "28800")),
    "notification_plugin": os.environ.get("AGENT_AUTH_NOTIFICATION_PLUGIN", "tests_support.env_plugin"),
    "notification_plugin_config": {},
}

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
PY

exec agent-auth serve
