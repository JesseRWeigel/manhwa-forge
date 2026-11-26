"""Progress history tests. No model servers, network listeners or real renders."""
import json
from types import SimpleNamespace

import pytest

from manhwa_forge import web


@pytest.fixture
def completed_job(tmp_path, monkeypatch):
    beat = SimpleNamespace(idx=0, framing="wide", dialogue=[], caption="")
    script = SimpleNamespace(
        title="Offline test", synopsis="Synthetic", style="ink", panels=[beat],
        model_dump_json=lambda **kwargs: "{}",
    )
    monkeypatch.setattr(web, "ErnieClient", lambda: SimpleNamespace(generate_to_file=lambda *a, **kw: None))
    monkeypatch.setattr(web, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setattr(web, "generate_script", lambda *a: script)
    monkeypatch.setattr(web, "size_for_framing", lambda *a: (64, 64))
    monkeypatch.setattr(web, "build_panel_prompt", lambda *a: "synthetic")
    monkeypatch.setattr(web, "compose_webtoon", lambda *a, **kw: None)
    job = web.Job("offline-job", "test", 6, None)
    app = web.create_app(tmp_path)
    app.extensions["manhwa_jobs"][job.id] = job
    web._run_job(job, tmp_path)
    return app, job


def events(body):
    result = []
    for packet in body.decode().strip().split("\n\n"):
        if packet.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in packet.splitlines())
        result.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return result


def test_two_viewers_get_same_history(completed_job):
    app, job = completed_job
    url = f"/api/stream/{job.id}"
    first = app.test_client().get(url, buffered=False)
    one, two = iter(first.response), None
    try:
        first_packet = next(one)
        second = app.test_client().get(url, buffered=False)
        two = iter(second.response)
        assert first_packet == next(two)
        left = events(first_packet + b"".join(one))
        right = events(first_packet + b"".join(two))
        assert left == right
        assert [(i, kind) for i, kind, _ in left] == [(1, "script"), (2, "panel"), (3, "done")]
    finally:
        if two is not None:
            two.close()
        one.close()


def test_resume_and_terminal_204(completed_job):
    app, job = completed_job
    url = f"/api/stream/{job.id}"
    initial = app.test_client().get(url, buffered=False)
    with initial:
        first_packet = next(iter(initial.response))
    assert events(first_packet)[0][:2] == (1, "script")
    response = app.test_client().get(url, headers={"Last-Event-ID": "1"})
    assert [(i, kind) for i, kind, _ in events(response.data)] == [(2, "panel"), (3, "done")]
    terminal = app.test_client().get(url, headers={"Last-Event-ID": "3"})
    assert terminal.status_code == 204


@pytest.mark.parametrize("cursor", ["-1", "not-an-id", "0" * 100, "999"])
def test_invalid_progress_cursor_returns_400(completed_job, cursor):
    app, job = completed_job
    response = app.test_client().get(f"/api/stream/{job.id}", headers={"Last-Event-ID": cursor})
    assert response.status_code == 400


def test_retained_window_and_terminal_error(tmp_path, monkeypatch):
    job = web.Job("window-job", "test", 6, None)
    job.events = web.ProgressLog(capacity=2)
    for i in range(3):
        job.events.publish("panel", {"idx": i})
    job.events.publish("error", {"message": "synthetic failure"})
    job.events.finish()
    app = web.create_app(tmp_path)
    app.extensions["manhwa_jobs"][job.id] = job
    url = f"/api/stream/{job.id}"
    assert app.test_client().get(url, headers={"Last-Event-ID": "1"}).status_code == 409
    ok = app.test_client().get(url, headers={"Last-Event-ID": "2"})
    assert [(i, kind) for i, kind, _ in events(ok.data)] == [(3, "panel"), (4, "error")]
    assert app.test_client().get(f"{url}-absent").status_code == 404


def test_live_heartbeat_then_fanout(tmp_path, monkeypatch):
    job = web.Job("live-job", "test", 6, None)
    monkeypatch.setattr(web, "_HEARTBEAT_SECONDS", 0)
    app = web.create_app(tmp_path)
    app.extensions["manhwa_jobs"][job.id] = job
    url = f"/api/stream/{job.id}"
    with app.test_client().get(url, buffered=False) as first:
        with app.test_client().get(url, buffered=False) as second:
            a, b = iter(first.response), iter(second.response)
            assert next(a) == next(b) == b": keepalive\n\n"
            job.events.publish("script", {"title": "Hello"})
            assert next(a) == next(b)
            job.events.publish("done", {"title": "Hello"})
            job.events.finish()
            assert events(b"".join(a)) == events(b"".join(b)) == [(2, "done", {"title": "Hello"})]


def test_lagging_stream_gets_progress_expired_event(tmp_path, monkeypatch):
    job = web.Job("lag-job", "test", 6, None)
    job.events = web.ProgressLog(capacity=1)
    job.events.publish("script", {"title": "Hello"})
    url = f"/api/stream/{job.id}"
    app = web.create_app(tmp_path)
    app.extensions["manhwa_jobs"][job.id] = job
    with app.test_client().get(url, buffered=False) as response:
        reader = iter(response.response)
        assert events(next(reader))[0][:2] == (1, "script")
        job.events.publish("panel", {"idx": 0})
        job.events.publish("panel", {"idx": 1})
        error = b"".join(reader)
    assert error.startswith(b"event: progress-expired\ndata: ")
    assert "history expired" in json.loads(error.decode().split("data: ")[1])["message"]
    assert not job.events.should_stop(3)
