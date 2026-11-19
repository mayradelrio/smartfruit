"""Create the owner's portable VS Code package without environment or credentials."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_project(output, include_originals=False):
    root = Path(__file__).resolve().parents[1]
    selected = set()
    for directory in (
        "src",
        "tests",
        "docs",
        "templates",
        "examples",
        "legacy",
        "hosting",
        "scripts",
        ".vscode",
    ):
        for path in (root / directory).rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.name != "agrofruit-logo.png"
                and not any(
                    part in ("__pycache__", ".pytest_cache", "node_modules")
                    or part.endswith(".egg-info")
                    for part in path.parts
                )
                and path.relative_to(root).as_posix() != "docs/source_inventory.json"
            ):
                selected.add(path.relative_to(root))
    for name in (
        "README.md",
        "SmartFruit.code-workspace",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        ".gitignore",
        ".env.example",
        "data/README.md",
        "notebooks/README.md",
    ):
        selected.add(Path(name))
    if include_originals:
        for original in json.loads((root / "docs/source_inventory.json").read_text())["originals"]:
            path = root / original["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != original["sha256"]:
                raise ValueError("Original modified: " + original["original_name"])
            selected.add(Path(original["path"]))
    manifest = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for relative in sorted(selected):
            data = (root / relative).read_bytes()
            manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
            archive.writestr("SmartFruit/" + relative.as_posix(), data)
        archive.writestr("SmartFruit/PACKAGE_SHA256.json", json.dumps(manifest, indent=2) + "\n")
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    return {
        "path": str(output),
        "files": len(manifest),
        "includes_originals": include_originals,
        "bytes": output.stat().st_size,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-originals", action="store_true")
    args = parser.parse_args()
    print(json.dumps(package_project(args.output.resolve(), args.include_originals)))
