#!/usr/bin/env python3
"""Clone a Label Studio project's config and create one project per JSON file.

Each JSON file (e.g. files/vfva-202604/part-000.json) becomes a new project that
reuses the labeling config + settings of a source ("template") project, with its
records imported as tasks.

Usage:
    python create_project.py

Override defaults via environment variables, e.g.:
    LS_URL=http://localhost:8080 \
    LS_TOKEN=xxxxxxxx \
    SRC_PROJECT_ID=9 \
    JSON_DIR=files/vfva-202604\
    LIMIT=100 \
    python create_project.py
"""

import glob
import json
import os

import requests

# ---- Config -----------------------------------------------------------------
LS_URL = os.environ.get("LS_URL", "http://localhost:8080").rstrip("/")
# Auth: prefer a Personal Access Token (PAT) — LS 1.20 disabled legacy tokens.
# Get it from the UI: Account & Settings -> Personal Access Token.
LS_PAT = os.environ.get("LS_PAT", "")
# Legacy static token (only works if "Legacy Tokens" are enabled for the org).
LS_TOKEN = os.environ.get("LS_TOKEN", "")
SRC_PROJECT_ID = int(os.environ.get("SRC_PROJECT_ID", "9"))

JSON_DIR = os.environ.get("JSON_DIR", "files/vfva-202604")
JSON_GLOB = os.environ.get("JSON_GLOB", "part-*.json")
# Process the slice [FROM:TO] of the sorted JSON files (0-based, TO exclusive).
# e.g. FROM=0 TO=100 -> first 100 files. TO empty/0 -> through the last file.
FROM = int(os.environ.get("FROM", "0"))
TO = int(os.environ.get("TO", "0"))  # 0 means "until the end"
TITLE_PREFIX = os.environ.get("TITLE_PREFIX", "VFVA 202604")  # new project title prefix

# Settings copied from the source project onto each clone.
CLONE_FIELDS = [
    "label_config",
    "description",
    "expert_instruction",
    "show_instruction",
    "show_skip_button",
    "enable_empty_annotation",
    "show_annotation_history",
    "maximum_annotations",
    "color",
    "control_weights",
    "sampling",
    "reveal_preannotations_interactively",
]

session = requests.Session()


def authenticate():
    """Set the session Authorization header.

    If LS_PAT is provided, exchange the Personal Access Token (a JWT refresh
    token) for a short-lived access token and use Bearer auth. Otherwise fall
    back to the legacy static Token (requires legacy tokens enabled for the org).
    """
    if LS_PAT:
        resp = session.post(
            f"{LS_URL}/api/token/refresh", json={"refresh": LS_PAT}, timeout=60
        )
        if not resp.ok:
            raise SystemExit(
                f"\n[ERROR] Could not exchange PAT at /api/token/refresh -> "
                f"{resp.status_code}\n{resp.text[:500]}\n"
            )
        access = resp.json()["access"]
        session.headers.update({"Authorization": f"Bearer {access}"})
        print("Authenticated with Personal Access Token (JWT).")
    else:
        session.headers.update({"Authorization": f"Token {LS_TOKEN}"})
        print("Authenticated with legacy static token.")


def api(method, path, **kwargs):
    url = f"{LS_URL}/api/{path.lstrip('/')}"
    resp = session.request(method, url, timeout=60, **kwargs)
    if not resp.ok:
        raise SystemExit(
            f"\n[ERROR] {method} {url} -> {resp.status_code}\n{resp.text[:500]}\n"
        )
    return resp.json() if resp.content else None


def get_source_settings():
    """Fetch the template project and keep only the fields we want to clone."""
    src = api("GET", f"projects/{SRC_PROJECT_ID}/")
    settings = {f: src[f] for f in CLONE_FIELDS if f in src and src[f] is not None}
    print(f"Cloning from project {SRC_PROJECT_ID}: {src.get('title')!r}")
    return settings


def create_project(title, settings):
    payload = dict(settings)
    payload["title"] = title
    proj = api("POST", "projects/", json=payload)
    return proj["id"]


def import_tasks(project_id, tasks):
    """Import a list of task dicts into a project. Returns task count imported."""
    result = api(
        "POST",
        f"projects/{project_id}/import",
        json=tasks,
        params={"return_task_ids": "false"},
    )
    return result.get("task_count", len(tasks)) if isinstance(result, dict) else len(tasks)


def main():
    authenticate()
    settings = get_source_settings()

    pattern = os.path.join(JSON_DIR, JSON_GLOB)
    json_files = sorted(glob.glob(pattern))
    if not json_files:
        raise SystemExit(f"No JSON files matched {pattern}")

    end = TO if TO > 0 else len(json_files)
    json_files = json_files[FROM:end]
    print(f"Found {len(json_files)} JSON file(s) to import (FROM={FROM}, TO={end}).\n")

    created = []
    for i, jf in enumerate(json_files, 1):
        name = os.path.splitext(os.path.basename(jf))[0]  # e.g. part-000
        title = f"{TITLE_PREFIX} {name}"

        with open(jf, encoding="utf-8") as f:
            tasks = json.load(f)
        if not isinstance(tasks, list):
            print(f"  [skip] {jf}: expected a JSON list, got {type(tasks).__name__}")
            continue

        try:
            pid = create_project(title, settings)
            n = import_tasks(pid, tasks)
            created.append((pid, title, n))
            print(f"  [{i}/{len(json_files)}] created project {pid} {title!r} ({n} tasks)")
        except SystemExit as e:
            print(e)
            print(f"  [{i}/{len(json_files)}] FAILED on {jf}")
            break

    print(f"\nDone. Created {len(created)} project(s).")


if __name__ == "__main__":
    main()
