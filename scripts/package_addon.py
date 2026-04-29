from __future__ import annotations

import argparse
import pathlib
import re
import zipfile


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ADDON_DIR = REPO_ROOT / "iyan_mochi_bone_cleaner"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Blender installable ZIP for the addon."
    )
    parser.add_argument(
        "--addon-dir",
        type=pathlib.Path,
        default=DEFAULT_ADDON_DIR,
        help="Path to the addon package directory.",
    )
    parser.add_argument(
        "--dist-dir",
        type=pathlib.Path,
        default=DEFAULT_DIST_DIR,
        help="Directory where the ZIP artifact will be created.",
    )
    return parser.parse_args()


def extract_version(init_file: pathlib.Path) -> str:
    content = init_file.read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*\(([^)]+)\)', content)
    if not match:
        raise ValueError(f"Could not find addon version in {init_file}")

    parts = [part.strip() for part in match.group(1).split(",") if part.strip()]
    if not parts:
        raise ValueError(f"Parsed empty version tuple in {init_file}")

    return ".".join(parts)


def build_zip(addon_dir: pathlib.Path, dist_dir: pathlib.Path) -> pathlib.Path:
    addon_dir = addon_dir.resolve()
    init_file = addon_dir / "__init__.py"

    if not addon_dir.is_dir():
        raise FileNotFoundError(f"Addon directory not found: {addon_dir}")
    if not init_file.is_file():
        raise FileNotFoundError(f"Addon entry point not found: {init_file}")

    version = extract_version(init_file)
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"{addon_dir.name}-v{version}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(addon_dir.rglob("*")):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts:
                continue
            archive.write(path, arcname=path.relative_to(addon_dir.parent))

    return zip_path


def main() -> int:
    args = parse_args()
    zip_path = build_zip(args.addon_dir, args.dist_dir)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
