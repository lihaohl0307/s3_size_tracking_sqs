Great — I’ll write you a **brand-new, clean, polished, professional README** that matches your **current architecture** (SNS → SQS → SizeTracking + Logging + MetricFilter + Alarm → Cleaner + Plot + Driver).
This replaces the old README completely.

👇 **You can copy-paste this as README.md.**

---

# S3 Size Tracking & Auto-Cleaning System (AWS CDK v2)

This project implements a fully event-driven AWS microservice system for:

* Tracking total size of an S3 bucket over time
* Logging per-object size changes
* Publishing CloudWatch metrics from logs
* Auto-deleting the largest object when bucket growth exceeds a threshold
* Plotting historical bucket size trends
* Running controlled demo flows via a driver Lambda

All infrastructure is defined using **AWS CDK v2 (TypeScript)** and deployed as four logically separated stacks.

---

# 📐 High-Level Architecture

```
                    ┌─────────────────────────┐
                    │     StorageStack        │
                    │  DynamoDB SizeHistory   │
                    │  + GSI (bucket,size)    │
                    └───────────┬─────────────┘
                                │
                      (read/write snapshots)
                                │
               ┌────────────────▼─────────────────┐
               │    SizeTrackingLambdaStack       │
               │                                   │
               │  TestBucket (S3)                  │
               │  SNS Topic (fanout)               │
               │  SQS Queue A → SizeTracking Lambda│
               │  SQS Queue B → Logging Lambda     │
               │  Logging LogGroup + MetricFilter  │
               │  CloudWatch Alarm → Cleaner Lambda│
               └───────────┬──────────────────────┘
                           │
                      (S3 read/write)
             ┌─────────────▼────────────────────────┐
             │           PlotLambdaStack             │
             │                                       │
             │  PlotLambda (queries DynamoDB, draws  │
             │  PNG, writes to S3)                   │
             │  API Gateway /dev → PlotLambda        │
             └─────────────┬────────────────────────┘
                           │
                      (S3 read/write + GET Plot API)
             ┌─────────────▼────────────────────────┐
             │         DriverLambdaStack             │
             │  DriverLambda: creates sample objects │
             │  waits between ops, triggers S3 events│
             │  calls Plot API at end                │
             └───────────────────────────────────────┘
```

---

# 🧱 Stack Breakdown

## 1) **StorageStack**

Contains only the persistent data store:

* DynamoDB table (`bucket` + `ts`)
* GSI `(bucket, size_bytes)` for fast “max size” lookups

Used by both SizeTracking Lambda and Plot Lambda.

---

## 2) **SizeTrackingLambdaStack**

This is the main event-processing stack:

### Includes:

* **S3 Bucket** (`TestBucket`)
* **SNS Topic** for S3 events fan-out
* **SQS Queue A** → SizeTrackingLambda
* **SQS Queue B** → LoggingLambda
* **SizeTracking Lambda**

  * triggered by SQS fan-out
  * recomputes the entire bucket size
  * writes a snapshot to DynamoDB
* **Logging Lambda**

  * extracts `{object_name, size_delta}` from SNS/S3 notifications
  * logs JSON to its own log group
* **LogGroup + MetricFilter**

  * Filter pattern extracts `$.size_delta`
  * Publishes metric:
    **Namespace**: `Assignment4App`
    **Metric**: `TotalObjectSize`
* **CloudWatch Alarm**

  * `Sum(size_delta)` > 20 (single evaluation period)
  * ALARM → invokes Cleaner
* **Cleaner Lambda**

  * lists objects
  * deletes the **largest object**
  * reduces bucket total until metric drops

### Why fan-out (SNS → SQS)?

* Loosely coupling
* Independent consumers (tracking vs logging)
* Reliable delivery with retry/backoff
* Lambda concurrency isolation

---

## 3) **PlotLambdaStack**

Contains:

* **PlotLambda**

  * Queries latest N-second snapshots from DynamoDB
  * Queries GSI for all-time max
  * Plots line graph using matplotlib layer
  * Writes PNG (`plots/plot.png`) to the S3 bucket
* **API Gateway**

  * `/dev/` endpoint proxies directly to PlotLambda

Exports `PlotApiUrl` for use by DriverLambda.

---

## 4) **DriverLambdaStack**

Demo / end-to-end test driver:

* Creates objects of different sizes
* Sleeps between operations to ensure CloudWatch periods advance
* Lets SizeTracking + Logging → Metric → Alarm → Cleaner trigger naturally
* Calls Plot API at the end and logs results

---

# 🗂 Project Structure

```
project-root/
├── bin/
│   └── app.ts                  # Instantiates 4 stacks
├── lib/
│   ├── storage-stack.ts
│   ├── size-tracking-lambda-stack.ts
│   ├── plot-lambda-stack.ts
│   └── driver-lambda-stack.ts
├── lambdas/
│   ├── lambda_size_tracking.py
│   ├── lambda_logging.py
│   ├── lambda_cleaner.py
│   ├── lambda_plotting.py
│   └── lambda_driver.py
├── layers/
│   └── matplotlib-py313-x86-layer.zip
├── package.json
├── tsconfig.json
└── cdk.json
```

---

# 🚀 Deploy Instructions

### Install dependencies

```bash
npm install
npm run build
```

### Bootstrap account/region (one-time)

```bash
npx cdk bootstrap aws://<ACCOUNT>/<REGION>
```

### Synthesize / view changes

```bash
npx cdk synth
npx cdk diff
```

### Deploy all stacks

```bash
npx cdk deploy --all
```

---

# ✔️ Verifying the Pipeline

### 1. Run Driver Lambda

Invoke `DriverLambda` manually from Console.
It will:

* create several S3 objects
* trigger fan-out event flow
* generate size snapshots in DynamoDB
* call the Plot API

### 2. Check DynamoDB table

You will see rows like:

| bucket | ts | object_count | size_bytes |
| ------ | -- | ------------ | ---------- |
| bucket | …  | 1            | 19         |
| bucket | …  | 2            | 46         |
| bucket | …  | 2            | 21         |
| bucket | …  | 3            | 45504      |

### 3. Check Logging Lambda log group

See entries like:

```json
{"bucket":"...","object_name":"assignment1.txt","size_delta":19}
{"object_name":"assignment2.txt","size_delta":28}
{"object_name":"assignment1.txt","size_delta":-19}
```

### 4. CloudWatch Metric

`Assignment4App / TotalObjectSize`
Should show positive deltas and occasional negatives (Cleaner deletes).

### 5. CloudWatch Alarm

History will show:

* `OK → ALARM` (threshold crossed)
* Action: Lambda invoked
* `ALARM → OK` after Cleaner deletes largest file

### 6. Cleaner Lambda Logs

You will see entries like:

```
[CLEANER] Alarm triggered with event: {...}
[CLEANER] Largest object: s3://bucket/assignment2.txt (size=x)
[CLEANER] Deleted object
```

### 7. Plot Output

Check bucket for:

```
plots/plot.png
```

Or hit:

```
GET <PlotApiUrl>?window=20
```

to regenerate.

---

# 🧹 Cleanup

```bash
npx cdk destroy --all
```

Because buckets use `autoDeleteObjects: true` and all stacks use `RemovalPolicy.DESTROY`, teardown is clean.

---

# 🐛 Troubleshooting

### Alarm only fires once

This is expected due to:

* CloudWatch metric period boundaries
* Positive/negative `size_delta` consolidation in the same window
* Alarm only triggers on **OK → ALARM**, not ALARM → ALARM

Explained fully in design notes.

### Infinite rollback loops

Delete orphan CloudWatch log groups:

```
/aws/lambda/SizeTrackingLambdaStack-LoggingLambda*
/aws/lambda/SizeTrackingLambdaStack-CleanerLambda*
```

They must not pre-exist or CDK fails to create them.

---
