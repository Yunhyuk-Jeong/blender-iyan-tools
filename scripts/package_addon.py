from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import tomllib
import zipfile


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ADDON_DIR = REPO_ROOT / "iyan_kim_tools"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Blender extension ZIP from a manifest-based add-on."
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
    parser.add_argument(
        "--builder",
        choices=("auto", "blender", "python"),
        default="auto",
        help="Use Blender's extension builder when available, or the Python fallback.",
    )
    parser.add_argument(
        "--blender-executable",
        type=pathlib.Path,
        help="Path to blender.exe when Blender is not available on PATH.",
    )
    return parser.parse_args()


def read_manifest(manifest_file: pathlib.Path) -> dict:
    with manifest_file.open("rb") as handle:
        manifest = tomllib.load(handle)

    required_fields = (
        "schema_version",
        "id",
        "version",
        "name",
        "tagline",
        "maintainer",
        "type",
        "blender_version_min",
        "license",
    )
    missing = [field for field in required_fields if not manifest.get(field)]
    if missing:
        raise ValueError(
            f"Missing required manifest field(s) in {manifest_file}: {', '.join(missing)}"
        )
    if manifest["schema_version"] != "1.0.0":
        raise ValueError(f"Unsupported manifest schema_version in {manifest_file}")
    if manifest["type"] != "add-on":
        raise ValueError(f"Expected add-on manifest type in {manifest_file}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]):
        raise ValueError(f"Manifest version must use MAJOR.MINOR.PATCH in {manifest_file}")
    if manifest["tagline"].endswith((".", "!", "?")):
        raise ValueError(f"Manifest tagline must not end with punctuation in {manifest_file}")
    if not all(
        isinstance(license_id, str) and license_id.startswith("SPDX:")
        for license_id in manifest["license"]
    ):
        raise ValueError(f"Manifest licenses must use SPDX identifiers in {manifest_file}")

    return manifest


def validate_source_dir(addon_dir: pathlib.Path) -> tuple[pathlib.Path, dict]:
    addon_dir = addon_dir.resolve()
    init_file = addon_dir / "__init__.py"
    manifest_file = addon_dir / "blender_manifest.toml"

    if not addon_dir.is_dir():
        raise FileNotFoundError(f"Addon directory not found: {addon_dir}")
    if not init_file.is_file():
        raise FileNotFoundError(f"Addon entry point not found: {init_file}")
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Extension manifest not found: {manifest_file}")

    manifest = read_manifest(manifest_file)
    return addon_dir, manifest


def output_path_for(dist_dir: pathlib.Path, manifest: dict) -> pathlib.Path:
    return dist_dir / f"{manifest['id']}-{manifest['version']}.zip"


def find_blender(blender_executable: pathlib.Path | None) -> str | None:
    if blender_executable is not None:
        blender_path = blender_executable.resolve()
        if not blender_path.is_file():
            raise FileNotFoundError(f"Blender executable not found: {blender_path}")
        return str(blender_path)
    return shutil.which("blender")


def build_with_blender(
    addon_dir: pathlib.Path,
    dist_dir: pathlib.Path,
    manifest: dict,
    blender_executable: pathlib.Path | None,
) -> pathlib.Path:
    blender = find_blender(blender_executable)
    if blender is None:
        raise FileNotFoundError("Blender executable was not found on PATH")

    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_path_for(dist_dir, manifest)

    subprocess.run(
        [
            blender,
            "--command",
            "extension",
            "build",
            "--source-dir",
            str(addon_dir),
            "--output-filepath",
            str(zip_path),
        ],
        check=True,
    )
    return zip_path


def build_with_python(
    addon_dir: pathlib.Path, dist_dir: pathlib.Path, manifest: dict
) -> pathlib.Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_path_for(dist_dir, manifest)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(addon_dir.rglob("*")):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts:
                continue
            archive.write(path, arcname=path.relative_to(addon_dir))

    return zip_path


def build_zip(
    addon_dir: pathlib.Path,
    dist_dir: pathlib.Path,
    builder: str,
    blender_executable: pathlib.Path | None,
) -> pathlib.Path:
    addon_dir, manifest = validate_source_dir(addon_dir)
    dist_dir = dist_dir.resolve()

    if builder == "blender":
        return build_with_blender(addon_dir, dist_dir, manifest, blender_executable)
    if builder == "auto" and find_blender(blender_executable) is not None:
        return build_with_blender(addon_dir, dist_dir, manifest, blender_executable)
    return build_with_python(addon_dir, dist_dir, manifest)


def main() -> int:
    args = parse_args()
    zip_path = build_zip(
        args.addon_dir, args.dist_dir, args.builder, args.blender_executable
    )
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
