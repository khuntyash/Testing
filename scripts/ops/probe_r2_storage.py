from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from hybrid.storage import S3ArtifactStore


def main() -> int:
    key = os.getenv("R2_PROBE_KEY", "probes/labelhub-r2-probe.txt")
    store = S3ArtifactStore()
    content = b"labelhub-r2-probe"
    store.upload_bytes(key, content)
    stream = store.open_stream(key)
    data = stream.read()
    if data != content:
        raise RuntimeError("R2 probe content mismatch")
    print(f"R2 probe passed for key: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
