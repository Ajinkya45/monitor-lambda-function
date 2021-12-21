**Monitor Lambda Functions in AWS Account**

AWS Lambda function logs execution statistics of an invocation in cloudwatch log group associated with lambda function

Example (with initialization duration)-
```
REPORT RequestId: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx	Duration: 7057.72 ms	Billed Duration: 7058 ms	Memory Size: 128 MB	Max Memory Used: 74 MB	Init Duration: 753.14 ms	
```

Example (without initialization duration))
```
REPORT RequestId: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx	Duration: 306853.55 ms	Billed Duration: 306854 ms	Memory Size: 128 MB	Max Memory Used: 69 MB	
```

Created [direct subscription with AWS ElasticSearch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_OpenSearch_Stream.html) on lambda function log group to extract **Report** line 

Filter pattern used - ```Report```

As part of subscription, a lambda function is created in AWS account with name **LogsToElasticsearch_<es-cluster-name>** that takes care of sending indexing request to selected elasticsearch cluster

Since the extrated line from cloudwatch log group is simple TAB delimited data, I extracted important information such as **Billed Duration**, **Max memory used** and **initialization duration** using Elasticsearch [ingest pipeline](https://www.elastic.co/guide/en/elasticsearch/reference/master/ingest.html) feature. Ingest pipelines let you perform common transformations on your data before indexing.

Ingest pipeline script is available in **ingest-pipeline.json** file

Created kibana dashboard to visualize execution statistics of all the lambda functions in AWS account

<iframe src="https://search-new-domain-hv5z4dbp4nkgacx32iwvixrudu.us-east-1.es.amazonaws.com/_plugin/kibana/goto/97b11ec39e435fe3b75370faf57cfc78?security_tenant=global" height="600" width="800"></iframe>


Automated the process of creating subscription filter on new lambda function log group using another lambda function that checks for new lambda function in AWS account and create subscription filter if it do not exist (CreateSubscriptionFilter.py)