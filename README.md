# PVE FREQ

A Python CLI and web dashboard for Proxmox infrastructure management.

**Work in progress.** We are sharing the current code so anyone interested can
look around, follow development and contribute. Features and infrastructure
workflows are at different stages of implementation and testing.

## Explore the source

- `freq/`: command-line tools, backend services, adapters and the embedded dashboard.
- `conf/`: example configuration and plugins.
- `tests/`: tests and configuration scenarios.
- `docs/`: selected CLI, API, configuration and interface documentation.

Start with [development setup](docs/development/SETUP.md) for a local checkout,
or browse the [CLI reference](docs/CLI-REFERENCE.md), [API reference](docs/API-REFERENCE.md)
and [configuration guide](docs/CONFIGURATION.md). [Contributing](CONTRIBUTING.md)
describes the development boundaries.

The Python project targets Python 3.11 or newer and declares no runtime pip
dependencies. The dashboard includes locally bundled xterm 5.5.0, fit 0.10.0,
clipboard 0.1.0 and embedded js-base64 3.7.7; see
[third-party notices](THIRD-PARTY-NOTICES.txt). Development tooling is separate.

This clean source snapshot is based on private development main
`37d23021b8fb4e9661866e3de245ccff1d66b21b`. Private operational records and old
repository history are not included. [SOURCE-RELEASE.md](SOURCE-RELEASE.md)
records the snapshot scope and validation; this publication is not a new stable
release or an announcement of PyPI/container packages.

## License and security

Copyright LOW FREQ Labs. The project declaration is [AGPL-3.0-or-later](LICENSE);
the complete terms are in [COPYING](COPYING). Bundled components retain their
separate notices in [LICENSES](LICENSES) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
For vulnerability reporting, see [SECURITY.md](SECURITY.md).
