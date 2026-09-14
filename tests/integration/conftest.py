import os
import uuid

import pytest
from botocore.exceptions import ClientError


def _credentials_available() -> bool:
    try:
        import boto3

        return boto3.session.Session().get_credentials() is not None
    except Exception:
        return False


def _integration_enabled() -> bool:
    return (
        os.environ.get("RUN_AWS_INTEGRATION") == "1"
        and os.environ.get("MODE") == "aws"
        and _credentials_available()
    )


if not _integration_enabled():
    collect_ignore_glob = ["*.py"]


@pytest.fixture
def disposable_table():
    """Create a disposable DynamoDB table for one test; delete it after."""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table_name = f"civicripple-integration-{uuid.uuid4()}"
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    yield table
    try:
        table.delete()
        table.wait_until_not_exists()
    except ClientError:
        pass  # teardown best-effort; orphaned tables cost pennies and can be swept
