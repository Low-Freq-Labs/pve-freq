"""RPCBind Block Policy.

Block rpcbind (port 111) on all non-NFS-server hosts. rpcbind is a
common attack surface that's often enabled by default but rarely needed
on hosts that only mount NFS shares (they don't need rpcbind).
"""

POLICY = {
    "name": "rpcbind-block",
    "description": "Block rpcbind (port 111) on all non-NFS hosts",
    "scope": ["linux", "pve"],
    "resources": [
        {
            "type": "command_check",
            "path": "",
            "applies_to": ["linux", "pve"],
            "entries": {},
            "check_cmd": "ss -tlnp | grep ':111 ' || echo CLEAN",
            "desired_output": "CLEAN",
            "fix_cmd": ("iptables -A INPUT -p tcp --dport 111 -j DROP && "
                        "iptables -A INPUT -p udp --dport 111 -j DROP && "
                        "netfilter-persistent save"),
            "after_change": {},
        },
    ],
}
