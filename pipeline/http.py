"""キャッシュ優先の HTTP 取得(N-02 / N-03)。

- 取得間隔は 1 秒以上を強制する
- 一度取得した URL はローカルキャッシュから返し、HTTP を出さない
- 全取得に URL・取得日・sha256 の provenance を残す

依存は標準ライブラリのみ。
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
USER_AGENT = "neko-atlas/0.1 (research; https://github.com/twill3c/neko-atlas)"
MIN_INTERVAL_S = 1.0

CACHE_DIR = Path("data/cache")

_last_request_at = 0.0
#: このプロセスで実際に発行した HTTP リクエスト数(再実行キャッシュの検査に使う — T-103)
http_requests = 0


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def fetch(url: str, *, cache_dir: Path | None = None) -> tuple[bytes, dict]:
    """URL を取得して (本体, provenance) を返す。キャッシュがあれば HTTP を出さない。"""
    global _last_request_at, http_requests
    cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _key(url)
    blob = cache_dir / f"{key}.bin"
    meta = cache_dir / f"{key}.json"

    if blob.exists() and meta.exists():
        body = blob.read_bytes()
        prov = json.loads(meta.read_text(encoding="utf-8"))
        return body, prov

    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    _last_request_at = time.monotonic()
    http_requests += 1

    prov = {
        "url": url,
        "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    blob.write_bytes(body)
    meta.write_text(json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")
    return body, prov
