"""Shared helpers: run hidden tests against a workspace."""
import os, subprocess


def run_tests(workspace, test_file, timeout=30):
    """Run the hidden test file with cwd=workspace; only PATH is kept from the env."""
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "EVAL_WORKSPACE": os.path.abspath(workspace)}
    p = subprocess.run(["python3", test_file], cwd=workspace, env=env,
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode == 0, (p.stdout + p.stderr).strip()
