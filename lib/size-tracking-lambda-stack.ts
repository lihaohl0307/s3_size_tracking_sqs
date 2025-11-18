import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  Bucket,
  BlockPublicAccess,
  BucketEncryption,
  EventType,
} from 'aws-cdk-lib/aws-s3';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import {
  Code,
  Function as LambdaFn,
  Runtime,
} from 'aws-cdk-lib/aws-lambda';
import {
  SnsDestination,
} from 'aws-cdk-lib/aws-s3-notifications';
import { RemovalPolicy, Duration } from 'aws-cdk-lib';
import { join } from 'path';

import * as sns from 'aws-cdk-lib/aws-sns';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as subs from 'aws-cdk-lib/aws-sns-subscriptions';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cw from 'aws-cdk-lib/aws-cloudwatch';
import * as cwActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';

interface Props extends cdk.StackProps {
  table: Table;
  gsiName: string;
}

export class SizeTrackingLambdaStack extends cdk.Stack {
  public readonly bucket: Bucket;
  public readonly sizeTrackingFn: LambdaFn;

  constructor(scope: Construct, id: string, props: Props) {
    super(scope, id, props);

    // 1) S3 bucket
    this.bucket = new Bucket(this, 'TestBucket', {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      autoDeleteObjects: true,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // 2) SNS topic for S3 events
    const s3EventsTopic = new sns.Topic(this, 'S3EventsTopic');

    // 3) Two SQS queues (fan-out consumers)
    const sizeTrackingQueue = new sqs.Queue(this, 'SizeTrackingQueue', {
      visibilityTimeout: Duration.seconds(60),
    });

    const loggingQueue = new sqs.Queue(this, 'LoggingQueue', {
      visibilityTimeout: Duration.seconds(60),
    });

    // SNS → SQS subscriptions
    s3EventsTopic.addSubscription(new subs.SqsSubscription(sizeTrackingQueue));
    s3EventsTopic.addSubscription(new subs.SqsSubscription(loggingQueue));

    // 4) S3 → SNS notifications (instead of S3 → Lambda)
    this.bucket.addEventNotification(
      EventType.OBJECT_CREATED,
      new SnsDestination(s3EventsTopic),
    );
    this.bucket.addEventNotification(
      EventType.OBJECT_REMOVED,
      new SnsDestination(s3EventsTopic),
    );

    // 5) Size-tracking Lambda (now triggered by SQS)
    this.sizeTrackingFn = new LambdaFn(this, 'SizeTrackingLambda', {
      runtime: Runtime.PYTHON_3_13,
      handler: 'lambda_size_tracking.lambda_handler',
      code: Code.fromAsset(join(__dirname, '..', 'lambdas')),
      environment: {
        REGION: this.region,
        BUCKET_NAME: this.bucket.bucketName,
        TABLE_NAME: props.table.tableName,
        GSI_NAME: props.gsiName,
      },
      timeout: Duration.seconds(30),
      description:
        'Consumes SQS messages for S3 events; recomputes bucket total size and writes a row to DynamoDB',
    });

    // permissions for size tracking
    this.bucket.grantRead(this.sizeTrackingFn);
    props.table.grantReadWriteData(this.sizeTrackingFn);
    sizeTrackingQueue.grantConsumeMessages(this.sizeTrackingFn);

    // size tracking lambda consumes messages from SQS
    this.sizeTrackingFn.addEventSource(
      new SqsEventSource(sizeTrackingQueue, {
        batchSize: 10,
      }),
    );

    // 6) Logging Lambda (other consumer)
    const loggingFn = new LambdaFn(this, 'LoggingLambda', {
      runtime: Runtime.PYTHON_3_13,
      handler: 'lambda_logging.lambda_handler',
      code: Code.fromAsset(join(__dirname, '..', 'lambdas')),
      environment: {
        REGION: this.region,
      },
      timeout: Duration.seconds(30),
      description:
        'Consumes SQS messages for S3 events and logs {object_name, size_delta} JSON to CloudWatch Logs',
    });

    loggingQueue.grantConsumeMessages(loggingFn);
    loggingFn.addEventSource(
      new SqsEventSource(loggingQueue, {
        batchSize: 10,
      }),
    );

    // Allow logging lambda to call filter_log_events on its own log group
    loggingFn.addToRolePolicy(
      new PolicyStatement({
        actions: ['logs:FilterLogEvents'],
        resources: ['*'], // you can restrict to specific log group if desired
      }),
    );

    // 7) Metric filter on Logging Lambda's log group.
    // Use the log group that CDK automatically creates for the function.
    const loggingLogGroup = loggingFn.logGroup;


    const metricFilter = new logs.MetricFilter(
      this,
      'ObjectSizeDeltaMetricFilter',
      {
        logGroup: loggingLogGroup,
        metricNamespace: 'Assignment4App',
        metricName: 'TotalObjectSize',
        // Match any log where size_delta exists and use its value
        filterPattern: logs.FilterPattern.exists('$.size_delta'),
        metricValue: '$.size_delta',
        defaultValue: 0,
      },
    );

    const totalSizeMetric = metricFilter.metric({
      statistic: 'Sum',
      period: Duration.seconds(30), // adjust for easier testing if desired
    });

    // 8) Cleaner Lambda (invoked by CloudWatch alarm)
    const cleanerFn = new LambdaFn(this, 'CleanerLambda', {
      runtime: Runtime.PYTHON_3_13,
      handler: 'lambda_cleaner.lambda_handler',
      code: Code.fromAsset(join(__dirname, '..', 'lambdas')),
      environment: {
        REGION: this.region,
        BUCKET_NAME: this.bucket.bucketName,
      },
      timeout: Duration.seconds(60),
      description:
        'Deletes the largest object from TestBucket when total size crosses threshold',
    });

    this.bucket.grantReadWrite(cleanerFn);

    // 9) Alarm on TotalObjectSize metric → triggers Cleaner
    const alarm = new cw.Alarm(this, 'TotalObjectSizeAlarm', {
      metric: totalSizeMetric,
      evaluationPeriods: 1,
      threshold: 20,
      comparisonOperator: cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cw.TreatMissingData.NOT_BREACHING,
    });

    alarm.addAlarmAction(new cwActions.LambdaAction(cleanerFn));

    new cdk.CfnOutput(this, 'BucketName', { value: this.bucket.bucketName });
  }
}
