# Studio Iyan Tools

`Studio Iyan Tools` is a unified Blender addon suite that bundles multiple production helpers under a single sidebar tab.

The current suite contains:

- `Mochi Bone Cleaner`
- `Mesh Cleanup`
- `UV Validation`

The suite installs as one addon and appears in one sidebar category:

- `View3D > Sidebar > Studio Iyan`

Current unified addon version: `2.0.2`

## Why This Structure

This repository previously grew as separate addons with separate sidebar categories. That scales poorly in Blender because each tool adds another visible tab or another independent addon entry. The unified package solves that by turning the repo into a single installable tool suite:

- one install target
- one sidebar tab
- one top-level parent panel
- one place to add future Studio Iyan tools

## UI Architecture

The unified addon uses:

- Sidebar category: `Studio Iyan`
- Root panel: `Studio Iyan Tools`
- Child panels:
  - `Mochi Bone Cleaner`
  - `Mesh Cleanup`
  - `UV Validation`

This gives you the “one tab with subtools” structure Blender supports well.

## Repository Structure

```text
iyan_kim_tools/
  blender_manifest.toml    Blender 4.2+ extension manifest
  __init__.py              Unified addon entry point
  config.py                Shared UI constants
  mochi_bone_cleaner.py    Bone analysis and cleanup tool
  mesh_cleanup.py          Mesh cleanup scanner/fixer
  uv_validation.py         UV validation scanner

scripts/
  package_addon.py         Packaging script

.github/workflows/
  package-addon.yml        GitHub Actions packaging workflow
```

## Tool Overview

### Mochi Bone Cleaner

Purpose:

- classify generated or retargeted leftover bones
- keep weighted or protected bones
- review ambiguous structural bones
- delete only `SAFE_DELETE` results

Core behavior:

- tokenizes bone names safely
- detects helper/generated naming patterns
- compares against optional reference armatures
- scans actual weight usage on meshes driven by the target armature
- supports review overrides before deletion

### Mesh Cleanup

Purpose:

- detect loose geometry
- find degenerate faces
- detect fully overlapping duplicate faces
- detect duplicate verts
- provide guarded cleanup operators

Core behavior:

- scan and select issue groups
- navigate duplicate-face groups
- guarded delete for keep-face protection
- quick-fix path for common cleanup flows
- optional viewport overlay for scan stats

### UV Validation

Purpose:

- detect zero-area or collapsed UV faces
- detect tiny or thin UV islands
- report missing UV-map cases across targets

Core behavior:

- active or selected-object scan modes
- configurable thresholds
- result selection in edit mode
- per-run summary counters

## Installation

### Install from ZIP

1. Build or download the packaged ZIP.
2. In Blender 4.2 or newer, open the extension preferences.
3. Click `Install from Disk...`.
4. Select the ZIP file.
5. Enable `Studio Iyan Tools`.

### Local Build

Build the installable Blender ZIP locally:

```bash
python scripts/package_addon.py
```

When Blender is available on `PATH`, the script uses Blender's official extension builder. To force the fallback builder:

```bash
python scripts/package_addon.py --builder python
```

To use a Blender executable that is not on `PATH`:

```bash
python scripts/package_addon.py --builder blender --blender-executable "E:\SteamLibrary\steamapps\common\Blender\blender.exe"
```

Expected output:

```text
dist/iyan_kim_tools-2.0.2.zip
```

The ZIP keeps `blender_manifest.toml` and `__init__.py` at the archive root, which Blender expects for extension packages.

## GitHub Actions Packaging

This repository includes `.github/workflows/package-addon.yml`.

- Push to `main` or `master`:
  - build the unified addon ZIP
  - upload it as a workflow artifact
- Push a tag like `v2.0.0`:
  - build the ZIP
  - attach it to a GitHub Release
- `workflow_dispatch`:
  - run packaging manually

## Data Flow

### Suite Level

1. Blender enables `iyan_kim_tools`
2. The root addon registers:
   - suite parent panel
   - Mochi tool
   - Mesh Cleanup tool
   - UV Validation tool
3. All tool panels render under the same `Studio Iyan` sidebar category

### Mochi Bone Cleaner

1. User selects target armature and optional references
2. Analyzer builds:
   - weighted bone cache
   - reference token indexes
3. Each bone is classified into:
   - `SAFE_DELETE`
   - `REVIEW`
   - `KEEP`
   - `PROTECTED`
4. User reviews results and applies overrides
5. Delete operator removes only `SAFE_DELETE` bones

### Mesh Cleanup

1. Tool reads the active mesh in edit mode
2. Scanner computes:
   - loose geometry
   - degenerate faces
   - duplicate-face groups
   - duplicate verts
3. Selection/fix operators act on those result sets
4. Overlay and stats reflect the last scan

### UV Validation

1. Tool resolves active or selected mesh targets
2. For each mesh, it reads the active UV layer
3. It marks:
   - bad faces
   - bad islands
   - no-UV objects
4. Results are written back into scene counters

## What Changed in 2.0.0

- Introduced the unified addon package: `iyan_kim_tools`
- Removed the old standalone addon directories from the active codebase
- Moved the UI to a single `Studio Iyan` sidebar category
- Reframed each tool as a subpanel under one parent panel
- Kept the improved Mochi Bone Cleaner analysis logic from `1.1.0`
- Added the Blender 4.2+ extension manifest
- Switched packaging to build a manifest-based extension ZIP
- Added CI validation for the suite source files and manifest before packaging

## Analysis Notes

The main structural issue was distribution and UI fragmentation. If future tools kept shipping as separate addons, you would end up with:

- multiple addon entries
- multiple sidebar categories
- duplicated registration patterns
- no stable place for shared UI conventions

The new unified package gives you a stable base for future tools without multiplying addon entries or sidebar tabs.

## Limitations

- Mesh Cleanup and UV Validation were integrated as suite modules, not fully refactored into smaller internal files yet.
- Blender runtime verification still needs to happen inside Blender for operator behavior, overlay behavior, and panel layout.

## Development Checks

Syntax-level verification without writing bytecode:

```bash
python -c "import ast, pathlib, tomllib; files=['iyan_kim_tools/__init__.py','iyan_kim_tools/config.py','iyan_kim_tools/mochi_bone_cleaner.py','iyan_kim_tools/mesh_cleanup.py','iyan_kim_tools/uv_validation.py','scripts/package_addon.py']; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8')) for f in files]; tomllib.loads(pathlib.Path('iyan_kim_tools/blender_manifest.toml').read_text(encoding='utf-8'))"
```

Package build:

```bash
python scripts/package_addon.py
```

Blender extension validation, when Blender is available on `PATH`:

```bash
blender --command extension validate dist/iyan_kim_tools-2.0.2.zip
```
