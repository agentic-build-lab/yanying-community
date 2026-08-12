# Contributing

Issues and focused pull requests are welcome. Before opening a change:

1. Keep generated media, model files, credentials and local runtime state out of Git.
2. Install `requirements-dev.txt`, then run `ruff check --select E4,E7,E9,F,I services scripts tests`, `ruff format --check services scripts tests`, and `python tests/test_public_surface.py`.
3. Run `scripts/verify-community.ps1` when changing a service or the browser studio.
4. Explain the user-visible behavior and the validation you performed in the pull request.

Use descriptive names tied to the product domain. Avoid temporary migration terminology in public interfaces, and keep compatibility-specific details behind adapter modules.
