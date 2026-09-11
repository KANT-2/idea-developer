"""Run a disposable 20-client brainstorm HTTP burst against a DEBUG server."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.middleware.csrf import _get_new_csrf_string  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.accounts.models import LocalUserMapping  # noqa: E402
from apps.brainstorm.models import BrainstormCanvas  # noqa: E402
from apps.prds.models import (  # noqa: E402
    Prd,
    PrdParticipant,
    PrdParticipantRole,
    PrdStatus,
    PrdType,
)

CLIENTS = 20
BASE_URL = os.getenv("BRAINSTORM_LOAD_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EXTERNAL_USER_ID = int(os.getenv("BRAINSTORM_LOAD_USER_ID", "24"))


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent) - 1)]


def print_result(label: str, results: list[tuple[int, float, int, dict]]) -> None:
    durations = [row[1] for row in results]
    statuses = Counter(row[0] for row in results)
    sizes = [row[2] for row in results]
    print(
        f"{label}: status={dict(statuses)}, "
        f"avg={sum(durations) / len(durations):.3f}s, "
        f"p95={percentile(durations, 0.95):.3f}s, "
        f"max={max(durations):.3f}s, "
        f"avg_payload={sum(sizes) / len(sizes):.0f}B"
    )


def make_session(user: LocalUserMapping) -> tuple[str, str, str]:
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    csrf = _get_new_csrf_string()
    cookie = f"{settings.SESSION_COOKIE_NAME}={session.session_key}; csrftoken={csrf}"
    return session.session_key, csrf, cookie


def http_json(
    path: str,
    *,
    cookie: str,
    csrf: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, float, int, dict]:
    raw_body = json.dumps(body).encode() if body is not None else None
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cookie": cookie,
        "X-CSRFToken": csrf,
        **(headers or {}),
    }
    request = Request(
        BASE_URL + path,
        data=raw_body,
        headers=request_headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            status = response.status
    except HTTPError as error:
        raw = error.read()
        status = error.code
    elapsed = time.perf_counter() - started
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw.decode(errors="replace")[:500]}
    return status, elapsed, len(raw), payload


def parallel(callback):
    barrier = threading.Barrier(CLIENTS)

    def synchronized(index):
        barrier.wait(timeout=10)
        return callback(index)

    with ThreadPoolExecutor(max_workers=CLIENTS) as executor:
        return [
            future.result(timeout=45)
            for future in [executor.submit(synchronized, i) for i in range(CLIENTS)]
        ]


def main() -> int:
    if not settings.DEBUG:
        raise RuntimeError("This disposable load smoke test only runs with DEBUG=True.")
    user = LocalUserMapping.objects.filter(external_user_id=EXTERNAL_USER_ID).first()
    created_user = user is None
    if user is None:
        user = LocalUserMapping.objects.create_user(
            EXTERNAL_USER_ID,
            f"load-user-{EXTERNAL_USER_ID}@example.test",
        )
    run_id = uuid.uuid4().hex
    prd = Prd.objects.create(
        title=f"[LOAD TEST] brainstorm {run_id}",
        description="Disposable 20-client HTTP load smoke test",
        deadline=timezone.localdate() + timedelta(days=1),
        prd_type=PrdType.NEW_PRODUCT,
        status=PrdStatus.IN_PROGRESS,
        round_id=None,
        team_id=None,
        creator_user_id=EXTERNAL_USER_ID,
        creation_idempotency_key=f"load-prd-{run_id}",
    )
    PrdParticipant.objects.create(
        prd=prd,
        user_id=EXTERNAL_USER_ID,
        role=PrdParticipantRole.OWNER,
    )
    canvas = BrainstormCanvas.objects.create(
        prd=prd,
        created_by_user_id=EXTERNAL_USER_ID,
        creation_idempotency_key=f"load-canvas-{run_id}",
    )
    sessions = [make_session(user) for _ in range(CLIENTS)]
    api_base = f"/api/v1/prds/{prd.pk}/brainstorm/"
    canvas_headers = {"X-Brainstorm-Canvas-Id": str(canvas.pk)}

    try:
        initial = parallel(
            lambda index: http_json(
                api_base + "canvas/",
                cookie=sessions[index][2],
                csrf=sessions[index][1],
                headers=canvas_headers,
            )
        )
        print_result("initial canvas GET", initial)
        cursors = [row[3].get("data", {}).get("cursor", 0) for row in initial]

        created = parallel(
            lambda index: http_json(
                api_base + "nodes/",
                cookie=sessions[index][2],
                csrf=sessions[index][1],
                method="POST",
                body={
                    "content": f"20-client load note {index}",
                    "color": "yellow",
                    "x": 100 + index * 20,
                    "y": 200 + index * 10,
                    "section_id": None,
                },
                headers={
                    **canvas_headers,
                    "Idempotency-Key": f"load-note-{run_id}-{index}",
                },
            )
        )
        print_result("simultaneous note POST", created)

        events = parallel(
            lambda index: http_json(
                api_base + f"events/?cursor={cursors[index]}",
                cookie=sessions[index][2],
                csrf=sessions[index][1],
                headers=canvas_headers,
            )
        )
        print_result("simultaneous events GET", events)
        event_counts = [len(row[3].get("data", {}).get("events", [])) for row in events]
        print(f"events per client: min={min(event_counts)}, max={max(event_counts)}")

        refreshed = parallel(
            lambda index: http_json(
                api_base + "canvas/",
                cookie=sessions[index][2],
                csrf=sessions[index][1],
                headers=canvas_headers,
            )
        )
        print_result("verification-only full canvas GET (optimized UI skips)", refreshed)
        node_counts = [len(row[3].get("data", {}).get("nodes", [])) for row in refreshed]
        print(f"visible nodes per client: min={min(node_counts)}, max={max(node_counts)}")
        return (
            0
            if all(
                row[0] in {200, 201}
                for group in (initial, created, events, refreshed)
                for row in group
            )
            else 1
        )
    finally:
        for session_key, _, _ in sessions:
            SessionStore(session_key=session_key).delete()
        prd.delete()
        if created_user:
            user.delete()


if __name__ == "__main__":
    raise SystemExit(main())
