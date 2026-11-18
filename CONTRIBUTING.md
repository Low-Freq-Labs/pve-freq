# Contributing

Start with [SOURCE-RELEASE.md](SOURCE-RELEASE.md) and
[development setup](docs/development/SETUP.md). This source snapshot is maintained
separately from the project's private operational history.

Keep Python runtime dependencies within the standard library. Preserve explicit
unknown/unavailable/partial states, original operation identity, authorization
and credential boundaries. Tests using fictional inputs do not establish live
infrastructure acceptance. Record the exact commands, results and limitations
for a proposed change; do not claim checks that were not run.

Use isolated local fixtures for tests. A clone, build or test request does not
authorize installation, real fleet operations, source credential use, device
writes or recovery actions. Keep credentials, private keys, live configuration,
runtime databases and captures outside Git.

Submit a focused pull request with its purpose and validation. Report security
issues through the channel in [SECURITY.md](SECURITY.md).
