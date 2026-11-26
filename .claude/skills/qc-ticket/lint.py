"""
Check QC ticket drafts against the rules in SKILL.md that can be checked mechanically.

    python3 lint.py <drafts folder>

Errors must be fixed. Warnings are judgement calls: fix them unless the ticket needs it (length is a soft aim).
Exits 1 when there are errors.
"""
import re
import sys
from pathlib import Path

ROUTE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) /")
CODE = re.compile(r"\b[1-5]\d\d\b")
REFUSAL = re.compile(r"\b(refused|is refused|are refused|not allowed|cannot|can't)\b", re.I)
BAD_PLACEHOLDER = re.compile(r"<[^>]*(version|host|namespace|owner)[^>]*>", re.I)
SENSITIVE = [
    (re.compile(r"\b(?!169\.254\.169\.254\b)(?:\d{1,3}\.){3}\d{1,3}(?:/\d+)?\b"), "an IP address"),
    (re.compile(r"--context\b|use-context\b|--kube-context\b"), "a kube context"),
    (re.compile(r"\b[\w.-]+\.(?:postgres\.database\.azure\.com|azmk8s\.io|blob\.core\.windows\.net|file\.core\.windows\.net|vault\.azure\.net)\b"), "a cloud resource name"),
    (re.compile(r"\b[\w.+-]+@(?!example\.(?:com|org)\b)[\w-]+\.[\w.-]+\b"), "an email address (made-up ones must be @example.com or @example.org)"),
    (re.compile(r"\b(?:ghp|gho|github_pat|glpat|xox[bp])_[A-Za-z0-9_]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY|\bAGE-SECRET-KEY-|\bage1[0-9a-z]{50,}"), "a token or key"),
]



PUBLIC_HOSTS = ("github.com", "aridhia-open-source.github.io", "ghcr.io", "example.com", "example.org", "docs.github.com", "getsops.io", "fluxcd.io")


def sensitive(text: str) -> list[str]:
    found = [f"contains {why}: tickets are public" for pattern, why in SENSITIVE if pattern.search(text)]
    for host in sorted(set(re.findall(r"https?://([\w.-]+)", text))):
        if host == "169.254.169.254" or re.search(r"\.svc(\.cluster\.local)?$", host):
            continue  # the same on every install: in-cluster service names and the cloud metadata address
        if not any(host == h or host.endswith("." + h) for h in PUBLIC_HOSTS):
            found.append(f"contains the address {host}: tickets are public, write \"QC's address\" or another public link")
    return found


FORBIDDEN = {
    "**Version": "no version line",
    "Assumes": "no \"Assumes\" lines",
    "### More": "no \"More\" section",
    "Already covered": "no \"Already covered\" lines",
    "QA plan": "never mention the QA plans",
    "—": "no em dashes",
}


def words(text: str) -> int:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return len(re.sub(r"`[^`]*`", "x", text).split())


def section(text: str, name: str) -> str:
    match = re.search(rf"^### {name}\n(.*?)(?=^### |\Z)", text, re.S | re.M)
    return match[1] if match else ""


def checks_of(text: str) -> list[str]:
    """Each check with any indented lines under it (command blocks), as one string."""
    found, current = [], None
    for line in section(text, "Checks").splitlines():
        if line.startswith("- [ ]"):
            current = [line]
            found.append(current)
        elif current is not None and (line.startswith("  ") or not line.strip()):
            current.append(line)
    return ["\n".join(c) for c in found]


def lint_ticket(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    errors, warnings = sensitive(text), []
    for token, why in FORBIDDEN.items():
        if token in text:
            errors.append(why)
    if re.search(r"^\*\*(PRs|Issues):\*\*.*`#\d+", text, re.M):
        errors.append("PR and issue numbers must be plain #123, not in backticks, so GitHub links them")
    if re.search(r"<[^>]*(made-up|address|e-?mail)[^>]*>", text, re.I):
        errors.append("placeholder for an email address: write a made-up one at example.org, like qc-admin@example.org")
    for bare in sorted(set(re.findall(r"\b[Aa]s ([A-Z])\b(?! \w+ role)", text))):
        errors.append(f"bare name \"{bare}\": write it with its role, like \"Admin {bare}\" or \"User {bare}\"")
    for placeholder in BAD_PLACEHOLDER.findall(text):
        errors.append(f"placeholder for a {placeholder}: use the value from \"What QC does now\" or a command that reads it")
    checks = checks_of(text)
    if not checks:
        errors.append("no checks")
    if len(checks) > 8:
        errors.append(f"{len(checks)} checks, at most 8: split the ticket")
    for n, check in enumerate(checks, 1):
        first = check.splitlines()[0]
        if REFUSAL.search(first) and not (ROUTE.search(check) and CODE.search(check)) and not re.search(r"\b(kubectl|flux|helm)\b", check):
            errors.append(f"check {n} is a refusal with no Postman request and status code")
        if words(first) > 40:
            warnings.append(f"check {n} is {words(first)} words, aim for under 40")
        if re.search(r"\bThen\b", first) or len(re.findall(r"\bAs (the |a |an )?\w+,", first)) > 2:
            warnings.append(f"check {n} may chain more than one action")
    changed = section(text, "What changed")
    if words(changed) > 60:
        warnings.append(f"\"What changed\" is {words(changed)} words, aim for under 60")
    total = words(text)
    if total > 350:
        warnings.append(f"{total} words, soft aim 350 (fine if the checks need it)")
    evidence = path.with_name(path.stem + ".evidence.md")
    if not evidence.exists():
        errors.append(f"no {evidence.name}: write the code evidence for each check")
    else:
        entries = [l for l in evidence.read_text(encoding="utf-8").splitlines() if re.match(r"^\d+\. ", l)]
        if len(entries) != len(checks):
            errors.append(f"{evidence.name} has {len(entries)} entries for {len(checks)} checks")
        for line in entries:
            if not re.search(r"\S+:\d+", line):
                errors.append(f"{evidence.name}: \"{line[:50]}\" gives no file:line")
    return errors, warnings


def lint_index(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    errors, warnings = sensitive(text), []
    if "QA plan" in text:
        errors.append("never mention the QA plans")
    if "—" in text:
        errors.append("no em dashes")
    found = re.search(r"^## Found while writing\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if found and len(re.findall(r"^- ", found[1], re.M)) > 5:
        errors.append("more than five bugs under \"Found while writing\"")
    return errors, warnings


def main(folder: str) -> int:
    failed = False
    for path in sorted(Path(folder).glob("*.md")):
        if path.name.endswith(".evidence.md"):
            continue
        errors, warnings = (lint_index if path.name.startswith("00-") else lint_ticket)(path)
        for e in errors:
            print(f"ERROR {path.name}: {e}")
        for w in warnings:
            print(f"warn  {path.name}: {w}")
        failed |= bool(errors)
    print("lint: errors found" if failed else "lint: clean")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
