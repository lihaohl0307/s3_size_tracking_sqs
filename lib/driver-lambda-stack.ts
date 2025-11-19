import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Code, Function as LambdaFn, Runtime } from 'aws-cdk-lib/aws-lambda';
import { join } from 'path';

interface Props extends cdk.StackProps {
  bucket: Bucket;
  plotApiUrl: string;
}

export class DriverLambdaStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: Props) {
    super(scope, id, props);

    const driverFn = new LambdaFn(this, 'DriverLambda', {
      runtime: Runtime.PYTHON_3_13,
      handler: 'lambda_driver.lambda_handler',
      code: Code.fromAsset(join(__dirname, '..', 'lambdas')),
      environment: {
        REGION: this.region,
        BUCKET_NAME: props.bucket.bucketName,
        SLEEP_SECONDS: '6', // avoid overwriting too quickly
        PLOT_WINDOW: '120',  // seconds
        PLOT_API_URL: props.plotApiUrl,
      },
      timeout: cdk.Duration.seconds(200),
    });

    props.bucket.grantReadWrite(driverFn);
  }
}
