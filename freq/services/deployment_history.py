"""Deployment-history process and parsing below dashboard HTTP transport."""

import subprocess


def read_deploy_log(install_dir):
    """Return recent repository commits from one installed checkout."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-20", "--format=%H|%s|%ar"],
            cwd=install_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commits = []
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.split("|", 2)
                if len(parts) >= 3:
                    commits.append(
                        {
                            "hash": parts[0][:8],
                            "message": parts[1],
                            "ago": parts[2],
                        }
                    )
        return {"commits": commits, "count": len(commits)}
    except Exception as error:
        return {"commits": [], "count": 0, "error": str(error)}
