# lambdas/lambda_size_tracking.py
import os
import time
import json
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REGION = os.environ.get("REGION", "us-east-1")
BUCKET_NAME = os.environ["BUCKET_NAME"]
TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

s3 = boto3.client("s3", region_name=REGION)


def _compute_bucket_size(bucket_name: str):
    """
    Computes the total size and object count for the bucket.
    """
    paginator = s3.get_paginator("list_objects_v2")
    total_size, total_count = 0, 0

    for page in paginator.paginate(Bucket=bucket_name):
        for obj in page.get("Contents", []):
            total_size += int(obj.get("Size", 0))
            total_count += 1

    return total_size, total_count


def lambda_handler(event, context):
    log.info("Received SQS event with %d records", len(event.get("Records", [])))

    # Recompute full bucket size each time an S3 event occurs
    size_bytes, object_count = _compute_bucket_size(BUCKET_NAME)
    now_ms = int(time.time() * 1000)

    snapshot = {
        "bucket": BUCKET_NAME,
        "ts": now_ms,
        "size_bytes": size_bytes,
        "object_count": object_count,
    }

    table.put_item(Item=snapshot)

    log.info("Snapshot written: %s", snapshot)

    return {
        "statusCode": 200,
        "body": json.dumps(snapshot)
    }
