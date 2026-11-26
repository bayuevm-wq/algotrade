"""Unduh lewat HTTP dengan jeda antar permintaan dan percobaan ulang."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable

MAX_BYTES = 50_000_000


class HttpError(RuntimeError):
    def __init__(self, status: int | None, url: str, detail: str = ""):
        super().__init__(f"HTTP {status} untuk {url} {detail}".strip())
        self.status = status


class Http:
    def __init__(self, min_interval: float = 0.0, retries: int = 5,
                 sleep: Callable[[float], None] = time.sleep, opener=urllib.request.urlopen):
        self.min_interval, self.retries = min_interval, retries
        self.sleep, self.opener = sleep, opener
        self._last = 0.0

    def get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "algotrade-data/0.1",
                                                       "Accept": "*/*"})
        for attempt in range(self.retries):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            try:
                with self.opener(request, timeout=30) as response:
                    body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise HttpError(None, url, "respons terlalu besar")
                return body
            except urllib.error.HTTPError as e:
                status, detail = e.code, ""
                if status != 429 and status < 500:      # salah permintaan: jangan diulang
                    raise HttpError(status, url) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                status, detail = None, str(e)
            if attempt < self.retries - 1:
                self.sleep(min(15 * 2 ** attempt, 120) if status == 429 else 2 ** attempt)
        raise HttpError(status, url, detail)
