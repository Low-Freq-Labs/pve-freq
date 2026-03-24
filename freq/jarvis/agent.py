"""Agent orchestration for FREQ.

Create, manage, and run AI specialist agents on your infrastructure.
Each agent gets: a VM, a CLAUDE.md, a tmux workspace, and a mission.

Usage:
  freq agent templates               # list available specialist templates
  freq agent create infra-manager    # spin up a new specialist
  freq agent list                    # show running agents
  freq agent start <name>            # start an agent's tmux session
  freq agent stop <name>             # stop an agent
  freq agent destroy <name>          # remove agent + VM

Architecture:
  Each agent = VM + user account + workspace + CLAUDE.md + tmux session
  FREQ handles: VM creation, user setup, workspace scaffolding, session management
  The user handles: API keys, customizing the CLAUDE.md, talking to the agent
"""
import json
import os
import shutil
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Agent operation timeouts
AGENT_CMD_TIMEOUT = 5
AGENT_CREATE_TIMEOUT = 120
AGENT_STOP_TIMEOUT = 30
AGENT_DEPLOY_TIMEOUT = 10


# --- Agent Templates ---

TEMPLATES = {
    "infra-manager": {
        "name": "infra-manager",
        "description": "Infrastructure operator — fleet monitoring, incident response, maintenance",
        "cores": 2,
        "ram": 4096,
        "disk": 32,
        "packages": ["git", "tmux", "jq", "curl", "openssh-client"],
        "claude_md": """# {name} — Infrastructure Manager

## Mission
Monitor and maintain cluster infrastructure. Respond to incidents. Keep the fleet healthy.

## Capabilities
- SSH access to fleet hosts (via service account)
- FREQ CLI for fleet operations
- Read-only access to monitoring data
- Alert on degradation, report to operator

## Boundaries
- Do NOT make changes without operator approval
- Do NOT touch production VMs directly
- Report findings, recommend actions, wait for confirmation

## Tools Available
- `freq status` — fleet health
- `freq health` — detailed metrics
- `freq audit` — security scan
- `freq check <policy>` — compliance check
- `freq learn <query>` — knowledge base
- `freq risk <target>` — blast radius analysis
""",
    },
    "security-ops": {
        "name": "security-ops",
        "description": "Security specialist — auditing, hardening, compliance, vulnerability scanning",
        "cores": 2,
        "ram": 2048,
        "disk": 32,
        "packages": ["git", "tmux", "jq", "nmap", "openssh-client"],
        "claude_md": """# {name} — Security Operations

## Mission
Harden cluster infrastructure. Audit configurations. Enforce compliance policies.

## Capabilities
- SSH access to fleet hosts for auditing
- FREQ security commands (audit, harden, check, fix)
- Network scanning (nmap) for port audits
- Policy engine for drift detection

## Boundaries
- Do NOT apply fixes without operator review (use --dry-run first)
- Do NOT scan networks outside the configured fleet
- Always show diffs before applying changes

## Tools Available
- `freq audit` — security scan across fleet
- `freq harden <host>` — apply SSH hardening
- `freq check ssh-hardening` — policy compliance
- `freq diff ssh-hardening` — show drift
- `freq sweep` — full audit + policy pipeline
""",
    },
    "dev": {
        "name": "dev",
        "description": "Development specialist — building, testing, shipping code",
        "cores": 4,
        "ram": 4096,
        "disk": 64,
        "packages": ["git", "tmux", "jq", "curl", "build-essential", "openssh-client"],
        "claude_md": """# {name} — Development Specialist

## Mission
Build, test, and ship software. Manage development workflows.

## Capabilities
- Full development environment (git, build tools, Python)
- SSH access to lab hosts for testing
- FREQ CLI for infrastructure operations
- VM management for test environments

## Boundaries
- Only create VMs in the configured lab VMID range
- Do NOT push to production branches without review
- Run tests before committing

## Tools Available
- `freq create` — spin up test VMs
- `freq clone` — clone existing VMs for testing
- `freq destroy` — clean up test VMs
- `freq exec` — run commands across fleet
""",
    },
    "media-ops": {
        "name": "media-ops",
        "description": "Media stack operator — Plex, Sonarr, Radarr, downloads, transcoding",
        "cores": 2,
        "ram": 2048,
        "disk": 32,
        "packages": ["git", "tmux", "jq", "curl", "openssh-client"],
        "claude_md": """# {name} — Media Stack Operator

## Mission
Manage the Plex media ecosystem. Monitor downloads, transcoding, library health.

## Capabilities
- Docker container management on media hosts
- API access to Sonarr, Radarr, Prowlarr, Plex, Tautulli
- FREQ media commands for stack health checks
- Container log analysis

## Boundaries
- Do NOT restart containers without checking active streams
- Do NOT modify download client configs
- Monitor and report, escalate issues to operator

## Tools Available
- `freq media` — media stack health
- `freq docker <host>` — container status
- `freq log <host>` — container logs
- `freq health` — infrastructure health
""",
    },
    "blank": {
        "name": "blank",
        "description": "Empty template — start from scratch with just FREQ installed",
        "cores": 2,
        "ram": 2048,
        "disk": 32,
        "packages": ["git", "tmux", "jq", "openssh-client"],
        "claude_md": """# {name} — Custom Agent

## Mission
Define your mission here.

## Capabilities
- FREQ CLI installed and configured
- SSH access to fleet hosts
- Define what this agent can do

## Boundaries
- Define what this agent should NOT do

## Tools Available
- All FREQ commands available
- Customize this section for your use case
""",
    },
}


# --- Agent Registry ---

def _agents_file(cfg: FreqConfig) -> str:
    """Path to the agents registry file."""
    return os.path.join(cfg.data_dir, "jarvis", "agents.json")


def _load_agents(cfg: FreqConfig) -> dict:
    """Load agent registry."""
    path = _agents_file(cfg)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_agents(cfg: FreqConfig, agents: dict) -> bool:
    """Save agent registry."""
    path = _agents_file(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(agents, f, indent=2)
        return True
    except OSError:
        return False


# --- Commands ---

def cmd_agent(cfg: FreqConfig, pack, args) -> int:
    """Agent management dispatcher."""
    action = getattr(args, "action", None)

    if not action:
        fmt.error("Usage: freq agent <templates|create|list|start|stop|destroy> [name]")
        return 1

    if action == "templates":
        return _cmd_templates(cfg)
    elif action == "create":
        return _cmd_create(cfg, args)
    elif action == "list":
        return _cmd_list(cfg)
    elif action == "start":
        return _cmd_start(cfg, args)
    elif action == "stop":
        return _cmd_stop(cfg, args)
    elif action == "destroy":
        return _cmd_destroy(cfg, args)
    elif action == "status":
        return _cmd_status(cfg, args)
    elif action == "ssh":
        return _cmd_ssh_agent(cfg, args)
    else:
        fmt.error(f"Unknown agent action: {action}")
        return 1


def _cmd_templates(cfg: FreqConfig) -> int:
    """List available agent templates."""
    fmt.header("Agent Templates")
    fmt.blank()

    fmt.table_header(
        ("TEMPLATE", 18),
        ("RESOURCES", 16),
        ("DESCRIPTION", 36),
    )

    for key, tmpl in TEMPLATES.items():
        resources = f"{tmpl['cores']}c/{tmpl['ram']}MB/{tmpl['disk']}GB"
        fmt.table_row(
            (f"{fmt.C.CYAN}{key}{fmt.C.RESET}", 18),
            (f"{fmt.C.DIM}{resources}{fmt.C.RESET}", 16),
            (f"{fmt.C.DIM}{tmpl['description'][:36]}{fmt.C.RESET}", 36),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Create: freq agent create <template> [--name <name>]{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_create(cfg: FreqConfig, args) -> int:
    """Create a new agent — VM + workspace + CLAUDE.md."""
    template_name = getattr(args, "name", None) or getattr(args, "template", None)
    if not template_name:
        fmt.error("Usage: freq agent create <template> [--name <agent-name>]")
        fmt.info(f"Templates: {', '.join(TEMPLATES.keys())}")
        return 1

    # Check if it's a template name or agent name
    if template_name in TEMPLATES:
        template = TEMPLATES[template_name]
        agent_name = getattr(args, "agent_name", None) or template_name
    else:
        # Treat as agent name, default to blank template
        agent_name = template_name
        template = TEMPLATES.get("blank", TEMPLATES["blank"])

    fmt.header(f"Create Agent: {agent_name}")
    fmt.blank()

    # Check if agent already exists
    agents = _load_agents(cfg)
    if agent_name in agents:
        fmt.error(f"Agent '{agent_name}' already exists.")
        fmt.info("Use 'freq agent destroy' first, or choose a different name.")
        fmt.blank()
        fmt.footer()
        return 1

    # Get image preference
    image = getattr(args, "image", None) or "debian-13"
    use_cloud_init = getattr(args, "no_cloud_init", None) is None

    # Show plan
    fmt.line(f"  {fmt.C.BOLD}Agent:{fmt.C.RESET}     {agent_name}")
    fmt.line(f"  {fmt.C.BOLD}Template:{fmt.C.RESET}  {template['name']}")
    fmt.line(f"  {fmt.C.BOLD}Resources:{fmt.C.RESET} {template['cores']} cores, {template['ram']}MB RAM, {template['disk']}GB disk")
    fmt.line(f"  {fmt.C.BOLD}Image:{fmt.C.RESET}     {image}")
    fmt.line(f"  {fmt.C.BOLD}Cloud-init:{fmt.C.RESET} {'Yes (auto-provision)' if use_cloud_init else 'No (empty VM)'}")
    fmt.line(f"  {fmt.C.BOLD}Packages:{fmt.C.RESET}  {', '.join(template['packages'])}")
    fmt.blank()

    # Confirm
    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Create this agent? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Step 1: Find PVE node
    fmt.step_start("Finding PVE node")
    from freq.modules.pve import _find_reachable_node, _pve_cmd
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("No PVE node reachable")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"Using {node_ip}")

    # Step 2: Get next VMID (in agent/lab range from fleet-boundaries.toml)
    fmt.step_start("Allocating VMID")
    lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
    vmid_floor = lab_cat.get("range_start", 5000)
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
    if not ok:
        fmt.step_fail("Cannot get VMID")
        fmt.blank()
        fmt.footer()
        return 1
    vmid = int(stdout.strip())
    # Ensure it's in the configured safe range
    if vmid < vmid_floor:
        vmid = vmid_floor
    fmt.step_ok(f"VMID {vmid}")

    # Step 3: Create VM (with cloud-init if available)
    if use_cloud_init:
        from freq.jarvis.provision import provision_agent_vm
        ok = provision_agent_vm(
            cfg, node_ip, vmid, agent_name,
            image_key=image,
            cores=template["cores"],
            ram=template["ram"],
            disk_gb=template["disk"],
        )
        if not ok:
            # Fallback to empty VM
            fmt.step_warn("Cloud-init failed — creating empty VM instead")
            use_cloud_init = False

    if not use_cloud_init:
        fmt.step_start(f"Creating VM {vmid}")
        create_cmd = (
            f"qm create {vmid} --name {agent_name} "
            f"--cores {template['cores']} --memory {template['ram']} "
            f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
            f"--net0 virtio,bridge={cfg.nic_bridge} "
            f"--scsihw {cfg.vm_scsihw}"
        )
        stdout, ok = _pve_cmd(cfg, node_ip, create_cmd, timeout=AGENT_CREATE_TIMEOUT)
        if ok:
            fmt.step_ok(f"VM {vmid} created (empty — install OS manually)")
        else:
            fmt.step_fail(f"VM creation failed: {stdout}")
            fmt.blank()
            fmt.footer()
            return 1

    # Step 4: Register agent
    fmt.step_start("Registering agent")
    agents[agent_name] = {
        "name": agent_name,
        "template": template["name"],
        "vmid": vmid,
        "node": node_ip,
        "status": "created",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cores": template["cores"],
        "ram": template["ram"],
        "disk": template["disk"],
    }
    if _save_agents(cfg, agents):
        fmt.step_ok("Agent registered")
    else:
        fmt.step_fail("Failed to save agent registry")

    # Step 5: Save CLAUDE.md for this agent
    fmt.step_start("Generating CLAUDE.md")
    claude_md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", agent_name)
    os.makedirs(claude_md_dir, exist_ok=True)
    claude_md_path = os.path.join(claude_md_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(template["claude_md"].format(name=agent_name))
    fmt.step_ok(f"CLAUDE.md saved to {claude_md_dir}")

    fmt.blank()
    fmt.divider("Agent Created")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}Agent '{agent_name}' is ready.{fmt.C.RESET}")
    fmt.blank()
    if use_cloud_init:
        fmt.line(f"  {fmt.C.GRAY}Next steps:{fmt.C.RESET}")
        fmt.line(f"    1. Wait ~60s for VM {vmid} to boot via cloud-init")
        fmt.line(f"    2. SSH in: ssh {cfg.ssh_service_account}@<vm-ip>")
        fmt.line(f"    3. Install FREQ: curl install.sh | sudo bash")
        fmt.line(f"    4. Copy CLAUDE.md: {claude_md_path}")
        fmt.line(f"    5. Set up Claude Code or your preferred LLM")
        fmt.line(f"    6. freq agent start {agent_name}")
    else:
        fmt.line(f"  {fmt.C.GRAY}Next steps:{fmt.C.RESET}")
        fmt.line(f"    1. Install an OS on VM {vmid} (attach ISO or cloud-init)")
        fmt.line(f"    2. Deploy FREQ: scp install.sh to VM, sudo bash install.sh")
        fmt.line(f"    3. Copy CLAUDE.md: {claude_md_path}")
        fmt.line(f"    4. Set up Claude Code or your preferred LLM")
        fmt.line(f"    5. freq agent start {agent_name}")
    fmt.blank()
    fmt.footer()

    logger.info(f"agent created: {agent_name} (VMID {vmid}, template {template['name']})")
    return 0


def _cmd_list(cfg: FreqConfig) -> int:
    """List all registered agents."""
    fmt.header("Agents")
    fmt.blank()

    agents = _load_agents(cfg)
    if not agents:
        fmt.line(f"{fmt.C.YELLOW}No agents registered.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Create one: freq agent create <template>{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 18),
        ("TEMPLATE", 16),
        ("VMID", 6),
        ("STATUS", 10),
        ("CREATED", 12),
    )

    for name, agent in agents.items():
        status = agent.get("status", "unknown")
        status_badge = fmt.badge(status) if status in ("running", "created", "stopped") else fmt.badge("unknown")

        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 18),
            (f"{fmt.C.DIM}{agent.get('template', '?')}{fmt.C.RESET}", 16),
            (str(agent.get("vmid", "?")), 6),
            (status_badge, 10),
            (f"{fmt.C.DIM}{agent.get('created', '?')[:10]}{fmt.C.RESET}", 12),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(agents)} agent(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_start(cfg: FreqConfig, args) -> int:
    """Start an agent's tmux session."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq agent start <name>")
        return 1

    agents = _load_agents(cfg)
    if name not in agents:
        fmt.error(f"Agent not found: {name}")
        return 1

    agent = agents[name]
    fmt.header(f"Start Agent: {name}")
    fmt.blank()

    # Check if tmux session already exists
    import subprocess
    session_name = f"FREQ-{name.upper()}"
    r = subprocess.run(["tmux", "has-session", "-t", session_name],
                       capture_output=True, timeout=AGENT_CMD_TIMEOUT)

    if r.returncode == 0:
        fmt.line(f"{fmt.C.YELLOW}Session '{session_name}' already running.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Attach: tmux attach -t {session_name}{fmt.C.RESET}")
    else:
        fmt.step_start(f"Creating tmux session '{session_name}'")
        claude_md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
        subprocess.run([
            "tmux", "new-session", "-d", "-s", session_name,
            "-x", "200", "-y", "50",
        ], capture_output=True, timeout=AGENT_CMD_TIMEOUT)
        fmt.step_ok(f"Session '{session_name}' created")

        # Update status
        agents[name]["status"] = "running"
        _save_agents(cfg, agents)

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Attach:{fmt.C.RESET}  tmux attach -t {session_name}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_stop(cfg: FreqConfig, args) -> int:
    """Stop an agent's tmux session."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq agent stop <name>")
        return 1

    agents = _load_agents(cfg)
    if name not in agents:
        fmt.error(f"Agent not found: {name}")
        return 1

    session_name = f"FREQ-{name.upper()}"
    import subprocess
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True, timeout=AGENT_CMD_TIMEOUT)

    agents[name]["status"] = "stopped"
    _save_agents(cfg, agents)

    fmt.success(f"Agent '{name}' stopped (session '{session_name}' killed)")
    return 0


def _cmd_destroy(cfg: FreqConfig, args) -> int:
    """Destroy an agent — remove VM and registration."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq agent destroy <name>")
        return 1

    agents = _load_agents(cfg)
    if name not in agents:
        fmt.error(f"Agent not found: {name}")
        return 1

    agent = agents[name]
    vmid = agent.get("vmid")

    fmt.header(f"Destroy Agent: {name}")
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}This will destroy VM {vmid} and remove agent '{name}'.{fmt.C.RESET}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.RED}Type the agent name to confirm:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != name:
            fmt.info("Cancelled.")
            return 0

    # Stop tmux session
    session_name = f"FREQ-{name.upper()}"
    import subprocess
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True, timeout=AGENT_CMD_TIMEOUT)

    # Destroy VM
    if vmid:
        fmt.step_start(f"Destroying VM {vmid}")
        from freq.modules.pve import _find_reachable_node, _pve_cmd
        node_ip = _find_reachable_node(cfg)
        if node_ip:
            _pve_cmd(cfg, node_ip, f"qm stop {vmid} --skiplock", timeout=AGENT_STOP_TIMEOUT)
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=AGENT_CREATE_TIMEOUT)
            if ok:
                fmt.step_ok(f"VM {vmid} destroyed")
            else:
                fmt.step_warn(f"VM destroy may have failed: {stdout}")
        else:
            fmt.step_warn("No PVE node reachable — VM may still exist")

    # Remove from registry
    del agents[name]
    _save_agents(cfg, agents)

    # Remove CLAUDE.md
    claude_md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
    if os.path.isdir(claude_md_dir):
        shutil.rmtree(claude_md_dir)

    fmt.step_ok(f"Agent '{name}' removed")
    fmt.blank()
    fmt.footer()

    logger.info(f"agent destroyed: {name} (VMID {vmid})")
    return 0


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Live health check on all agents — VM running? SSH reachable?"""
    fmt.header("Agent Status")
    fmt.blank()

    agents = _load_agents(cfg)
    if not agents:
        fmt.line(f"{fmt.C.YELLOW}No agents registered.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    from freq.modules.pve import _find_reachable_node, _pve_cmd
    import json as json_mod

    node_ip = _find_reachable_node(cfg)

    # Get live VM status from PVE
    vm_status = {}
    if node_ip:
        stdout, ok = _pve_cmd(cfg, node_ip,
                              "pvesh get /cluster/resources --type vm --output-format json")
        if ok and stdout:
            try:
                for vm in json_mod.loads(stdout):
                    vm_status[vm.get("vmid")] = vm
            except json_mod.JSONDecodeError:
                pass

    fmt.table_header(
        ("NAME", 16),
        ("VMID", 6),
        ("VM STATE", 10),
        ("SSH", 8),
        ("TEMPLATE", 14),
    )

    for name, agent in agents.items():
        vmid = agent.get("vmid")

        # Check VM state from PVE
        vm_info = vm_status.get(vmid, {})
        vm_state = vm_info.get("status", "unknown")
        if vm_state == "running":
            vm_badge = fmt.badge("running")
        elif vm_state == "stopped":
            vm_badge = fmt.badge("down")
        else:
            vm_badge = fmt.badge("unknown")

        # Quick SSH check (only if running)
        ssh_badge = fmt.badge("skip")
        if vm_state == "running":
            # Try to find IP from PVE agent
            r = ssh_run(host=node_ip,
                        command=f"qm agent {vmid} network-get-interfaces 2>/dev/null | python3 -c \"import json,sys; data=json.load(sys.stdin); [print(a['ip-address']) for i in data.get('result',[]) for a in i.get('ip-addresses',[]) if a.get('ip-address-type')=='ipv4' and not a['ip-address'].startswith('127.')]\" 2>/dev/null || echo ''",
                        key_path=cfg.ssh_key_path,
                        connect_timeout=5, command_timeout=AGENT_DEPLOY_TIMEOUT,
                        htype="pve", use_sudo=True)
            if r.returncode == 0 and r.stdout.strip():
                ip = r.stdout.strip().split('\n')[0]
                agent["ip"] = ip
                # Quick SSH test
                ssh_result = ssh_run(host=ip, command="echo ok",
                                     key_path=cfg.ssh_key_path,
                                     connect_timeout=3, command_timeout=AGENT_CMD_TIMEOUT,
                                     htype="linux", use_sudo=False)
                ssh_badge = fmt.badge("ok") if ssh_result.returncode == 0 else fmt.badge("fail")
            else:
                ssh_badge = fmt.badge("pending")

        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 16),
            (str(vmid), 6),
            (vm_badge, 10),
            (ssh_badge, 8),
            (f"{fmt.C.DIM}{agent.get('template', '?')}{fmt.C.RESET}", 14),
        )

    # Save any discovered IPs
    _save_agents(cfg, agents)

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_ssh_agent(cfg: FreqConfig, args) -> int:
    """SSH directly to an agent's VM."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq agent ssh <name>")
        return 1

    agents = _load_agents(cfg)
    if name not in agents:
        fmt.error(f"Agent not found: {name}")
        return 1

    agent = agents[name]
    ip = agent.get("ip")

    if not ip:
        # Try to discover IP
        fmt.info(f"No IP cached for '{name}'. Run 'freq agent status' first to discover.")
        return 1

    fmt.dim(f"  Connecting to agent '{name}' at {ip}...")
    print()

    import os as _os
    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if cfg.ssh_key_path:
        ssh_cmd.extend(["-i", cfg.ssh_key_path])
    ssh_cmd.append(f"{cfg.ssh_service_account}@{ip}")

    _os.execvp("ssh", ssh_cmd)
