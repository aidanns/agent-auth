# Changelog

## [0.13.1](https://github.com/aidanns/agent-auth/compare/v0.13.0...v0.13.1) (2026-04-25)

### Features

- **ci:** bot-mediated changelog authoring via PR markers ([#314](https://github.com/aidanns/agent-auth/issues/314))

- **ci:** CLI helper to scaffold changelog entries ([#322](https://github.com/aidanns/agent-auth/issues/322))

### Bug Fixes

- **store:** preserve original SQL error from failed up-migration ([#330](https://github.com/aidanns/agent-auth/issues/330))

## [0.13.0](https://github.com/aidanns/agent-auth/compare/v0.12.2...v0.13.0) (2026-04-25)

### Features

- **ci:** changelog YAML schema + PR-time lint ([#303](https://github.com/aidanns/agent-auth/issues/303))

- **ci:** merge bot extracts ==COMMIT_MSG== as squash body ([#310](https://github.com/aidanns/agent-auth/issues/310))

- **ci:** PR template + commit-msg block lint ([#302](https://github.com/aidanns/agent-auth/issues/302))

- **gpg-cli:** add task setup-devcontainer-signing for one-shot wiring ([#315](https://github.com/aidanns/agent-auth/issues/315))

## [0.12.2](https://github.com/aidanns/agent-auth/compare/v0.12.1...v0.12.2) (2026-04-25)

### Bug Fixes

- **test-support:** install SIGTERM handler in notifier so compose teardown exits cleanly ([#300](https://github.com/aidanns/agent-auth/issues/300))

## [0.12.1](https://github.com/aidanns/agent-auth/compare/v0.12.0...v0.12.1) (2026-04-25)

### Bug Fixes

- **test-harness:** drop docker compose -t override; gate compose_stop budget ([#292](https://github.com/aidanns/agent-auth/issues/292))

## [0.12.0](https://github.com/aidanns/agent-auth/compare/v0.11.0...v0.12.0) (2026-04-25)

### Features

- **coverage:** split --cov-fail-under into per-package floors ([#293](https://github.com/aidanns/agent-auth/issues/293))

## [0.11.0](https://github.com/aidanns/agent-auth/compare/v0.10.0...v0.11.0) (2026-04-25)

### ⚠ BREAKING CHANGES

- \*\* the root `install.sh` is deleted. Users must switch
  to the per-service installers (root README lists them). Every shipped
  console-script continues to work from its per-service package.

Closes #105.

## Test plan

- [x] `uv run pytest tests/ --ignore=tests/integration` — 509 passed,
  coverage 80.27 %.
- [x] `uv run ruff check`, `uv run mypy`, `uv run pyright` — clean
  across the new `packages/*/src` trees.
- [x] `scripts/verify-standards.sh`,
  `scripts/verify-integration-isolation.sh`,
  `scripts/verify-function-tests.sh`, `scripts/verify-design.sh`,
  `scripts/verify-token-cli-http-parity.sh`, `scripts/reuse-lint.sh` — all
  green.
- [ ] CI integration suite on all four `integration-*` jobs (requires
  Docker — not run locally).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

### Features

- **ci:** verify workspace dep graph against an explicit allowlist ([#285](https://github.com/aidanns/agent-auth/issues/285))

- **gpg-bridge:** implement gpg-cli / gpg-bridge packages (MVP) ([#254](https://github.com/aidanns/agent-auth/issues/254))

- **standards:** derive install.sh requirement from [project.scripts] ([#284](https://github.com/aidanns/agent-auth/issues/284))

- **taskfile:** per-package namespaces via Taskfile includes ([#279](https://github.com/aidanns/agent-auth/issues/279))

- **things-bridge:** restrict subprocess env to minimal allowlist ([#277](https://github.com/aidanns/agent-auth/issues/277))

### Code Refactoring

- split services into a uv workspace of per-service subprojects ([#257](https://github.com/aidanns/agent-auth/issues/257))

## [0.10.0](https://github.com/aidanns/agent-auth/compare/v0.9.1...v0.10.0) (2026-04-23)

### Features

- **design:** wire generator + CI drift gate for design/\*.yaml renders ([#256](https://github.com/aidanns/agent-auth/issues/256))

## [0.9.1](https://github.com/aidanns/agent-auth/compare/v0.9.0...v0.9.1) (2026-04-23)

### Bug Fixes

- **verify-standards:** tighten tool-name regexes against hyphen word boundaries ([#247](https://github.com/aidanns/agent-auth/issues/247))

## [0.9.0](https://github.com/aidanns/agent-auth/compare/v0.8.0...v0.9.0) (2026-04-23)

### Features

- **vscode:** commit .vscode workspace ([#245](https://github.com/aidanns/agent-auth/issues/245))

## [0.8.0](https://github.com/aidanns/agent-auth/compare/v0.7.1...v0.8.0) (2026-04-23)

### Features

- **benchmark:** pytest-benchmark suite with scheduled CI ([#241](https://github.com/aidanns/agent-auth/issues/241))

## [0.7.1](https://github.com/aidanns/agent-auth/compare/v0.7.0...v0.7.1) (2026-04-23)

### Bug Fixes

- **things-bridge:** bound subprocess stderr capture ([#239](https://github.com/aidanns/agent-auth/issues/239))

## [0.7.0](https://github.com/aidanns/agent-auth/compare/v0.6.0...v0.7.0) (2026-04-23)

### ⚠ BREAKING CHANGES

- **audit:** HMAC-chained audit log with verify-audit CLI (#103) (#230)

### Features

- **audit:** HMAC-chained audit log with verify-audit CLI ([#103](https://github.com/aidanns/agent-auth/issues/103)) ([#230](https://github.com/aidanns/agent-auth/issues/230))

## [0.6.0](https://github.com/aidanns/agent-auth/compare/v0.5.0...v0.6.0) (2026-04-23)

### ⚠ BREAKING CHANGES

- **notifier:** migrate notification plugin to out-of-process HTTP (#6) (#227)

### Features

- **notifier:** migrate notification plugin to out-of-process HTTP ([#6](https://github.com/aidanns/agent-auth/issues/6)) ([#227](https://github.com/aidanns/agent-auth/issues/227))

## [0.5.0](https://github.com/aidanns/agent-auth/compare/v0.4.0...v0.5.0) (2026-04-23)

### Features

- **rate-limit:** in-memory per-token-family rate limiting ([#102](https://github.com/aidanns/agent-auth/issues/102)) ([#226](https://github.com/aidanns/agent-auth/issues/226))

## [0.4.0](https://github.com/aidanns/agent-auth/compare/v0.3.0...v0.4.0) (2026-04-23)

### Features

- **store:** numbered-SQL migration runner for the token store ([#29](https://github.com/aidanns/agent-auth/issues/29)) ([#222](https://github.com/aidanns/agent-auth/issues/222))

## [0.3.0](https://github.com/aidanns/agent-auth/compare/v0.2.2...v0.3.0) (2026-04-23)

### Features

- **keys:** detect keyring wipe against a non-empty token store ([#31](https://github.com/aidanns/agent-auth/issues/31)) ([#202](https://github.com/aidanns/agent-auth/issues/202))

## [0.2.2](https://github.com/aidanns/agent-auth/compare/v0.2.1...v0.2.2) (2026-04-23)

### Bug Fixes

- **release:** drop commit-hash and closes-issue links from changelog ([#220](https://github.com/aidanns/agent-auth/issues/220))

## [0.2.1](https://github.com/aidanns/agent-auth/compare/v0.2.0...v0.2.1) (2026-04-23)

### Bug Fixes

- **release:** run task format on semantic-release output ([#219](https://github.com/aidanns/agent-auth/issues/219)) ([f4ec2e1](https://github.com/aidanns/agent-auth/commit/f4ec2e1394f6bfcbe83dbd714dc719255325ecb0))

## [0.2.0](https://github.com/aidanns/agent-auth/compare/v0.1.0...v0.2.0) (2026-04-23)

### Features

- **api:** publish OpenAPI 3.1 specs for agent-auth and things-bridge ([#176](https://github.com/aidanns/agent-auth/issues/176)) ([b782b04](https://github.com/aidanns/agent-auth/commit/b782b047e377243a4bdb32ee3d95f8bdc664edbb)), closes [#28](https://github.com/aidanns/agent-auth/issues/28) [#94](https://github.com/aidanns/agent-auth/issues/94)
- **audit:** add schema_version field and stability policy ([#167](https://github.com/aidanns/agent-auth/issues/167)) ([eecc9d6](https://github.com/aidanns/agent-auth/commit/eecc9d62760f81f4b7cafc2b55fb0cd2567e2e54)), closes [#20](https://github.com/aidanns/agent-auth/issues/20)
- **audit:** attach OTel service.name/service.version to every audit entry ([#100](https://github.com/aidanns/agent-auth/issues/100)) ([#200](https://github.com/aidanns/agent-auth/issues/200)) ([ad72be7](https://github.com/aidanns/agent-auth/commit/ad72be7f54c1a4108df0cf008e710604a7aa763d))
- expose token management operations via HTTP API ([#97](https://github.com/aidanns/agent-auth/issues/97)) ([20b73a9](https://github.com/aidanns/agent-auth/commit/20b73a97fbb8383e449f359b8d6948dd2c15bd5a))
- **metrics:** /agent-auth/metrics and /things-bridge/metrics Prometheus endpoints ([#26](https://github.com/aidanns/agent-auth/issues/26)) ([#186](https://github.com/aidanns/agent-auth/issues/186)) ([6d266fb](https://github.com/aidanns/agent-auth/commit/6d266fbbddfd78c94ebb708d28e39f2c72bed969))
- migrate config to YAML, version APIs at /v1/, and add error/audit contract tests ([#126](https://github.com/aidanns/agent-auth/issues/126)) ([4c61c2a](https://github.com/aidanns/agent-auth/commit/4c61c2ae10f553ed115fd2bddbd3d2bfc483abe4)), closes [#24](https://github.com/aidanns/agent-auth/issues/24) [#27](https://github.com/aidanns/agent-auth/issues/27) [#28](https://github.com/aidanns/agent-auth/issues/28) [#20](https://github.com/aidanns/agent-auth/issues/20)
- **release:** attest SLSA Build L3 provenance on every release ([#109](https://github.com/aidanns/agent-auth/issues/109)) ([#180](https://github.com/aidanns/agent-auth/issues/180)) ([7eb1efd](https://github.com/aidanns/agent-auth/commit/7eb1efd3c35f86dcb8e6e69259ac08d3c710040c))
- **release:** migrate autorelease driver to semantic-release ([#204](https://github.com/aidanns/agent-auth/issues/204)) ([857958c](https://github.com/aidanns/agent-auth/commit/857958c718d5811d131052e0352e7971ff100a92))
- **release:** signed SBOMs, autorelease via Release Please, REUSE compliance ([#132](https://github.com/aidanns/agent-auth/issues/132)) ([38e257b](https://github.com/aidanns/agent-auth/commit/38e257b28bceba20c0110dddf01f020785f53974)), closes [SECURITY.md#supply-chain-artifacts](https://github.com/aidanns/SECURITY.md/issues/supply-chain-artifacts) [#97](https://github.com/aidanns/agent-auth/issues/97) [110/#111](https://github.com/110/agent-auth/issues/111) [#127](https://github.com/aidanns/agent-auth/issues/127) [#128](https://github.com/aidanns/agent-auth/issues/128) [#109](https://github.com/aidanns/agent-auth/issues/109) [#93](https://github.com/aidanns/agent-auth/issues/93) [#18](https://github.com/aidanns/agent-auth/issues/18) [#106](https://github.com/aidanns/agent-auth/issues/106) [#110](https://github.com/aidanns/agent-auth/issues/110) [#111](https://github.com/aidanns/agent-auth/issues/111)
- **security:** adopt OWASP ASVS v5 as application security standard ([#177](https://github.com/aidanns/agent-auth/issues/177)) ([de46858](https://github.com/aidanns/agent-auth/commit/de4685815f4bdca146c0f3049476c537a4374c62))
- **server:** graceful SIGTERM / SIGINT shutdown for agent-auth and things-bridge ([#154](https://github.com/aidanns/agent-auth/issues/154)) ([#162](https://github.com/aidanns/agent-auth/issues/162)) ([600a901](https://github.com/aidanns/agent-auth/commit/600a9014a4a5989115cc24f157e137a524a73857)), closes [#152](https://github.com/aidanns/agent-auth/issues/152) [#152](https://github.com/aidanns/agent-auth/issues/152)
- **things-bridge:** deepen /health to verify things-client binary is resolvable ([#91](https://github.com/aidanns/agent-auth/issues/91)) ([#198](https://github.com/aidanns/agent-auth/issues/198)) ([4f93930](https://github.com/aidanns/agent-auth/commit/4f93930a833d916ca89156f9cdbee64c25356552))
- **tls:** optional in-process TLS listener on both HTTP servers ([#101](https://github.com/aidanns/agent-auth/issues/101)) ([#201](https://github.com/aidanns/agent-auth/issues/201)) ([076fa6d](https://github.com/aidanns/agent-auth/commit/076fa6dd35f8bb3ed61881323aca36cff2c52fd3))
- **typecheck:** ratchet agent_auth/\* to strict mypy + pyright ([#164](https://github.com/aidanns/agent-auth/issues/164)) ([35a95e4](https://github.com/aidanns/agent-auth/commit/35a95e488a13177e11147471aaca39725fc4c25d)), closes [#145](https://github.com/aidanns/agent-auth/issues/145)
- **typecheck:** ratchet tests/ + tests_support/ under strict mypy + pyright ([#171](https://github.com/aidanns/agent-auth/issues/171)) ([f51a9f6](https://github.com/aidanns/agent-auth/commit/f51a9f6843aa73b831f1c8f4e56be46f84a364d2)), closes [#148](https://github.com/aidanns/agent-auth/issues/148)
- **typecheck:** ratchet things_bridge/\* to strict mypy + pyright ([#156](https://github.com/aidanns/agent-auth/issues/156)) ([5f090a7](https://github.com/aidanns/agent-auth/commit/5f090a77fc3913e1cac489d76cbc0a4e5717b648)), closes [#146](https://github.com/aidanns/agent-auth/issues/146) [#147](https://github.com/aidanns/agent-auth/issues/147)
- **typecheck:** ratchet things_cli/\* + things_client_common/\* + things_models/\* to strict ([#161](https://github.com/aidanns/agent-auth/issues/161)) ([b0f76f9](https://github.com/aidanns/agent-auth/commit/b0f76f9a86c8e3955625ca342fc426168022d17b)), closes [#147](https://github.com/aidanns/agent-auth/issues/147)
- **verify-standards:** gate graceful-shutdown standard ([#32](https://github.com/aidanns/agent-auth/issues/32)) ([#188](https://github.com/aidanns/agent-auth/issues/188)) ([563c297](https://github.com/aidanns/agent-auth/commit/563c29770706aeaef57637d4352d6f78fbc89140)), closes [#154](https://github.com/aidanns/agent-auth/issues/154)
- **verify-standards:** gate health-endpoint standard ([#25](https://github.com/aidanns/agent-auth/issues/25)) ([#179](https://github.com/aidanns/agent-auth/issues/179)) ([f01491f](https://github.com/aidanns/agent-auth/commit/f01491f943d6e1f68d1d278b177ec90497e20ed4))

### Bug Fixes

- move token management routes under /v1/ namespace ([#137](https://github.com/aidanns/agent-auth/issues/137)) ([#142](https://github.com/aidanns/agent-auth/issues/142)) ([0ead162](https://github.com/aidanns/agent-auth/commit/0ead162e6a037b767de8824256da23dd6411505e)), closes [#126](https://github.com/aidanns/agent-auth/issues/126) [#97](https://github.com/aidanns/agent-auth/issues/97)
- **release:** repair github plugin options and anchor CHANGELOG title ([#213](https://github.com/aidanns/agent-auth/issues/213)) ([7ffd296](https://github.com/aidanns/agent-auth/commit/7ffd296a0a030200f52b685784a7ce955ffad4b8))
- **server:** drain oversize request bodies before rejecting ([#144](https://github.com/aidanns/agent-auth/issues/144)) ([#199](https://github.com/aidanns/agent-auth/issues/199)) ([6c73ec1](https://github.com/aidanns/agent-auth/commit/6c73ec1e6b09c10c4ee37456155e4fab12777a94)), closes [#139](https://github.com/aidanns/agent-auth/issues/139)

## [0.1.0] - 2026-04-19

### Added

- **agent-auth server and CLI** — HTTP validation server (`agent-auth serve`) with full
  token lifecycle management: create, list, modify, revoke, rotate. HMAC-SHA256 signed
  tokens with AES-256-GCM field encryption and signing key held in the system keyring.
  Three-tier scope model (allow / prompt / deny), JIT approval via pluggable notification
  plugin, token families with refresh-token reuse detection, and audit logging.
- **things-bridge** — HTTP bridge server (`things-bridge serve`) that delegates token
  validation to agent-auth and exposes read-only Things 3 endpoints under
  `/things-bridge/`. The bridge contains no Things 3 logic; it shells out to a configured
  Things-client CLI per request.
- **things-client-cli-applescript** — Standalone read-only CLI that talks to Things 3 via
  `osascript` on macOS. Emits JSON on stdout; usable independently of things-bridge for
  local debugging.
- **things-cli** — Thin HTTP client for things-bridge that auto-refreshes/reissues tokens
  via agent-auth. Stores credentials in the system keyring (falls back to a
  `~/.config/things-cli/credentials.yaml` file when no keyring backend is available).

### Changed

- **`task release` auto-derives the next version.** Run `task release` with no
  argument and the script walks Conventional Commits since the last `v*` tag to
  pick a major / minor / patch bump (BREAKING → major, `feat:` → minor,
  `fix:` → patch). Pass `task release -- X.Y.Z` to override. While the current
  tag is in the `0.x` range the API is not considered stable (SemVer 2.0.0 §4),
  so a detected major bump is demoted to a minor bump; pass an explicit
  `task release -- 1.0.0` to graduate.
- **`task release -- -y` skips the confirmation prompt** so the release can
  run hands-off (e.g. `task release -- -y 1.2.3`). The signed-tag step still
  needs your signing key; see `CONTRIBUTING.md` § "Non-interactive signing
  for `task release`" for gpg-agent / ssh-agent pre-warm instructions.

[0.1.0]: https://github.com/aidanns/agent-auth/releases/tag/v0.1.0
