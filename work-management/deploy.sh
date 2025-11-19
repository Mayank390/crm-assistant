#!/usr/bin/env bash
set -euo pipefail

# build-and-push-acr.sh
# Usage:
#   ./build-and-push-acr.sh v1.0.0
#   ./build-and-push-acr.sh         # will read RELEASE_VERSION or prompt
#
# Requirements:
#  - docker installed (and able to build)
#  - either az CLI (recommended) or ACR credentials (ACR_USERNAME/ACR_PASSWORD) exported
#  - run from repo root where Dockerfiles and contexts exist

# -----------------------
# CONFIG - change if your repo layout differs
# -----------------------
ACR_REGISTRY="${ACR_REGISTRY:-aiplanboard.azurecr.io}"
IMAGE_PREFIX="${IMAGE_PREFIX:-aiplanboard}"

# Services: name:Dockerfile:context
SERVICES=(
  "backend:agent/Dockerfile:."
  "embedding:embedding_service/Dockerfile:."
  "splade:splade_service/Dockerfile:."
  "consumer:data-sync/consumer/Dockerfile:."
  "backfill:data-sync/consumer/Dockerfile:."
  "monitoring:agent/Dockerfile:."
)

# Third-party images to mirror (optional with az acr import)
# Format: "source_image:target_repo:tag"
# Example: "docker.io/library/redis:7.0:redis:7.0"
MIRRORS=(
  # "docker.io/library/redis:7.0:redis:7.0"
  # "docker.io/confluentinc/cp-kafka:7.8.0:cp-kafka:7.8.0"
  # "docker.io/qdrant/qdrant:latest:qdrant:latest"
)

# -----------------------
# Helper functions
# -----------------------
info(){ printf "\033[1;34m[INFO]\033[0m %s\n" "$*"; }
warn(){ printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err(){ printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

# -----------------------
# Resolve VERSION
# -----------------------
if [ "${1:-}" != "" ]; then
  VERSION="$1"
elif [ -f RELEASE_VERSION ]; then
  VERSION=$(<RELEASE_VERSION)
else
  read -r -p "Enter version to push (semantic form e.g. v1.0.0): " VERSION
fi

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  warn "VERSION does not strictly match vMAJOR.MINOR.PATCH. Proceeding anyway: '$VERSION'"
fi

info "Using VERSION = $VERSION"
info "Target ACR registry = $ACR_REGISTRY"
info "Image prefix = $IMAGE_PREFIX"

# -----------------------
# Check Dockerfiles exist
# -----------------------
for entry in "${SERVICES[@]}"; do
  IFS=":" read -r svc dockerfile context <<< "$entry"
  if [[ ! -f "$dockerfile" ]]; then
    err "Dockerfile for service '$svc' not found at: $dockerfile"
    exit 2
  fi
  if [[ ! -d "$context" ]]; then
    # context may be '.' which is fine; check existence
    err "Build context directory for '$svc' not found: $context"
    exit 2
  fi
done

# -----------------------
# Login to ACR (prefer az)
# -----------------------
if command -v az >/dev/null 2>&1; then
  ACR_NAME=$(echo "$ACR_REGISTRY" | cut -d'.' -f1)
  info "Using Azure CLI to login to ACR: az acr login --name $ACR_NAME"
  az acr login --name "$ACR_NAME"
else
  if [[ -z "${ACR_USERNAME:-}" || -z "${ACR_PASSWORD:-}" ]]; then
    warn "az CLI not found and ACR_USERNAME/ACR_PASSWORD not set. Attempting interactive docker login."
    docker login "$ACR_REGISTRY"
  else
    info "Logging into ACR via docker login (from env ACR_USERNAME/ACR_PASSWORD)"
    echo "$ACR_PASSWORD" | docker login "$ACR_REGISTRY" -u "$ACR_USERNAME" --password-stdin
  fi
fi

# -----------------------
# Build & push each service
# -----------------------
for entry in "${SERVICES[@]}"; do
  IFS=":" read -r svc dockerfile context <<< "$entry"
  img="$ACR_REGISTRY/${IMAGE_PREFIX}-${svc}:${VERSION}"
  info "Building service: $svc"
  docker build -f "$dockerfile" -t "$img" "$context"
  info "Pushing image: $img"
  docker push "$img"
done

info "All application images built and pushed to $ACR_REGISTRY with tag $VERSION."

# -----------------------
# Optional: mirror third-party images into ACR (use az acr import)
# -----------------------
if [ "${#MIRRORS[@]}" -gt 0 ]; then
  if ! command -v az >/dev/null 2>&1; then
    warn "Skipping mirror step because 'az' CLI is not available. Install Azure CLI to use az acr import."
  else
    for m in "${MIRRORS[@]}"; do
      # m format: source_image:target_repo:tag
      IFS=":" read -r src target_repo target_tag <<< "$m"
      info "Importing $src into $ACR_REGISTRY as $target_repo:$target_tag"
      az acr import --name "$ACR_NAME" --source "$src" --image "${target_repo}:${target_tag}"
    done
    info "Mirror import complete."
  fi
fi

info "Done. Verify tags in ACR with:"
info "  az acr repository show-tags --name ${ACR_NAME} --repository ${IMAGE_PREFIX}-backend --output table"
