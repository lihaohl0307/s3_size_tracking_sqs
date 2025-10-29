# lambdas/lambda_driver.py
import os
import time
import json
import logging
import urllib.request
from urllib.error import HTTPError, URLError

import boto3

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REGION        = os.environ.get("REGION", "us-east-1")
BUCKET_NAME   = os.environ["BUCKET_NAME"]
SLEEP_BETWEEN = int(os.environ.get("SLEEP_SECONDS", "4"))
PLOT_API_URL  = os.environ["PLOT_API_URL"]         # injected by CDK (PlotLambdaStack output)
PLOT_WINDOW   = int(os.environ.get("PLOT_WINDOW", "30"))

s3 = boto3.client("s3", region_name=REGION)

def _put_text(key: str, text: str):
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=text.encode("utf-8"))
    log.info("PUT s3://%s/%s (%d bytes)", BUCKET_NAME, key, len(text.encode("utf-8")))

def _delete(key: str):
    s3.delete_object(Bucket=BUCKET_NAME, Key=key)
    log.info("DEL s3://%s/%s", BUCKET_NAME, key)

def _call_plot_api(base_url: str, window: int):
    # base_url typically ends with '/dev/' since proxy=true; query string is enough
    full = f"{base_url}?window={window}"
    req = urllib.request.Request(full, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
            return r.status, body
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        log.error("Plot API HTTPError %s, body: %s", e, err_body)
        raise
    except URLError as e:
        log.error("Plot API URLError %s", e)
        raise

def lambda_handler(event, context):
    log.info("Driver start: bucket=%s, api=%s", BUCKET_NAME, PLOT_API_URL)

    # 1) Create assignment1.txt -> 19 bytes (with newline)
    _put_text("assignment1.txt", "Empty Assignment 1\n")
    time.sleep(SLEEP_BETWEEN)

    # 2) Update assignment1.txt -> 28 bytes (with newline)
    _put_text("assignment1.txt", "Empty Assignment 2222222222\n")
    time.sleep(SLEEP_BETWEEN)

    # 3) Delete assignment1.txt
    _delete("assignment1.txt")
    time.sleep(SLEEP_BETWEEN)

    # 4) Create assignment2.txt -> 2 bytes (no newline)
    _put_text("assignment2.txt", "33")

    # Give size-tracking lambda a moment to write to DynamoDB
    time.sleep(1)

    # 5) Trigger plotting lambda via API
    status, body = _call_plot_api(PLOT_API_URL, PLOT_WINDOW)
    log.info("Plot API status=%s body=%s", status, body[:500])

    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "bucket": BUCKET_NAME,
            "plot_api_url": PLOT_API_URL,
            "plot_window_seconds": PLOT_WINDOW,
            "result": body,
        }),
    }
