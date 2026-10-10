"""Conservative read-only integration impact plan for indexed CK3 components.

A plan is NOT authorization to clone/overwrite game definitions. Missing graph
edges never prove that a mechanism is safe to compose or isolated from vanilla.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .indexer import transitive_dependencies


def assess(graph: dict[str, Any], component: str) -> dict[str, Any]:
    """Prepare a review dossier with transitive dependencies and risk evidence.

    No scripts or GFX are copied. All paths are references to already-indexed
    game source and may be incomplete. Only node IDs and evidence are exported.
    """
    if graph.get("schema_version") != 1 or graph.get("status") != "STATIC_PARTIAL_NOT_GAME_VALIDATED":
        raise ValueError("Unsupported or untrusted graph format")
    nodes = {item["id"]: item for item in graph["nodes"]}
    if component not in nodes or nodes[component]["kind"] == "file":
        raise ValueError(f"Component not indexed: {component}")
    reachable = transitive_dependencies(graph, component)["reachable"]
    closure = {component, *(item["node"] for item in reachable)}
    files: dict[str, dict] = {}
    for key in sorted(closure):
        entry = nodes[key]
        for definition in entry.get("definitions", []):
            path = definition["path"]
            source = nodes.get(f"file:{path}", {})
            files[path] = {"path": path, "kind": "source_definition",
                           "sha256": source.get("sha256"), "read_only": True}
        if entry["kind"] == "file" and entry.get("path"):
            path = entry["path"]
            if path not in files:
                files[path] = {"path": path, "kind": "referenced_asset_or_file",
                               "sha256": entry.get("sha256"), "read_only": True}
    unresolved = [v for v in graph.get("unresolved", []) if v["source"] in closure]
    dynamic = [v for v in graph.get("dynamic_references", []) if v["source"] in closure]
    heuristic = [e for e in graph["edges"] if e["source"] in closure and
                 e["target"] in closure and e["confidence"] != "exact"]
    problem_paths = set(files)
    warnings = [w for w in graph.get("warnings", [])
                if w.get("symbol") in closure or w.get("path") in problem_paths]
    # Buildability cannot be declared safe by static analysis alone. No game
    # validation and no engine-hardcoded semantics are available here.
    blockers = any(w.get("reason") in ("duplicate_identifier", "unverified_asset", "parse_failure")
                   for w in warnings) or bool(unresolved)
    status = "STATIC_BLOCKERS_OR_GAPS" if blockers else "REVIEW_REQUIRED"
    return {
        "plan_version": 1,
        "component": component,
        "source_version_label": graph.get("source_version_label", "unspecified"),
        "status": status,
        "game_validated": False,
        "generates_mod": False,
        "reason": "Graph coverage is partial; runtime, DLC and GUI integration remain unverified.",
        "dependency_nodes": sorted(closure - {component}),
        "referenced_files": [files[k] for k in sorted(files)],
        "unresolved": unresolved,
        "dynamic_references": dynamic,
        "heuristic_edges": heuristic,
        "warnings": warnings,
        "review_requirements": [
            "Verify CK3 installation build and applicable DLC, independent of the user-supplied version label.",
            "Review all unresolved and heuristic references, including engine-dispatched hooks.",
            "Verify referenced assets, GUI bindings, localization and event lifecycle in game.",
            "Decide per component whether to reuse, extend, clone with namespace, or implement an explicit adapter.",
            "Do not override vanilla files or redistribute proprietary assets without separate authorization."
        ],
        "summary": {"dependency_nodes": len(closure) - 1, "referenced_files": len(files),
                    "unresolved": len(unresolved), "dynamic_references": len(dynamic),
                    "heuristic_edges": len(heuristic), "warnings": len(warnings)}
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Produce a read-only CK3 component integration review plan")
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--component", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    graph_path, output = args.graph.resolve(strict=True), args.output.resolve()
    if output == graph_path or output.exists():
        parser.error("Output must be new and cannot overwrite the input graph")
    try:
        report = assess(json.loads(graph_path.read_text(encoding="utf-8")), args.component)
    except (ValueError, KeyError, TypeError) as err:
        parser.error(str(err))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": report["status"], "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
