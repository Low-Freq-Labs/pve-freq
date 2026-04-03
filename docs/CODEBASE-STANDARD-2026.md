# PVE FREQ — Codebase Standard 2026

**Author:** Morty (with Sonny's direction)
**Written:** 2026-04-03
**Purpose:** This is the engineering standard. Every file we touch going forward meets this bar.

---

## The Standard We're Stealing From

We studied the best codebases that exist right now:

| Codebase | Why It's Great | What We Steal |
|----------|---------------|---------------|
| **Tailscale** | Control plane / data plane separation, daemon+CLI architecture, security-first, platform abstraction | Separation of concerns, LocalAPI pattern, state machine architecture |
| **NetBox** | Django domain apps, plugin system, 5-layer validation, REST API consistency | Domain-per-app, validation layers, consistent naming conventions |
| **Kubernetes/kubectl** | Builder/Visitor patterns, plugin system, client-go library | Command dispatch patterns, resource abstraction |
| **Claude Code** | Minimal scaffolding, tool execution system, permission layers, memory persistence | Permission system design, compaction-aware architecture, "delete code with each release" |
| **Homebrew** | DSL for formulae, RuboCop enforcement, hierarchical config | Code quality automation, style enforcement from day one |
| **Terraform** | Module structure, provider design, state management | Config organization, module boundaries, workspace patterns |

### The Claude Code Lesson

Anthropic's most important principle: **"Every feature meant to be helpful ends up limiting the model."** They delete code with each release. Their codebase got SMALLER as it got more capable. 90% of Claude Code is written by Claude Code itself. They ship 60-100 internal releases daily.

**Our translation:** Stop adding complexity. Delete dead code aggressively. If a feature doesn't work end-to-end, it doesn't exist.

### The Tailscale Lesson

Tailscale's architecture separates:
1. **Control plane** — coordination and policy
2. **Data plane** — actual packet forwarding
3. **Management plane** — CLI and LocalAPI

Each plane operates independently. The data plane keeps working even when the control plane is offline.

**Our translation:** FREQ should separate:
1. **Config plane** — freq.toml, hosts.toml, fleet-boundaries.toml
2. **Operation plane** — SSH commands, PVE API calls, device probes
3. **Presentation plane** — CLI output, dashboard, API responses

### The NetBox Lesson

NetBox organizes into discrete Django apps by domain: dcim, ipam, circuits, virtualization, tenancy. Each app contains models, views, serializers, filtersets, forms, urls — all self-contained. Plugins are first-class citizens with a standardized interface.

**Our translation:** FREQ's domain structure should mirror this. Each domain (vm, fleet, firewall, storage, docker) should be self-contained with its own module, API handler, and CLI commands.

---

## Python Version & Features

**Target:** Python 3.13+ (3.14 when ecosystem stabilizes)
**Runtime:** CPython, standard GIL-enabled build

### Features We Use

| Feature | Since | How We Use It |
|---------|-------|---------------|
| `dataclass(slots=True, frozen=True)` | 3.10 | All value objects, config types, result types |
| `dataclass(kw_only=True)` | 3.10 | All dataclasses with 3+ fields — prevents positional mistakes |
| `match/case` (structural pattern matching) | 3.10 | Command dispatch, device type routing, error handling |
| `tomllib` (stdlib TOML) | 3.11 | Config parsing — zero dependencies |
| Type unions with `X | Y` syntax | 3.10 | All type hints — no more `Union[X, Y]` or `Optional[X]` |
| `Self` type | 3.11 | Builder/fluent patterns |
| `TypeAlias` | 3.10 | Complex type definitions |
| `Protocol` classes | 3.8+ | Interface contracts — prefer over ABC |
| `asyncio.TaskGroup` | 3.11 | Structured concurrency for parallel SSH |
| `ExceptionGroup` | 3.11 | Multi-error reporting from fleet operations |
| Deferred annotation evaluation | 3.14 | Forward references without string quotes |

### Features We DON'T Use (Yet)

| Feature | Why Not |
|---------|---------|
| Free-threading (no-GIL) | 5-10% single-thread penalty, ecosystem not ready |
| Template strings (t-strings) | Too new (3.14), ecosystem hasn't adopted |
| JIT compiler | Experimental, unpredictable performance |

---

## Tooling Standard

### Required Tools

| Tool | Purpose | Config |
|------|---------|--------|
| **Ruff** | Linting + formatting (replaces flake8, black, isort) | `pyproject.toml [tool.ruff]` |
| **mypy** (strict mode) | Static type checking | `pyproject.toml [tool.mypy]` |
| **uv** | Package management (replaces pip, poetry, pyenv) | `pyproject.toml` |
| **pytest** | Testing | `pyproject.toml [tool.pytest]` |

### pyproject.toml Configuration

```toml
[tool.ruff]
target-version = "py313"
line-length = 120
indent-width = 4

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # pyflakes
    "I",      # isort
    "N",      # pep8-naming
    "UP",     # pyupgrade — enforce modern syntax
    "B",      # flake8-bugbear
    "A",      # flake8-builtins
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "RUF",    # ruff-specific rules
    "S",      # flake8-bandit (security)
    "PTH",    # flake8-use-pathlib
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # allow assert in tests

[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

---

## Architecture Patterns

### 1. Domain Modules (NetBox-style)

Each domain is self-contained:

```
freq/
├── domains/
│   ├── vm/
│   │   ├── __init__.py
│   │   ├── commands.py     # CLI commands (argparse handlers)
│   │   ├── api.py          # REST API handlers
│   │   ├── service.py      # Business logic
│   │   ├── types.py        # Domain-specific types
│   │   └── tests/
│   ├── fleet/
│   ├── firewall/
│   ├── storage/
│   └── docker/
├── core/
│   ├── ssh.py              # Transport layer (never changes)
│   ├── config.py           # Config loader
│   ├── types.py            # Shared types
│   └── validate.py         # Input validation
├── server/
│   ├── app.py              # HTTP server
│   ├── routes.py           # Route registration
│   ├── auth.py             # Authentication
│   └── middleware.py       # CORS, logging, errors
└── web/
    ├── js/app.js           # Frontend SPA
    └── app.html            # HTML shell
```

### 2. Result Types (Not Exceptions for Expected Failures)

```python
from dataclasses import dataclass

@dataclass(slots=True, frozen=True)
class Result[T]:
    """Operation result — success or failure with context."""
    ok: bool
    value: T | None = None
    error: str = ""
    
    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return cls(ok=True, value=value)
    
    @classmethod
    def failure(cls, error: str) -> "Result[T]":
        return cls(ok=False, error=error)
```

### 3. Protocol-Based Interfaces (Not ABC)

```python
from typing import Protocol

class DeviceProber(Protocol):
    """Any device that can be probed for health."""
    def probe(self, ip: str, cfg: FreqConfig) -> ProbeResult: ...
    def device_type(self) -> str: ...

class SSHTransport(Protocol):
    """Anything that can run SSH commands."""
    def run(self, host: str, command: str, **kwargs) -> CmdResult: ...
    async def async_run(self, host: str, command: str, **kwargs) -> CmdResult: ...
```

### 4. Validation at Boundaries Only

```python
# YES — validate at the API boundary
def handle_vm_create(handler: RequestHandler) -> None:
    params = get_params(handler)
    name = params.get("name", [""])[0]
    if not validate.label(name):
        json_response(handler, {"error": "Invalid name"}, 400)
        return
    # From here, name is trusted
    result = vm_service.create(name=name, ...)

# NO — don't re-validate inside the service
def create(self, name: str, ...) -> Result:
    # name was already validated at the boundary
    # just use it
    ...
```

### 5. Command Dispatch (kubectl-style)

```python
# Pattern matching for clean dispatch
match args.command:
    case "vm" | "vms":
        match args.action:
            case "list":
                return vm.cmd_list(cfg, args)
            case "create":
                return vm.cmd_create(cfg, args)
            case _:
                fmt.error(f"Unknown action: {args.action}")
                return 1
    case "fleet":
        ...
```

---

## Naming Conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Files | `snake_case.py` | `init_cmd.py` |
| Classes | `PascalCase` | `FreqConfig`, `CmdResult` |
| Functions | `snake_case` | `load_config()`, `find_reachable_node()` |
| Constants | `UPPER_SNAKE` | `SSH_TIMEOUT`, `MAX_PARALLEL` |
| Private | `_leading_underscore` | `_parse_entries()`, `_bg_cache` |
| API handlers | `handle_{resource}_{action}` | `handle_vm_create`, `handle_fleet_status` |
| CLI commands | `cmd_{domain}_{action}` | `cmd_vm_list`, `cmd_fleet_run` |
| Types | `{Domain}{Thing}` | `VMConfig`, `FleetHealth`, `ProbeResult` |
| Test files | `test_{module}.py` | `test_ssh.py`, `test_vm_create.py` |

---

## Code Rules

### DO
- Use `dataclass(slots=True, frozen=True)` for all value objects
- Use `Protocol` for interface contracts
- Use `match/case` for dispatch (not if/elif chains)
- Use `asyncio.TaskGroup` for parallel operations
- Validate at system boundaries, trust internally
- Return `Result` types for expected failures
- Log errors server-side, return generic messages to clients
- Use `shlex.quote()` for any user input going into shell commands

### DON'T
- Don't use `shell=True` in subprocess unless admin-configured commands (cron/webhooks)
- Don't catch `Exception` broadly — catch specific exceptions
- Don't use `str(e)` in API responses — log it, return generic error
- Don't use mutable default arguments
- Don't use `Any` type — find the real type
- Don't add features without E2E verification
- Don't leave dead code — delete it or don't merge it

### Auth Rules
- Every write/modify API endpoint MUST have `_check_session_role()`
- Destructive operations (destroy, delete, migrate, clone): `admin`
- Modify operations (power, resize, snapshot, tag): `operator`
- Read operations: no auth required (dashboard needs them)
- Setup wizard endpoints: gated by `_is_first_run()` only

---

## Quality Gates

Before any code ships:

1. **ruff check** passes with zero warnings
2. **mypy --strict** passes (gradual: new files only for now)
3. **All existing tests pass**
4. **No dead imports** (ruff catches these)
5. **No `str(e)` in API responses**
6. **No missing auth on write endpoints**
7. **Browser verification** — if it touches the dashboard, open the browser

---

## References

### Architecture Inspiration
- Tailscale: https://deepwiki.com/tailscale/tailscale
- NetBox: https://deepwiki.com/netbox-community/netbox
- Kubernetes design patterns: https://dev.to/arriqaaq/golang-design-patterns-in-kubernetes-codebase-2ol0
- Claude Code architecture: https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built

### Python 2026 Standards
- Python 3.14 features: https://docs.python.org/3/whatsnew/3.14.html
- Ruff + uv + ty: https://www.w3resource.com/python/astral-python-tooling-revolution-in-2026.php
- Type safety: https://dasroot.net/posts/2026/02/type-safety-python-mypy-pydantic-runtime-validation/
- Modern Python patterns: https://thinhdanggroup.github.io/python-code-structure/

### Domain-Driven Design
- DDD for IaC: https://caylent.com/blog/domain-driven-design-for-large-infrastructure-as-code-projects
- Clean Architecture in Python: https://www.glukhov.org/post/2025/11/python-design-patterns-for-clean-architecture/
