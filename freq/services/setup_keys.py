"""Setup SSH-key generation below dashboard HTTP transport."""

import os
import subprocess


def generate_setup_keys(key_dir):
    """Generate or project the installer keypairs for one key directory."""
    # Keygen may outlive its call. Fence this invoking process before even
    # directory creation; no source/state gate spans the native helper IO.
    from freq.core.read_source_epoch import retire_process_reads
    retire_process_reads()

    os.makedirs(key_dir, mode=0o700, exist_ok=True)

    hostname = os.uname().nodename
    ed_key = os.path.join(key_dir, "freq_id_ed25519")

    if os.path.isfile(ed_key):
        pub_path = f"{ed_key}.pub"
        pubkey = ""
        if os.path.isfile(pub_path):
            with open(pub_path) as f:
                pubkey = f.read().strip()
        return {
            "ok": True,
            "exists": True,
            "pubkey": pubkey,
            "key_path": ed_key,
        }, 200

    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-C", f"freq@{hostname}", "-f", ed_key, "-N", "", "-q"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return {"error": f"Key generation failed: {result.stderr[:100]}"}, 500

    os.chmod(ed_key, 0o600)
    os.chmod(f"{ed_key}.pub", 0o644)

    rsa_key = os.path.join(key_dir, "freq_id_rsa")
    if not os.path.isfile(rsa_key):
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "rsa",
                "-b",
                "4096",
                "-C",
                f"freq-legacy@{hostname}",
                "-f",
                rsa_key,
                "-N",
                "",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if os.path.isfile(rsa_key):
            os.chmod(rsa_key, 0o600)
            os.chmod(f"{rsa_key}.pub", 0o644)

    pubkey = ""
    pub_path = f"{ed_key}.pub"
    if os.path.isfile(pub_path):
        with open(pub_path) as f:
            pubkey = f.read().strip()

    return {
        "ok": True,
        "exists": False,
        "pubkey": pubkey,
        "key_path": ed_key,
    }, 200
