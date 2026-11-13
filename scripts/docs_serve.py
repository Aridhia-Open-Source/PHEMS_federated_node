"""Serve every docs version locally with the version dropdown and live reload.

Same layout as the published site: /<repo>/docs/<branch>/<version>/, a versions.json for
the dropdown, and the branch path opening the newest version. Saving a file under
docs/versions/<version>/ rebuilds that version and refreshes the open page.

Usage: python scripts/docs_serve.py <base path, e.g. /PHEMS_federated_node/docs/main> <port>
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from livereload import Server

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "docs" / "versions"
OUT = ROOT / ".venv-docs" / "site"
MKDOCS = ROOT / ".venv-docs" / "bin" / "mkdocs"


def version_key(name):
    return [int(p) if p.isdigit() else p for p in name.replace("x", "0").split(".")]


def build(version, site):
    subprocess.run(
        [str(MKDOCS), "build", "-q", "-f", str(VERSIONS / version / "mkdocs.yml"), "-d", str(site / version)],
        check=False,
    )


def rebuilder(version, site):
    def rebuild(*_changed):
        build(version, site)

    return rebuild


def main():
    base, port = sys.argv[1], int(sys.argv[2])
    versions = sorted((p.name for p in VERSIONS.iterdir() if (p / "mkdocs.yml").exists()), key=version_key, reverse=True)
    shutil.rmtree(OUT, ignore_errors=True)
    site = OUT / base.strip("/")
    site.mkdir(parents=True)
    for v in versions:
        build(v, site)
    (site / "versions.json").write_text(json.dumps([{"version": v, "title": v, "aliases": []} for v in versions]))
    (site / "index.html").write_text(f'<meta http-equiv="refresh" content="0; url={versions[0]}/">\n')

    server = Server()
    for v in versions:
        # livereload passes the changed paths to the callback, so bind the version here
        server.watch(str(VERSIONS / v / "**" / "*"), rebuilder(v, site), delay=1)
    print(f"Docs with the version dropdown and live reload: http://localhost:{port}{base}/", flush=True)
    server.serve(root=str(OUT), host="localhost", port=port, open_url_delay=None)


if __name__ == "__main__":
    main()
