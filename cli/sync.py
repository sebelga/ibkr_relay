import shutil
import subprocess

from cli import (
    PROJECT_DIR,
    die,
    env,
    load_env,
    scp_file,
    ssh_cmd,
    ssh_key_path,
    validate_poller_env,
)

SERVICE_MAP = {
    "gateway": "ib-gateway",
    "ib-gateway": "ib-gateway",
    "novnc": "novnc",
    "vnc": "novnc",
    "caddy": "caddy",
    "relay": "webhook-relay",
    "webhook-relay": "webhook-relay",
    "poller": "poller",
    "poller2": "poller-2",
    "poller-2": "poller-2",
}


def _run_checks(skip_e2e):
    """Run pre-deploy checks: branch, clean tree, typecheck, tests, E2E."""
    # Must be on main branch
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True, cwd=PROJECT_DIR,
    ).stdout.strip()
    if branch != "main":
        die(f"Cannot sync: on branch '{branch}', switch to 'main' first")

    # Working tree must be clean
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True, cwd=PROJECT_DIR,
    ).stdout.strip()
    if dirty:
        die("Cannot sync: uncommitted changes — commit or stash first")

    print("Running type checks...")
    subprocess.run(["make", "typecheck"], check=True, cwd=PROJECT_DIR)

    print("Running unit tests...")
    subprocess.run(["make", "test"], check=True, cwd=PROJECT_DIR)

    if skip_e2e:
        print("Skipping E2E tests (--skip-e2e)")
    else:
        print("Running E2E tests...")
        subprocess.run(["make", "e2e"], check=True, cwd=PROJECT_DIR)


def _sync_local_files(droplet_ip):
    """Rsync project files to the droplet."""
    if not shutil.which("rsync"):
        die("rsync is required for --local-files "
            "(install via: brew install rsync / apt install rsync)")

    print("Syncing files to droplet...")
    cmd = [
        "rsync", "-az", "--delete",
        "-e", f"ssh -i {ssh_key_path()}",
        "--filter", ":- .gitignore",
        "--exclude", ".git/",
        "--exclude", ".env",
        "--exclude", ".env.test",
        "--exclude", ".deployed-sha",
        f"{PROJECT_DIR}/",
        f"root@{droplet_ip}:/opt/ibkr-relay/",
    ]
    subprocess.run(cmd, check=True)

    # Write deployed commit SHA for traceability
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, cwd=PROJECT_DIR,
    ).stdout.strip()
    ssh_cmd(droplet_ip, f"echo '{sha}' > /opt/ibkr-relay/.deployed-sha")
    print(f"Deployed commit: {sha[:12]}")


def run(args):
    load_env()

    droplet_ip = env("DROPLET_IP")
    profiles = ""
    if validate_poller_env("_2"):
        profiles = "poller2"

    if args.local_files:
        _run_checks(args.skip_e2e)
        _sync_local_files(droplet_ip)

    build = "--build " if (args.build or args.local_files) else ""

    print("Pushing .env to droplet...")
    scp_file(PROJECT_DIR / ".env", "/opt/ibkr-relay/.env", droplet_ip)

    if not args.services:
        print(f"{'Rebuilding + restarting' if build else 'Restarting'} all services...")
        ssh_cmd(droplet_ip,
                f"cd /opt/ibkr-relay && COMPOSE_PROFILES='{profiles}' "
                f"docker compose up -d {build}--force-recreate")
    else:
        services = []
        for name in args.services:
            svc = SERVICE_MAP.get(name)
            if not svc:
                valid = ", ".join(sorted(set(SERVICE_MAP.keys())))
                die(f"Unknown service: {name}\nValid names: {valid}")
            services.append(svc)

        svc_str = " ".join(services)
        print(f"{'Rebuilding + restarting' if build else 'Restarting'}: {svc_str}...")
        ssh_cmd(droplet_ip,
                f"cd /opt/ibkr-relay && COMPOSE_PROFILES='{profiles}' "
                f"docker compose up -d {build}--force-recreate {svc_str}")

    print("Done.")
