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

REGION = os.environ.get("REGION", "us-east-1")
BUCKET_NAME = os.environ["BUCKET_NAME"]
SLEEP = int(os.environ.get("SLEEP_SECONDS", "30"))  # long enough to cross CloudWatch periods
PLOT_API_URL = os.environ["PLOT_API_URL"]
PLOT_WINDOW = int(os.environ.get("PLOT_WINDOW", "60"))

s3 = boto3.client("s3", region_name=REGION)


def put_text(key: str, text: str):
    data = text.encode("utf-8")
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=data)
    log.info("PUT s3://%s/%s (%d bytes)", BUCKET_NAME, key, len(data))


def call_plot_api(url: str, window: int):
    full_url = f"{url}?window={window}"
    log.info("Calling plot API: %s", full_url)
    req = urllib.request.Request(full_url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode("utf-8")


def lambda_handler(event, context):
    log.info("Driver start")

    # assignment1 (19 bytes)
    put_text("assignment1.txt", "Empty Assignment 11")
    time.sleep(SLEEP)

    # assignment2 (28 bytes) → should trigger first alarm, Cleaner removes assignment2
    put_text("assignment2.txt", "Empty Assignment 2222222222")
    time.sleep(SLEEP)

    # assignment3 (2 bytes) → should trigger second alarm, Cleaner removes assignment1
    put_text("assignment3.txt", "33")
    time.sleep(SLEEP)

    # call plot API
    try:
        status, body = call_plot_api(PLOT_API_URL, PLOT_WINDOW)
    except Exception as e:
        log.exception("Plot API failed")
        status, body = 500, str(e)

    return {
        "statusCode": status,
        "body": json.dumps({"plot_response": body})
    }
