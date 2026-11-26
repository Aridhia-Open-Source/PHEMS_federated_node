"""MkDocs hook that publishes a Postman collection next to the API reference.

The collection is built from the same openapi.json the API page renders, so every branch and
version of the docs carries the collection for its own API. Testers import it in Postman by
link (Import > Link) along with the empty environment, then fill in baseUrl, username and
password. See project/QA/README.md ("Making HTTP calls").
"""

import importlib.util
import json
import tempfile
from pathlib import Path

from mkdocs.structure.files import File

COLLECTION = "api/fn.postman_collection.json"
ENVIRONMENT = "api/fn.postman_environment.json"


def _builder(repo: Path):
    spec = importlib.util.spec_from_file_location("postman_collection", repo / "scripts/postman_collection.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def on_files(files, config):
    openapi = Path(config.docs_dir) / "api" / "openapi.json"
    if not openapi.exists():
        return files
    # docs/versions/<version>/mkdocs.yml -> the repo root
    repo = Path(config.config_file_path).resolve().parents[3]
    postman = repo / "project/QA/postman"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "collection.json"
        _builder(repo).main(str(openapi), str(postman / "prerequest.js"), str(out))
        collection = out.read_text(encoding="utf-8")
    json.loads(collection)  # fail the build on a broken collection, not the tester's import
    files.append(File.generated(config, COLLECTION, content=collection))
    files.append(File.generated(config, ENVIRONMENT, abs_src_path=str(postman / "fn.postman_environment.json")))
    return files
