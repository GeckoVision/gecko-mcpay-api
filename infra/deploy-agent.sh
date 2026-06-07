#!/usr/bin/env bash
# =============================================================================
# infra/deploy-agent.sh — build/push the gecko-agent image + deploy
# ecs-agent-stack. Discovers VPC / cluster / private-subnets from the running
# gecko-api-ecs stack so the agent reuses the existing networking. Founder-run
# (touches AWS). Paper-only — safety env is baked in the container entrypoint.
#
# Usage:  ./infra/deploy-agent.sh [--region us-east-2]
# Prereqs: AWS CLI configured; Docker running; SSM params pushed
#          (./infra/push-agent-ssm-params.sh); the gecko-api-ecs stack live.
# =============================================================================
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-2}"
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

API_STACK="gecko-api-ecs"
AGENT_STACK="gecko-agent-ecs"
ECR_REPOSITORY="gecko-agent"
CLUSTER_NAME="gecko-api"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_TAG="agent-$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo latest)-$(date +%s)"
FULL_IMAGE="${ECR_URI}:${IMAGE_TAG}"

# Discover networking from the api stack's physical resources.
CLUSTER_ARN=$(aws ecs describe-clusters --clusters "$CLUSTER_NAME" --region "$REGION" \
  --query 'clusters[0].clusterArn' --output text)
VPC_ID=$(aws cloudformation describe-stack-resources --stack-name "$API_STACK" --region "$REGION" \
  --query "StackResources[?ResourceType=='AWS::EC2::VPC'].PhysicalResourceId" --output text)
SUBNETS=$(aws cloudformation describe-stack-resources --stack-name "$API_STACK" --region "$REGION" \
  --query "StackResources[?LogicalResourceId=='PrivateSubnet1'||LogicalResourceId=='PrivateSubnet2'].PhysicalResourceId" \
  --output text | tr '\t' ',')

echo "==> region=$REGION cluster=$CLUSTER_ARN"
echo "==> vpc=$VPC_ID subnets=$SUBNETS"
echo "==> image=$FULL_IMAGE"

aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URI"
docker build -f "$REPO_ROOT/Dockerfile.agent" -t "$FULL_IMAGE" "$REPO_ROOT"
docker push "$FULL_IMAGE"

aws cloudformation deploy --stack-name "$AGENT_STACK" --region "$REGION" \
  --template-file "$REPO_ROOT/infra/ecs-agent-stack.yml" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      Image="$FULL_IMAGE" \
      ClusterArn="$CLUSTER_ARN" \
      VpcId="$VPC_ID" \
      PrivateSubnets="$SUBNETS"

echo "==> deployed. tail logs:"
echo "    aws logs tail /ecs/gecko-agent --follow --region $REGION"
