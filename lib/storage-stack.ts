import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Table, AttributeType, BillingMode, ProjectionType } from 'aws-cdk-lib/aws-dynamodb';
import { RemovalPolicy } from 'aws-cdk-lib';

export class StorageStack extends cdk.Stack {
  public readonly table: Table;
  public readonly gsiName = 'GSI_ByBucketSize';

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.table = new Table(this, 'SizeHistoryTable', {
      partitionKey: { name: 'bucket', type: AttributeType.STRING },
      sortKey:      { name: 'ts',     type: AttributeType.NUMBER },
      billingMode: BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.table.addGlobalSecondaryIndex({
      indexName: this.gsiName,
      partitionKey: { name: 'bucket', type: AttributeType.STRING },
      sortKey:      { name: 'size_bytes', type: AttributeType.NUMBER },
      projectionType: ProjectionType.ALL,
    });

    new cdk.CfnOutput(this, 'TableName', { value: this.table.tableName });
    new cdk.CfnOutput(this, 'GsiName',   { value: this.gsiName });
  }
}
