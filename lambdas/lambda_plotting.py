# lambdas/lambda_plotting.py
import os
import io
import json
import time
import logging
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key  
from botocore.exceptions import ClientError

# Headless rendering
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REGION      = os.environ.get("REGION", "us-east-1")
BUCKET_NAME = os.environ["BUCKET_NAME"]
TABLE_NAME  = os.environ["TABLE_NAME"]
GSI_NAME    = os.environ["GSI_NAME"]
PLOT_KEY    = os.environ.get("PLOT_KEY", "plots/plot.png")
WINDOW_SEC  = int(os.environ.get("PLOT_WINDOW", "30"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)

def _parse_window(event) -> int:
    """Allow ?window=NN to override default window seconds."""
    try:
        qs = event.get("queryStringParameters") or {}
        if "window" in qs:
            return max(1, int(qs["window"]))
    except Exception:
        pass
    return WINDOW_SEC

def _query_recent_points(bucket: str, window_sec: int):
    now_ms = int(time.time() * 1000)
    start  = now_ms - window_sec * 1000
    resp = table.query(
        KeyConditionExpression=Key("bucket").eq(bucket) & Key("ts").between(start, now_ms),
        ScanIndexForward=True,  # chronological
    )
    items = resp.get("Items", [])
    xs = [int(i["ts"]) for i in items]
    ys = [int(i["size_bytes"]) for i in items]
    return xs, ys

def _query_all_time_max(bucket: str) -> int:
    """Query GSI (bucket, size_bytes) descending to get the max efficiently."""
    resp = table.query(
        IndexName=GSI_NAME,
        KeyConditionExpression=Key("bucket").eq(bucket),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return int(items[0]["size_bytes"]) if items else 0

def _plot(xs, ys, max_size: int, bucket: str):
    fig = plt.figure()
    ax = fig.add_subplot(111)
    if xs and ys:
        ax.plot(xs, ys, marker="o", linestyle="-", label=f"Recent size")
        ax.set_xlim(min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1)
    else:
        ax.plot([], [], label="No points in window")
    ax.axhline(max_size, linestyle="--", label=f"All-time max: {max_size} bytes")
    ax.set_xlabel("timestamp (ms epoch)")
    ax.set_ylabel("size (bytes)")
    ax.legend()
    ax.set_title(f"S3 Bucket Size: {bucket}")
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

def lambda_handler(event, context):
    # Works for API Gateway events and direct Lambda test (no queryStringParameters)
    log.info("Event: %s", json.dumps(event)[:1000])

    window = _parse_window(event)
    try:
        xs, ys = _query_recent_points(BUCKET_NAME, window)
        max_size = _query_all_time_max(BUCKET_NAME)
    except ClientError as e:
        log.exception("DynamoDB query failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "where": "dynamodb"})
        }

    buf = _plot(xs, ys, max_size, BUCKET_NAME)

    # Write plot to S3
    try:
        s3.put_object(Bucket=BUCKET_NAME, Key=PLOT_KEY, Body=buf.getvalue(), ContentType="image/png")
    except ClientError as e:
        log.exception("Failed to upload plot to s3://%s/%s", BUCKET_NAME, PLOT_KEY)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "where": "s3.put_object"})
        }

    # Presign URL for convenience (requires s3:GetObject permission)
    try:
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": PLOT_KEY},
            ExpiresIn=300
        )
    except Exception:
        presigned = None

    body = {
        "bucket": BUCKET_NAME,
        "plot_key": PLOT_KEY,
        "window_seconds": window,
        "points": len(xs),
        "all_time_max_bytes": max_size,
        "s3_uri": f"s3://{BUCKET_NAME}/{PLOT_KEY}",
        "presigned_url": presigned,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    # If via API Gateway, return JSON
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }
