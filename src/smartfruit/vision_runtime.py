"""Lazy persistent subprocess controller, isolated from the web Python runtime."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

_MAX_PROTOCOL_LINE = 1024 * 1024


class VisionRuntime:
    """Serialize worker requests while allowing close() to interrupt inference.

    After timeout, EOF, application error or malformed protocol the worker is
    discarded. A later request starts a new worker; failed jobs are never retried
    silently. ``command`` allows a lightweight protocol stub in transport tests.
    """

    def __init__(self, python, environment=None, command=None):
        self.command = list(command) if command is not None else [
            str(python), "-u", "-m", "smartfruit.vision_worker"
        ]
        self.environment = environment
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process = None
        self._responses = None
        self._closed = False
        self._stderr = deque(maxlen=20)

    @property
    def pid(self):
        with self._state_lock:
            process = self._process
            return process.pid if process is not None and process.poll() is None else None

    @property
    def busy(self):
        return self._request_lock.locked()

    @staticmethod
    def _emit(responses, item):
        try:
            responses.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _read_stdout(self, stream, responses):
        try:
            while True:
                line = stream.readline(_MAX_PROTOCOL_LINE + 1)
                if not line:
                    break
                if len(line) > _MAX_PROTOCOL_LINE:
                    self._emit(responses, ("error", "Respuesta del worker Vision demasiado extensa."))
                    break
                if not self._emit(responses, ("line", line)):
                    break
        except (OSError, ValueError) as exc:
            self._emit(responses, ("error", str(exc)))
        finally:
            self._emit(responses, ("eof", "El worker Vision se cerró sin completar la respuesta."))
            stream.close()

    def _read_stderr(self, stream):
        try:
            while True:
                line = stream.readline(4096)
                if not line:
                    break
                self._stderr.append(line.rstrip()[-2048:])
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def _start(self):
        previous = None
        with self._state_lock:
            if self._closed:
                raise RuntimeError("El runtime Vision está cerrado.")
            if self._process is not None and self._process.poll() is None:
                return self._process, self._responses
            previous = self._process
            self._stderr.clear()
            process = subprocess.Popen(
                self.command, env=self.environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            responses = queue.Queue(maxsize=64)
            self._process, self._responses = process, responses
            threading.Thread(target=self._read_stdout, args=(process.stdout, responses),
                             daemon=True, name="vision-worker-stdout").start()
            threading.Thread(target=self._read_stderr, args=(process.stderr,),
                             daemon=True, name="vision-worker-stderr").start()
        if previous is not None:
            self._dispose(previous)
        return process, responses

    @staticmethod
    def _dispose(process):
        if process.poll() is None:
            if os.name == "nt":
                # Windows venv python.exe can be a redirector supervising the
                # actual interpreter. Terminate only this owned process tree,
                # so closing a job cannot leave an inference child running.
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            except OSError:
                pass
        if process.stdin is not None:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

    def _discard(self, process):
        with self._state_lock:
            if self._process is process:
                responses = self._responses
                self._process = self._responses = None
            else:
                responses = None
                return
        if responses is not None:
            self._emit(responses, ("eof", "El worker Vision se cerró."))
        self._dispose(process)

    def request(self, operation, *, timeout=1800, **parameters):
        deadline = time.monotonic() + timeout
        if not self._request_lock.acquire(timeout=timeout):
            # Another request owns the worker: do not terminate its inference.
            raise TimeoutError("El worker Vision está ocupado; vuelve a consultar su estado.")
        try:
            process, responses = self._start()
            request_id = str(uuid4())
            message = {"id": request_id, "op": operation, **parameters}
            try:
                process.stdin.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n")
                process.stdin.flush()
                try:
                    kind, value = responses.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty as exc:
                    raise TimeoutError("Vision superó el tiempo de procesamiento permitido.") from exc
                if kind != "line":
                    raise RuntimeError(value)
                try:
                    response = json.loads(value)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Respuesta no válida del worker Vision.") from exc
                if (not isinstance(response, dict) or response.get("id") != request_id
                        or not isinstance(response.get("ok"), bool)):
                    raise RuntimeError("El protocolo del worker Vision no coincide con la solicitud.")
                if not response["ok"]:
                    raise RuntimeError(str(response.get("error") or "Falló la inferencia Vision."))
                result = response.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("El worker Vision devolvió un resultado no válido.")
                return result
            except Exception:
                self._discard(process)
                raise
        finally:
            self._request_lock.release()

    def status(self, models_dir, input_kind="fruit_crop", *, timeout=30):
        return self.request("status", models_dir=str(models_dir), input_kind=input_kind, timeout=timeout)

    def infer(self, request_path, output_path, *, timeout=1800):
        self.request(
            "infer", request_path=str(request_path), output_path=str(output_path), timeout=timeout
        )
        result = json.loads(Path(output_path).read_text("utf-8"))
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(
                str(result.get("error")) if isinstance(result, dict) else
                "El worker Vision no guardó un resultado válido."
            )
        return result

    def close(self):
        # Do not wait on _request_lock: a request may be blocked on worker I/O.
        with self._state_lock:
            self._closed = True
            process, responses = self._process, self._responses
            self._process = self._responses = None
        if responses is not None:
            self._emit(responses, ("eof", "El runtime Vision se cerró."))
        if process is not None:
            self._dispose(process)
