from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import boto3


def _get_json(url: str, token: str) -> dict:
    req = Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req, timeout=10) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _parse_time(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish queue depth/age to CloudWatch custom metrics.")
    parser.add_argument("--base-url", default=os.getenv("OPS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("OPS_BEARER_TOKEN", ""))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    parser.add_argument("--namespace", default=os.getenv("CW_QUEUE_NAMESPACE", "CropperHub/Queue"))
    parser.add_argument("--cluster", default=os.getenv("ECS_CLUSTER", "cropperhub-cluster"))
    parser.add_argument("--service", default=os.getenv("ECS_WORKER_SERVICE", "cropperhub-worker-svc"))
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    payload = _get_json(f"{base_url}/api/admin/ops/metrics", args.token)
    queue = payload.get("queue") or {}
    queued = int(queue.get("queued") or 0)
    running = int(queue.get("running") or 0)
    oldest_age = int(queue.get("oldest_queued_age_sec") or 0)
    oldest_at = _parse_time(str(queue.get("oldest_queued_at") or ""))

    # Fallback computation when API version does not expose oldest_queued_age_sec yet.
    if oldest_age <= 0 and oldest_at is not None:
        oldest_age = max(0, int((datetime.now(timezone.utc) - oldest_at).total_seconds()))

    cloudwatch = boto3.client("cloudwatch", region_name=args.region)
    dimensions = [
        {"Name": "ClusterName", "Value": args.cluster},
        {"Name": "ServiceName", "Value": args.service},
    ]
    cloudwatch.put_metric_data(
        Namespace=args.namespace,
        MetricData=[
            {
                "MetricName": "QueuedDepth",
                "Dimensions": dimensions,
                "Timestamp": datetime.now(timezone.utc),
                "Value": float(queued),
                "Unit": "Count",
            },
            {
                "MetricName": "OldestQueuedAgeSec",
                "Dimensions": dimensions,
                "Timestamp": datetime.now(timezone.utc),
                "Value": float(oldest_age),
                "Unit": "Seconds",
            },
            {
                "MetricName": "RunningJobs",
                "Dimensions": dimensions,
                "Timestamp": datetime.now(timezone.utc),
                "Value": float(running),
                "Unit": "Count",
            },
        ],
    )
    print(
        f"published namespace={args.namespace} queued={queued} running={running} oldest_queued_age_sec={oldest_age}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
