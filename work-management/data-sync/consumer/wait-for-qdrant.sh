#!/usr/bin/env sh
set -e

# Use QDRANT_URL if provided, otherwise use the docker service name 'qdrant'
QDRANT_URL="${QDRANT_URL:-http://qdrant:6333}"
EMBEDDING_SERVICE_URL="${EMBEDDING_SERVICE_URL:-http://embedding:8080}"
SPLADE_SERVICE_URL="${SPLADE_SERVICE_URL:-http://splade:8080}"

# Remove trailing slash for safety
QDRANT_URL=$(echo "$QDRANT_URL" | sed 's:/*$::')
EMBEDDING_SERVICE_URL=$(echo "$EMBEDDING_SERVICE_URL" | sed 's:/*$::')
SPLADE_SERVICE_URL=$(echo "$SPLADE_SERVICE_URL" | sed 's:/*$::')

echo "Waiting for Qdrant at ${QDRANT_URL} ..."
echo "Waiting for embedding service at ${EMBEDDING_SERVICE_URL} ..."
echo "Waiting for SPLADE service at ${SPLADE_SERVICE_URL} ..."

attempt=0
max_attempts=12
sleep_secs=2

while [ $attempt -lt $max_attempts ]; do
  attempt=$((attempt+1))
    if command -v curl >/dev/null 2>&1; then
      qdrant_ok=false
      embedding_ok=false
      splade_ok=false

      if curl -fsS "${QDRANT_URL}/collections" >/dev/null 2>&1; then
        qdrant_ok=true
      fi

      if curl -fsS "${EMBEDDING_SERVICE_URL}/health" >/dev/null 2>&1; then
        embedding_ok=true
      fi

      if curl -fsS "${SPLADE_SERVICE_URL}/health" >/dev/null 2>&1; then
        splade_ok=true
      fi

      if [ "$qdrant_ok" = true ] && [ "$embedding_ok" = true ] && [ "$splade_ok" = true ]; then
        echo "Qdrant, embedding, and SPLADE services ready"
        exec "$@"
      fi
  else
    # fallback to nc if curl not present
      host=$(echo "$QDRANT_URL" | sed -n 's|^[a-z]*://\([^:/]*\).*|\1|p')
      port=$(echo "$QDRANT_URL" | sed -n 's|^[a-z]*://[^:/]*:\?\([0-9]*\).*|\1|p')
      if [ -z "$port" ]; then port=6333; fi
      emb_host=$(echo "$EMBEDDING_SERVICE_URL" | sed -n 's|^[a-z]*://\([^:/]*\).*|\1|p')
      emb_port=$(echo "$EMBEDDING_SERVICE_URL" | sed -n 's|^[a-z]*://[^:/]*:\?\([0-9]*\).*|\1|p')
      if [ -z "$emb_port" ]; then emb_port=8080; fi
      spl_host=$(echo "$SPLADE_SERVICE_URL" | sed -n 's|^[a-z]*://\([^:/]*\).*|\1|p')
      spl_port=$(echo "$SPLADE_SERVICE_URL" | sed -n 's|^[a-z]*://[^:/]*:\?\([0-9]*\).*|\1|p')
      if [ -z "$spl_port" ]; then spl_port=8080; fi
      if nc -z "$host" "$port" >/dev/null 2>&1 \
        && nc -z "$emb_host" "$emb_port" >/dev/null 2>&1 \
        && nc -z "$spl_host" "$spl_port" >/dev/null 2>&1; then
        echo "Qdrant ready (tcp) at ${host}:${port}"
        echo "Embedding service ready (tcp) at ${emb_host}:${emb_port}"
        echo "SPLADE service ready (tcp) at ${spl_host}:${spl_port}"
        exec "$@"
      fi
  fi

  # Simple exponential backoff: cap at 32 seconds
  if [ $attempt -gt 5 ]; then
    wait_secs=32
  else
    wait_secs=$((sleep_secs * (1 << attempt)))
  fi
  echo "Attempt ${attempt}: services not ready yet, waiting ${wait_secs}s..."
  sleep "$wait_secs"
done

echo "Timed out waiting for Qdrant (${QDRANT_URL}), embedding service (${EMBEDDING_SERVICE_URL}), or SPLADE service (${SPLADE_SERVICE_URL})" >&2
exit 1
