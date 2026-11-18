# Development from a source checkout

Use Python 3.11 or newer. The runtime project declares no pip dependencies;
development tooling is pinned separately.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
```

Review a test's fixtures and effects before running it. Record commands and
actual results; see [SOURCE-RELEASE.md](../../SOURCE-RELEASE.md) for this snapshot's
executed validation and limitations. No full-suite or fresh-fleet acceptance is
implied by the presence of tests or workflows.

Generated cache/SQLite state and the unrequired production-style profile E are
not distributed. Profile A-D configuration examples remain paired with their
unchanged overnight test assertions. Private operational handoffs and reference
archives are not build inputs. Credentials and mutable runtime state stay outside
the checkout. Building or testing does not select installation or live operations.
