"""Catálogo local y trabajos de inferencia con asociación externa a la inspección."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .local_files import write_json_atomic
from .vision import VISION_FIELDS, load_vision_json
from .vision_runtime import VisionRuntime

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
_CROP_SUFFIX = re.compile(r"_L\d+$", re.IGNORECASE)


def _write_json(path, value):
    write_json_atomic(path, value, indent=2)


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{name}: completar un identificador de texto válido.")
    return value.strip()


def _now():
    return datetime.now(timezone.utc).isoformat()


class VisionCapture:
    """Ejecuta Vision fuera del proceso web; conserva resultados y su contexto.

    ``runner`` se puede inyectar para verificar el transporte sin cargar modelos.
    En producción siempre se ejecuta el módulo de inferencia con los pesos locales.
    """

    def __init__(self, input_dir=None, output_dir=None, runner=None):
        project = Path(__file__).resolve().parents[2]
        self.input_dir = Path(
            input_dir or os.getenv("SMARTFRUIT_VISION_INPUT_DIR", "")
            or project / "data/local/vision_input"
        ).resolve()
        self.photos_dir = self.input_dir / "images"
        self.models_dir = self.input_dir / "models"
        self.output_dir = Path(
            output_dir or os.getenv("SMARTFRUIT_VISION_OUTPUT_DIR", "")
            or self.input_dir.parent / "vision_output"
        ).resolve() / "jobs"
        self._runner = runner
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smartfruit-vision")
        self._lock = threading.RLock()
        self._submission_lock = threading.Lock()
        self._jobs = {}
        self._photos = {}
        self._fingerprints = {}
        self._runtime_cache = None
        self._runtime = None
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
            runtime = self._runtime
        if runtime is not None:
            runtime.close()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _catalog(self):
        photos = {}
        if not self.photos_dir.is_dir():
            self._photos = photos
            return photos
        root = self.photos_dir.resolve()
        for path in sorted(root.rglob("*"), key=lambda path: (
            not bool(_CROP_SUFFIX.search(path.stem)), str(path).lower()
        )):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            stat = path.stat()
            fingerprint = (str(resolved), stat.st_mtime_ns, stat.st_size)
            digest = self._fingerprints.get(fingerprint)
            if digest is None:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
                self._fingerprints[fingerprint] = digest
            photo_id = "PHOTO_" + digest
            # Una copia idéntica bajo otro nombre tampoco duplica frutos.
            if photo_id in photos:
                continue
            is_crop = bool(_CROP_SUFFIX.search(path.stem))
            photos[photo_id] = {
                "photo_id": photo_id,
                "image_id": photo_id,
                "name": path.name,
                "url": f"/api/vision/photos/{photo_id}/image",
                "input_kind": "fruit_crop" if is_crop else "scene",
                "source_group": _CROP_SUFFIX.sub("", path.stem) if is_crop else path.stem,
                "_path": resolved,
            }
        self._photos = photos
        return photos

    def catalog(self):
        with self._lock:
            photos = list(self._catalog().values())
        kinds = {photo["input_kind"] for photo in photos}
        return {
            "photos": [{k: v for k, v in photo.items() if k != "_path"} for photo in photos],
            "runtime": self.runtime_status("scene" if kinds == {"scene"} else "fruit_crop"),
        }

    def photo_path(self, photo_id):
        with self._lock:
            photo = self._photos.get(photo_id)
            if photo is None:
                photo = self._catalog().get(photo_id)
            if photo is None:
                raise KeyError("Fotografía no encontrada.")
            path = photo["_path"].resolve()
            if not path.is_relative_to(self.photos_dir.resolve()) or not path.is_file():
                raise KeyError("Fotografía no encontrada.")
            return path

    def job_photo_path(self, job_id, photo_id):
        """Sirve solo la copia inmutable de una imagen perteneciente al trabajo."""
        job = self.get(job_id)
        photo = next((item for item in job.get("photos", [])
                      if item.get("photo_id") == photo_id), None)
        if photo is None or not isinstance(photo_id, str) or Path(photo_id).name != photo_id:
            raise KeyError("Fotografía no encontrada en esta revisión.")
        name = photo.get("name")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise KeyError("Fotografía no encontrada en esta revisión.")
        root = (self.output_dir / job_id).resolve()
        images = (root / "images").resolve()
        path = (images / photo_id / name).resolve()
        if (not root.is_relative_to(self.output_dir.resolve())
                or not images.is_relative_to(root)
                or not path.is_relative_to(images) or not path.is_file()):
            raise KeyError("Fotografía no encontrada en esta revisión.")
        return path

    def report_evidence_resolver(self):
        """Resolve source predictions to local photos, never to client paths/URLs.

        Ready jobs with the same commercial context take precedence. Their
        records must match the supplied Vision output before an immutable image
        is reused. Historical JSONs can match unambiguous catalog crop names.
        """
        with self._lock:
            catalog = deepcopy(self._catalog())
        jobs = {}
        root = self.output_dir.resolve()
        if root.is_dir():
            for directory in root.iterdir():
                try:
                    if str(UUID(directory.name)) != directory.name:
                        continue
                    resolved = directory.resolve()
                    path = (resolved / "job.json").resolve()
                    if not resolved.is_relative_to(root) or not path.is_relative_to(root):
                        continue
                    job = json.loads(path.read_text("utf-8"))
                    if job.get("status") != "ready":
                        continue
                    context = job.get("context", {})
                    key = tuple(str(context.get(field, ""))
                                for field in ("lot_id", "pallet_id", "sample_id"))
                    photos = {photo.get("image_id"): photo for photo in job.get("photos", [])}
                    for record in job.get("records", []):
                        photo = photos.get(record.get("image_id"))
                        if photo:
                            jobs.setdefault((key, record["image_id"]), []).append(
                                (directory.name, record, photo)
                            )
                except (OSError, ValueError, TypeError, AttributeError, KeyError):
                    continue
        by_name, by_stem = {}, {}
        for photo in catalog.values():
            by_name.setdefault(photo["name"].casefold(), []).append(photo)
            by_stem.setdefault(Path(photo["name"]).stem.casefold(), []).append(photo)
        read_cache = {}

        def read_photo(path, photo):
            key = str(path)
            if key not in read_cache:
                try:
                    raw = path.read_bytes() if path.stat().st_size <= 20 * 1024 * 1024 else None
                    if raw is None:
                        read_cache[key] = None
                        return None
                    expected_id = "PHOTO_" + hashlib.sha256(raw).hexdigest()[:24]
                    if photo["photo_id"] != expected_id:
                        raw = None
                except OSError:
                    raw = None
                read_cache[key] = raw
            raw = read_cache[key]
            return {"image_bytes": raw, "input_kind": photo.get("input_kind", "scene")} if raw else None

        def find_named(value, *, allow_stem=False):
            if not isinstance(value, str) or not value or any(c in value for c in "/\\:"):
                return None
            matches = by_name.get(value.casefold(), [])
            if not matches and allow_stem:
                matches = by_stem.get(value.casefold(), [])
            return matches[0] if len(matches) == 1 else None

        def from_catalog(photo):
            if photo is None:
                return None
            path = photo["_path"].resolve()
            if not path.is_relative_to(self.photos_dir.resolve()):
                return None
            return read_photo(path, photo)

        def resolve(record, prediction_index, context):
            key = tuple(context.get(field, "")
                        for field in ("lot_id", "pallet_id", "sample_id"))
            candidates = jobs.get((key, record["image_id"]), [])
            for job_id, stored, photo in candidates:
                # Human review adds audit fields without changing model evidence.
                def raw(value):
                    value = deepcopy(value)
                    for prediction in value.get("fruit_predictions", []):
                        for field in ("review_status", "reviewed_by", "reviewed_at",
                                      "override_label", "override_reason", "qc_final_label"):
                            prediction.pop(field, None)
                    return value

                original, supplied = raw(stored), raw(record)
                if any(supplied.get(field) != original.get(field)
                       for field in (*VISION_FIELDS, "inference")):
                    continue
                try:
                    path = self.job_photo_path(job_id, photo["photo_id"])
                except (KeyError, OSError, ValueError):
                    continue
                source = read_photo(path, photo)
                if source is not None:
                    return source
            if candidates:
                # A changed JSON must not borrow photographic proof from a
                # known local inference whose predictions do not match it.
                return None
            prediction = record["fruit_predictions"][prediction_index]
            crop = find_named(prediction.get("crop_id"))
            if crop is not None and crop.get("input_kind") == "fruit_crop":
                return from_catalog(crop)
            photo = catalog.get(record["image_id"])
            metadata = record.get("inference")
            metadata = metadata if isinstance(metadata, dict) else {}
            if photo is None:
                photo = find_named(metadata.get("source_filename"))
            if photo is None:
                photo = find_named(record["image_id"], allow_stem=True)
            source = from_catalog(photo)
            if (source is not None and record["total_fruits"] == 1
                    and metadata.get("input_kind") == "fruit_crop"):
                source["input_kind"] = "fruit_crop"
            return source

        return resolve

    def _python(self):
        explicit = os.getenv("SMARTFRUIT_VISION_PYTHON")
        if explicit:
            candidate = Path(explicit).expanduser()
            if not candidate.is_file():
                raise ValueError("SMARTFRUIT_VISION_PYTHON no apunta a un intérprete existente.")
            return candidate
        project = Path(__file__).resolve().parents[2]
        candidates = [
            project / ".venv-vision/Scripts/python.exe",
            project / ".venv-vision/bin/python",
        ]
        if os.name == "nt":
            # El servidor puede usar Python sin GIL y Vision un Python estándar.
            base = Path(sys.base_prefix)
            candidates.extend([
                base.with_name(base.name.rstrip("t")) / "python.exe",
                Path(os.getenv("ProgramFiles", "C:/Program Files"))
                / f"Python{sys.version_info.major}{sys.version_info.minor}" / "python.exe",
            ])
        candidates.append(Path(sys.executable))
        return next(path for path in candidates if path.is_file())

    def _environment(self):
        environment = os.environ.copy()
        source = str(Path(__file__).resolve().parents[1])
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (source, environment.get("PYTHONPATH")) if value
        )
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

    def _worker(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("El servidor se cerró durante el proceso de Vision.")
            if self._runtime is None:
                self._runtime = VisionRuntime(self._python(), self._environment())
            return self._runtime

    def runtime_status(self, input_kind="fruit_crop"):
        if self._runner is not None:
            return {"available": True, "message": "Vision disponible.",
                    "capabilities": {"fruit_crop": True, "scene": True}}
        with self._lock:
            cache = self._runtime_cache
            runtime = self._runtime
            if cache and runtime is not None and runtime.busy:
                status = deepcopy(cache[1])
                if cache[0] != input_kind:
                    available = bool(status.get("capabilities", {}).get(input_kind))
                    status.update(
                        available=available, ready=available, input_kind=input_kind,
                        message=("Vision disponible para procesar estas imágenes." if available else
                                 "Vision no está disponible para este tipo de imágenes."),
                    )
                return status
            if cache and cache[0] == input_kind and time.monotonic() - cache[2] < 15:
                return deepcopy(cache[1])
        received = False
        try:
            raw = self._worker().status(self.models_dir, input_kind)
            received = True
            available = bool(raw.get("ready"))
            missing = raw.get("missing_dependencies", []) + raw.get("missing_models", [])
            message = ("Vision disponible para procesar estas imágenes." if available
                       else raw.get("message") or "Vision requiere: " + ", ".join(missing))
            status = {**raw, "available": available, "message": message,
                      "python": str(self._python())}
            if not available and not missing and not raw.get("message"):
                status["message"] = "No se pudo iniciar Vision. Revisa el entorno de inferencia."
        except (OSError, ValueError, RuntimeError) as exc:
            status = {"available": False, "message": f"Vision no disponible: {exc}"}
        with self._lock:
            self._runtime_cache = (input_kind, status, time.monotonic()) if received else None
        return deepcopy(status)

    def submit(self, payload):
        # Serialize selection/snapshot creation so concurrent clicks cannot queue
        # two jobs against the same inspection while models are starting.
        with self._submission_lock:
            return self._submit(payload)

    def _submit(self, payload):
        if self._closed:
            raise ValueError("Vision se está cerrando. Vuelve a iniciar el servidor.")
        context = {key: _identifier(payload.get(key), key)
                   for key in ("lot_id", "pallet_id", "sample_id")}
        context["review_kind"] = payload.get("review_kind", "initial")
        if context["review_kind"] not in ("initial", "additional"):
            raise ValueError("Tipo de revisión Vision no válido.")
        ids = payload.get("photo_ids")
        if (not isinstance(ids, list) or not ids or len(ids) > 500
                or any(not isinstance(item, str) for item in ids)):
            raise ValueError("Selecciona entre 1 y 500 imágenes para esta revisión.")
        if len(set(ids)) != len(ids):
            raise ValueError("Una fotografía no se puede seleccionar dos veces.")
        with self._lock:
            for job in self._jobs.values():
                if job.get("status") not in ("queued", "running") or job.get("context") != context:
                    continue
                if {photo["photo_id"] for photo in job["photos"]} == set(ids):
                    return deepcopy(job)
                raise ValueError("Esta caja ya se está procesando. Espera el resultado.")
            catalog = self._catalog()
            if any(photo_id not in catalog for photo_id in ids):
                raise ValueError("Una imagen seleccionada ya no está disponible. Actualiza la lista.")
            photos = [catalog[photo_id] for photo_id in ids]
        for kind in {photo["input_kind"] for photo in photos}:
            runtime = self.runtime_status(kind)
            if not runtime["available"]:
                raise ValueError(runtime["message"])
        job_id = str(uuid4())
        folder = self.output_dir / job_id
        folder.mkdir(parents=True)
        images = []
        for photo in photos:
            # Una revisión conserva sus entradas aunque cambie la carpeta de llegada.
            try:
                image_bytes = photo["_path"].read_bytes()
            except OSError as exc:
                raise ValueError("Una imagen ya no está disponible. Actualiza las fotos.") from exc
            if "PHOTO_" + hashlib.sha256(image_bytes).hexdigest()[:24] != photo["photo_id"]:
                raise ValueError("Una imagen cambió durante la selección. Actualiza las fotos.")
            snapshot = folder / "images" / photo["photo_id"] / photo["name"]
            snapshot.parent.mkdir(parents=True)
            snapshot.write_bytes(image_bytes)
            images.append({"path": str(snapshot), "image_id": photo["image_id"],
                           "input_kind": photo["input_kind"]})
        request = {
            "models_dir": str(self.models_dir), "partition": "capture",
            "progress_path": str(folder / "progress.json"),
            "images": images,
        }
        job = {
            "job_id": job_id, "status": "queued", "phase": "QUEUED", "context": context,
            "created_at": _now(), "progress": {"completed": 0, "total": len(photos)},
            "photos": [{**{k: v for k, v in photo.items() if k != "_path"},
                        "evidence_url": f"/api/vision/jobs/{job_id}/photos/{photo['photo_id']}/image"}
                       for photo in photos],
            "records": [],
        }
        _write_json(folder / "request.json", request)
        _write_json(folder / "job.json", job)
        with self._lock:
            if self._closed:
                raise ValueError("Vision se está cerrando. Vuelve a iniciar el servidor.")
            self._jobs[job_id] = job
            snapshot = deepcopy(job)
            self._executor.submit(self._run, job_id, request, folder)
        return snapshot

    def _update(self, job_id, folder, **values):
        with self._lock:
            self._jobs[job_id].update(values)
            _write_json(folder / "job.json", self._jobs[job_id])

    def _run(self, job_id, request, folder):
        try:
            self._update(job_id, folder, status="running", phase="LOADING_MODEL", started_at=_now())
            if self._runner is not None:
                result = self._runner(request)
            else:
                result = self._worker().infer(folder / "request.json", folder / "response.json")
            records = [load_vision_json(record) for record in result.get("records", [])]
            expected = {image["image_id"] for image in request["images"]}
            if len(records) != len(expected) or {r["image_id"] for r in records} != expected:
                raise ValueError("Vision devolvió resultados que no corresponden a las imágenes.")
            context = self._jobs[job_id]["context"]
            bindings = [{"image_id": record["image_id"],
                         **{k: context[k] for k in ("lot_id", "pallet_id", "sample_id")}}
                        for record in records]
            for record in records:
                _write_json(folder / f"{record['image_id']}.json", record)
            self._update(job_id, folder, status="ready", phase="REVIEW_READY",
                         records=records, image_bindings=bindings,
                         pipeline=result.get("pipeline"), finished_at=_now(),
                         progress={"completed": len(records), "total": len(records)})
        except Exception as exc:
            timeout = isinstance(exc, TimeoutError)
            self._update(job_id, folder, status="failed", phase="TIMEOUT" if timeout else "ERROR",
                         error_type="timeout" if timeout else "error", error=str(exc),
                         finished_at=_now())

    def get(self, job_id):
        try:
            if str(UUID(job_id)) != job_id:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise KeyError("Trabajo de Vision no encontrado.") from exc
        folder = self.output_dir / job_id
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                try:
                    job = json.loads((folder / "job.json").read_text("utf-8"))
                except (OSError, ValueError) as exc:
                    raise KeyError("Trabajo de Vision no encontrado.") from exc
                if job["status"] in ("queued", "running"):
                    job.update(status="failed", phase="ERROR", error_type="interrupted",
                               error="El servidor se reinició durante el proceso. "
                               "Vuelve a procesar las imágenes.")
                    _write_json(folder / "job.json", job)
                self._jobs[job_id] = job
            snapshot = deepcopy(job)
        if snapshot["status"] == "running":
            try:
                progress = json.loads((folder / "progress.json").read_text("utf-8"))
                if (isinstance(progress.get("completed"), int)
                        and 0 <= progress["completed"] <= snapshot["progress"]["total"]):
                    snapshot["progress"]["completed"] = progress["completed"]
                    if progress.get("phase") in ("LOADING_MODEL", "DETECTING", "CLASSIFYING"):
                        snapshot["phase"] = progress["phase"]
                    detected = progress.get("detected_fruits")
                    if type(detected) is int and detected >= 0:
                        snapshot["progress"]["detected_fruits"] = detected
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        return snapshot
