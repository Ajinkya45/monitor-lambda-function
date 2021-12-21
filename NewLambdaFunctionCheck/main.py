######################################################################################################
## 1. list all lambda functions                                                                     ##
## 2. check lambda function count against count of lambdas in DDB table                             ##
## 3. if lambda function count is more than DDB item count then check for subscription on new       ##
##    lambda function log group and add new lambda to DDB table                                     ##
## 4. if lambda function count is less than DDB item count then delete lambda entry from DDB table  ##
######################################################################################################

import os
import boto3
import botocore

ddb_client = boto3.client("dynamodb")
lambda_client = boto3.client("lambda")
logs_client = boto3.client("logs")
table_name = os.environ['table_name']
filter_name = os.environ['filter_name']

def lambda_handler(event, context):
    # list all available lambda functions in AWS account in given region
    functions = get_lambda_functions()
    # remove the lambda function that is used with subscription to avoid loop
    functions.remove("LogsToElasticsearch_new-domain")

    # Get all lambda function entries from DDB table
    items = get_ddb_items()

    # check if there are any new lambda function created since last run of this code
    new_functions = set(functions).difference(items)

    # check if any lambda function is deleted since last run of this code
    delete_items = set(items).difference(functions)

    dynamodb = boto3.resource("dynamodb")
    my_table = dynamodb.Table(table_name)

    if len(new_functions) > 0:
        function_subscription_list = create_log_subscription(new_functions)

        with my_table.batch_writer() as batch:
            for func in function_subscription_list:
                batch.put_item(
                    Item={
                        'functionName': func['function'],
                        'subscription': func['subscription']
                    }
                )
    else:
        print(f'No new function to add to DDB table')
    
    if len(delete_items) > 0:
        delete_log_subscription(delete_items)

        with my_table.batch_writer() as batch:
            for item in delete_items:
                batch.delete_item(
                    Key={
                        'functionName': item
                    }
                )

    else:
        print(f'Nothing to delete from DDB table')

def get_lambda_functions():
    next_marker = False
    functions = []
    
    response = lambda_client.list_functions()

    [functions.append(func["FunctionName"]) for func in response["Functions"]]

    # check if additional functions are avialble or not
    if 'NextMarker' in response.keys():
        next_marker = True
    
    while(next_marker):
        response = lambda_client.list_functions(
            #FunctionVersion='ALL',
            Marker = response["NextMarker"]
        )

        [functions.append(func["FunctionName"]) for func in response["Functions"]]

        if 'NextMarker' not in response.keys():
            next_marker = False

    print(f'Function count : {len(functions)}')

    return functions

def get_ddb_items():
    ddb_items = []

    additional_results = False
    if check_if_ddb_exist():
        
        scan_response = ddb_client.scan(
            TableName=table_name,
            Select="SPECIFIC_ATTRIBUTES",
            ProjectionExpression="functionName,subscription"
        )
        # append the function name to list where subscription filter is already created
        if len(scan_response['Items']) > 0:
            [ddb_items.append(Item['functionName']['S']) for Item in scan_response['Items'] if Item['subscription']['BOOL'] == True]

        # check if additional items are available in table or not
        if 'LastEvaluatedKey' in scan_response.keys():
            additional_results = True

        while(additional_results):

            scan_response = ddb_client.scan(
                TableName=table_name,
                Select="SPECIFIC_ATTRIBUTES",
                ProjectionExpression="functionName,subscription",
                ExclusiveStartKey={
                    "functionName": {
                        "S": scan_response['LastEvaluatedKey']['functionName']['S']                    
                    }
                }
            )

            if 'LastEvaluatedKey' not in scan_response.keys():
                additional_results = False
        
            if len(scan_response['Items']) > 0:
                [ddb_items.append(Item['functionName']['S']) for Item in scan_response['Items'] if Item['subscription']['BOOL'] == True]

    else:
        ddb_create_table()
        return get_ddb_items()

    print(f'Item count : {len(ddb_items)}')

    return ddb_items

def check_if_ddb_exist():

    try:
        response = ddb_client.describe_table(
            TableName=table_name
        )
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == "ResourceNotFoundException":
            return False
        else:
            print(f"retryable error. Retrying describe request - {error.response['Error']['Code']}")
            return check_if_ddb_exist()
    
    return True
            

def ddb_create_table():

    create_response = ddb_client.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {
                'AttributeName': 'functionName',
                'AttributeType': 'S'
            }
        ],
        KeySchema=[
            {
                'AttributeName': 'functionName',
                'KeyType': 'HASH'
            }
        ],
        BillingMode='PROVISIONED',
        ProvisionedThroughput={
            'ReadCapacityUnits': 1,
            'WriteCapacityUnits': 1
        }
    )

    if create_response["TableDescription"]["TableStatus"] == "CREATING":
        ddb_table_exist_waiter = ddb_client.get_waiter('table_exists')

        # DDB table waiter feature to wiat until DDB table is in active status
        ddb_table_exist_waiter.wait(
            TableName=table_name,
            WaiterConfig={
                'Delay': 10,
                'MaxAttempts': 10
            }
        )

        print(f"table created")

def check_if_function_exist_in_ddb(func):

    item_response = ddb_client.get_item(
        TableName=table_name,
        Key={
            'functionName': {
                'S': func["functionName"]
            }
        }
    )

    if 'Item' in item_response.keys():
        return True
    else:
        return False

def create_batch_requests(functions, items):
    requests = []
    put_request =  {'PutRequest': {'Item': {}}}
    delete_request =  {'DeleteRequest': {'Key': {}}}

    for func in functions:
        put_request["PutRequest"]["Item"].update({"functionName": {'S' : func}})
        requests.append(put_request)

    for item in items:
        delete_request["DeleteRequest"]["Key"].update({"functionName": {'S' : item}})
        requests.append(delete_request)

    return requests

def create_log_subscription(functions):
    lambda_destination = os.environ['lambda_arn']
    log_group_prefix = "/aws/lambda/"
    function_subscription_list = []

    for func in functions:
        log_group_description = logs_client.describe_log_groups(
            logGroupNamePrefix = log_group_prefix + func
        )

        # check if log group exist or not
        if len(log_group_description['logGroups']) > 0:
            
            subscription_filters_response = logs_client.describe_subscription_filters(
                logGroupName = log_group_prefix + func,
                filterNamePrefix = filter_name
            )

            # check if subscription filter exist on log group or not
            if len(subscription_filters_response["subscriptionFilters"]) == 0:

                subscription_response = logs_client.put_subscription_filter(
                    logGroupName = log_group_prefix + func,
                    filterName = filter_name,
                    filterPattern = "REPORT",
                    destinationArn = lambda_destination
                )

                function_subscription_list.append({"function":func, "subscription": True})
                print(f'Subscription filter created for log group {log_group_prefix + func}')
            
            else:
                function_subscription_list.append({"function":func, "subscription": True})
                print(f'Subscription filter already exist for log group {log_group_prefix + func}')

        else:
            function_subscription_list.append({"function":func, "subscription": False})
            print(f'log group {log_group_prefix + func} do not exist')
    
    return function_subscription_list

def delete_log_subscription(items):
    log_group_prefix = "/aws/lambda/"

    for item in items:

        log_group_description = logs_client.describe_log_groups(
            logGroupNamePrefix = log_group_prefix + item
        )

        # check if log group exist or not
        if len(log_group_description['logGroups']) > 0:
            subscription_filters_response = logs_client.describe_subscription_filters(
                logGroupName = log_group_prefix + item,
                filterNamePrefix = filter_name
            )

            # check if subscription filter exist on log group or not
            if len(subscription_filters_response["subscriptionFilters"]) > 0:

                subscription_response = logs_client.delete_subscription_filter(
                    logGroupName = log_group_prefix + item,
                    filterName = filter_name
                )

                print(f'Subscription filter deleted for log group {log_group_prefix + item}') 
            else:
                print(f'Subscription filter do not exist for log group {log_group_prefix + item}')

        else:
            print(f'log group {log_group_prefix + item} do not exist')