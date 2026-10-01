<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Contributing

Thank you for your interest in contributing to this project! We value and appreciate any contributions you can make.
To maintain a collaborative and respectful environment, please consider the following guidelines when contributing to this project.

## Prerequisites

- Before starting to contribute to the code, you must first sign the
  Contributor License Agreement (CLA).
  Detailed instructions on how to proceed can be found [here](https://github.com/InditexTech/foss/blob/main/CONTRIBUTING.md).

## How to Contribute

1. Open an issue to discuss and gather feedback on the feature or fix you wish to address.
2. Fork the repository and clone it to your local machine.
3. Create a new branch to work on your contribution: `git checkout -b your-branch-name`.
4. Make the necessary changes in your local branch.
5. Ensure that your code follows the established project style and formatting guidelines.
6. Perform testing to ensure your changes do not introduce errors.
7. Make clear and descriptive commits that explain your changes.
8. Push your branch to the remote repository: `git push origin your-branch-name`.
9. Open a pull request describing your changes and linking the corresponding issue.
10. Await comments and discussions on your pull request. Make any necessary modifications based on the received feedback.
11. Once your pull request is approved, your contribution will be merged into the main branch.

## Contribution Guidelines

- All contributors are expected to follow the project's [code of conduct](CODE_OF_CONDUCT.md). Please be respectful and
considerate towards other contributors.
- Before starting work on a new feature or fix, check existing [issues](https://github.com/InditexTech/kumoss/issues) and [pull requests](https://github.com/InditexTech/kumoss/pulls)
to avoid duplications and unnecessary discussions.
- If you wish to work on an existing issue, comment on the issue to inform other contributors that you are working on it.
This will help coordinate efforts and prevent conflicts.
- It is always advisable to discuss and gather feedback from the community before making significant changes to the
project's structure or architecture.
- Ensure a clean and organized commit history. Divide your changes into logical and descriptive commits. Commit subjects must follow the [Conventional Commits Specification](https://www.conventionalcommits.org/en/v1.0.0/) (for example `fix(core): release session lock`); CI rejects other subjects. Sign your commits (`git commit -S`) — signing is required by policy and checked in review, not enforced by any CI workflow.
- Document any new changes or features you add. This will help other contributors and project users understand your work
and its purpose.
- Be sure to link the corresponding issue in your pull request to maintain proper tracking of contributions.
- Remember to add license and copyright information following the [REUSE Specification](https://reuse.software/spec-3.3/#licensing-information): every new file starts with an SPDX header (`SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)` and `SPDX-License-Identifier: Apache-2.0`). CI runs the REUSE check.

## Development

The repository is a monorepo: the FastAPI core in `core/`, four sidecar services in `services/`, the React web application in `client/web/`, and the sidecar OpenAPI contracts in `contracts/`. [Architecture](https://inditextech.github.io/kumoss/stable/main/architecture/) explains how they fit together.

**Run the stack.** Copy each `env.sample` to a `.env` next to it (`core/.env` is required), set the two model strings in `config.yaml`, and run `docker compose up --build`. [Quickstart](https://inditextech.github.io/kumoss/stable/main/quickstart/) is the step-by-step guide. `docker compose up --watch` syncs `core/` into the running container, but the server runs without `--reload`, so run `docker compose restart core` after a sync.

**Core tests** (Python 3.13, `uv`): `pytest` and `pytest-cov` live in the
`tooling` dependency group, so sync the project first. **Async tests use
`unittest.IsolatedAsyncioTestCase`** (no pytest-asyncio plugin required,
so no `--asyncio-mode` flag):

```bash
cd core
uv sync --frozen --group tooling
uv run --no-sync pytest tests/
```

Async tests use `unittest.IsolatedAsyncioTestCase` and need no plugin or extra flag. `core/tests/conftest.py` supplies placeholder values for the LLM credential, the database URL and the mandatory `NEBULA_IAC_TOKEN` that the configuration module validates at import; suites that talk to PostgreSQL or Redis need the compose stack (or point `NEBULA_SQL_DATABASE_URL` and `NEBULA_REDIS_URL` at your own instances).

**Frontend checks** (Node 24): `cd client/web && npm ci && npm run lint && npm run test:ci && npm run build`.

**Sidecar tests:** `cd services/<name> && uv sync --group tooling && uv run pytest`.

**Lint and format.** `pre-commit run --all-files` runs Ruff (check and format), the REUSE check, and gitleaks secret scanning; install the hooks with `pre-commit install`.

**CI.** Pull requests run Repolinter, the REUSE check, the Conventional Commits check, and an offline Markdown link and anchor check, plus the `Verify` workflow: frontend type check, tests, and production build, and the pytest suite of each sidecar. The core suite is not run in CI, so run it locally against the compose stack before opening a pull request.

**Contracts.** Changing a sidecar behaviour means updating its spec in `contracts/openapi/`, its conformance suite in `contracts/conformance/`, and regenerating the core's client as described in [`contracts/openapi/README.md`](contracts/openapi/README.md).

**Pull requests.** Fill in the pull-request template (signed commits, Conventional Commits, documentation updated, CLA signed) and link the issue. Include UI screenshots for visible changes.
