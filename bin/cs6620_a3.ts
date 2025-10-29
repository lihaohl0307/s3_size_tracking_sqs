#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { StorageStack } from '../lib/storage-stack';
import { SizeTrackingLambdaStack } from '../lib/size-tracking-lambda-stack';
import { PlotLambdaStack } from '../lib/plot-lambda-stack';
import { DriverLambdaStack } from '../lib/driver-lambda-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION || 'us-east-1' };

const storage = new StorageStack(app, 'StorageStack', { env });

const sizeTracking = new SizeTrackingLambdaStack(app, 'SizeTrackingLambdaStack', {
  env,
  table: storage.table,
  gsiName: storage.gsiName,
});

const plot = new PlotLambdaStack(app, 'PlotLambdaStack', {
  env,
  bucket: sizeTracking.bucket,
  table: storage.table,
  gsiName: storage.gsiName,
  attachMatplotlibLayer: true,
});

new DriverLambdaStack(app, 'DriverLambdaStack', {
  env,
  bucket: sizeTracking.bucket,
  plotApiUrl: plot.restApiUrl,
});

// CDK will infer the correct deploy order from refs; no explicit addDependency needed.
