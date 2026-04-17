"""Thin client for the ERNIE-Image-Turbo Flask server."""
from __future__ import annotations
import os
import time
from pathlib import Path
import requests


class ErnieClient:
    def __init__(self, host: str | None = None):
        self.host = host or os.environ.get("ERNIE_HOST", "http://127.0.0.1:7860")

    def health(self) -> dict:
        r = requests.get(f"{self.host}/health", timeout=5)
        r.raise_for_status()
        return r.json()

    def generate(
        self,
        prompt: str,
        height: int,
        width: int,
        seed: int | None = None,
        steps: int = 8,
        use_pe: bool = True,
    ) -> bytes:
        payload = {
            "prompt": prompt,
            "height": height,
            "width": width,
            "seed": seed,
            "steps": steps,
            "use_pe": use_pe,
        }
        r = requests.post(f"{self.host}/generate", json=payload, timeout=300)
        r.raise_for_status()
        return r.content

    def generate_to_file(self, path: Path, prompt: str, height: int, width: int, **kwargs) -> Path:
        data = self.generate(prompt, height, width, **kwargs)
        path.write_bytes(data)
        return path


def wait_for_server(client: ErnieClient, timeout_s: int = 60) -> bool:
    """Poll /health until the server responds. Useful if the caller just launched it."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            client.health()
            return True
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2)
    return False
