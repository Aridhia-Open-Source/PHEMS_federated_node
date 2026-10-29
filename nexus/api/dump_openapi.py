"""Writes the generated OpenAPI spec to nexus/api/openapi.json, which the UI generates its types from."""
import json
from pathlib import Path

from app import create_app

Path(__file__).with_name("openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
