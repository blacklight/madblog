#!/bin/sh

[ -z "$REGISTRY_REPO" ] && echo "Please set the REGISTRY_REPO environment variable" && exit 1
[ -z "$DOCKER_USER" ] && echo "Please set the DOCKER_USER environment variable" && exit 1
[ -z "$DOCKER_PASS" ] && echo "Please set the DOCKER_PASS environment variable" && exit 1

export REGISTRY_ENDPOINT="${REGISTRY_ENDPOINT:-quay.io}"
export IMAGE_NAME="$REGISTRY_ENDPOINT/$REGISTRY_REPO"

# Log in to the registry
docker login "$REGISTRY_ENDPOINT" -u "$DOCKER_USER" -p "$DOCKER_PASS"

# On tag events, push both `latest` and the release tag
# (e.g. `v0.2.8`, plus `0.2.8` without the `v` prefix)
TAGS="latest"
if [ -n "$DRONE_TAG" ]; then
  TAGS="$TAGS $DRONE_TAG"
  VERSION="${DRONE_TAG#v}"
  [ "$VERSION" != "$DRONE_TAG" ] && TAGS="$TAGS $VERSION"
fi

# Build the Docker image using the minimal Dockerfile
BUILD_ARGS=""
for tag in $TAGS; do
  BUILD_ARGS="$BUILD_ARGS -t $IMAGE_NAME:$tag"
done

docker build \
  -f docker/minimal.Dockerfile \
  $BUILD_ARGS \
  .

# Push all the image tags
docker push "$IMAGE_NAME" --all-tags
