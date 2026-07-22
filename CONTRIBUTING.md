# Contributing to PHEMS Federated Node

Thank you for your interest in contributing! This document explains how to
propose changes, report bugs, and submit code to the project.

## Ways to contribute

- **Report a bug** — open a [GitHub issue](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/issues) using the bug report template.
- **Request a feature** — open an issue using the feature request template, describing the use case and the problem it solves.
- **Improve documentation** — typo fixes, clarifications, and new examples are all welcome.
- **Submit code** — fix a bug, implement a feature, or improve test coverage.

## Before you start

For anything beyond a small fix, please open an issue first (or comment on an
existing one) to discuss the approach. This avoids duplicated effort and
makes sure the change fits the project's direction before you invest time in
a pull request.

## Development workflow

1. **Fork** the repository and clone your fork locally.
2. **Create a branch** for your change:
   ```bash
   git checkout -b fix/short-description
   ```
3. **Set up your environment.** The project is written in Python; install
   dependencies as described in the repository `README.md`.
4. **Make your change**, keeping commits focused and descriptive.
5. **Add or update tests** covering the change where applicable.
6. **Run the test suite and linters** locally before opening a PR.
7. **Update documentation** (README, docstrings, etc.) if behaviour changes.

## Submitting a pull request

- Open your PR against the `main` branch (or the branch specified by
  maintainers).
- Fill in the PR template, including a clear description of *what* changed
  and *why*.
- Link the related issue (e.g. `Closes #123`) if one exists.
- Keep PRs focused — smaller, single-purpose PRs are reviewed faster than
  large ones.
- Be responsive to review feedback. A maintainer will review and may request
  changes before merging.

## Commit messages

Use short, descriptive commit messages in the imperative mood, e.g.
`Fix token refresh on expired session` rather than `Fixed a bug`.

## Coding style

- Follow the existing code style and structure used elsewhere in the
  repository.
- Keep functions small and testable, and prefer clear naming over comments
  that explain unclear naming.
- Add tests alongside new functionality; PRs without any test coverage for
  new behaviour may be asked to add some before merge.

## Code of Conduct

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you agree to abide by its terms.

## Licensing

By contributing, you agree that your contributions will be licensed under
the project's existing license (GPL-3.0), as declared in the repository.

## Getting help

If you have questions about contributing, see [SUPPORT.md](SUPPORT.md) or
open a [discussion](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/discussions).
