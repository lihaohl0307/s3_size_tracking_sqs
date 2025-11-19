import os
import json
import time
import urllib.parse

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("REGION", "us-east-1")

logs_client = boto3.client("logs", region_name=REGION)


def _lookup_created_size(log_group_name: str, bucket: str, key: str) -> int | None:
    """
    Look in this lambda's own log group for the most recent ObjectCreated log
    for the given key, and return its size (bytes).
    """
    # Look back 1 hour but start from a bit before the current time to account for any clock skew
    start_ms = int((time.time() - 3600) * 1000)

    print(f"[LOOKUP] === STARTING LOOKUP for key={key} ===")
    print(f"[LOOKUP] Log group: {log_group_name}")
    print(f"[LOOKUP] Start time: {start_ms} ({time.ctime(start_ms/1000)})")
    
    # Try multiple times with increasing delays
    for attempt in range(3):
        print(f"[LOOKUP] Attempt {attempt + 1}/3")
        
        try:
            # Get recent log events with pagination support
            resp = logs_client.filter_log_events(
                logGroupName=log_group_name,
                startTime=start_ms,
                limit=1000,  # Get more events
            )
        except ClientError as e:
            print(f"[LOOKUP] filter_log_events failed: {e}")
            if attempt < 2:
                time.sleep(2)
                continue
            return None

        events = resp.get("events", [])
        print(f"[LOOKUP] Retrieved {len(events)} total log events")

        # Sort by timestamp (newest first to get the most recent creation)
        events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        found_creation_size = None
        json_events_examined = 0
        
        for i, ev in enumerate(events):
            msg = ev.get("message", "").strip()
            timestamp = ev.get("timestamp", 0)
            
            # Skip Lambda runtime and debug messages
            if (msg.startswith(('START RequestId:', 'END RequestId:', 'REPORT RequestId:', 
                               '[LOOKUP]', '[LOGGING]')) or
                'RequestId:' in msg):
                continue
                
            # Try to parse as JSON
            try:
                data = json.loads(msg)
                json_events_examined += 1
                
                # Print more events for debugging and include key match info
                if json_events_examined <= 20:
                    obj_name = data.get("object_name", "")
                    event_name = data.get("event_name", "")
                    size_delta = data.get("size_delta", "")
                    is_match = obj_name == key
                    print(f"[LOOKUP] JSON event {json_events_examined}: key='{obj_name}' (match:{is_match}), event='{event_name}', size_delta={size_delta}")
                
            except Exception as e:
                if json_events_examined < 5:  # Only show first few parsing errors
                    print(f"[LOOKUP] Failed to parse: {msg[:100]}...")
                continue

            # Check if this is an ObjectCreated event for our key
            event_name = data.get("event_name", "")
            object_name = data.get("object_name", "")
            size_delta = data.get("size_delta")
            
            if (object_name == key and 
                event_name.startswith("ObjectCreated") and 
                size_delta is not None):
                
                try:
                    size = int(size_delta)
                    if size > 0:
                        found_creation_size = size
                        event_time = time.ctime(timestamp/1000)
                        print(f"[LOOKUP] ✓ FOUND ObjectCreated for {key}: size={size}, time={event_time}")
                        break  # Take the most recent one
                except Exception as e:
                    print(f"[LOOKUP] Error parsing size_delta {size_delta}: {e}")

        print(f"[LOOKUP] Examined {json_events_examined} JSON events")
        
        if found_creation_size is not None:
            print(f"[LOOKUP] Success on attempt {attempt + 1}: {found_creation_size}")
            break
        else:
            print(f"[LOOKUP] Attempt {attempt + 1} failed, no creation event found")
            if attempt < 2:
                print(f"[LOOKUP] Waiting 5 seconds before retry...")
                time.sleep(5)
    
    print(f"[LOOKUP] Final result for {key}: {found_creation_size}")
    print(f"[LOOKUP] === LOOKUP COMPLETE ===")
    
    return found_creation_size


def _handle_s3_record(s3rec: dict, log_group_name: str):
    """Handle a single S3 event record."""
    bucket = s3rec["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(s3rec["s3"]["object"]["key"])
    event_name = s3rec["eventName"]

    print(f"")  # Empty line for readability
    print(f"[LOGGING] ==========================================")
    print(f"[LOGGING] Processing: {event_name}")
    print(f"[LOGGING] Key: {key}")
    print(f"[LOGGING] Bucket: {bucket}")

    if event_name.startswith("ObjectCreated"):
        size = int(s3rec["s3"]["object"].get("size", 0))
        size_delta = size
        print(f"[LOGGING] ObjectCreated - Size from S3 event: {size}")

    elif event_name.startswith("ObjectRemoved"):
        print(f"[LOGGING] ObjectRemoved - Need to lookup original size")
        
        # Longer delay to ensure logs are available for searching
        print(f"[LOGGING] Waiting 10 seconds for log availability...")
        time.sleep(10)
        
        created_size = _lookup_created_size(log_group_name, bucket, key)
        if created_size is None or created_size <= 0:
            print(f"[LOGGING] ❌ Could not find creation size for {key} - using -1")
            size_delta = -1
        else:
            size_delta = -created_size
            print(f"[LOGGING] ✓ Found creation size {created_size} - using size_delta={size_delta}")

    else:
        print(f"[LOGGING] Ignoring event type: {event_name}")
        return

    # Create the JSON payload for the metric filter
    payload = {
        "bucket": bucket,
        "object_name": key,
        "size_delta": size_delta,
        "event_name": event_name,
    }
    
    json_line = json.dumps(payload)
    print(f"[LOGGING] Metric filter payload: {json_line}")
    print(json_line)  # This plain JSON line is what the metric filter reads
    print(f"[LOGGING] ==========================================")


def lambda_handler(event, context):
    """Logging Lambda entry point."""
    log_group_name = context.log_group_name
    records = event.get("Records", [])
    
    print(f"")
    print(f"===============================================")
    print(f"[LOGGING] LAMBDA INVOCATION START")
    print(f"[LOGGING] Timestamp: {time.ctime()}")
    print(f"[LOGGING] Log group: {log_group_name}")
    print(f"[LOGGING] Number of SQS records: {len(records)}")
    print(f"===============================================")

    for i, record in enumerate(records):
        print(f"[LOGGING] --- Processing SQS record {i+1}/{len(records)} ---")
        
        try:
            # Parse SQS -> SNS -> S3 event chain
            body = json.loads(record["body"])
            sns_msg = json.loads(body["Message"])
            
            s3_records = sns_msg.get("Records", [])
            print(f"[LOGGING] Found {len(s3_records)} S3 records in SNS message")
            
        except Exception as e:
            print(f"[LOGGING] ❌ Failed to parse SQS record: {e}")
            print(f"[LOGGING] Record body: {record.get('body', 'N/A')[:500]}")
            continue

        for j, s3rec in enumerate(s3_records):
            print(f"[LOGGING] Processing S3 record {j+1}/{len(s3_records)}")
            try:
                _handle_s3_record(s3rec, log_group_name)
            except Exception as e:
                print(f"[LOGGING] ❌ Error handling S3 record: {e}")
                print(f"[LOGGING] S3 record: {json.dumps(s3rec, indent=2)}")

    print(f"")
    print(f"===============================================")
    print(f"[LOGGING] LAMBDA INVOCATION COMPLETE")
    print(f"===============================================")
    
    return {"statusCode": 200}