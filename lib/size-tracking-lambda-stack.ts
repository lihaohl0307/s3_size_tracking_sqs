import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Bucket, BlockPublicAccess, BucketEncryption, EventType } from 'aws-cdk-lib/aws-s3';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Code, Function as LambdaFn, Runtime } from 'aws-cdk-lib/aws-lambda';
import { LambdaDestination } from 'aws-cdk-lib/aws-s3-notifications';
import { RemovalPolicy } from 'aws-cdk-lib';
import { join } from 'path';

interface Props extends cdk.StackProps {
  table: Table;
  gsiName: string;
}

export class SizeTrackingLambdaStack extends cdk.Stack {
  public readonly bucket: Bucket;
  public readonly sizeTrackingFn: LambdaFn;

  constructor(scope: Construct, id: string, props: Props) {
    super(scope, id, props);

    // Define the bucket in the SAME stack as the size-tracking lambda
    this.bucket = new Bucket(this, 'TestBucket', {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      autoDeleteObjects: true,              // dev convenience
      removalPolicy: RemovalPolicy.DESTROY, // dev convenience
    });

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
      timeout: cdk.Duration.seconds(30),
      description: 'Triggered by S3 events; computes bucket total and writes a row to DynamoDB',
    });

    // IAM
    this.bucket.grantRead(this.sizeTrackingFn);
    props.table.grantReadWriteData(this.sizeTrackingFn);

    // S3 → Lambda notifications (live on the bucket’s resource in THIS stack)
    this.bucket.addEventNotification(EventType.OBJECT_CREATED, new LambdaDestination(this.sizeTrackingFn));
    this.bucket.addEventNotification(EventType.OBJECT_REMOVED, new LambdaDestination(this.sizeTrackingFn));

    new cdk.CfnOutput(this, 'BucketName', { value: this.bucket.bucketName });
  }
}
