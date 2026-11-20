"""Minimal Flask + SSE web UI for manhwa-forge.

LOCALHOST ONLY. No auth, no rate limiting, no sandboxing beyond Flask
defaults. Do not expose this server to the public internet without auth +
a reverse proxy. The `web` CLI command deliberately defaults to 127.0.0.1.

Design:
  * One threading.Thread per job runs a tiny inline copy of the pipeline
    (script -> per-panel -> compose) so we can emit SSE events between
    steps without touching pipeline.py.
  * Each job keeps a bounded, replayable event log; SSE readers do not drain it.
  * Jobs live in an in-memory dict — they vanish when the server restarts.
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from .layout import compose_webtoon
from .prompts import build_panel_prompt, size_for_framing
from .render import ErnieClient, wait_for_server
from .story import generate_script

# The current UI targets up to 60 panels (plus two for story pacing),
# with one script event and one terminal event.
_PROGRESS_CAPACITY = 64
_HEARTBEAT_SECONDS = 15.0


class CursorExpired(ValueError):
    """The reader fell behind the retained event window."""


class ProgressLog:
    """Bounded per-job in-memory history with independent reader cursors."""

    def __init__(self, capacity: int = _PROGRESS_CAPACITY):
        if capacity < 1:
            raise ValueError("progress capacity must be positive")
        self._entries: deque[tuple[int, str, str]] = deque(maxlen=capacity)
        self._condition = threading.Condition()
        self._last_id = 0
        self._finished = False

    def publish(self, name: str, payload: Any) -> None:
        encoded = json.dumps(payload)
        with self._condition:
            self._last_id += 1
            self._entries.append((self._last_id, name, encoded))
            self._condition.notify_all()

    def finish(self) -> None:
        with self._condition:
            self._finished = True
            self._condition.notify_all()

    def should_stop(self, cursor: int) -> bool:
        with self._condition:
            if cursor > self._last_id:
                raise ValueError("Last-Event-ID is ahead of job progress")
            self._check_window(cursor)
            return self._finished and cursor == self._last_id

    def _check_window(self, cursor: int) -> None:
        if self._entries and cursor < self._entries[0][0] - 1:
            raise CursorExpired("Progress history expired; the existing job may still be running.")

    def after(self, cursor: int, timeout: float) -> tuple[tuple[int, str, str] | None, bool]:
        with self._condition:
            self._condition.wait_for(
                lambda: cursor < self._last_id or self._finished, timeout=timeout
            )
            self._check_window(cursor)
            if cursor < self._last_id:
                return self._entries[cursor + 1 - self._entries[0][0]], False
            return None, self._finished


@dataclass
class Job:
    """One generation job. Mutated by worker thread, read by SSE view."""
    id: str
    idea: str
    n_panels: int
    style_hint: str | None
    status: str = "pending"  # pending | running | done | error
    script: Any = None
    panel_paths: list[Path] = field(default_factory=list)
    final_chapter_path: Path | None = None
    error: str | None = None
    events: ProgressLog = field(default_factory=ProgressLog)


# Module-level registry. Lock guards inserts; dict reads are atomic in CPython.
JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def _sse(event: str, encoded: str, *, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {encoded}\n\n"


def _run_job(job: Job, out_root: Path) -> None:
    """Worker body. Any exception becomes an 'error' SSE event, never crashes."""
    job_dir = out_root / job.id
    panels_dir = job_dir / "panels"
    try:
        panels_dir.mkdir(parents=True, exist_ok=True)
        job.status = "running"
        ernie = ErnieClient()
        if not wait_for_server(ernie, timeout_s=10):
            raise RuntimeError(f"ERNIE server not reachable at {ernie.host}.")

        # Phase 1 — script (slow LLM call).
        script = generate_script(job.idea, job.n_panels, job.style_hint)
        job.script = script
        (job_dir / "script.json").write_text(script.model_dump_json(indent=2))
        job.events.publish("script", {
            "title": script.title, "synopsis": script.synopsis,
            "style": script.style, "n_panels": len(script.panels),
        })

        # Phase 2 — per-panel render, one SSE event each.
        for beat in script.panels:
            h, w = size_for_framing(beat.framing)
            prompt = build_panel_prompt(beat, script)
            path = panels_dir / f"panel_{beat.idx:02d}.png"
            ernie.generate_to_file(path, prompt=prompt, height=h, width=w, seed=42 + beat.idx)
            (panels_dir / f"panel_{beat.idx:02d}.prompt.txt").write_text(prompt)
            job.panel_paths.append(path)
            job.events.publish("panel", {
                "idx": beat.idx, "total": len(script.panels),
                "url": f"/api/image/{job.id}/panels/panel_{beat.idx:02d}.png",
                "framing": beat.framing, "dialogue": beat.dialogue, "caption": beat.caption,
            })

        # Phase 3 — composite tall chapter PNG.
        final_path = job_dir / "chapter.png"
        compose_webtoon(job.panel_paths, final_path, title=script.title)
        job.final_chapter_path = final_path
        job.status = "done"
        job.events.publish("done", {"url": f"/api/image/{job.id}/chapter.png", "title": script.title})
    except Exception as e:
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        job.events.publish("error", {"message": job.error})
    finally:
        job.events.finish()


def create_app(out_root: Path | None = None) -> Flask:
    """Flask app factory. `out_root` defaults to ./outputs/web."""
    app = Flask(__name__, template_folder="templates")
    app.config["OUT_ROOT"] = Path(out_root) if out_root else Path("outputs/web")
    app.config["OUT_ROOT"].mkdir(parents=True, exist_ok=True)
    # Tests monkey-patch RUN_JOB to skip ERNIE/LLM calls.
    app.config["RUN_JOB"] = _run_job

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/generate")
    def api_generate():
        data = request.get_json(silent=True) or request.form
        idea = (data.get("idea") or "").strip()
        if not idea:
            return jsonify(error="idea is required"), 400
        try:
            n_panels = int(data.get("panels") or 30)
        except (TypeError, ValueError):
            return jsonify(error="panels must be an integer"), 400
        n_panels = max(6, min(60, n_panels))
        style_hint = (data.get("style") or "").strip() or None

        job = Job(id=uuid.uuid4().hex[:12], idea=idea, n_panels=n_panels, style_hint=style_hint)
        with _JOBS_LOCK:
            JOBS[job.id] = job

        run_job = app.config["RUN_JOB"]
        threading.Thread(
            target=run_job, args=(job, app.config["OUT_ROOT"]),
            daemon=True, name=f"manhwa-job-{job.id}",
        ).start()
        return jsonify(job_id=job.id)

    @app.get("/api/stream/<job_id>")
    def api_stream(job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            return jsonify(error="unknown job_id"), 404

        raw_cursor = request.headers.get("Last-Event-ID") or "0"
        if len(raw_cursor) > 20 or not (raw_cursor.isascii() and raw_cursor.isdecimal()):
            return jsonify(error="Last-Event-ID must be a non-negative integer"), 400
        start = int(raw_cursor)
        try:
            if job.events.should_stop(start):
                # EventSource treats 204 as an instruction not to reconnect.
                return Response(status=204)
        except CursorExpired as exc:
            return jsonify(error=str(exc)), 409
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        def stream():
            cursor = start
            while True:
                try:
                    item, finished = job.events.after(cursor, _HEARTBEAT_SECONDS)
                except CursorExpired as exc:
                    yield _sse("error", json.dumps({"message": str(exc)}))
                    return
                if item is None:
                    if finished:
                        return
                    yield ": keepalive\n\n"
                    continue
                cursor, name, payload = item
                yield _sse(name, payload, event_id=cursor)

        return Response(stream(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if ever proxied
        })

    @app.get("/api/image/<job_id>/<path:filename>")
    def api_image(job_id: str, filename: str):
        # send_from_directory protects against path traversal.
        return send_from_directory(app.config["OUT_ROOT"] / job_id, filename)

    return app


def main() -> None:
    """Entry point for `python -m manhwa_forge.web`."""
    create_app().run(host="127.0.0.1", port=5001, debug=False, threaded=True)


if __name__ == "__main__":
    main()
