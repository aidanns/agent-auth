# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Typed accessor for a Compose service's external port mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DockerPort:
    """External/internal port mapping for a running Compose service.

    Obtained via ``StartedCluster.service(name).port(internal_port)``.
    Mirrors ``DockerPort`` from ``palantir/docker-compose-rule`` — the
    structured triple replaces hand-rolled string concatenation of host +
    port pairs that the testcontainers-era harness relied on.
    """

    host: str
    external_port: int
    internal_port: int

    def in_format(self, template: str) -> str:
        """Substitute ``$HOST``, ``$EXTERNAL_PORT``, ``$INTERNAL_PORT`` into ``template``.

        Typical use: ``port.in_format("http://$HOST:$EXTERNAL_PORT/api")``.
        Placeholders are plain string replacements — no regex, no escaping —
        so a literal ``$`` in the template outside a placeholder is preserved
        as-is.
        """
        return (
            template.replace("$HOST", self.host)
            .replace("$EXTERNAL_PORT", str(self.external_port))
            .replace("$INTERNAL_PORT", str(self.internal_port))
        )
