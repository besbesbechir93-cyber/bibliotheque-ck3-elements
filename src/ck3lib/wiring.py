"""v0.6: conservatively connect a pinned v0.5 event clone to a new activity and on_action.

Generates a NEW mod fragment, never edits a game file, never patches vanilla
on_actions. Supports only statically recognized scalar references. Not a full
Jomini parser, an automatic GUI/localization linker, or a game validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from .composer import (
    CompositionError, tokenize, matching_braces, assignments,
    git_blob_sha, apply_edits, confined_path,
)
from .event_cloner import _analyze, NUMBERED_EVENT, NS, SHA, MAX_SOURCE_BYTES

ACTIVITY_PATH = re.compile(r"common/activities/activity_types/[a-zA-Z0-9_-]+\.txt\Z")
ON_ACTION_PATH = re.compile(r"common/on_action/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.txt\Z")
EVENT_PATH = re.compile(r"events/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.txt\Z")
ACTIVITY_NAME = re.compile(r"cklib_activity_[a-z0-9_]+\Z")
OA_NAME = re.compile(r"cklib_[a-z0-9_]+\Z")
REPORT = "event-clone-report.json"


def _read_pinned(root: Path, rel: str, sha: str, matcher: re.Pattern) -> str:
    if not isinstance(rel, str) or not matcher.fullmatch(rel):
        raise CompositionError("Unsupported or unsafe source path")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise CompositionError("Source Git blob SHA must be pinned")
    path = root / rel
    if any(root.joinpath(*Path(rel).parts[:i]).is_symlink()
           for i in range(1, len(Path(rel).parts) + 1)):
        raise CompositionError("Source symlink is forbidden")
    path = confined_path(root, rel)
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise CompositionError("Source missing or oversized")
    raw = path.read_bytes()
    if git_blob_sha(raw) != sha:
        raise CompositionError("Source Git blob SHA mismatch")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CompositionError("Invalid UTF-8 source") from exc


def _single_root(source: str, original_key: str):
    ts = tokenize(source)
    pairs = matching_braces(ts)
    roots = list(assignments(ts, pairs, 0, len(ts)))
    if len(roots) != 1 or roots[0][0].text != original_key or roots[0][2] is None:
        raise CompositionError("Expected exactly one named block at file root")
    return ts


def _rewrite(source: str, old_key: str, new_key: str,
             event_map: dict[str, str], on_action_map: dict[str, str]):
    """Token-position edits with explicit parent-context allowlist."""
    ts = _single_root(source, old_key)
    if not ts or ts[0].text != old_key:
        raise CompositionError("Root must begin with expected declaration")
    # Track enclosing block names (the nearest assignment `key = { ... }`).
    stack = []
    context = []
    for i, t in enumerate(ts):
        context.append(stack[-1] if stack else None)
        if t.text == "{":
            owner = ts[i-2].text if i >= 2 and ts[i-1].text == "=" else None
            stack.append(owner)
        elif t.text == "}":
            stack.pop()
    edits = [(ts[0].start, ts[0].end, new_key)]
    wired_events = set()
    wired_actions = set()
    expected_event_ns = {key.split(".", 1)[0] for key in event_map}
    for i, token in enumerate(ts[1:], 1):
        value = token.text
        # Quoted strings are not rewritten. Fail if they contain target identifiers.
        if value.startswith('"'):
            if any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(ns) + r"\.\d+", value)
                   for ns in expected_event_ns):
                raise CompositionError("Quoted event identifier needs manual review")
            continue
        if value in event_map or (NUMBERED_EVENT.fullmatch(value) and value.split(".", 1)[0] in expected_event_ns):
            if value not in event_map:
                raise CompositionError("Reference to an event outside the cloned event bundle")
            owner = context[i]
            field = ts[i-2].text if i >= 2 and ts[i-1].text == "=" else None
            safe = (
                field == "trigger_event"
                or (field == "id" and owner == "trigger_event")
                or (owner == "random_events" and field is not None and field.isdigit())
                or (owner == "events" and field is None)
            )
            if not safe:
                raise CompositionError(f"Unsupported event reference at {value!r}")
            edits.append((token.start, token.end, event_map[value]))
            wired_events.add(value)
        elif value in on_action_map:
            # A bare or ambiguous on_action symbol cannot be rewritten safely.
            field = ts[i-2].text if i >= 2 and ts[i-1].text == "=" else None
            if field != "on_action":
                raise CompositionError("Unsupported on_action reference context")
            edits.append((token.start, token.end, on_action_map[value]))
            wired_actions.add(value)
        elif value in set(on_action_map.values()):
            raise CompositionError("Target on_action ID is unexpectedly present in the source")
    out = apply_edits(source, edits)
    _single_root(out, new_key)
    return out, sorted(wired_events), sorted(wired_actions)


def _verify_event_fragment(event_fragment: Path, vanilla: Path):
    event_fragment = event_fragment.resolve(strict=True)
    if not event_fragment.is_dir() or event_fragment == vanilla or event_fragment.is_relative_to(vanilla):
        raise CompositionError("Event fragment must be separate from vanilla")
    report_file = event_fragment / REPORT
    if report_file.is_symlink() or not report_file.is_file() or report_file.stat().st_size > 100_000:
        raise CompositionError("Missing or unsafe event clone report")
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise CompositionError("Invalid event clone report") from exc
    if (report.get("status") != "STATIC_ONLY_REVIEW_REQUIRED"
        or report.get("version") != 1 or report.get("changes_vanilla") is not False
        or report.get("is_complete_mod") is not False):
        raise CompositionError("Unexpected event clone report provenance")
    path = report.get("generated_event_file")
    old_path = report.get("source_path")
    event_map = report.get("id_map")
    ns = report.get("target_namespace")
    if (not isinstance(path, str) or not EVENT_PATH.fullmatch(path)
        or not isinstance(old_path, str) or not EVENT_PATH.fullmatch(old_path)
        or not isinstance(ns, str) or not NS.fullmatch(ns)
        or not isinstance(event_map, dict) or not event_map
        or not all(isinstance(k, str) and isinstance(v, str) for k,v in event_map.items())):
        raise CompositionError("Malformed event clone manifest")
    source = _read_pinned(vanilla, old_path, report.get("source_git_blob_sha"), EVENT_PATH)
    original_ns = next(iter(event_map)).split(".", 1)[0]
    rendered, expected_map, _ = _analyze(source, original_ns, sorted(event_map), ns)
    if expected_map != event_map:
        raise CompositionError("Event ID map diverges from source")
    if any(event_fragment.joinpath(*Path(path).parts[:i]).is_symlink()
           for i in range(1, len(Path(path).parts) + 1)):
        raise CompositionError("Event clone symlink is forbidden")
    generated = confined_path(event_fragment, path)
    if not generated.is_file() or generated.stat().st_size > MAX_SOURCE_BYTES:
        raise CompositionError("Event clone file missing or oversized")
    if generated.read_bytes() != rendered.encode("utf-8-sig"):
        raise CompositionError("Event clone content does not match pinned source")
    return report, path, generated.read_bytes(), event_map


def assemble(recipe: dict, vanilla_root: Path, event_fragment_root: Path, output_root: Path) -> dict:
    """Create an entirely new fragment, linking a cloned activity and private on_action."""
    if not isinstance(recipe, dict) or set(recipe) != {"version", "activity", "on_action"} or recipe.get("version") != 1:
        raise CompositionError("Invalid v0.6 wiring recipe")
    a, o = recipe["activity"], recipe["on_action"]
    expected = {"source_path", "source_git_blob_sha", "source_id", "target_id"}
    if not isinstance(a, dict) or not isinstance(o, dict) or set(a) != expected or set(o) != expected:
        raise CompositionError("Invalid activity/on_action recipe fields")
    if (not isinstance(a["source_id"], str) or not NS.fullmatch(a["source_id"])
        or not isinstance(o["source_id"], str) or not NS.fullmatch(o["source_id"])
        or not isinstance(a["target_id"], str) or not ACTIVITY_NAME.fullmatch(a["target_id"])
        or not isinstance(o["target_id"], str) or not OA_NAME.fullmatch(o["target_id"])
        or len(a["target_id"]) > 64 or len(o["target_id"]) > 64
        or a["source_id"] == a["target_id"] or o["source_id"] == o["target_id"]):
        raise CompositionError("Invalid activity or on_action identifiers")
    vanilla = vanilla_root.resolve(strict=True)
    if not vanilla.is_dir():
        raise CompositionError("Vanilla root is not a directory")
    report, event_path, event_content, event_map = _verify_event_fragment(event_fragment_root, vanilla)
    old_a = _read_pinned(vanilla, a["source_path"], a["source_git_blob_sha"], ACTIVITY_PATH)
    old_o = _read_pinned(vanilla, o["source_path"], o["source_git_blob_sha"], ON_ACTION_PATH)
    action_map = {o["source_id"]: o["target_id"]}
    activity, activity_events, activity_actions = _rewrite(old_a, a["source_id"], a["target_id"], event_map, action_map)
    on_action, on_action_events, nested_actions = _rewrite(old_o, o["source_id"], o["target_id"], event_map, {})
    if not activity_actions or not on_action_events:
        raise CompositionError("Missing activity→on_action or on_action→event wiring")
    if nested_actions:
        raise CompositionError("Chained on_action dependencies are not supported")
    # Fail closed if the same custom identifiers already exist in vanilla.
    for rel_dir, target_id in (("common/activities/activity_types", a["target_id"]),
                               ("common/on_action", o["target_id"])):
        folder = vanilla / rel_dir
        for p in folder.rglob("*.txt") if folder.is_dir() else ():
            if p.is_symlink() or p.stat().st_size > MAX_SOURCE_BYTES:
                raise CompositionError("Unable to verify identifier uniqueness")
            if re.search(rb"(?m)^(?:\xef\xbb\xbf)?[ \t]*" + re.escape(target_id.encode()) + rb"[ \t]*=[ \t]*\{", p.read_bytes()):
                raise CompositionError("Generated ID collides with a vanilla definition")
    dest = output_root.absolute()
    parent = dest.parent.resolve(strict=True)
    event_fragment = event_fragment_root.resolve(strict=True)
    if (dest.exists() or dest.is_symlink() or dest.parent != parent
        or dest == vanilla or dest.is_relative_to(vanilla)
        or vanilla.is_relative_to(dest) or dest == event_fragment
        or dest.is_relative_to(event_fragment) or event_fragment.is_relative_to(dest)):
        raise CompositionError("Output must be a new independent directory")
    all_event_tokens = {
        t.text for content in (activity, on_action) for t in tokenize(content)
        if NUMBERED_EVENT.fullmatch(t.text)
    }
    retained_events = sorted(all_event_tokens.difference(event_map.values()))
    act_path = f"common/activities/activity_types/{a['target_id']}.txt"
    action_path = f"common/on_action/{o['target_id']}.txt"
    outcome = {
        "version": 1, "status": "STATIC_LINKED_REVIEW_REQUIRED", "game_validated": False,
        "is_complete_mod": False, "changes_vanilla": False,
        "source_event_clone_hash": git_blob_sha(event_content),
        "event_clone_source_path": report["source_path"],
        "retained_external_event_ids": retained_events,
        "source_activity_path": a["source_path"],
        "source_on_action_path": o["source_path"],
        "files": [event_path, act_path, action_path],
        "references": {"activity_to_events": activity_events,
                       "activity_to_on_actions": activity_actions,
                       "on_action_to_events": on_action_events},
        "warnings": [
            "Only explicitly recognized script references are wired.",
            "Retained external event IDs are not cloned or independently validated.",
            "Localization, GUI/GFX, external scripts, DLC and engine behavior remain unverified.",
            "Not a complete CK3 mod; game validation and integration review are required.",
        ],
    }
    try:
        dest.mkdir()
    except FileExistsError as exc:
        raise CompositionError("Destination already exists") from exc
    try:
        artifacts = {event_path: event_content, act_path: activity.encode("utf-8-sig"),
                     action_path: on_action.encode("utf-8-sig")}
        for rel, data in artifacts.items():
            target = confined_path(dest, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (dest / "wiring-report.json").write_text(
            json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(dest)
        raise
    return outcome


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate a new linked CK3 activity/event/on_action fragment")
    p.add_argument("--recipe", type=Path, required=True)
    p.add_argument("--vanilla-root", type=Path, required=True)
    p.add_argument("--event-fragment", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    result = assemble(json.loads(args.recipe.read_text(encoding="utf-8")), args.vanilla_root,
                      args.event_fragment, args.output)
    print(json.dumps({"status": result["status"], "files": result["files"]}, indent=2))


if __name__ == "__main__":
    main()
