#!/usr/bin/env bash

# Cut a release (version bump, tag, GitHub release, publish). Automation is
# tracked in https://github.com/aidanns/agent-auth/issues/18. Running this
# script before that issue lands exits non-zero to prevent accidental manual
# releases that skip the standard checks.

set -euo pipefail

cat >&2 <<'EOF'
task release: release automation is not yet implemented.

Tracking issue: https://github.com/aidanns/agent-auth/issues/18

Do not cut a release manually — the intended automation handles version
bumping, tagging, GitHub release creation, and publishing in one step.
EOF

exit 1
