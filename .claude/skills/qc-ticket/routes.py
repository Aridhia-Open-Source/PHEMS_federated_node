"""
Print the nexus-api routes the app registers at a git ref, with the access check each one makes, as a
markdown table. Reads the source with `git show`, so it works even when the app cannot start.

    python3 routes.py <ref>

Only modules named in `from app import (...)` in nexus/api/app/__init__.py are read, so old copies of a
router that are not registered never show up. Read only.
"""
import re
import subprocess
import sys

APP = "nexus/api/app"
METHODS = "get|post|put|patch|delete"


def show(ref: str, path: str) -> str | None:
    try:
        return subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def registered_modules(init: str) -> list[str]:
    match = re.search(r"from app import \(([^)]*)\)", init, re.S)
    names = re.findall(r"\b(\w+)\b", match[1]) if match else []
    return [name for name in names if name.endswith("_api") or name == "main"]


def access_of(block: str) -> str:
    found = []
    for model, action in re.findall(r"Access\(\s*model=(\w+)\s*,\s*action=Action\.(\w+)", block):
        found.append(f"{action.lower()} on {model}")
    if re.search(r"\bSYSTEM_ONLY\b|\bsystem_only\b", block):
        found.append("system user only")
    for dep in re.findall(r"Depends\((manage|read|write|operate|execute|assign)\)", block):
        found.append(f"{dep} on the record")
    if re.search(r"Action\.UNCHECKED", block) and not found:
        found.append("unchecked")
    return ", ".join(dict.fromkeys(found)) or "role only"


def routes(ref: str, module: str, open_routers: str) -> list[tuple[str, str, str]]:
    source = show(ref, f"{APP}/{module}.py")
    if source is None:
        return [("?", f"({module}.py is missing at this ref)", "")]
    prefixes = dict(re.findall(r"(\w+)\s*=\s*APIRouter\([^)]*prefix=['\"]([^'\"]*)['\"]", source))
    rows = []
    factory = re.findall(r"_\w+_router\(\s*['\"](/[^'\"]+)['\"]", source)
    for match in re.finditer(rf"@(\w+)\.({METHODS})\(\s*['\"]([^'\"]*)['\"]", source):
        router, method, path = match.groups()
        end = source.find("\ndef ", match.end())
        end = source.find(":\n", end) if end != -1 else match.end() + 400
        block = source[match.start():end]
        prefix = prefixes.get(router, "<factory prefix>" if router == "router" and "def _" in source[:match.start()] else "")
        is_open = f"{module}.{router}" in open_routers
        rows.append((method.upper(), f"{prefix}{path}" or "/", "open (no token)" if is_open else access_of(block)))
    if factory:
        rows.append(("", f"<factory prefix> is each of: {', '.join(factory)}", ""))
    return rows


def main(ref: str):
    init = show(ref, f"{APP}/__init__.py")
    if init is None:
        print(f"(no {APP}/__init__.py at {ref})")
        return
    open_match = re.search(r"OPEN_ROUTERS\s*=\s*\(([^)]*)\)", init, re.S)
    open_routers = open_match[1] if open_match else ""
    print("| Method | Path | Access check |")
    print("|---|---|---|")
    for module in registered_modules(init):
        for method, path, access in routes(ref, module, open_routers):
            print(f"| {method} | `{path}` | {access} |")
    print()
    print("Signed-in routers also need a node role. A refused access check is a 409 naming the owner.")
    print("\"role only\" means no per-record check on the route itself: list routes filter by the caller's access,")
    print("and some routes check more in their body (for example only the SuperUser may change an owner).")
    print("Read the route's code for any refusal a ticket relies on.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "HEAD")
