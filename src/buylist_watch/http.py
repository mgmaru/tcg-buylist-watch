from __future__ import annotations

import time
import urllib.error
import urllib.request

USER_AGENT = "tcg-buylist-watch/0.1 (+https://github.com/mgmaru/tcg-buylist-watch)"


class Fetcher:
    """間隔を空けて1件ずつ取得する。相手のサーバーに負荷をかけないための最小限の作法。"""

    def __init__(self, delay: float = 1.5, timeout: float = 60, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0

    def get(self, url: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    return res.read()
            except urllib.error.HTTPError as e:
                # 4xx は待っても直らないので、すぐにあきらめる（429 を除く）
                if 400 <= e.code < 500 and e.code != 429:
                    raise
                last_error = e
            except (urllib.error.URLError, TimeoutError) as e:
                last_error = e
            finally:
                self._last = time.monotonic()
            time.sleep(self.delay * (2**attempt))
        raise RuntimeError(f"取得に失敗しました: {url}") from last_error
