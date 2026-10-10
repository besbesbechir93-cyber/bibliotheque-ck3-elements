"""Read-only, conservative CK3 source dependency indexer (standard library only).

This is not a complete Clausewitz/Jomini parser. Only explicitly supported
reference shapes are resolved; a missing edge is NOT proof of independence.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .composer import CompositionError, tokenize

SOURCE_DIRS = ("common", "events", "gui", "interface", "gfx", "localization")
TEXT_SUFFIXES = frozenset((".txt", ".gui", ".gfx", ".asset", ".yml", ".yaml"))
GRAPHICS_SUFFIXES = frozenset((".dds", ".png", ".tga", ".mesh", ".anim", ".texture"))
ASSET_PATH = re.compile(r"^gfx/[A-Za-z0-9_./-]+\.(?:dds|png|tga|mesh|anim|texture)$", re.I)
LOC_LINE = re.compile(r'^\s*([A-Za-z_][\w.\-]*):\d*\s+(?:"|\S)')
ATOM = re.compile(r"^[A-Za-z_][\w.\-]*$")
EVENT_ID = re.compile(r"^[\w.\-]+\.\d+$")
GUI_TYPES = frozenset(("windowType", "widgetType", "containerWindowType", "buttonType", "iconType", "textBoxType", "editBoxType", "listboxType", "scrollareaType", "dynamicgridboxType", "gridBoxType"))
GFX_TYPES = frozenset(("spriteType", "progressbarType", "frameAnimatedSpriteType", "corneredTileSpriteType"))

# This list is intentionally reviewed, finite, and conservative. New field
# families require fixtures before accepting them as verified references.
FIELD_TARGETS = {
    "has_government": "government",
    "set_government_type": "government",
    "domicile_type": "domicile",
    "house_unity": "house_unity",
    "tax_slot_type": "tax_slot",
    "vassal_contract_group": "subject_contract_group",
    "primary_holding": "holding",
    "has_holding_type": "holding",
    "primary_building": "building",
    "has_building": "building",
    "add_building": "building",
    "on_action": "on_action",
    "is_activity_type_on_cooldown": "activity",
    "government_has_flag": "government_flag",
    "has_government_flag": "government_flag",
    "has_law": "law",
    "activity_type": "activity",
}
GUI_REFERENCE_FIELDS = frozenset(("widget", "widget_name", "window", "window_name"))
GUI_DYNAMIC_FIELDS = frozenset(("datacontext", "onclick", "visible", "enabled", "text", "tooltip", "tooltip_text", "dataobject", "effect", "parentanchor"))
SPRITE_REFERENCE_FIELDS = frozenset(("sprite", "sprite_name", "icon", "icon_sprite"))
LOCALIZATION_FIELDS = frozenset(("desc", "text", "tooltip", "title", "localization_key", "custom_tooltip", "province_description"))
DECLARATION_CATEGORIES = {
    "governments": "government", "activities/activity_types": "activity", "tax_slots/types": "tax_slot",
    "house_unities": "house_unity", "house_aspirations": "house_aspiration",
    "house_relation_types": "house_relation", "confederation_types": "confederation",
    "succession_appointment": "succession_appointment", "laws": "law",
    "buildings": "building", "holdings": "holding", "domiciles/types": "domicile",
    "domiciles/buildings": "domicile_building", "on_action": "on_action",
    "scripted_effects": "scripted_effect", "scripted_triggers": "scripted_trigger",
    "script_values": "script_value", "decisions": "decision", "modifiers": "modifier",
    "subject_contracts/groups": "subject_contract_group", "subject_contracts/contracts": "subject_contract",
    "tax_slots/obligations": "tax_obligation", "succession_election": "succession_election",
    "great_projects/types": "great_project", "traits": "trait",
}


def _category(relative: str) -> str | None:
    if not relative.startswith("common/"):
        return None
    path = relative[len("common/"):]
    # Longest prefix first: e.g. domicile buildings before buildings.
    for prefix in sorted(DECLARATION_CATEGORIES, key=len, reverse=True):
        if path.startswith(prefix + "/"):
            return DECLARATION_CATEGORIES[prefix]
    return None


def _atom(value: str) -> str | None:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value if value and value not in ("{", "}", "=") else None



def _parse(text: str) -> tuple[list, dict[int, int], list[tuple[int, int, int, int | None]]]:
    """Return tokens, brace pairs, assignments (key, operator, value, owner_scope)."""
    ts = tokenize(text)
    stack: list[int] = []
    end: dict[int, int] = {}
    owner: list[int | None] = []
    for n, token in enumerate(ts):
        owner.append(stack[-1] if stack else None)
        if token.text == "{":
            stack.append(n)
        elif token.text == "}":
            if not stack:
                raise CompositionError("Unmatched closing brace")
            end[stack.pop()] = n
    if stack:
        raise CompositionError("Unterminated brace block")
    assignments = []
    for n in range(len(ts) - 2):
        if ts[n+1].text in ("=", "?=", "==") and ts[n].text not in ("{", "}", "=") and ts[n+2].text != "}":
            # Only assignments whose key and operator are within the same scope.
            if owner[n] == owner[n+1] == owner[n+2]:
                assignments.append((n, n+1, n+2, owner[n]))
    return ts, end, assignments


def _on_action_entries(ts: list, open_index: int, close_index: int, *, weighted: bool) -> list[tuple[str, int]]:
    """Read supported top-level entries in on_action event/on_action lists.

    Nested blocks and numeric weights are skipped. This does not evaluate
    triggers, weights, dynamic effects or game-engine dispatch.
    """
    items: list[tuple[str, int]] = []
    depth = 0
    i = open_index + 1
    while i < close_index:
        word = ts[i].text
        if word == "{":
            depth += 1
        elif word == "}":
            depth -= 1
        elif depth == 0:
            if weighted and word.isdigit() and i + 2 < close_index and ts[i + 1].text == "=":
                items.append((ts[i + 2].text, ts[i + 2].start))
                i += 2
            elif not weighted and word not in ("=", "?=") and (i + 1 >= close_index or ts[i + 1].text != "="):
                items.append((word, ts[i].start))
        i += 1
    return items


def _file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_file(root: Path, path: Path) -> bool:
    # Reject symlinks, including symlinked subdirectories.
    return path.resolve().is_relative_to(root) and not any(p.is_symlink() for p in (path, *path.parents) if p != root)


def scan(vanilla_root: Path, *, version: str = "unspecified", max_file_bytes: int = 10_000_000) -> dict[str, Any]:
    """Create a deterministic JSON-serializable graph without writing to disk.

    Sources may contain proprietary content, but output includes only identifiers,
    paths, line numbers and hashes; never the source bodies or binary assets.
    """
    root = vanilla_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Vanilla root must be a directory")
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_seen = set()
    unresolved: list[dict] = []
    warnings: list[dict] = []
    dynamic_references: list[dict] = []
    dynamic_seen: set[tuple[str, str, int, str]] = set()
    pending: list[tuple[str, str, str, str, int, str]] = []
    possible_script_calls: list[tuple[str, str, str, int]] = []
    symbol_defs: dict[str, list[dict]] = defaultdict(list)

    def node(node_id: str, kind: str, **attrs):
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, **attrs}

    def edge(src: str, dst: str, relation: str, source_path: str, line: int, confidence: str = "exact"):
        k = (src, dst, relation, source_path, line)
        if k not in edge_seen:
            edge_seen.add(k)
            edges.append({"source": src, "target": dst, "relation": relation,
                          "evidence": {"path": source_path, "line": line}, "confidence": confidence})

    def define(kind: str, name: str, rel: str, line: int) -> str:
        key = f"{kind}:{name}"
        node(key, kind, name=name, definitions=[])
        definition = {"path": rel, "line": line}
        if definition not in symbol_defs[key]:
            symbol_defs[key].append(definition)
            nodes[key]["definitions"].append(definition)
            edge(f"file:{rel}", key, "defines", rel, line)
        return key

    paths: list[Path] = []
    for prefix in SOURCE_DIRS:
        directory = root / prefix
        if directory.is_dir() and not directory.is_symlink():
            paths.extend(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    for path in sorted(set(paths)):
        rel = path.relative_to(root).as_posix()
        if not _safe_file(root, path):
            warnings.append({"path": rel, "reason": "symlink_or_path_escape"})
            continue
        if path.stat().st_size > max_file_bytes:
            warnings.append({"path": rel, "reason": "exceeds_size_limit"})
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            warnings.append({"path": rel, "reason": "not_utf8"})
            continue
        file_id = f"file:{rel}"
        node(file_id, "file", path=rel, bytes=len(raw), sha256=_file_digest(raw))
        newline_offsets = [m.start() for m in re.finditer("\n", text)]
        def line_of(offset: int) -> int:
            return bisect_right(newline_offsets, offset) + 1
        if path.suffix.lower() in (".yml", ".yaml"):
            if rel.startswith("localization/"):
                for line_num, row in enumerate(text.splitlines(), 1):
                    m = LOC_LINE.match(row)
                    if m and not m.group(1).startswith("l_"):
                        define("localization", m.group(1), rel, line_num)
            continue
        try:
            ts, brace_end, assn = _parse(text)
        except CompositionError as err:
            warnings.append({"path": rel, "reason": "parse_failure", "details": str(err)})
            continue
        direct = defaultdict(list)
        for key_i, _, value_i, owner in assn:
            direct[owner].append((key_i, value_i))
        roots = {}  # (open block token index) => graph entity
        category = _category(rel)

        # Public database keys (root-level assignments).
        if category:
            for ki, vi in direct[None]:
                if ts[vi].text == "{" and not ts[ki].text.startswith("_"):
                    roots[vi] = define(category, ts[ki].text, rel, line_of(ts[ki].start))

        # Events: event ids are in `id` inside character_event / similar roots.
        if rel.startswith("events/"):
            for ki, vi in direct[None]:
                if ts[ki].text.endswith("_event") and ts[vi].text == "{":
                    for sub_k, sub_v in direct[vi]:
                        if ts[sub_k].text == "id" and ts[sub_v].text != "{":
                            name = _atom(ts[sub_v].text)
                            if name:
                                roots[vi] = define("event", name, rel, line_of(ts[sub_k].start))

        # GUI/GFX: named widget/sprite declarations can be nested.
        for ki, _, vi, owner in assn:
            kind = "gui" if ts[ki].text in GUI_TYPES else "sprite" if ts[ki].text in GFX_TYPES else None
            if kind and ts[vi].text == "{" and (rel.startswith("gui/") or rel.startswith("interface/") or rel.startswith("gfx/")):
                for sub_k, sub_v in direct[vi]:
                    if ts[sub_k].text == "name":
                        name = _atom(ts[sub_v].text)
                        if name and ts[sub_v].text != "{":
                            roots[vi] = define(kind, name, rel, line_of(ts[sub_k].start))
                            break

        # Explicit on_action event lists. CK3 uses both `events = { x.1 }`
        # and `random_events = { 100 = x.1 }`. They are not generic scalar
        # assignments, so v0.2 skipped them. Names inside nested conditions
        # are deliberately excluded until a separate grammar is supported.
        if category == "on_action":
            for ki, _, vi, owner in assn:
                if owner not in roots or ts[vi].text != "{":
                    continue
                kind = ts[ki].text
                if kind not in ("events", "random_events", "on_actions"):
                    continue
                origin = roots[owner]
                weighted = kind == "random_events"
                for value, offset in _on_action_entries(ts, vi, brace_end[vi], weighted=weighted):
                    target_kind = "on_action" if kind == "on_actions" else "event"
                    if (ATOM.fullmatch(value) if target_kind == "on_action" else EVENT_ID.fullmatch(value)):
                        pending.append((origin, target_kind, value, rel, line_of(offset), "exact"))

        # Government flags appear as a bare list in a `flags` block.
        if category == "government":
            for ki, _, vi, owner in assn:
                if ts[ki].text != "flags" or ts[vi].text != "{":
                    continue
                gov = roots.get(owner)
                if gov is None:
                    continue
                # Only direct raw atoms; comments have already been skipped.
                for i in range(vi + 1, brace_end[vi]):
                    if ts[i].text in ("{", "}", "=") or ts[i].text.startswith('"'):
                        continue
                    if _is_direct_token(i, vi, ts):
                        flag_name = ts[i].text
                        if ATOM.fullmatch(flag_name):
                            flag = define("government_flag", flag_name, rel, line_of(ts[i].start))
                            edge(gov, flag, "declares_flag", rel, line_of(ts[i].start))

        # Assign references to innermost indexed entity (or file if no such entity).
        block_keys = {vi: ts[ki].text for ki, _, vi, _ in assn if ts[vi].text == "{"}
        scopes: dict[int, int | None] = {}
        for _, _, vi, owner in assn:
            if ts[vi].text == "{":
                scopes[vi] = owner

        def source_at(owner: int | None) -> str:
            scope = owner
            while scope is not None:
                if scope in roots:
                    return roots[scope]
                scope = scopes.get(scope)
            return file_id

        for ki, _, vi, owner in assn:
            field = ts[ki].text
            token = ts[vi]
            if token.text == "{":
                continue
            value = _atom(token.text)
            if value is None:
                continue
            origin = source_at(owner)
            line_num = line_of(ts[ki].start)
            target_type = FIELD_TARGETS.get(field)
            if rel.startswith("gui/") and field.lower() in GUI_DYNAMIC_FIELDS and token.text.startswith('"'):
                if "[" in value or "Get" in value or "GuiScope" in value:
                    marker = (origin, rel, line_num, field)
                    if marker not in dynamic_seen:
                        dynamic_seen.add(marker)
                        dynamic_references.append({"source": origin, "kind": "gui_expression",
                                                   "field": field, "evidence": {"path": rel, "line": line_num},
                                                   "reason": "runtime_binding_unresolved"})
            if field == "trigger_event" and EVENT_ID.fullmatch(value):
                target_type = "event"
            elif field == "id" and owner is not None and block_keys.get(owner) == "trigger_event":
                # Distinguish literal event dispatch from unrecognized runtime
                # references. Only evidence metadata is kept, not script bodies.
                if EVENT_ID.fullmatch(value):
                    target_type = "event"
                else:
                    marker = (origin, rel, line_num, "id")
                    if marker not in dynamic_seen:
                        dynamic_seen.add(marker)
                        dynamic_references.append({"source": origin, "kind": "event_dispatch",
                                                   "field": "id", "evidence": {"path": rel, "line": line_num},
                                                   "reason": "dynamic_event_id_unresolved"})
            elif field == "illustration" and ASSET_PATH.fullmatch(value):
                target_type = None
            if target_type and ATOM.fullmatch(value):
                pending.append((origin, target_type, value, rel, line_num, "exact"))
            if ASSET_PATH.fullmatch(value):
                asset = f"file:{value}"
                node(asset, "file", path=value, external_reference=True)
                edge(origin, asset, "uses_asset", rel, line_num)
            if field in LOCALIZATION_FIELDS and ATOM.fullmatch(value):
                pending.append((origin, "localization", value, rel, line_num, "heuristic"))
            if field in GUI_REFERENCE_FIELDS and ATOM.fullmatch(value):
                pending.append((origin, "gui", value, rel, line_num, "heuristic"))
            if field in SPRITE_REFERENCE_FIELDS and value.startswith("GFX_") and ATOM.fullmatch(value):
                pending.append((origin, "sprite", value, rel, line_num, "heuristic"))
            # Known scripted-effect and scripted-trigger keys; infer only from
            # assignments, never from comments, strings or mere token presence.
            if field not in ("namespace", "name", "id"):
                possible_script_calls.append((origin, field, rel, line_num))

    for origin, field, rel, line_num in possible_script_calls:
        for target_type in ("scripted_effect", "scripted_trigger"):
            if f"{target_type}:{field}" in nodes:
                pending.append((origin, target_type, field, rel, line_num, "heuristic"))

    # Resolve after complete definition inventory. Missing inferred script keys
    # are normal and must not flood the unresolved list.
    for origin, kind, value, rel, lineno, confidence in pending:
        target = f"{kind}:{value}"
        if target in nodes:
            if target != origin:
                relation = "calls_script" if kind.startswith("scripted_") else "localizes" if kind == "localization" else "references"
                edge(origin, target, relation, rel, lineno, confidence)
        elif confidence == "exact":
            unresolved.append({"source": origin, "target_kind": kind, "identifier": value,
                               "evidence": {"path": rel, "line": lineno},
                               "reason": "not_found_in_index_not_proven_missing"})

    for key, locations in sorted(symbol_defs.items()):
        if len(locations) > 1:
            warnings.append({"reason": "duplicate_identifier", "symbol": key, "definitions": locations})
    for key, n in nodes.items():
        if n["kind"] == "file" and n.get("external_reference"):
            exists = (root / n["path"]).is_file()
            n["exists_in_source"] = exists
            if exists and _safe_file(root, root / n["path"]):
                n["external_reference"] = False
            else:
                warnings.append({"reason": "unverified_asset", "path": n["path"]})
    edges.sort(key=lambda e: (e["source"], e["target"], e["relation"], e["evidence"]["path"], e["evidence"]["line"]))
    unresolved.sort(key=lambda e: (e["source"], e["target_kind"], e["identifier"], e["evidence"]["path"], e["evidence"]["line"]))
    warnings.sort(key=lambda w: (w.get("path", ""), w.get("reason", ""), w.get("symbol", "")))
    dynamic_references.sort(key=lambda e: (e["source"], e["evidence"]["path"], e["evidence"]["line"], e["field"]))
    return {"schema_version": 1, "status": "STATIC_PARTIAL_NOT_GAME_VALIDATED",
            "source_version_label": version,
            "limitations": ["Not a full CK3 grammar or engine dependency analyzer.",
                             "Dynamic references, GUI bindings, inline localization and hardcoded mechanics are not exhaustively resolved.",
                             "Unresolved does not imply an error; absent edges do not prove independence."],
            "nodes": [nodes[k] for k in sorted(nodes)], "edges": edges,
            "unresolved": unresolved, "warnings": warnings, "dynamic_references": dynamic_references,
            "summary": {"nodes": len(nodes), "edges": len(edges), "unresolved": len(unresolved), "warnings": len(warnings), "dynamic_references": len(dynamic_references)}}


def _is_direct_token(i: int, parent_open: int, ts: list) -> bool:
    # A `flags` block contains a flat collection of flags; nested values must
    # not accidentally be treated as declared government flags.
    depth = 0
    for token in ts[parent_open + 1:i]:
        if token.text == "{":
            depth += 1
        elif token.text == "}":
            depth -= 1
    return depth == 0


def transitive_dependencies(graph: dict, identifier: str, *, reverse: bool = False, max_depth: int | None = None) -> dict:
    """Find reachable graph nodes; includes shortest provenance paths."""
    ids = {n["id"] for n in graph["nodes"]}
    if identifier not in ids:
        raise ValueError(f"Symbol not indexed: {identifier}")
    links = defaultdict(list)
    for e in graph["edges"]:
        src, dst = (e["target"], e["source"]) if reverse else (e["source"], e["target"])
        links[src].append((dst, e))
    seen = {identifier}
    queue = deque([(identifier, 0)])
    result = []
    while queue:
        current, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for target, edge in sorted(links[current], key=lambda x: x[0]):
            if target in seen:
                continue
            seen.add(target)
            result.append({"node": target, "depth": depth + 1, "via": edge})
            queue.append((target, depth + 1))
    return {"root": identifier, "direction": "reverse" if reverse else "forward", "reachable": result}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Index CK3 script/GUI/GFX/localization dependencies; read only")
    parser.add_argument("--vanilla-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Graph JSON, OUTSIDE vanilla root")
    parser.add_argument("--version", default="unspecified")
    parser.add_argument("--query", default=None, help="Optional symbol id: activity:activity_camp_party")
    parser.add_argument("--reverse", action="store_true", help="Reverse impact query")
    parser.add_argument("--depth", type=int, default=None)
    args = parser.parse_args(argv)
    root = args.vanilla_root.resolve(strict=True)
    out = args.output.resolve()
    if args.depth is not None and args.depth < 0:
        parser.error("--depth must be non-negative")
    if out == root or out.is_relative_to(root):
        parser.error("Output may not be placed inside the source game directory")
    if out.exists():
        parser.error("Output exists; refusing to overwrite")
    graph = scan(root, version=args.version)
    if args.query:
        graph["query"] = transitive_dependencies(graph, args.query, reverse=args.reverse, max_depth=args.depth)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "summary": graph["summary"], "status": graph["status"]}, indent=2))


if __name__ == "__main__":
    main()
