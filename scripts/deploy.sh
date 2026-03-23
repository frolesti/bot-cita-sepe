#!/bin/bash
# Deploy script - runs ON the VM (Container-Optimized OS)
# Usage: called by GitHub Actions via SSH on each push to main
set -e

REPO_DIR="$HOME/bot-cita-sepe"
REPO_URL="https://github.com/frolesti/bot-cita-sepe.git"
CONTAINER_NAME="sepe-bot-container"
IMAGE_NAME="sepe-bot"

echo "=== DEPLOY START $(date) ==="

# Pull latest code (COS has no git, use alpine/git Docker image)
if [ -d "$REPO_DIR/.git" ]; then
    echo ">> Pulling latest changes..."
    docker run --rm -v "$REPO_DIR":/repo alpine/git -C /repo pull origin main
else
    echo ">> Cloning repo..."
    rm -rf "$REPO_DIR"
    docker run --rm -v "$REPO_DIR":/repo alpine/git clone "$REPO_URL" /repo
fi

# Build new image
echo ">> Building Docker image..."
cd "$REPO_DIR"
docker build -t "$IMAGE_NAME" .

# Stop and remove old container
echo ">> Restarting container..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Start new container
docker run -d \
    --name "$CONTAINER_NAME" \
    -p 10000:10000 \
    --env-file "$REPO_DIR/.env" \
    --restart unless-stopped \
    "$IMAGE_NAME"

# Quick health check
sleep 4
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo ">> Container running OK"
    docker logs "$CONTAINER_NAME" --tail 3
else
    echo ">> ERROR: Container not running!"
    docker logs "$CONTAINER_NAME" --tail 20
    exit 1
fi

echo "=== DEPLOY OK $(date) ==="
