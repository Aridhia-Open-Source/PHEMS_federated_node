"""
Builds a Postman collection from nexus-api's OpenAPI spec, with bearer auth on {{token}} and the
login script in project/QA/postman/prerequest.js. Run by `mise run postman` (scripts/postman.sh).

    python scripts/postman_collection.py <openapi.json> <prerequest.js> <out.json>
"""
import json
import re
import sys

METHODS = ("get", "post", "put", "patch", "delete")


def resolve(spec: dict, schema: dict) -> dict:
    """Follow a local $ref."""
    while "$ref" in schema:
        node = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def example(spec: dict, schema: dict):
    """A placeholder value for a schema: required fields of objects, empty scalars."""
    schema = resolve(spec, schema)
    if "anyOf" in schema:
        return example(spec, next(s for s in schema["anyOf"] if s.get("type") != "null"))
    if "default" in schema:
        return schema["default"]
    kind = schema.get("type", "object")
    if kind == "object":
        props = schema.get("properties", {})
        keys = schema.get("required", list(props))
        return {key: example(spec, props[key]) for key in keys}
    return {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False}[kind]


def body(spec: dict, op: dict) -> dict | None:
    content = op.get("requestBody", {}).get("content", {})
    if "application/json" in content:
        raw = json.dumps(example(spec, content["application/json"]["schema"]), indent=2)
        return {"mode": "raw", "raw": raw, "options": {"raw": {"language": "json"}}}
    if "application/x-www-form-urlencoded" in content:
        form = example(spec, content["application/x-www-form-urlencoded"]["schema"])
        return {"mode": "urlencoded", "urlencoded": [{"key": k, "value": str(v)} for k, v in form.items()]}
    return None


def item(spec: dict, path: str, method: str, op: dict) -> dict:
    params = op.get("parameters", [])
    segments = re.sub(r"\{(\w+)\}", r":\1", path).strip("/").split("/")
    query = [p for p in params if p["in"] == "query"]
    request = {
        "method": method.upper(),
        "header": [],
        "url": {
            "raw": "{{baseUrl}}/" + "/".join(segments),
            "host": ["{{baseUrl}}"],
            "path": segments,
            "variable": [{"key": p["name"], "value": ""} for p in params if p["in"] == "path"],
            "query": [{"key": p["name"], "value": "", "disabled": not p.get("required")} for p in query],
        },
    }
    if request_body := body(spec, op):
        request["body"] = request_body
    return {"name": op.get("summary", f"{method.upper()} {path}"), "request": request}


def main(spec_path: str, script_path: str, out_path: str):
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    with open(script_path, encoding="utf-8") as f:
        script = f.read().splitlines()

    folders: dict[str, list] = {}
    for path, ops in spec["paths"].items():
        for method in METHODS:
            if op := ops.get(method):
                folders.setdefault(op.get("tags", ["other"])[0], []).append(item(spec, path, method, op))

    collection = {
        "info": {
            "name": spec["info"]["title"],
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": script}}],
        "item": [{"name": name, "item": items} for name, items in sorted(folders.items())],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=2)


if __name__ == "__main__":
    main(*sys.argv[1:])
