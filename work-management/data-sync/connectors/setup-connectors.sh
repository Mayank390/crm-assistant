#!/bin/bash
set -euo pipefail

# Wait for Kafka Connect to be ready
echo "Waiting for Kafka Connect to be ready..."
until curl -f http://localhost:8083/connectors > /dev/null 2>&1; do
  echo "Kafka Connect not ready, waiting..."
  sleep 5
done

echo "Installing MongoDB Source Connector..."

export CONFIG_PATH=/tmp/mongodb-source-connector.json

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Python interpreter not found; attempting to install python3..."
  if command -v apt-get > /dev/null 2>&1; then
    apt-get update && apt-get install -y python3 >/dev/null 2>&1
    PYTHON_BIN="$(command -v python3 || true)"
  else
    echo "ERROR: Unable to install python3 (apt-get not available)" >&2
  fi
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: No python interpreter available for connector bootstrap" >&2
  exit 1
fi

echo "Using python executable: $PYTHON_BIN"

$PYTHON_BIN - <<'PY'
import json
import os
import re


def namespace_regex(db_name, coll_names):
    escaped_db = re.escape(db_name)
    escaped_colls = [re.escape(name) for name in coll_names]
    return f"{escaped_db}\\.({'|'.join(escaped_colls)})"


config_path = os.environ.get("CONFIG_PATH", "/tmp/mongodb-source-connector.json")

uri = os.environ.get(
    "MONGODB_URI",
    "mongodb://WebsiteBuilderAdmin:JfOCiOKMVgSIMPOBUILDERGkli8@13.90.63.91:27017,172.171.192.172:27017/ProjectManagement?authSource=admin&replicaSet=rs0",
)
database = os.environ.get("MONGODB_DATABASE", "ProjectManagement")
topic_prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "ProjectManagement.")

collections = sorted(
    {
        "page",
        "workItem",
        "project",
        "cycle",
        "module",
        "epic",
        "features",
        "userStory"
      }
)

pipeline = [
    {
        "$match": {
            "operationType": {"$in": ["insert", "update", "replace", "delete"]},
            "ns.coll": {"$in": collections},
        }
    }
]

# Create explicit topic mappings instead of using prefix
topic_namespace_map = {}
for coll in collections:
    topic_namespace_map[f"{database}.{coll}"] = f"{database}.{coll}"

config = {
    "name": "mongodb-source-connector",
    "config": {
        "connector.class": "com.mongodb.kafka.connect.MongoSourceConnector",
        "connection.uri": uri,
        "database": database,
        "change.stream.full.document": "updateLookup",
        "publish.full.document.only": "false",
        "pipeline": json.dumps(pipeline),
        "topic.namespace.map": json.dumps(topic_namespace_map),
        "copy.existing": "true",
        "copy.existing.namespace.regex": namespace_regex(database, collections),
        "copy.existing.pipeline": json.dumps(pipeline),
        "key.converter": "org.apache.kafka.connect.storage.StringConverter",
        "key.converter.schemas.enable": "false",
        "value.converter": "org.apache.kafka.connect.json.JsonConverter",
        "value.converter.schemas.enable": "false",
    },
}

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config, f)
PY

# Remove existing connector if present to apply the latest config
curl -s -X DELETE http://localhost:8083/connectors/mongodb-source-connector > /dev/null 2>&1 || true

echo "Registering mongodb-source-connector from ${CONFIG_PATH}"
response="$(curl -s -o /tmp/connector_response.json -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  --data @${CONFIG_PATH} \
  http://localhost:8083/connectors)"

if [ "$response" != "201" ] && [ "$response" != "409" ]; then
  echo "ERROR: Failed to register connector (HTTP $response)" >&2
  cat /tmp/connector_response.json >&2 || true
  exit 1
fi

cat /tmp/connector_response.json

echo "Connectors installation completed (Qdrant sink disabled; Python consumer handles upserts)."