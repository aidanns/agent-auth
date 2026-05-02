# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""pr-lint-validator: PR-title and ==COMMIT_MSG== block validators.

The package's CLI entry point is :func:`pr_lint_validator.cli.main`,
exposed as the ``pr-lint-validator`` console script. The pure
validation surface is in :mod:`pr_lint_validator.title` and
:mod:`pr_lint_validator.commit_msg`.
"""
