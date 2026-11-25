"""Three-way merge of a conflicted JSON file by key, for scripts/verify_branch.sh.

Reads the base, ours and theirs stages from the git index and writes the merged file. A key one side
deletes and the other leaves alone stays deleted; a key both sides change differently stops the merge.
"""
import json
import subprocess
import sys

MISSING = object()


def stage(n, path):
    out = subprocess.run(["git", "show", f":{n}:{path}"], capture_output=True, text=True, check=False)
    return json.loads(out.stdout) if out.returncode == 0 else MISSING


def merge(base, ours, theirs, where):
    if ours == theirs:
        return ours
    if base == ours:
        return theirs
    if base == theirs:
        return ours
    if all(isinstance(x, dict) for x in (ours, theirs)) and (base is MISSING or isinstance(base, dict)):
        base = {} if base is MISSING else base
        out = {}
        for key in list(ours) + [k for k in theirs if k not in ours]:
            value = merge(base.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING), f"{where}.{key}")
            if value is not MISSING:
                out[key] = value
        return out
    sys.exit(f"verify_merge_json: both sides change {where} differently")


def main(path):
    merged = merge(stage(1, path), stage(2, path), stage(3, path), path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=4, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
