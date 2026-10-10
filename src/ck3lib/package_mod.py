"""v0.7: package a v0.6 fragment with pinned localization/GFX adapters.

Input is always read-only. Output is a brand-new mod directory. This is
structural packaging, NOT proof the mod works with the CK3 runtime.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .composer import CompositionError, tokenize, apply_edits, confined_path, git_blob_sha
from .wiring import _read_pinned, EVENT_PATH, MAX_SOURCE_BYTES

LOC_SOURCE = re.compile(r"localization/([a-z_]+)/([A-Za-z0-9_/-]+)_l_\1\.yml\Z")
LOC_LINE = re.compile(r'^(\s*)([A-Za-z0-9_.-]+)(:[0-9]*\s+"(?:[^"\\]|\\.)*"(?:\s*#.*)?)\s*$')
LOC_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
LOCAL_TARGET = re.compile(r"cklib_[A-Za-z0-9_.-]+\Z")
ASSET_SOURCE = re.compile(r"gfx/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:dds|png|tga|jpg)\Z")
ASSET_TARGET = re.compile(r"gfx/cklib/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:dds|png|tga|jpg)\Z")
MOD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{2,64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
SUPPORTED = re.compile(r"[0-9]+\.[0-9]+\.\*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_ASSET_BYTES = 20_000_000
MAX_TOTAL_BYTES = 50_000_000
SAFE_LOC_FIELDS = frozenset({"title", "desc", "name", "text", "tooltip", "description", "custom_tooltip"})


def _checked_source(root: Path, rel: str, sha: str, matcher: re.Pattern, size: int) -> bytes:
    if not isinstance(rel, str) or not matcher.fullmatch(rel) or not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise CompositionError("Source path or pinned SHA is invalid")
    parts = Path(rel).parts
    if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
        raise CompositionError("Source symlink forbidden")
    p = confined_path(root, rel)
    if not p.is_file() or p.stat().st_size > size:
        raise CompositionError("Source missing or oversized")
    data = p.read_bytes()
    if git_blob_sha(data) != sha:
        raise CompositionError("Pinned source SHA mismatch")
    return data


def _fragment_files(fragment: Path, vanilla: Path) -> tuple[list[str], dict[str, bytes]]:
    if fragment == vanilla or fragment.is_relative_to(vanilla) or vanilla.is_relative_to(fragment):
        raise CompositionError("Fragment cannot overlap vanilla")
    p = fragment / "wiring-report.json"
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 100_000:
        raise CompositionError("Missing or unsafe v0.6 wiring report")
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise CompositionError("Invalid wiring report") from exc
    if (r.get("version") != 1 or r.get("status") != "STATIC_LINKED_REVIEW_REQUIRED"
        or r.get("game_validated") is not False or r.get("changes_vanilla") is not False
        or r.get("is_complete_mod") is not False):
        raise CompositionError("Unexpected v0.6 report status")
    rels = r.get("files")
    if (not isinstance(rels, list) or len(rels) != 3 or len(set(map(str, rels))) != 3
        or sum(bool(EVENT_PATH.fullmatch(x)) for x in rels if isinstance(x, str)) != 1
        or sum(bool(re.fullmatch(r"common/activities/activity_types/cklib_[a-z0-9_]+\.txt", x)) for x in rels if isinstance(x, str)) != 1
        or sum(bool(re.fullmatch(r"common/on_action/cklib_[a-z0-9_]+\.txt", x)) for x in rels if isinstance(x, str)) != 1):
        raise CompositionError("Unexpected fragment file manifest")
    actual_paths = set()
    for f in fragment.rglob("*"):
        if f.is_symlink():
            raise CompositionError("Fragment symlink forbidden")
        if f.is_file():
            actual_paths.add(f.relative_to(fragment).as_posix())
    if actual_paths != set(rels) | {"wiring-report.json"}:
        raise CompositionError("Fragment contains unexpected or missing files")
    artifacts = {}
    for rel in rels:
        f = confined_path(fragment, rel)
        if not f.is_file() or f.stat().st_size > MAX_SOURCE_BYTES:
            raise CompositionError("Fragment file missing or oversized")
        data = f.read_bytes()
        try:
            tokenize(data.decode("utf-8-sig"))
        except (UnicodeError, ValueError) as exc:
            raise CompositionError("Invalid fragment script") from exc
        artifacts[rel] = data
    return rels, artifacts


def _loc_keys(data: bytes, language: str, renamed: dict[str, str]) -> list[str]:
    if not data.startswith(b"\xef\xbb\xbf"):
        raise CompositionError("Source CK3 localization requires a UTF-8 BOM")
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeError as exc:
        raise CompositionError("Invalid UTF-8 localization") from exc
    if not lines or lines[0].strip() != f"l_{language}:":
        raise CompositionError("Localization language header mismatch")
    found = {}
    for line in lines[1:]:
        match = LOC_LINE.fullmatch(line)
        if match:
            key = match.group(2)
            if key in found:
                raise CompositionError("Duplicate source localization key")
            found[key] = f" {renamed.get(key, key)}{match.group(3)}"
        elif line.strip() and not line.lstrip().startswith("#"):
            # We don't need to understand unrelated lines, but do not ignore a requested key.
            if any(re.match(r"^\s*" + re.escape(k) + r"\s*:", line) for k in renamed):
                raise CompositionError("Unsupported localization entry")
    missing = set(renamed) - set(found)
    if missing:
        raise CompositionError("Requested localization keys absent: " + ", ".join(sorted(missing)))
    return [found[k] for k in renamed]


def _rewrite_scripts(artifacts: dict[str, bytes], loc_map: dict[str, str], gfx_map: dict[str, str]):
    counts = {"localization": {k: 0 for k in loc_map}, "gfx": {k: 0 for k in gfx_map}}
    output = {}
    for path, data in artifacts.items():
        text = data.decode("utf-8-sig")
        ts = tokenize(text)
        edits = []
        for i, token in enumerate(ts):
            field = ts[i-2].text if i >= 2 and ts[i-1].text == "=" else None
            if token.text in loc_map:
                if field not in SAFE_LOC_FIELDS:
                    raise CompositionError("Localization key in unsafe script context: " + token.text)
                edits.append((token.start, token.end, loc_map[token.text]))
                counts["localization"][token.text] += 1
            elif token.text in gfx_map:
                raise CompositionError("Unquoted GFX path requires manual review")
            elif token.text.startswith('"'):
                # Only an exact quoted texture path is rewritten; preserve all other text.
                literal = token.text[1:-1]
                if literal in gfx_map:
                    edits.append((token.start, token.end, '"' + gfx_map[literal] + '"'))
                    counts["gfx"][literal] += 1
                elif any(re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(k) + r"(?![A-Za-z0-9_.-])", literal) for k in loc_map):
                    raise CompositionError("Quoted localization reference requires review")
        modified = apply_edits(text, edits)
        output[path] = modified.encode("utf-8-sig")
    for kind, vals in counts.items():
        unused = [k for k, n in vals.items() if n == 0]
        if unused:
            raise CompositionError("Unused " + kind + " rewrite(s): " + ", ".join(sorted(unused)))
    return output, counts


def package(recipe: dict, vanilla_root: Path, wired_fragment: Path, output_root: Path) -> dict:
    """Produce a new mod folder; all inputs validated before any output is created."""
    if not isinstance(recipe, dict) or set(recipe) != {"version", "name", "mod_version", "supported_version", "localizations", "gfx"} or recipe.get("version") != 1:
        raise CompositionError("Invalid v0.7 package recipe")
    name, version, supported = (recipe[k] for k in ("name", "mod_version", "supported_version"))
    if (not isinstance(name, str) or not MOD_NAME.fullmatch(name)
        or not isinstance(version, str) or not VERSION.fullmatch(version)
        or not isinstance(supported, str) or not SUPPORTED.fullmatch(supported)):
        raise CompositionError("Invalid CK3 mod descriptor field")
    locs, gfxs = recipe["localizations"], recipe["gfx"]
    if not isinstance(locs, list) or not isinstance(gfxs, list) or len(locs) > 12 or len(gfxs) > 20:
        raise CompositionError("Invalid localization or GFX manifest")
    vanilla, fragment = vanilla_root.resolve(strict=True), wired_fragment.resolve(strict=True)
    if not vanilla.is_dir() or not fragment.is_dir():
        raise CompositionError("Invalid vanilla or fragment directory")
    file_list, fragments = _fragment_files(fragment, vanilla)
    lang_output = {}
    global_loc_map = {}
    for item in locs:
        if not isinstance(item, dict) or set(item) != {"source_path", "source_git_blob_sha", "language", "renames"}:
            raise CompositionError("Invalid localization item")
        rel, sha, language, renames = (item[k] for k in ("source_path", "source_git_blob_sha", "language", "renames"))
        match = LOC_SOURCE.fullmatch(rel) if isinstance(rel, str) else None
        if not match or language != match.group(1) or not isinstance(renames, dict) or not renames:
            raise CompositionError("Invalid localization source/language/map")
        for old, new in renames.items():
            if (not isinstance(old, str) or not LOC_KEY.fullmatch(old)
                or not isinstance(new, str) or not LOCAL_TARGET.fullmatch(new)
                or old == new or (old in global_loc_map and global_loc_map[old] != new)):
                raise CompositionError("Invalid or inconsistent localization key mapping")
            global_loc_map[old] = new
        data = _checked_source(vanilla, rel, sha, LOC_SOURCE, MAX_SOURCE_BYTES)
        parsed = _loc_keys(data, language, renames)
        lang_output.setdefault(language, []).extend(parsed)
    if len(set(global_loc_map.values())) != len(global_loc_map):
        raise CompositionError("Localization target-key collision")
    for lang, lines in lang_output.items():
        keys = [LOC_LINE.fullmatch(line).group(2) for line in lines]
        if len(keys) != len(set(keys)):
            raise CompositionError("Duplicate generated localization key")

    gfx_map, asset_out, gfx_manifest = {}, {}, []
    for item in gfxs:
        if not isinstance(item, dict) or set(item) not in ({"mode", "source_path", "source_git_blob_sha"},
                                                          {"mode", "source_path", "source_git_blob_sha", "target_path"}):
            raise CompositionError("Invalid GFX asset item")
        mode, rel, sha = item["mode"], item["source_path"], item["source_git_blob_sha"]
        if mode not in ("reference", "clone") or not isinstance(rel, str) or not ASSET_SOURCE.fullmatch(rel):
            raise CompositionError("Invalid GFX source or mode")
        data = _checked_source(vanilla, rel, sha, ASSET_SOURCE, MAX_ASSET_BYTES)
        if mode == "clone":
            target = item.get("target_path")
            if not isinstance(target, str) or not ASSET_TARGET.fullmatch(target) or target == rel:
                raise CompositionError("Unsafe cloned GFX path")
            if rel in gfx_map or target in asset_out:
                raise CompositionError("GFX rewrite or destination collision")
            gfx_map[rel] = target
            asset_out[target] = data
        elif "target_path" in item:
            raise CompositionError("Reference-only GFX must not declare a target")
        gfx_manifest.append({"mode": mode, "source_path": rel, "source_git_blob_sha": sha,
                             "target_path": item.get("target_path")})
    scripts, rewritten = _rewrite_scripts(fragments, global_loc_map, gfx_map)
    for lang, lines in lang_output.items():
        if lines:
            rel = f"localization/{lang}/cklib_generated_l_{lang}.yml"
            scripts[rel] = ("\ufeffl_" + lang + ":\n" + "\n".join(lines) + "\n").encode("utf-8")
    scripts.update(asset_out)
    scripts["descriptor.mod"] = (
        f'name="{name}"\nversion="{version}"\nsupported_version="{supported}"\n'
    ).encode("utf-8")
    report = {
        "version": 1, "status": "PACKAGED_UNVALIDATED", "game_validated": False,
        "is_complete_mod": False, "changes_vanilla": False,
        "wiring_files": file_list, "generated_files": sorted(scripts),
        "source_fragment_files": {p: git_blob_sha(data) for p, data in fragments.items()},
        "localization_key_mapping": global_loc_map,
        "rewritten_references": rewritten, "gfx_sources": gfx_manifest,
        "warnings": ["Structural package only; CK3 engine, GUI, DLC, runtime and load order unverified.",
                     "External references retained by v0.6 may require additional dependencies.",
                     "For installation use the Paradox launcher to configure a matching .mod entry.",
                     "Original vanilla resources must be supplied from a lawful local installation."],
    }
    scripts["cklib-package-report.json"] = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if sum(len(v) for v in scripts.values()) > MAX_TOTAL_BYTES:
        raise CompositionError("Generated package exceeds total size limit")
    dest = output_root.absolute()
    parent = dest.parent.resolve(strict=True)
    if (dest.exists() or dest.is_symlink() or dest.parent != parent
        or dest == vanilla or dest.is_relative_to(vanilla) or vanilla.is_relative_to(dest)
        or dest == fragment or dest.is_relative_to(fragment) or fragment.is_relative_to(dest)):
        raise CompositionError("Output must be a new isolated directory")
    try:
        dest.mkdir()
        for rel, data in scripts.items():
            p = confined_path(dest, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    except Exception:
        if dest.exists():
            shutil.rmtree(dest)
        raise
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Package a v0.6 CK3 fragment with pinned localization and GFX")
    p.add_argument("--recipe", type=Path, required=True)
    p.add_argument("--vanilla-root", type=Path, required=True)
    p.add_argument("--wired-fragment", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    report = package(json.loads(args.recipe.read_text(encoding="utf-8-sig")), args.vanilla_root,
                     args.wired_fragment, args.output)
    print(json.dumps({"status": report["status"], "files": report["generated_files"]}, indent=2))


if __name__ == "__main__":
    main()
