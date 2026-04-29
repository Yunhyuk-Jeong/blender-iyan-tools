# blender-mochi-bone-cleaner

Blender addon for classifying and cleaning retargeted or generated bones.

## Packaging

Create an installable Blender ZIP locally:

```bash
python scripts/package_addon.py
```

The archive is written to `dist/` and keeps the addon folder at the ZIP root, which is the layout Blender expects.

## GitHub Actions

This repository includes [`.github/workflows/package-addon.yml`](G:\GitHub\blender-mochi-bone-cleaner\.github\workflows\package-addon.yml).

- Push to `main` or `master`: build the ZIP and upload it as a workflow artifact.
- Push a tag like `v1.0.1`: build the ZIP, upload the artifact, and attach the ZIP to a GitHub Release.
- Run manually with `workflow_dispatch` when needed.
