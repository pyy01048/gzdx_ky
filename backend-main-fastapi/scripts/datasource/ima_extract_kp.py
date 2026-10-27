"""Trigger knowledge-point extraction for one document via the FastAPI ASGI app.

Usage:
    python ima_extract_kp.py <doc_id> [<doc_id> ...]

Uses the project's own ASGIClient (tests/asgi_client.py) so no HTTP server is
needed and no dependency versions are touched. Calls
    POST /api/documents/{doc_id}/extract-knowledge-points

Prints, per document: extracted count and the knowledge-point names.
"""
import json
import os
import sys
import time
from typing import Any, Dict, List

# Full-text docs produce 30+ chunks; each chunk is one local-Ollama call, so the
# default 60s write timeout in utils/timeout_guard returns 504 before the job can
# commit. Widen it for this path at runtime (env override, no source change).
os.environ.setdefault("API_TIMEOUT_PATH_MAP", "/api/documents=1800")

BACKEND = r"D:\平台\backend-main-fastapi"
sys.path.insert(0, BACKEND)
sys.path.insert(0, BACKEND + r"\tests")

from main import app  # noqa: E402
from asgi_client import ASGIClient  # noqa: E402

ENDPOINT = "/api/documents/{doc_id}/extract-knowledge-points"


def extract_one(client: ASGIClient, doc_id: int) -> Dict[str, Any]:
    """Run extraction for a single document and return a compact report."""
    started = time.time()
    resp = client.post(ENDPOINT.format(doc_id=doc_id))
    elapsed = time.time() - started
    report: Dict[str, Any] = {
        "doc_id": doc_id,
        "status_code": resp.status_code,
        "elapsed_sec": round(elapsed, 1),
        "extracted": 0,
        "names": [],
    }
    if resp.status_code != 200:
        report["error"] = resp.text[:500]
        return report
    try:
        data = resp.json()
    except ValueError:
        report["error"] = resp.text[:500]
        return report
    report["extracted"] = data.get("extracted", 0)
    report["message"] = data.get("message", "")
    kps: List[Dict[str, Any]] = data.get("knowledge_points") or []
    report["names"] = [kp.get("name", "") for kp in kps][:12]
    return report


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    doc_ids = [int(x) for x in sys.argv[1:]]
    client = ASGIClient(app)
    reports = []
    for doc_id in doc_ids:
        try:
            reports.append(extract_one(client, doc_id))
        except Exception as exc:  # noqa: BLE001 - surface any failure verbatim
            reports.append({"doc_id": doc_id, "error": "%s: %s" % (type(exc).__name__, exc)})
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
