# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""World-readable bind-mount perms helper.

The integration tests bind-mount per-test tmpdirs into containers
running under UID 1001. ``tmp_path_factory.mktemp`` defaults to mode
0700 owned by the host runner's UID; without widening, the in-
container process can't read its own config / fixture files.

The chmod calls are isolated in this module — and only this module —
so the CodeQL ``security-extended`` query
``py/overly-permissive-file-permissions`` can be excluded from a
single explicitly-named source path
(``.github/codeql/codeql-config.yml``) instead of being suppressed
across the whole tests_support library. Production-code regressions
on the same query stay loud.

The directory mode (0o755) only adds world-execute (search) and
world-read on the directory entry itself — no write permission is
granted to anyone outside the file owner. The file mode (0o644)
adds world-read on test-scoped config / fixture content (no
secrets); world-write is never granted.
"""

from __future__ import annotations

import os
from pathlib import Path

_BIND_MOUNT_DIR_MODE = 0o755
_BIND_MOUNT_FILE_MODE = 0o644


def make_bind_mount_dir_readable(path: Path) -> None:
    """Widen ``path`` to mode 0o755 so a container UID can ``open``+read it."""
    os.chmod(path, _BIND_MOUNT_DIR_MODE)


def make_bind_mount_file_readable(path: Path) -> None:
    """Widen ``path`` to mode 0o644 so a container UID can read it."""
    os.chmod(path, _BIND_MOUNT_FILE_MODE)
