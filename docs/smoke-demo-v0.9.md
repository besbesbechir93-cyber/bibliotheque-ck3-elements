# v0.9 — First CK3 load-test artifact (decision → event)

This is a **small standalone test mod**, not yet a cloned activity or proof of runtime success. It adds two new `cklib_` script definitions, translations, and a launcher manifest. There is no `replace_path`, no override of vanilla identifiers, and no redistributed game assets. The decision illustration **references** the existing vanilla path `gfx/interface/illustrations/decisions/decision_misc.dds` (confirmed in the 1.20.0.3 mirror).

## Reproducible build

From the repository root (Python standard library):

```sh
PYTHONPATH=src python -m ck3lib.smoke_demo --recipe examples/smoke-demo-v0.9.json --output /tmp/cklib-smoke-install
PYTHONPATH=src python -m ck3lib.validator --mod-dir /tmp/cklib-smoke-install/cklib_smoke_v09 --report-out /tmp/cklib-smoke-validation.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

The directory given to `--output` **must not exist**. `--vanilla-root /path/to/game` can additionally block accidental writes inside the game folder and let the validator check real vanilla art paths. No source game files are read or changed by this builder.

## Install the demo (Windows)

Copy the generated `cklib_smoke_v09` directory **and** the sibling `cklib_smoke_v09.mod` file into:

`Documents/Paradox Interactive/Crusader Kings III/mod/`

The launcher descriptor refers to `path="mod/cklib_smoke_v09"`. If the Documents folder is redirected by OneDrive, use the CK3 folder actually used by the launcher. Use an isolated playset and disable other mods during this first test.

## Human runtime test (required)

1. Enable **CKLib v0.9 Smoke Test** in the launcher. Start CK3 1.20.x.
2. Load a throwaway save and select an adult playable character.
3. Open Decisions. Verify the **CKLib integration test** decision appears (French: **Test d'intégration CKLib**).
4. Activate it. Verify the **CKLib test event** is displayed and the Continue button works.
5. Record game version, game language, screenshot/observation, the test time, and whether the game log references `cklib_smoke_v09` errors.
6. Analyze the logs using `python -m ck3lib.validator --log-dir <CK3/logs> ...`, and share log excerpts if CK3 reports an error.

**Not tested in-game in this release.** A report with zero static errors only says the limited checks passed. The decision/event path is a controlled first test of the mod loader; an activity clone will be addressed after a successful real-game smoke test.

## Dependency / asset policy

The demo's code and original translations are part of CKLib and can be included in GitHub. It references but **does not copy** the vanilla illustration. The bundle has independent names and paths, and does not overwrite vanilla definitions. Future adapters will integrate vanilla events, UI bindings, and GFX with explicit provenance and compatibility checks.
