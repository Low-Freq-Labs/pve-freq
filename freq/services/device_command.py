"""Device-command output policy below dashboard HTTP transport."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PfSenseExecutionRuntime:
    """Live dependencies for one pfSense command execution."""

    resolve_auth: Callable[[Any, str], Mapping[str, Any]]
    ssh_single: Callable[..., Any]
    redact_output: Callable[[str], str]


@dataclass(frozen=True)
class PfSenseExecutionResult:
    """Secret-safe pfSense command result below HTTP transport."""

    action: str
    target: str
    label: str
    host: str
    ip: str
    auth_failed: bool
    returncode: int
    stdout: str
    stderr: str


def redact_device_command_output(output: str) -> str:
    """Strip secrets from raw device CLI output before transport consumes it."""
    text = str(output or "")
    return re.sub(
        r"(?im)^(\s*(?:private key|preshared key)\s*:\s*).*$",
        r"\1[redacted]",
        text,
    )


def resolve_pfsense_execution(
    cfg: Any,
    action: str,
    target: Any,
    *,
    runtime: PfSenseExecutionRuntime,
) -> PfSenseExecutionResult:
    """Execute one read-only pfSense action and return secret-safe truth."""
    pf_ip = target.ip
    pf_label = getattr(target, "label", "") or getattr(target, "key", "") or "firewall"

    actions = {
        "status": (
            'echo "=== SYSTEM === ";uname -sr; uptime;'
            'echo "=== PF STATUS === ";pfctl -s info 2>/dev/null | head -12;'
            'echo "=== GATEWAY === ";netstat -rn | grep default | head -5'
        ),
        "rules": (
            'echo "=== FILTER RULES === ";'
            "pfctl -sr 2>/dev/null | grep -v '^scrub' | grep -v '^anchor' | "
            'sed \'s/ label "[^"]*"//g; s/ ridentifier [0-9]*//g\' | '
            "grep -v 'icmp6-type' | "
            "awk '{"
            '  action=$1; dir=$2; quick="";'
            '  if($3=="quick"){quick=" quick"; iface=$5; rest="";'
            '    for(i=6;i<=NF;i++) rest=rest" "$i}'
            '  else{iface=$4; rest="";'
            '    for(i=5;i<=NF;i++) rest=rest" "$i}'
            '  gsub(/^ /,"",rest);'
            '  if(action=="block") color="BLOCK";'
            '  else if(action=="pass") color="PASS";'
            "  else color=action;"
            '  printf "%-6s %-4s %-8s  %-18s  %s\\n", toupper(color), dir, quick, iface, rest'
            "}' | head -40;"
            'echo "";'
            'echo "=== SUMMARY === ";'
            "total=$(pfctl -sr 2>/dev/null | wc -l | tr -d ' ');"
            "blocks=$(pfctl -sr 2>/dev/null | grep -c '^block');"
            "passes=$(pfctl -sr 2>/dev/null | grep -c '^pass');"
            "scrubs=$(pfctl -sr 2>/dev/null | grep -c '^scrub');"
            'printf \'Total: %s  |  Pass: %s  |  Block: %s  |  Scrub: %s\\n\' "$total" "$passes" "$blocks" "$scrubs"'
        ),
        "nat": (
            'echo "=== NAT RULES === ";'
            "pfctl -sn 2>/dev/null | grep -v '^no ' | grep -v '^rdr-anchor' | grep -v '^nat-anchor' | "
            "awk '{"
            "  type=$1;"
            '  if(type=="nat"){'
            '    iface=$3; proto=""; src=""; dst=""; arrow=""; target="";'
            "    for(i=4;i<=NF;i++){"
            '      if($i=="inet"||$i=="inet6") proto=$i;'
            '      else if($i=="from"){src=$(i+1); i++}'
            '      else if($i=="to"){dst=$(i+1); i++}'
            '      else if($i=="->"){target=$(i+1); i++}'
            "    }"
            '    if(src=="any") src="*";'
            '    if(dst=="any") dst="*";'
            '    printf "NAT  %-14s  %-6s  %-22s -> %-22s  => %s\\n", iface, proto, src, dst, target'
            "  }"
            '  else if(type=="rdr"){'
            '    iface=$3; proto=""; src=""; port=""; target=""; tport="";'
            "    for(i=4;i<=NF;i++){"
            '      if($i=="proto"){proto=$(i+1); i++}'
            '      else if($i=="to" && target==""){dst=$(i+1); i++; if($(i+1)=="port"){port=$(i+2); i+=2}}'
            '      else if($i=="->"){target=$(i+1); i++; if($(i+1)=="port"){tport=$(i+2); i+=2}}'
            "    }"
            '    printf "RDR  %-14s  %-6s  %-22s => %s:%s\\n", iface, proto, dst":"port, target, tport'
            "  }"
            "}';"
            'echo "";'
            'echo "=== PORT FORWARDS === ";'
            "pfctl -sn 2>/dev/null | grep '^rdr' | grep -v 'anchor' | "
            "sed 's/ ridentifier [0-9]*//g' | head -10;"
            'echo "";'
            'echo "=== SUMMARY === ";'
            "nat_count=$(pfctl -sn 2>/dev/null | grep -c '^nat');"
            "rdr_count=$(pfctl -sn 2>/dev/null | grep -c '^rdr[^-]');"
            'printf \'NAT rules: %s  |  Port forwards: %s\\n\' "$nat_count" "$rdr_count"'
        ),
        "states": (
            "echo \"Active states: $(pfctl -ss 2>/dev/null | wc -l | tr -d ' ')\";"
            'echo "";echo "=== TOP STATES (by source) === ";'
            "pfctl -ss 2>/dev/null | awk '{print $3}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15"
        ),
        "interfaces": (
            'echo "=== INTERFACES === ";'
            "printf '%-18s  %s\\n' 'INTERFACE' 'IP ADDRESS';"
            "printf '%-18s  %s\\n' '──────────────────' '────────────────────────';"
            "for iface in $(ifconfig -l); do "
            '  ips=$(ifconfig "$iface" 2>/dev/null | awk \'/ inet /{print $2}\' | tr \'\\n\' \',\' | sed \'s/,$//\'); '
            '  [ -n "$ips" ] || ips="no IP assigned"; '
            '  printf "%-18s  %s\\n" "$iface" "$ips"; '
            "done"
        ),
        "gateways": (
            'echo "=== ROUTING TABLE === ";netstat -rn | head -25;'
            'echo "";echo "=== DEFAULT GATEWAYS === ";netstat -rn | grep default'
        ),
        "vpn": (
            'echo "=== WIREGUARD TUNNELS === ";wg show 2>/dev/null || echo No_WireGuard_tunnels;'
            'echo "";echo "=== IPSEC === ";ipsec statusall 2>/dev/null | head -10 || echo No_IPsec'
        ),
        "arp": (
            'echo "=== ARP TABLE === ";'
            'echo "";'
            "printf '%-18s  %-20s  %-16s  %-8s\\n' 'IP ADDRESS' 'MAC ADDRESS' 'INTERFACE' 'TYPE';"
            "printf '%-18s  %-20s  %-16s  %-8s\\n' '──────────────────' '────────────────────' '────────────────' '────────';"
            "arp -an | sed 's/? (//;s/) at / /;s/ on / /;s/ permanent/PERM/;s/ expires in [0-9]* seconds//' | "
            "sed 's/\\[ethernet\\]//;s/\\[vlan\\]//' | "
            'awk \'{printf "%-18s  %-20s  %-16s  %-8s\\n", $1, $2, $3, ($4=="PERM"?"PERM":"DYN")}\' | '
            "sort -t. -k1,1n -k2,2n -k3,3n -k4,4n;"
            'echo "";'
            'echo "=== SUMMARY === ";'
            "total=$(arp -an | wc -l | tr -d ' ');"
            "perm=$(arp -an | grep -c 'permanent');"
            "dyn=$((total - perm));"
            'printf \'Total: %s  |  Permanent: %s  |  Dynamic: %s\\n\' "$total" "$perm" "$dyn";'
            'echo "";'
            'echo "=== BY INTERFACE === ";'
            "arp -an | awk '{for(i=1;i<=NF;i++) if($i==\"on\") print $(i+1)}' | sort | uniq -c | sort -rn | "
            "awk '{printf \"  %-16s  %s entries\\n\", $2, $1}'"
        ),
        "services": (
            'echo "=== RUNNING SERVICES === ";'
            "for svc in sshd unbound dhcpd ntpd dpinger filterdns syslogd; do "
            "  pid=$(pgrep -x $svc 2>/dev/null); "
            '  [ -n "$pid" ] && printf \'  %-12s RUNNING (PID %s)\\n\' "$svc" "$pid" || printf \'  %-12s STOPPED\\n\' "$svc"; '
            "done"
        ),
        "log": (
            'echo "=== RECENT FIREWALL LOG (last 30) === ";'
            "tail -30 /var/log/filter.log 2>/dev/null || echo Log_unavailable"
        ),
        "dhcp": (
            'echo "=== DHCP LEASES === ";'
            "cat /var/dhcpd/var/db/dhcpd.leases 2>/dev/null | grep -E 'lease|starts|ends|hardware|client-hostname' | head -60 || echo No_DHCP_leases"
        ),
        "gateway_monitor": (
            'echo "=== GATEWAY STATUS === ";'
            "pfctl -s info 2>/dev/null | grep -i status | head -2; "
            'echo "";echo "=== DPINGER (latency/loss) === ";'
            "cat /tmp/dpinger_*.sock 2>/dev/null || echo dpinger_unavailable; "
            'echo "";echo "=== WAN INTERFACES === ";'
            "netstat -rn | grep default; "
            'echo "";echo "=== PING TEST === ";'
            "ping -c 3 -t 3 1.1.1.1 2>/dev/null | tail -3 || echo Ping_failed"
        ),
        "dns": (
            'echo "=== UNBOUND STATUS === ";'
            "unbound-control status 2>/dev/null | head -10 || echo Unbound_not_running; "
            'echo "";echo "=== CACHE STATS === ";'
            "unbound-control stats_noreset 2>/dev/null | grep -E 'total.num|cache.count|num.query' | head -15 || echo Stats_unavailable; "
            'echo "";echo "=== DNS TEST === ";'
            "drill google.com @127.0.0.1 2>/dev/null | grep -E 'rcode|ANSWER|Query time' | head -5 || "
            "host google.com 127.0.0.1 2>/dev/null | head -3 || echo DNS_test_failed"
        ),
        "traffic": (
            'echo "=== INTERFACE TRAFFIC === ";'
            "netstat -ibnd | head -1; netstat -ibnd | grep -v lo0 | grep Link | head -20; "
            'echo "";echo "=== TOP CONNECTIONS BY STATE === ";'
            "pfctl -ss 2>/dev/null | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15; "
            'echo "";echo "=== BANDWIDTH (bytes in/out per interface) === ";'
            "netstat -I lagg0 -bnd 2>/dev/null | tail -1; "
            "netstat -I lagg1 -bnd 2>/dev/null | tail -1"
        ),
        "syslog": (
            'echo "=== SYSTEM LOG (last 40) === ";'
            "tail -40 /var/log/system.log 2>/dev/null || tail -40 /var/log/messages 2>/dev/null || echo Log_unavailable"
        ),
        "aliases": (
            'echo "=== PF TABLES (aliases) === ";'
            "pfctl -s Tables 2>/dev/null; "
            'echo "";echo "=== TABLE CONTENTS === ";'
            "for tbl in $(pfctl -s Tables 2>/dev/null); do "
            "  cnt=$(pfctl -t $tbl -T show 2>/dev/null | wc -l | tr -d ' '); "
            '  echo "$tbl ($cnt entries)"; '
            "  pfctl -t $tbl -T show 2>/dev/null | head -10; "
            '  echo "";'
            "done"
        ),
        "backup": (
            'echo "=== CONFIG BACKUP === ";'
            "ls -la /cf/conf/backup/ 2>/dev/null | tail -10 || echo No_backups_found; "
            'echo "";echo "=== CURRENT CONFIG === ";'
            "ls -la /cf/conf/config.xml 2>/dev/null; "
            'echo "";echo "=== LAST MODIFIED === ";'
            "stat -f '%Sm' /cf/conf/config.xml 2>/dev/null || stat -c '%y' /cf/conf/config.xml 2>/dev/null || echo Unknown"
        ),
    }

    command = actions.get(action, actions["status"])
    auth = runtime.resolve_auth(cfg, "pfsense")
    completed = runtime.ssh_single(
        host=pf_ip,
        command=command,
        key_path=auth["key_path"],
        user=auth["user"],
        local_user=auth.get("local_user"),
        password_file=auth.get("password_file") or None,
        sudo_password_file=auth.get("sudo_password_file", False),
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
        htype="pfsense",
        use_sudo=False,
        cfg=cfg,
        failure_log_level="warn",
    )

    auth_failed = "permission denied" in (completed.stderr or "").lower() or "publickey" in (
        completed.stderr or ""
    ).lower()
    reachable = completed.returncode == 0
    return PfSenseExecutionResult(
        action=action,
        target=pf_label,
        label=pf_label,
        host=pf_ip,
        ip=pf_ip,
        auth_failed=auth_failed,
        returncode=completed.returncode,
        stdout=runtime.redact_output(completed.stdout) if reachable else "",
        stderr=completed.stderr[:100] if not reachable else "",
    )
