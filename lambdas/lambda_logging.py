# lambdas/lambda_logging.py
import os
import json
import logging
import boto3
from datetime import datetime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REGION = os.environ.get("REGION", "us-east-1")

logs_client = boto3.client("logs", region_name=REGION)


def lambda_handler(event, context):
    """
    This lambda receives messages from SQS.
    Each message body contains an SNS notification, which contains an S3 event.
    It extracts (object_name, size_delta) and prints a JSON line.
    """

    for record in event.get("Records", []):
        sns_msg = json.loads(record["body"])
        sns_body = json.loads(sns_msg["Message"])

        for s3_event in sns_body.get("Records", []):
            bucket_name = s3_event["s3"]["bucket"]["name"]
            key = s3_event["s3"]["object"]["key"]
            event_name = s3_event["eventName"]

            # Determine size delta for create or delete
            if event_name.startswith("ObjectCreated"):
                size = int(s3_event["s3"]["object"]["size"])
                size_delta = size
            else:
                # For deletions, size must be fetched from logs (assignment requirement)
                size_delta = -1

            payload = {
                "bucket": bucket_name,
                "object_name": key,
                "size_delta": size_delta,
                "event_name": event_name
            }

            # This printed JSON is parsed by the CloudWatch Metric Filter
            print(json.dumps(payload))

            log.info("[LOGGING] Event processed: %s", json.dumps(payload))
