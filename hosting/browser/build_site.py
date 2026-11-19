"""Package the existing Python MVP for private, browser-local Sites hosting."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile


def build(output, runtime_assets, licenses, zoneinfo, project_archive=None):
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    source = root / "src/smartfruit"
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / "runtime"
    runtime.mkdir(exist_ok=True)
    for entry in json.loads((here / "runtime_assets.json").read_text()):
        asset = runtime_assets / entry["file"]
        if hashlib.sha256(asset.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Unexpected runtime asset hash: " + entry["file"])
        shutil.copy2(asset, runtime / entry["file"])
    html = (source / "web/index.html").read_text("utf-8")
    if html.count("<script>") != 1:
        raise ValueError("Expected one UI script to precede with the browser adapter")
    download_directory = output / "downloads"
    if project_archive is not None:
        with ZipFile(project_archive) as archive:
            if archive.testzip() is not None:
                raise ValueError("Project ZIP integrity check failed")
        download_directory.mkdir(exist_ok=True)
        target = download_directory / "SmartFruit_VSCode.zip"
        shutil.copyfile(project_archive, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        (download_directory / "SmartFruit_VSCode.sha256").write_text(
            digest + "  SmartFruit_VSCode.zip\n", "utf-8"
        )
        html = html.replace(
            "<main>",
            '<main>\n<section class="card" aria-labelledby="project-download-title">'
            '<h2 id="project-download-title">Proyecto para Visual Studio Code</h2>'
            '<p>ZIP completo con código, guía de instalación y los adjuntos originales. '
            'Descarga privada para la cuenta propietaria.</p>'
            '<div class="download-links"><a href="/downloads/SmartFruit_VSCode.zip" '
            'download="SmartFruit_VSCode.zip">Descargar proyecto para VS Code (.zip)</a></div>'
            '<p class="hint">Descomprime el archivo y abre LEEME_VSCODE.md para comenzar.</p>'
            '</section>',
            1,
        )
    else:
        # No conservar accidentalmente una entrega privada al construir sin ella.
        for name in ("SmartFruit_VSCode.zip", "SmartFruit_VSCode.sha256"):
            (download_directory / name).unlink(missing_ok=True)
    html = html.replace("<script>", '<script src="/bridge.js"></script>\n<script>', 1)
    (output / "index.html").write_text(html, "utf-8")
    (output / "assets").mkdir(exist_ok=True)
    for asset in ("drafts.js", "field_sources.js", "vision_defaults.js", "vision_capture.js"):
        shutil.copy2(source / "web" / asset, output / "assets" / asset)
    shutil.copy2(source / "resources/branding/agroperu-logo.png", output / "assets/agroperu-logo.png")
    shutil.copy2(here / "bridge.js", output / "bridge.js")
    (output / "python").mkdir(exist_ok=True)
    shutil.copy2(here / "browser_api.py", output / "python/browser_api.py")
    provenance = []
    with ZipFile(output / "python/smartfruit_bundle.zip", "w", ZIP_DEFLATED) as bundle:
        for name in (
            "__init__",
            "vision",
            "image_binding",
            "additional_review",
            "reception",
            "lot_inspection",
            "lot_summary",
            "inspection",
            "box_inspection",
            "report_evidence",
            "business_rules",
            "decision",
            "predictive",
            "workflow",
            "qc_report",
            "evidence_display",
            "print_report",
        ):
            path = source / (name + ".py")
            bundle.write(path, "smartfruit/" + path.name)
            provenance.append(
                {"module": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        bundle.write(source / "resources/qc_template.xlsx", "smartfruit/resources/qc_template.xlsx")
        for name in ("IMG_6426.json", "IMG_6427.json", "IMG_6428.json"):
            bundle.write(source / "resources/vision" / name, "smartfruit/resources/vision/" + name)
        for package in ("openpyxl", "et_xmlfile"):
            package_root = Path(importlib.util.find_spec(package).origin).parent
            for path in sorted(package_root.rglob("*.py")):
                if "__pycache__" not in path.parts:
                    bundle.write(path, package + "/" + path.relative_to(package_root).as_posix())
        bundle.write(zoneinfo, "zoneinfo/America/Lima")
    (output / "source_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    shutil.copytree(licenses, output / "licenses", dirs_exist_ok=True)
    for path in output.rglob("*"):
        if path.is_file():
            path.chmod(0o644)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-assets", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--zoneinfo", type=Path, default=Path("/usr/share/zoneinfo/America/Lima"))
    parser.add_argument("--project-archive", type=Path,
                        help="Optional owner-private project ZIP; confirm Site audience before publishing")
    args = parser.parse_args()
    build(args.output, args.runtime_assets, args.licenses, args.zoneinfo, args.project_archive)
