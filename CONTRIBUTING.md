# Contributing to har2mcp

Thanks for helping! Small, focused PRs get merged fastest.

## Dev setup

```bash
git clone https://github.com/hydope/har2mcp && cd har2mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Ground rules

- Every bug fix comes with a test that fails before the fix.
- Keep the core dependency-light. New runtime dependencies need a reason in the PR.
- Never commit real credentials, tokens, cookies or personal data, including inside test fixtures.
- Run the test suite before opening a PR; CI runs it on Python 3.10 to 3.13.

## Good first issues

Look for the `good first issue` label, or pick something from the Roadmap in the README.

## CI

The GitHub Actions workflow lives at `ci/github-actions-ci.yml` (pytest on Python 3.10–3.13). To enable it, move it to `.github/workflows/ci.yml`. It was published outside that folder because the token that created this repo had no `workflow` scope.
