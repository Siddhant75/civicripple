"""Direct-code deployment of CivicRipple to AgentCore Runtime.

Adapted from the official sample:
awslabs/amazon-bedrock-agentcore-samples -> 01-features/02-host-your-agent/
01-runtime/01-hosting-agents/01-http-protocol/01-strands-bedrock/deploy.py
(Apache-2.0). Packages the project for linux/arm64 with uv, provisions the
execution role, creates the runtime with env config, waits for READY.

Usage: uv run python infra/agentcore/deploy.py [--region us-east-1]
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent.parent  # CivicRipple repo root
HERE = Path(__file__).parent
BUILD = HERE / "build"
ENTRY = HERE / "main.py"
ENV_VARS = {
    "MODE": "aws",
    "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
    "DYNAMODB_TABLE": "civicripple-demo",
    "AWS_REGION": "us-east-1",
}
RUNTIME_NAME = "civicripple_agent"
ROLE_NAME = "CivicRippleAgentCoreRole"
TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": None}},
        }
    ],
}
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            "Resource": [
                "arn:aws:bedrock:*::foundation-model/*",
                "arn:aws:bedrock:*:*:inference-profile/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": ["geo-routes:CalculateRoutes"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/civicripple-demo",
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogStreams",
                "cloudwatch:PutMetricData",
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
            ],
            "Resource": "*",
        },
    ],
}


def sh(cmd: list) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def package() -> Path:
    """Project source + arm64 linux deps -> zip."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    pkg = BUILD / "pkg"
    pkg.mkdir(parents=True)

    sh([
        "uv",
        "pip",
        "install",
        "--python-platform",
        "aarch64-unknown-linux-gnu",
        "--python-version",
        "3.11",
        "--target",
        pkg,
        ".",
    ])
    # uv --target installs the civicripple package itself (non-editable);
    # only add the entrypoint on top.
    if not (pkg / "civicripple").exists():
        shutil.copytree(ROOT / "src" / "civicripple", pkg / "civicripple")
    shutil.copy2(ENTRY, pkg / "main.py")

    zip_path = BUILD / "civicripple-agent"
    if zip_path.with_suffix(".zip").exists():
        zip_path.with_suffix(".zip").unlink()
    shutil.make_archive(str(zip_path), "zip", pkg)
    final = zip_path.with_suffix(".zip")
    print(f"packaged {final} ({final.stat().st_size / 1e6:.1f} MB)")
    return final


def ensure_role(iam, account_id: str) -> str:
    trust = json.loads(json.dumps(TRUST))
    trust["Statement"][0]["Condition"]["StringEquals"]["aws:SourceAccount"] = account_id
    roles = iam.list_roles()["Roles"]
    role = next((r for r in roles if r["RoleName"] == ROLE_NAME), None)
    if role is None:
        iam.create_role(
            RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust)
        )
        print("role created; waiting 10s for propagation ...")
        time.sleep(10)
    # Always refresh the inline policy (redeploys may widen permissions).
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="CivicRippleRuntime",
        PolicyDocument=json.dumps(POLICY),
    )
    return f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    region = args.region

    session = boto3.Session(profile_name="civicripple-dev", region_name=region)
    account_id = session.client("sts").get_caller_identity()["Account"]

    zip_path = package()
    role_arn = ensure_role(session.client("iam"), account_id)

    s3 = session.client("s3")
    bucket = f"civicripple-agentcore-{account_id}-{region}"
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        kwargs = {"Bucket": bucket}
        if region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
    s3.upload_file(str(zip_path), bucket, "civicripple-agent.zip")

    cp = session.client("bedrock-agentcore-control")
    existing = [
        r
        for r in cp.list_agent_runtimes().get("agentRuntimes", [])
        if r.get("agentRuntimeName") == RUNTIME_NAME
    ]
    artifact = {
        "codeConfiguration": {
            "code": {"s3": {"bucket": bucket, "prefix": "civicripple-agent.zip"}},
            "runtime": "PYTHON_3_11",
            "entryPoint": ["main.py"],
        }
    }
    if existing:
        found = existing[0]
        resp = cp.update_agent_runtime(
            agentRuntimeId=found["agentRuntimeId"],
            roleArn=role_arn,
            agentRuntimeArtifact=artifact,
            networkConfiguration={"networkMode": "PUBLIC"},
            environmentVariables=ENV_VARS,
        )
    else:
        resp = cp.create_agent_runtime(
            agentRuntimeName=RUNTIME_NAME,
            roleArn=role_arn,
            environmentVariables=ENV_VARS,
            agentRuntimeArtifact=artifact,
            networkConfiguration={"networkMode": "PUBLIC"},
        )

    arn = resp["agentRuntimeArn"]
    runtime_id = resp.get("agentRuntimeId") or arn.rsplit("/", 1)[-1]
    print("waiting for runtime READY ...")
    for _ in range(60):
        detail = cp.get_agent_runtime(agentRuntimeId=runtime_id)
        status = detail.get("status")
        print("  status:", status)
        if status == "READY":
            break
        if "FAIL" in str(status).upper():
            sys.exit(f"runtime failed: {json.dumps(detail, default=str)[:2000]}")
        time.sleep(10)

    out = {"agentRuntimeArn": arn, "region": region}
    (HERE / "runtime.json").write_text(json.dumps(out, indent=2))
    print("DEPLOYED:", json.dumps(out))


if __name__ == "__main__":
    main()
