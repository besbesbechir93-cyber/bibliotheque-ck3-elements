"""Conservative CK3 dependency adapter intentions (dry-run ONLY).

No generated Clausewitz/Jomini scripts, no source copies, no filesystem writes
except an explicitly new JSON report through the CLI. No game compatibility
claim follows from this static model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .planner import assess

NAMESPACE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
EVENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\.([0-9]+)$")
POLICIES = frozenset({"reference", "clone", "exclude"})
SUPPORTED_KINDS = frozenset({"activity", "event", "on_action", "gui", "sprite", "localization",
                            "file", "scripted_effect", "scripted_trigger", "script_value",
                            "government", "government_flag", "holding", "building", "domicile",
                            "house_unity", "house_aspiration", "house_relation", "confederation",
                            "tax_slot", "subject_contract", "subject_contract_group", "tax_obligation",
                            "law", "succession_appointment", "succession_election", "great_project",
                            "decision", "modifier", "trait", "domicile_building"})


def _fingerprint(graph: dict[str, Any]) -> str:
    """Bind a recipe to exact indexed metadata, not to a claimed CK3 build."""
    encoded = json.dumps(graph, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _name_for_clone(node: dict[str, Any], namespace: str) -> str:
    kind, name = node["kind"], node.get("name")
    if kind == "file":
        path = node.get("path", "")
        if (not path.startswith("gfx/") or not IDENTIFIER.fullmatch(path.replace("/", "_"))
                or any(part in ("", ".", "..") for part in path.split("/"))
                or not path.lower().endswith((".dds", ".png", ".tga", ".mesh", ".anim", ".texture"))):
            raise ValueError("Only normalized gfx/ paths may be proposed for local asset copies")
        prefix, _, basename = path.rpartition("/")
        return f"{prefix}/cklib_{namespace}_{basename}"
    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
        raise ValueError(f"Unsupported source identifier: {node['id']}")
    if kind == "event":
        match = EVENT.fullmatch(name)
        if not match:
            raise ValueError(f"Unsupported event ID; expected namespace.integer: {name}")
        return f"cklib_{namespace}_{match.group(1)}.{match.group(2)}"
    if kind == "sprite" and name.startswith("GFX_"):
        return f"GFX_cklib_{namespace}_{name[4:]}"
    return f"cklib_{namespace}_{name}"


def _checks_for(kind: str, action: str) -> list[str]:
    if action == "reference":
        return ["Verify the vanilla symbol is available with required DLC and load order."]
    if action == "exclude":
        return ["Prove this dependency can be omitted without changing the desired behavior."]
    checks = ["Implement explicit symbol-level rewrite; no textual search/replace is authorized.",
              "Resolve inbound and outbound references, then validate in game."]
    if kind in {"event", "on_action"}:
        checks += ["Audit event namespace declaration, dispatches and on_action hook integration."]
    if kind == "gui":
        checks += ["Audit runtime datacontexts, widgets, callbacks and template references."]
    if kind == "sprite":
        checks += ["Audit sprite names, .gfx mappings and all consumer widgets."]
    if kind == "file":
        checks += ["Use local authorized asset at build time; never publish proprietary bytes.",
                   "Verify new gfx path and all texture references."]
    if kind == "localization":
        checks += ["Provide translated keys or explicit fallbacks for every supported language."]
    if kind == "activity":
        checks += ["Audit phases, options, events, visuals, DLC conditions, cost and cooldown."]
    return checks


def prepare(graph: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    """Report proposed adapters without cloning or declaring an integration safe.

    Recipe v1: {version:1, component:'kind:name', namespace:'demo',
      graph_sha256:64hex, default_dependency_policy:'reference',
      decisions:{'event:name':'clone', ...}}
    The root is always a clone request. Each dependency defaults to reference.
    """
    if not isinstance(recipe, dict) or set(recipe) != {
            "version", "component", "namespace", "graph_sha256",
            "default_dependency_policy", "decisions"}:
        raise ValueError("Recipe must use exactly the six adapter-v1 keys")
    if type(recipe["version"]) is not int or recipe["version"] != 1:
        raise ValueError("Unsupported adapter recipe version")
    namespace = recipe["namespace"]
    if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
        raise ValueError("Namespace must be lowercase ASCII: [a-z][a-z0-9_]{1,23}")
    if not isinstance(recipe["component"], str):
        raise ValueError("Component must be a string")
    if recipe["graph_sha256"] != _fingerprint(graph):
        raise ValueError("Stale recipe: graph fingerprint mismatch")
    if recipe["default_dependency_policy"] != "reference":
        raise ValueError("Only explicit reference-by-default is supported")
    choices = recipe["decisions"]
    if not isinstance(choices, dict) or not all(isinstance(k, str) and isinstance(v, str) and v in POLICIES
                                                for k, v in choices.items()):
        raise ValueError("Decisions must be a mapping of indexed node IDs to supported actions")
    component = recipe["component"]
    review = assess(graph, component)
    nodes = {node["id"]: node for node in graph["nodes"]}
    closure = {component, *review["dependency_nodes"]}
    unknown = sorted(set(choices) - (closure - {component}))
    if unknown:
        raise ValueError(f"Decisions cannot address root or out-of-closure nodes: {unknown}")
    proposals = []
    proposed_ids: set[str] = set()
    failures = []
    for node_id in sorted(closure):
        node = nodes[node_id]
        kind = node["kind"]
        action = "clone" if node_id == component else choices.get(node_id, "reference")
        target = None
        notes = _checks_for(kind, action)
        if kind not in SUPPORTED_KINDS:
            failures.append({"node": node_id, "reason": "unsupported_node_kind"})
        if action == "clone":
            try:
                target = _name_for_clone(node, namespace)
                new_id = f"{kind}:{target}"
                if new_id in nodes or new_id in proposed_ids:
                    failures.append({"node": node_id, "reason": "proposed_identifier_collision", "target": new_id})
                proposed_ids.add(new_id)
            except ValueError as error:
                failures.append({"node": node_id, "reason": "unresolved_clone_mapping", "details": str(error)})
        proposals.append({"source": node_id, "kind": kind, "action": action,
                          "proposed_identifier": target, "requires_manual_implementation": action != "reference",
                          "review_checks": notes})
    # A cloned dependency is not useful unless calls from all its consumers are
    # redirected. Inbound edges from unrelated nodes remain a compatibility risk.
    clones = {x["source"] for x in proposals if x["action"] == "clone"}
    inbound = sorted([{"source": e["source"], "target": e["target"], "relation": e["relation"],
                       "evidence": e["evidence"]} for e in graph["edges"]
                      if e["target"] in clones and e["source"] not in clones and e["relation"] != "defines"],
                     key=lambda e: (e["target"], e["source"], e["evidence"]["path"], e["evidence"]["line"]))
    # Explicit guard: a requested clone is never assumed to exist until its
    # callsites are audited (especially if consumers reference vanilla IDs).
    if inbound:
        failures.append({"reason": "incoming_vanilla_references_require_review", "count": len(inbound)})
    return {
        "adapter_plan_version": 1,
        "component": component,
        "namespace": namespace,
        "source_graph_sha256": recipe["graph_sha256"],
        "source_version_label": graph.get("source_version_label"),
        "status": "STATIC_BLOCKERS_OR_GAPS" if failures or review["status"] == "STATIC_BLOCKERS_OR_GAPS" else "REVIEW_REQUIRED",
        "game_validated": False,
        "generates_mod": False,
        "changes_vanilla": False,
        "operations": proposals,
        "inbound_cloned_references": inbound,
        "failures": failures,
        "unresolved": review["unresolved"],
        "dynamic_references": review["dynamic_references"],
        "review_requirements": review["review_requirements"] + [
            "Implement each requested clone with a grammar-aware adapter; no auto-rewrite is provided.",
            "Reindex generated content and verify all source-to-clone redirects before execution.",
            "Validate DLC, GUI, GFX and event dispatch in a CK3 game session."
        ],
        "summary": {"operations": len(proposals), "clones_requested": len(clones),
                    "unresolved": len(review["unresolved"]), "dynamic": len(review["dynamic_references"]),
                    "inbound_review": len(inbound), "failures": len(failures)}
    }


def make_recipe(graph: dict[str, Any], component: str, namespace: str) -> dict[str, Any]:
    """Initialize an explicit, conservative recipe bound to the graph digest."""
    if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
        raise ValueError("Invalid namespace")
    assess(graph, component)  # Fail for unindexed components and untrusted graphs.
    return {"version": 1, "component": component, "namespace": namespace,
            "graph_sha256": _fingerprint(graph), "default_dependency_policy": "reference",
            "decisions": {}}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="CK3 adapter dry-run: does not copy files or generate mods")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--init-recipe", action="store_true")
    parser.add_argument("--component")
    parser.add_argument("--namespace")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vanilla-root", type=Path, required=True,
                        help="Protected, immutable CK3 game directory")
    args = parser.parse_args(argv)
    source = args.graph.resolve(strict=True)
    if args.init_recipe:
        if args.recipe or not args.component or not args.namespace:
            parser.error("--init-recipe requires --component and --namespace, without --recipe")
    elif not args.recipe or args.component or args.namespace:
        parser.error("Dry-run requires --recipe, without --component/--namespace")
    recipe_path = args.recipe.resolve(strict=True) if args.recipe else None
    try:
        protected = args.vanilla_root.resolve(strict=True)
    except OSError as error:
        parser.error(str(error))
    if not protected.is_dir():
        parser.error("Vanilla root must be a directory")
    output = args.output.resolve()
    if output.exists() or output in (source, recipe_path) or output.is_relative_to(protected):
        parser.error("Output must be new, outside the game, and cannot overwrite any input")
    try:
        graph = json.loads(source.read_text(encoding="utf-8"))
        if args.init_recipe:
            report = make_recipe(graph, args.component, args.namespace)
        else:
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            report = prepare(graph, recipe)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.init_recipe:
        print(json.dumps({"output": str(output), "recipe_initialized": True}, indent=2))
    else:
        print(json.dumps({"output": str(output), "status": report["status"],
                          "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
