"""Fail-closed, source-pinned CK3 event-file clone (v0.5 prototype).

Only a complete, self-contained source EVENT FILE is eligible. This module
never edits the game. It deliberately refuses ambiguous or unrecognized event
references instead of producing subtly broken copies. It is not a Jomini
parser, event router, localization copier, or guarantee of game compatibility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from .composer import CompositionError, tokenize, matching_braces, git_blob_sha, apply_edits, confined_path

NS = re.compile(r"[a-z][a-z0-9_]*\Z")
NUMBERED_EVENT = re.compile(r"([a-z][a-z0-9_]*)\.([0-9]+)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_REL = re.compile(r"events/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.txt\Z")
EVENT_TYPES = frozenset({"character_event", "province_event", "letter_event", "activity_event"})
MAX_SOURCE_BYTES = 4_000_000


def _members(ts, pairs, start, end):
    """List top-level assignments, rejecting every unexpected sequence."""
    i = start
    result = []
    while i < end:
        if i + 2 >= end or ts[i + 1].text != "=":
            raise CompositionError(f"Unexpected top-level construct at token {ts[i].text!r}")
        key, v = i, i + 2
        if ts[v].text == "{":
            close = pairs[v]
            if close >= end:
                raise CompositionError("Unclosed nested block")
            result.append((key, v, close))
            i = close + 1
        else:
            result.append((key, v, None))
            i = v + 1
    return result


def _token_scopes(ts):
    stack = []
    scope = []
    for i, t in enumerate(ts):
        scope.append(stack[-1] if stack else None)
        if t.text == "{":
            stack.append(i)
        if t.text == "}":
            if not stack:
                raise CompositionError("Extra closing brace")
            stack.pop()
    if stack:
        raise CompositionError("Unterminated brace")
    return scope


def _analyze(source: str, expected_ns: str, expected_ids: list[str], target_ns: str):
    if not NS.fullmatch(expected_ns) or not NS.fullmatch(target_ns) or expected_ns == target_ns:
        raise CompositionError("Invalid or unchanged source/target namespace")
    ts = tokenize(source)
    pairs = matching_braces(ts)
    scope = _token_scopes(ts)
    root_assignments = _members(ts, pairs, 0, len(ts))
    ns_decl = []
    event_defs = {}
    event_scopes = set()
    for key, value, close in root_assignments:
        name = ts[key].text
        if name == "namespace":
            if close is not None:
                raise CompositionError("Namespace must be scalar")
            ns_decl.append(value)
        elif (matched := NUMBERED_EVENT.fullmatch(name)) and matched.group(1) == expected_ns:
            if close is None or name in event_defs:
                raise CompositionError("Duplicate or invalid event declaration")
            event_defs[name] = key
            event_scopes.add(value)
        elif name in EVENT_TYPES:
            if close is None:
                raise CompositionError("Event type must hold an event block")
            ids = [(k, v, c) for k, v, c in _members(ts, pairs, value + 1, close)
                   if ts[k].text == "id"]
            if len(ids) != 1 or ids[0][2] is not None:
                raise CompositionError("Typed event must contain exactly one scalar id")
            event_id = ts[ids[0][1]].text
            if not NUMBERED_EVENT.fullmatch(event_id) or not event_id.startswith(expected_ns + ".") or event_id in event_defs:
                raise CompositionError("Typed event id outside expected namespace or duplicated")
            event_defs[event_id] = ids[0][1]
            event_scopes.add(value)
        else:
            raise CompositionError(f"Unrecognized top-level declaration {name!r}; use a dedicated adapter")
    if len(ns_decl) != 1 or ts[ns_decl[0]].text != expected_ns:
        raise CompositionError("Expected exactly one matching source namespace")
    if not event_defs:
        raise CompositionError("No event definitions found")
    if (not isinstance(expected_ids, list) or not expected_ids
        or any(not isinstance(x, str) for x in expected_ids)
        or len(set(expected_ids)) != len(expected_ids)
        or set(event_defs) != set(expected_ids)):
        raise CompositionError("Pinned event ID inventory does not match the full source file")
    # Root blocks are validated above. Referencing an old namespace event ID
    # from another expression is refused rather than guessed/replaced.
    block_name = {}
    for i, t in enumerate(ts):
        if t.text == "{" and i >= 2 and ts[i-1].text == "=":
            block_name[i] = ts[i-2].text
    edits = [(ts[ns_decl[0]].start, ts[ns_decl[0]].end, target_ns)]
    definitions = set(event_defs.values())
    references = []
    for i, token in enumerate(ts):
        literal = token.text
        if literal.startswith('"') and re.search(r"(?<![a-zA-Z0-9_])" + re.escape(expected_ns) + r"\.\d+", literal):
            raise CompositionError("Quoted legacy event identifier requires manual review")
        if not literal.startswith(expected_ns + ".") or not NUMBERED_EVENT.fullmatch(literal):
            continue
        if literal not in event_defs:
            raise CompositionError(f"Reference to event absent from clone bundle: {literal}")
        if i in definitions:
            safe = True
        elif scope[i] in event_scopes and i > 1 and ts[i-1].text == "=":
            # Root event declaration is handled above; the token itself is the key.
            safe = False
        elif i >= 2 and ts[i-1].text == "=":
            field = ts[i-2].text
            owner = scope[i]
            safe = (field == "trigger_event" or
                    (field == "id" and block_name.get(owner) == "trigger_event") or
                    (field.isdigit() and block_name.get(owner) == "random_events"))
        else:
            safe = block_name.get(scope[i]) == "events"
        if not safe:
            raise CompositionError(f"Unsupported event reference context near {literal!r}")
        if i not in definitions:
            references.append(literal)
        edits.append((token.start, token.end, target_ns + literal[len(expected_ns):]))
    # Avoid accidentally applying twice to a typed event id via nested token walk.
    offsets = [(a, b) for a, b, _ in edits]
    if len(offsets) != len(set(offsets)):
        raise CompositionError("Overlapping event rewrite locations")
    result = apply_edits(source, edits)
    # Ensure no stale IDs remain as unquoted scalar identifiers.
    for t in tokenize(result):
        if NUMBERED_EVENT.fullmatch(t.text) and t.text.startswith(expected_ns + "."):
            raise CompositionError("Stale source event reference after rewrite")
    return result, {name: target_ns + name[len(expected_ns):] for name in sorted(event_defs)}, sorted(set(references))


def clone(recipe: dict, vanilla_root: Path, output_root: Path) -> dict:
    """Generate an isolated mod *fragment* in a new output directory."""
    keys = {"version", "source_path", "source_git_blob_sha", "source_namespace",
            "expected_event_ids", "namespace", "source_version_label"}
    if not isinstance(recipe, dict) or set(recipe) != keys or type(recipe.get("version")) is not int or recipe["version"] != 1:
        raise CompositionError("Invalid v0.5 recipe fields/version")
    rel = recipe["source_path"]
    namespace = recipe["namespace"]
    old_ns = recipe["source_namespace"]
    if not isinstance(rel, str) or not SOURCE_REL.fullmatch(rel):
        raise CompositionError("Source path must be a normalized events/*.txt path")
    if not isinstance(namespace, str) or not NS.fullmatch(namespace) or len(namespace) > 24:
        raise CompositionError("Namespace must be lowercase ASCII and at most 24 characters")
    if not isinstance(old_ns, str) or not NS.fullmatch(old_ns):
        raise CompositionError("Invalid source namespace")
    target_ns = f"cklib_{namespace}_{old_ns}"
    if len(target_ns) > 64 or target_ns == old_ns:
        raise CompositionError("Generated namespace too long or unchanged")
    digest = recipe["source_git_blob_sha"]
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise CompositionError("A pinned SHA1 Git blob is required")
    label = recipe["source_version_label"]
    if not isinstance(label, str) or not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
        raise CompositionError("Invalid version label")
    vanilla = vanilla_root.resolve(strict=True)
    if not vanilla.is_dir():
        raise CompositionError("Game source is not a directory")
    # Check the lexical source path *before* resolving it. Otherwise
    # confined_path() would hide an in-root symlink to a different file.
    lexical_src = vanilla / rel
    if any((vanilla.joinpath(*Path(rel).parts[:n])).is_symlink()
           for n in range(1, len(Path(rel).parts) + 1)):
        raise CompositionError("Symlinked source path is forbidden")
    src = confined_path(vanilla, rel)
    if not src.is_file():
        raise CompositionError("Missing source file")
    if src.stat().st_size > MAX_SOURCE_BYTES:
        raise CompositionError("Source file too large")
    raw = src.read_bytes()
    actual = git_blob_sha(raw)
    if actual != digest:
        raise CompositionError("Pinned source Git SHA mismatch")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CompositionError("Source is not UTF-8") from exc
    rewritten, id_map, refs = _analyze(text, old_ns, recipe["expected_event_ids"], target_ns)
    output = output_root.absolute()
    parent = output.parent.resolve(strict=True)
    if output.exists() or output.is_symlink() or not parent.is_dir():
        raise CompositionError("Output must be a new directory")
    if parent == vanilla or parent.is_relative_to(vanilla) or vanilla.is_relative_to(parent / output.name):
        raise CompositionError("Output directory overlaps or contains vanilla source")
    # Check for an existing namespace in the target game source. This is
    # deliberately a conservative byte scan; false positives may block.
    event_dir = vanilla / "events"
    for path in event_dir.rglob("*.txt") if event_dir.is_dir() else ():
        if path.is_symlink() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise CompositionError("Cannot establish target namespace uniqueness")
        if re.search(rb"\bnamespace\s*=\s*" + re.escape(target_ns.encode()) + rb"\b", path.read_bytes()):
            raise CompositionError("Target namespace collides with game source")
    out_rel = f"events/cklib_{namespace}_{Path(rel).stem}.txt"
    report = {
        "version": 1, "status": "STATIC_ONLY_REVIEW_REQUIRED", "game_validated": False,
        "changes_vanilla": False, "is_complete_mod": False,
        "source_version_label": label, "source_path": rel, "source_git_blob_sha": actual,
        "target_namespace": target_ns, "generated_event_file": out_rel,
        "id_map": id_map, "internal_references_rewritten": refs,
        "warnings": [
            "Cloned event dispatch is NOT wired to vanilla on_actions or activity phases.",
            "GUI, GFX, localization, script effects and DLC conditions are NOT cloned or validated.",
            "This output is a mod fragment, not a complete CK3 mod. Test in game before use."
        ]
    }
    # Reserve the destination exclusively. No pre-existing files can be
    # overwritten, and exceptions remove only this newly created directory.
    try:
        output.mkdir()
    except FileExistsError as exc:
        raise CompositionError("Refusing existing destination") from exc
    try:
        dest = confined_path(output, out_rel)
        dest.parent.mkdir(parents=True)
        dest.write_text(rewritten, encoding="utf-8-sig")
        (output / "event-clone-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(output)
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Clone a standalone CK3 event file into a new mod fragment")
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--vanilla-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = clone(json.loads(args.recipe.read_text(encoding="utf-8-sig")), args.vanilla_root, args.output)
    print(json.dumps({"status": report["status"], "event_ids": len(report["id_map"]), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
