# lambdas/lambda_cleaner.py
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REGION = os.environ.get("REGION", "us-east-1")
BUCKET_NAME = os.environ["BUCKET_NAME"]

s3 = boto3.client("s3", region_name=REGION)


def _find_largest_object(bucket: str):
    """
    Iterate all objects in the bucket and return the one with the largest size.
    Returns a dict { "Key": key, "Size": size } or None if the bucket is empty.
    """
    paginator = s3.get_paginator("list_objects_v2")
    largest = None

    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            size = int(obj.get("Size", 0))
            key = obj.get("Key")

            if largest is None or size > largest["Size"]:
                largest = {"Key": key, "Size": size}

    return largest


def lambda_handler(event, context):
    # Log the CloudWatch alarm event
    log.warning(
        "[CLEANER] Alarm triggered. Cleaner invoked with event: %s",
        json.dumps(event)[:500]
    )

    # Find the largest object in the bucket
    largest = _find_largest_object(BUCKET_NAME)

    if not largest:
        log.warning("[CLEANER] Bucket is empty, nothing to delete.")
        return {"statusCode": 200, "body": json.dumps({"deleted": None})}

    key = largest["Key"]
    size = largest["Size"]

    log.warning(
        "[CLEANER] Largest object detected: s3://%s/%s (size=%d)",
        BUCKET_NAME, key, size
    )

    # Delete the object
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
        log.warning(
            "[CLEANER] Deleted object: s3://%s/%s (size=%d)",
            BUCKET_NAME, key, size
        )
    except ClientError:
        log.exception("[CLEANER] Failed to delete object %s", key)
        raise

    return {
        "statusCode": 200,
        "body": json.dumps({"deleted_key": key, "deleted_size": size})
    }
