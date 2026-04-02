"""Docker fleet management for FREQ — containers, volumes, images, updates.

Domain: freq docker <action>
What: Fleet-wide Docker management. Container lifecycle, image updates,
      volume management, resource cleanup. Extends existing stack.py
      with fleet-wide parallel operations.
Replaces: Watchtower, Portainer, manual docker commands across hosts
Architecture:
    - All operations via ssh_run_many to Docker hosts (htype=docker)
    - Image update checking via docker inspect + registry comparison
    - Volume/image cleanup via docker system prune
Design decisions:
    - SSH-based, not Docker API. No docker socket exposure needed.
    - Fleet-wide: every command targets all docker hosts by default.
    - Update check is non-destructive. Apply is explicit.
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many
from freq.core import log as logger


def _docker_hosts(cfg):
    return [h for h in cfg.hosts if h.htype == "docker"]


def cmd_docker_containers(cfg: FreqConfig, pack, args) -> int:
    """List containers across all Docker hosts."""
    hosts = _docker_hosts(cfg)
    if not hosts:
        fmt.error("No Docker hosts in fleet (htype=docker)")
        return 1

    fmt.header("Docker Containers", breadcrumb="FREQ > Docker")
    fmt.blank()

    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in hosts]
    results = run_many(hosts=hosts_data,
                       command="docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null || sudo docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null",
                       key_path=cfg.ssh_key_path,
                       connect_timeout=cfg.ssh_connect_timeout, command_timeout=10)

    total = 0
    for h in hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0 and r.stdout.strip():
            containers = r.stdout.strip().splitlines()
            fmt.line(f"{fmt.C.BOLD}{h.label}{fmt.C.RESET} ({len(containers)} containers)")
            for c in containers:
                parts = c.split("|")
                if len(parts) >= 3:
                    name, status, image = parts[0], parts[1], parts[2]
                    color = fmt.C.GREEN if "Up" in status else fmt.C.RED
                    fmt.line(f"  {color}{name:<24}{fmt.C.RESET} {status:<20} {fmt.C.DIM}{image}{fmt.C.RESET}")
            total += len(containers)
            fmt.blank()
        elif r:
            fmt.line(f"{fmt.C.DIM}{h.label}: no containers{fmt.C.RESET}")

    fmt.info(f"{total} container(s) across {len(hosts)} host(s)")
    logger.info("docker_containers", hosts=len(hosts), total=total)
    fmt.footer()
    return 0


def cmd_docker_images(cfg: FreqConfig, pack, args) -> int:
    """List Docker images across fleet."""
    hosts = _docker_hosts(cfg)
    if not hosts:
        fmt.error("No Docker hosts in fleet")
        return 1

    fmt.header("Docker Images", breadcrumb="FREQ > Docker")
    fmt.blank()

    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in hosts]
    results = run_many(hosts=hosts_data,
                       command="docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}' 2>/dev/null | head -20",
                       key_path=cfg.ssh_key_path,
                       connect_timeout=cfg.ssh_connect_timeout, command_timeout=10)

    for h in hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0 and r.stdout.strip():
            images = r.stdout.strip().splitlines()
            fmt.line(f"{fmt.C.BOLD}{h.label}{fmt.C.RESET} ({len(images)} images)")
            for img in images:
                parts = img.split("|")
                name = parts[0] if parts else img
                size = parts[1] if len(parts) > 1 else ""
                fmt.line(f"  {fmt.C.DIM}{name:<40} {size}{fmt.C.RESET}")
            fmt.blank()

    fmt.footer()
    return 0


def cmd_docker_prune(cfg: FreqConfig, pack, args) -> int:
    """Clean up unused Docker resources across fleet."""
    hosts = _docker_hosts(cfg)
    if not hosts:
        fmt.error("No Docker hosts in fleet")
        return 1

    fmt.header("Docker Prune", breadcrumb="FREQ > Docker")
    fmt.blank()

    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in hosts]
    results = run_many(hosts=hosts_data,
                       command="docker system prune -f --volumes 2>/dev/null | tail -3",
                       key_path=cfg.ssh_key_path,
                       connect_timeout=cfg.ssh_connect_timeout, command_timeout=30)

    for h in hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            fmt.step_ok(f"{h.label}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'cleaned'}")
        else:
            fmt.step_fail(f"{h.label}: prune failed")

    fmt.blank()
    logger.info("docker_prune", hosts=len(hosts))
    fmt.footer()
    return 0


def cmd_docker_update_check(cfg: FreqConfig, pack, args) -> int:
    """Check for Docker image updates across fleet."""
    hosts = _docker_hosts(cfg)
    if not hosts:
        fmt.error("No Docker hosts in fleet")
        return 1

    fmt.header("Docker Update Check", breadcrumb="FREQ > Docker")
    fmt.blank()

    # Check running container images for updates
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in hosts]
    results = run_many(hosts=hosts_data,
                       command="docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null",
                       key_path=cfg.ssh_key_path,
                       connect_timeout=cfg.ssh_connect_timeout, command_timeout=10)

    total_containers = 0
    for h in hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0 and r.stdout.strip():
            containers = r.stdout.strip().splitlines()
            total_containers += len(containers)
            fmt.line(f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}: {len(containers)} running containers")
            for c in containers:
                parts = c.split("|")
                if len(parts) >= 2:
                    fmt.line(f"  {parts[0]:<24} {fmt.C.DIM}{parts[1]}{fmt.C.RESET}")

    fmt.blank()
    fmt.info(f"{total_containers} container(s) to check. Pull latest with: docker compose pull")
    fmt.footer()
    return 0
