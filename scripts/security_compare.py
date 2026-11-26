#!/usr/bin/env python3
"""Compare the security scanners' SARIF output by area (ADR 0044).

Reads megalinter-reports/sarif/*.sarif and megalinter-reports/mega-linter-report.json (and any
extra SARIF files given as arguments) and writes a Markdown summary: findings seen by more than
one tool, findings seen by only one, counts by severity, and run time per tool.
Usage: security_compare.py [REPORT_DIR] [EXTRA.sarif ...] > summary.md
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

AREAS = {
    "dependencies": {"trivy", "grype", "osv-scanner"},
    "config": {"checkov", "kics", "trivy"},
    "secrets": {"betterleaks", "gitleaks", "trufflehog", "trivy"},
    "code": {"bandit", "semgrep"},
    "workflows": {"zizmor", "actionlint"},
}
VULN_ID = re.compile(r"(CVE-\d{4}-\d+|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})", re.I)


def tool_name(run):
    return run["tool"]["driver"]["name"].split(" (")[0].split()[0].lower()  # "Semgrep OSS" -> semgrep


def area_of(tool, rule_id):
    rid = rule_id.lower()
    if tool in ("trivy", "checkov", "kics"):
        if VULN_ID.search(rule_id) or rid.startswith("pkg"):
            return "dependencies" if tool == "trivy" else "config"
        if "secret" in rid:
            return "secrets"
        return "config"
    return next((a for a, tools in AREAS.items() if tool in tools and (a != "config" or tool != "trivy")), "other")


def location(result):
    loc = (result.get("locations") or [{}])[0].get("physicalLocation", {})
    uri = loc.get("artifactLocation", {}).get("uri", "").removeprefix("file:///github/workspace/").lstrip("./")
    return uri, loc.get("region", {}).get("startLine", 0)


def findings(paths):
    found = defaultdict(lambda: defaultdict(set))  # area -> key -> tools
    severity = defaultdict(lambda: defaultdict(int))  # tool -> level -> count
    for path in paths:
        for run in json.loads(Path(path).read_text())["runs"]:
            tool = tool_name(run)
            for result in run.get("results", []):
                if result.get("suppressions"):
                    continue
                rule = result.get("ruleId", "")
                area = area_of(tool, rule)
                uri, line = location(result)
                vuln = VULN_ID.search(rule) or VULN_ID.search(result.get("message", {}).get("text", ""))
                key = (uri, vuln.group(1).upper()) if area == "dependencies" and vuln else (uri, line // 5)
                found[area][key].add(tool)
                severity[tool][result.get("level", "warning")] += 1
    return found, severity


def main():
    report_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "megalinter-reports")
    paths = sorted(report_dir.glob("sarif/*.sarif")) + [Path(p) for p in sys.argv[2:]]
    found, severity = findings(paths)
    out = ["# Security scanner comparison", "", "## Findings by area", "",
           "| Area | Seen by 2+ tools | Seen by one tool | Only-one-tool breakdown |", "|---|---|---|---|"]
    for area, keys in sorted(found.items()):
        multi = sum(1 for tools in keys.values() if len(tools) > 1)
        solo = defaultdict(int)
        for tools in keys.values():
            if len(tools) == 1:
                solo[next(iter(tools))] += 1
        out.append(f"| {area} | {multi} | {sum(solo.values())} | "
                   + ", ".join(f"{t}: {n}" for t, n in sorted(solo.items())) + " |")
    out += ["", "## Findings by severity (SARIF level)", "", "| Tool | error | warning | note |", "|---|---|---|---|"]
    for tool, levels in sorted(severity.items()):
        out.append(f"| {tool} | {levels['error']} | {levels['warning']} | {levels['note']} |")
    report_json = report_dir / "mega-linter-report.json"
    if report_json.exists():
        out += ["", "## Run time per tool", "", "| Tool | Seconds | Errors | Status |", "|---|---|---|---|"]
        linters = json.loads(report_json.read_text())["linters"]
        for lint in sorted(linters, key=lambda x: -x["elapsed_time_s"]):
            out.append(f"| {lint['name']} | {lint['elapsed_time_s']:.1f} | {lint.get('total_number_errors')} | {lint['status']} |")
    print("\n".join(out))


if __name__ == "__main__":
    main()
