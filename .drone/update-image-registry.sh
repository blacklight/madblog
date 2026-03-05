#!/bin/sh

[ -z "$REGISTRY_REPO" ] && echo "Please set the REGISTRY_REPO environment variable" && exit 1
[ -z "$DOCKER_USER" ] && echo "Please set the DOCKER_USER environment variable" && exit 1
[ -z "$DOCKER_PASS" ] && echo "Please set the DOCKER_PASS environment variable" && exit 1

export REGISTRY_ENDPOINT="${REGISTRY_ENDPOINT:-quay.io}"
export IMAGE_NAME="$REGISTRY_ENDPOINT/$REGISTRY_REPO"

# Log in to the registry
docker login "$REGISTRY_ENDPOINT" -u "$DOCKER_USER" -p "$DOCKER_PASS"

# Build the Docker image using the minimal Dockerfile
docker build \
  -f docker/minimal.Dockerfile \
  -t "$IMAGE_NAME:latest" \
  .

# Push the image
docker push "$IMAGE_NAME:latest"
