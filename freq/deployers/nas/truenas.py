"""TrueNAS deployer.

TrueNAS SCALE uses midclt (middleware client) for user management.
TrueNAS CORE (FreeBSD) uses pw. Standard useradd does NOT persist
across reboots or updates on either platform.

This deployer detects which platform and uses the right tool.
"""

import base64
import os

from freq.core import fmt

CATEGORY = "nas"
VENDOR = "truenas"
NEEDS_PASSWORD = False
NEEDS_RSA = False


def deploy(ip, ctx, auth_pass, auth_key, auth_user, htype="truenas"):
    """Deploy FREQ service account to TrueNAS."""
    from freq.modules.init_cmd import _init_ssh, _run, MARKER_DEPLOY_OK

    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    pubkey = ctx["pubkey"]

    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    rc, out, err = _ssh("echo OK")
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({err[:60]})")
        return False
    fmt.step_ok("Connected")

    pass_b64 = base64.b64encode(svc_pass.encode()).decode()
    pubkey_b64 = base64.b64encode((pubkey or "").encode()).decode()

    deploy_script = f"""set -e
if command -v midclt >/dev/null 2>&1; then
    VARIANT="scale"
elif command -v pw >/dev/null 2>&1; then
    VARIANT="core"
else
    VARIANT="linux"
fi

if [ "$VARIANT" = "scale" ]; then
    POOL_PATH=$(midclt call pool.query | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[0].get("path","") if data else "")')
    if [ -n "$POOL_PATH" ]; then
        HOME_PARENT="$POOL_PATH/.freq-home"
        mkdir -p "$HOME_PARENT"
    else
        HOME_PARENT="/var/empty"
    fi
    export FREQ_USER='{svc_name}'
    export FREQ_PASS_B64='{pass_b64}'
    export FREQ_PUBKEY_B64='{pubkey_b64}'
    export FREQ_HOME_PARENT="$HOME_PARENT"
    python3 - <<'PY'
import base64
import json
import os
import subprocess
import sys

svc_name = os.environ["FREQ_USER"]
svc_pass = base64.b64decode(os.environ["FREQ_PASS_B64"]).decode()
pubkey = base64.b64decode(os.environ["FREQ_PUBKEY_B64"]).decode().strip()
home_parent = os.environ["FREQ_HOME_PARENT"] or "/var/empty"

query = subprocess.run(
    ["midclt", "call", "user.query", json.dumps([["username", "=", svc_name]])],
    capture_output=True,
    text=True,
    timeout=30,
)
if query.returncode != 0:
    print("USERADD_FAIL: " + (query.stderr or query.stdout)[:120], file=sys.stderr)
    sys.exit(1)

users = json.loads(query.stdout or "[]")
payload = {
    "full_name": "FREQ Service Account",
    "shell": "/usr/bin/bash",
    "password": svc_pass,
    "smb": False,
    "ssh_password_enabled": False,
    "password_disabled": False,
    "sshpubkey": pubkey or None,
    "sudo_commands_nopasswd": ["ALL"],
}

if users:
    uid = str(users[0]["id"])
    result = subprocess.run(
        ["midclt", "call", "user.update", uid, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=30,
    )
else:
    payload.update({
        "username": svc_name,
        "group_create": True,
        "home": home_parent,
        "home_create": home_parent != "/var/empty",
    })
    result = subprocess.run(
        ["midclt", "call", "user.create", json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=30,
    )

if result.returncode != 0:
    print("USERADD_FAIL: " + (result.stderr or result.stdout)[:160], file=sys.stderr)
    sys.exit(1)

print("ACCOUNT_OK")
PY
    test "$(midclt call user.query "[[\\"username\\",\\"=\\",\\"{svc_name}\\"]]" | python3 -c 'import json,sys; data=json.load(sys.stdin); print("1" if data else "")')" = "1" || {{ echo ACCOUNT_MISSING; exit 1; }}
elif [ "$VARIANT" = "core" ]; then
    if ! id '{svc_name}' >/dev/null 2>&1; then
        pw useradd '{svc_name}' -m -s /bin/sh -c "FREQ Service Account" || {{ echo USERADD_FAIL; exit 1; }}
    fi
    _pass=$(echo '{pass_b64}' | base64 -d)
    echo "$_pass" | pw usermod '{svc_name}' -h 0 || echo CHPASSWD_FAIL
    unset _pass
else
    if ! id '{svc_name}' >/dev/null 2>&1; then
        useradd -m -s /bin/bash '{svc_name}' || {{ echo USERADD_FAIL; exit 1; }}
    fi
    _pass=$(echo '{pass_b64}' | base64 -d)
    printf '%s:%s\\n' '{svc_name}' "$_pass" | chpasswd 2>/dev/null || echo CHPASSWD_FAIL
    unset _pass
fi

if [ "$VARIANT" != "scale" ]; then
    id '{svc_name}' >/dev/null 2>&1 || {{ echo ACCOUNT_MISSING; exit 1; }}
fi

if [ "$VARIANT" != "scale" ]; then
    svc_home=""
    if command -v getent >/dev/null 2>&1; then
        svc_home=$(getent passwd '{svc_name}' | cut -d: -f6 2>/dev/null)
    fi
    if [ -z "$svc_home" ] && command -v pw >/dev/null 2>&1; then
        svc_home=$(pw usershow '{svc_name}' | cut -d: -f9 2>/dev/null)
    fi
    if [ -z "$svc_home" ]; then
        svc_home="/home/{svc_name}"
    fi
    mkdir -p "$svc_home/.ssh"
    chmod 700 "$svc_home/.ssh"
    if [ -n '{pubkey}' ]; then
        grep -qF '{pubkey}' "$svc_home/.ssh/authorized_keys" 2>/dev/null || echo '{pubkey}' >> "$svc_home/.ssh/authorized_keys"
        chmod 600 "$svc_home/.ssh/authorized_keys"
        chown -R '{svc_name}' "$svc_home/.ssh"
    fi
fi

if [ "$VARIANT" = "core" ] && [ -d /usr/local/etc/sudoers.d ]; then
    echo '{svc_name} ALL=(ALL) NOPASSWD: ALL' > '/usr/local/etc/sudoers.d/freq-{svc_name}'
    chmod 440 '/usr/local/etc/sudoers.d/freq-{svc_name}'
elif [ "$VARIANT" != "scale" ] && [ -d /etc/sudoers.d ]; then
    echo '{svc_name} ALL=(ALL) NOPASSWD: ALL' > '/etc/sudoers.d/freq-{svc_name}'
    chmod 440 '/etc/sudoers.d/freq-{svc_name}'
    visudo -cf '/etc/sudoers.d/freq-{svc_name}' 2>/dev/null || true
fi

echo DEPLOY_OK
"""
    rc, out, err = _ssh(deploy_script, as_root=True)
    if "USERADD_FAIL" in out or "ACCOUNT_MISSING" in out:
        fmt.step_fail(f"Failed to create account '{svc_name}'")
        return False
    elif MARKER_DEPLOY_OK not in out:
        fmt.step_fail(f"Deploy script failed ({(err or out)[:80]})")
        return False

    if "CHPASSWD_FAIL" in out:
        fmt.step_warn("Password set failed — SSH key auth only")
    else:
        fmt.step_ok("Account + SSH key deployed")

    success = True
    if ctx.get("key_path") and os.path.isfile(ctx["key_path"]):
        rc2, _, _ = _run(
            [
                "ssh",
                "-n",
                "-i",
                ctx["key_path"],
                "-o",
                "ConnectTimeout=3",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{svc_name}@{ip}",
                "echo OK",
            ]
        )
        if rc2 == 0:
            fmt.step_ok(f"Verified: FREQ key SSH as {svc_name}")
        else:
            fmt.step_fail(f"FREQ key login FAILED as {svc_name}")
            success = False

        if rc2 == 0:
            rc3, _, _ = _run(
                [
                    "ssh",
                    "-n",
                    "-i",
                    ctx["key_path"],
                    "-o",
                    "ConnectTimeout=3",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    f"{svc_name}@{ip}",
                    "sudo -n true",
                ]
            )
            if rc3 == 0:
                fmt.step_ok(f"Verified: NOPASSWD sudo as {svc_name}")
            else:
                fmt.step_warn("sudo not available — TrueNAS may restrict sudo")

    return success


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from TrueNAS.

    Detects SCALE (midclt) vs CORE (pw) vs Linux fallback, matching deploy().
    """
    from freq.core.ssh import run as ssh_run

    remove_script = f"""
# Detect TrueNAS variant
if command -v midclt >/dev/null 2>&1; then
    # TrueNAS SCALE — use midclt
    uid=$(midclt call user.query '[["username","=","{svc_name}"]]' 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['id'])" 2>/dev/null)
    if [ -n "$uid" ]; then
        midclt call user.delete "$uid" '{{"delete_group": true}}' >/dev/null 2>&1 && echo REMOVE_OK || echo REMOVE_FAIL
    else
        echo REMOVE_OK
    fi
elif command -v pw >/dev/null 2>&1; then
    # TrueNAS CORE (FreeBSD)
    pw userdel '{svc_name}' -r 2>/dev/null; echo REMOVE_OK
else
    # Linux fallback
    userdel -r '{svc_name}' 2>/dev/null; echo REMOVE_OK
fi
# Clean up sudoers
rm -f /etc/sudoers.d/freq-{svc_name} /usr/local/etc/sudoers.d/freq-{svc_name} 2>/dev/null
"""
    r = ssh_run(
        host=ip,
        command=remove_script,
        key_path=key_path,
        connect_timeout=5,
        command_timeout=30,
        htype="truenas",
        use_sudo=True,
    )
    if r.returncode == 0 and "REMOVE_OK" in (r.stdout or ""):
        return True, "Account removed"
    return False, (r.stderr or r.stdout or "Remove failed")[:100]
