import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Code, Function as LambdaFn, Runtime, LayerVersion } from 'aws-cdk-lib/aws-lambda';
import { LambdaRestApi, EndpointType } from 'aws-cdk-lib/aws-apigateway';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { join } from 'path';

interface Props extends cdk.StackProps {
  bucket: Bucket;
  table: Table;
  gsiName: string;
  attachMatplotlibLayer?: boolean;
}

export class PlotLambdaStack extends cdk.Stack {
  public readonly restApiUrl: string;

  constructor(scope: Construct, id: string, props: Props) {
    super(scope, id, props);

    let plotLayer: LayerVersion | undefined;
    if (props.attachMatplotlibLayer) {
      plotLayer = new LayerVersion(this, 'MatplotlibLayer', {
        code: Code.fromAsset(join(__dirname, '..', 'layers', 'matplotlib-py313-x86-layer.zip')),
        compatibleRuntimes: [Runtime.PYTHON_3_13],
      });
    }

    const plotFn = new LambdaFn(this, 'PlotLambda', {
      runtime: Runtime.PYTHON_3_13,
      handler: 'lambda_plotting.lambda_handler',
      code: Code.fromAsset(join(__dirname, '..', 'lambdas')),
      environment: {
        REGION: this.region,
        BUCKET_NAME: props.bucket.bucketName,
        TABLE_NAME: props.table.tableName,
        GSI_NAME: props.gsiName,
        PLOT_KEY: 'plots/plot.png',
        PLOT_WINDOW: '10',
      },
      layers: plotLayer ? [plotLayer] : undefined,
      memorySize: 512,
      timeout: cdk.Duration.seconds(45),
    });

    props.table.grantReadData(plotFn);
    props.bucket.grantReadWrite(plotFn);
    plotFn.addToRolePolicy(new PolicyStatement({
      actions: ['s3:PutObject', 's3:GetObject'],
      resources: [props.bucket.arnForObjects('*')],
    }));

    const api = new LambdaRestApi(this, 'PlotApi', {
      handler: plotFn,
      proxy: true,
      endpointConfiguration: { types: [EndpointType.REGIONAL] },
      deployOptions: { stageName: 'dev' },
    });

    this.restApiUrl = api.url;
    new cdk.CfnOutput(this, 'PlotApiUrl', { value: this.restApiUrl });
  }
}
