"""Durable localhost job metadata; no real provider or listener."""
import sqlite3
import subprocess
import sys
import threading

from manhwa_forge import web


def test_pending_job_becomes_interrupted_in_new_server(tmp_path):
    started = threading.Event()
    worker_starts = []

    def idle(job, out_root):
        worker_starts.append(job.id)
        started.set()

    first = web.create_app(tmp_path)
    first.config["RUN_JOB"] = idle
    client = first.test_client()
    job_id = client.post("/api/generate", json={"idea": "local sensitive prompt"}).get_json()["job_id"]
    assert started.wait(1)
    url = f"/api/jobs/{job_id}"
    assert client.get(url).get_json() == {"job_id": job_id, "status": "pending"}

    # A fresh application instance approximates the documented single-server restart.
    # No previous application object or in-memory registry is used to read status.
    restored = web.create_app(tmp_path)
    restored.config["RUN_JOB"] = idle
    assert restored.test_client().get(url).get_json() == {"job_id": job_id, "status": "interrupted"}
    assert worker_starts == [job_id]


def test_running_and_terminal_metadata_across_instances(tmp_path):
    started = threading.Event()
    finish = threading.Event()
    closed = threading.Event()

    def fake_worker(job, root):
        job.set_status("running")
        started.set()
        assert finish.wait(2)
        job.set_status("done")
        closed.set()

    app = web.create_app(tmp_path)
    app.config["RUN_JOB"] = fake_worker
    client = app.test_client()
    job = client.post("/api/generate", json={"idea": "not indexed", "style": "private style"})
    assert job.status_code == 200
    job_id = job.get_json()["job_id"]
    url = f"/api/jobs/{job_id}"
    try:
        assert started.wait(1)
        assert client.get(url).get_json()["status"] == "running"
        restored = web.create_app(tmp_path)
        assert restored.test_client().get(url).get_json()["status"] == "interrupted"
        assert restored.test_client().get(f"/api/stream/{job_id}").status_code == 404
    finally:
        finish.set()
    assert closed.wait(1)
    restarted = web.create_app(tmp_path).test_client()
    response = restarted.get(url)
    assert response.get_json() == {"job_id": job_id, "status": "done"}
    assert response.headers["Cache-Control"] == "no-store"
    with sqlite3.connect(tmp_path / ".web-job-status.sqlite3") as db:
        assert [column[1] for column in db.execute("PRAGMA table_info(jobs)")] == [
            "id", "instance", "status"
        ]


def test_real_worker_path_failure_persists_error_without_provider(tmp_path, monkeypatch):
    started = threading.Event()
    providers_called = []

    def worker(job, root):
        (root / job.id).touch()  # A file cannot also be a generation directory.
        web._run_job(job, root)
        started.set()

    monkeypatch.setattr(web, "ErnieClient", lambda: providers_called.append(True))
    app = web.create_app(tmp_path)
    app.config["RUN_JOB"] = worker
    client = app.test_client()
    new_job = client.post("/api/generate", json={"idea": "fake"})
    assert started.wait(1)
    job_id = new_job.get_json()["job_id"]
    assert not providers_called
    assert b"event: error" in client.get(f"/api/stream/{job_id}").data
    restored = web.create_app(tmp_path).test_client()
    assert restored.get(f"/api/jobs/{job_id}").get_json()["status"] == "error"


def test_reservation_error_launches_no_worker(tmp_path, monkeypatch):
    app = web.create_app(tmp_path)
    starts = []

    def no_record(*args):
        raise sqlite3.OperationalError("synthetic locked database")

    monkeypatch.setattr(web.JobStatusStore, "reserve", no_record)
    app.config["RUN_JOB"] = lambda *args: starts.append(True)
    response = app.test_client().post("/api/generate", json={"idea": "fake"})
    assert response.status_code == 503
    assert not starts
    assert not app.extensions["manhwa_jobs"]


def test_worker_launch_failure_keeps_error_metadata(tmp_path, monkeypatch):
    def reject(self):
        raise RuntimeError("synthetic start failure")

    app = web.create_app(tmp_path)
    monkeypatch.setattr(web.threading.Thread, "start", reject)
    client = app.test_client()
    response = client.post("/api/generate", json={"idea": "fake"})
    assert response.status_code == 503
    job_id = response.get_json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "error"
    assert not app.extensions["manhwa_jobs"]


def test_job_status_unknown_and_artifact_still_serves(tmp_path):
    app = web.create_app(tmp_path)
    client = app.test_client()
    job_id = "a1b2c3d4e5f6"
    folder = tmp_path / job_id
    folder.mkdir()
    (folder / "chapter.png").write_bytes(b"offline artifact")
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get("/api/jobs/not-a-job-id").status_code == 404
    assert client.get(f"/api/image/{job_id}/chapter.png").data == b"offline artifact"


def test_abrupt_worker_process_exit_keeps_interrupted_status(tmp_path):
    child = """
import os
import sys
import threading
from pathlib import Path
from manhwa_forge.web import create_app

started = threading.Event()
alive = threading.Event()
app = create_app(Path(sys.argv[1]))

def worker(job, root):
    job.set_status("running")
    started.set()
    alive.wait()

app.config["RUN_JOB"] = worker
result = app.test_client().post("/api/generate", json={"idea": "offline"})
assert started.wait(2)
print(result.get_json()["job_id"], flush=True)
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=8,
    )
    job_id = result.stdout.strip()
    assert web.valid_job_id(job_id)
    client = web.create_app(tmp_path).test_client()
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "interrupted"
    assert client.get(f"/api/stream/{job_id}").status_code == 404
