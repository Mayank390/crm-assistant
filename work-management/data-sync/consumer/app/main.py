import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from huggingface_hub import login
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from embedding.service_client import EmbeddingServiceClient, EmbeddingServiceError


# Ensure repo-root packages (qdrant, etc.) are importable when running locally
if not any("qdrant" in p for p in sys.path):
    try:
        REPO_ROOT = Path(__file__).resolve().parents[3]
        if str(REPO_ROOT) not in sys.path:
            sys.path.append(str(REPO_ROOT))
    except IndexError:
        pass

from qdrant.encoder import get_splade_encoder  # noqa: E402
from qdrant.indexing_shared import (  # noqa: E402
    CHUNKING_CONFIG,
    chunk_prepared_document,
    ensure_collection_with_hybrid,
    generate_points,
    normalize_mongo_id,
    prepare_document,
)


# Updated to match setup-connectors.sh exactly
RELEVANT_COLLECTIONS = {
    "page",
    "pages",
    "workItem",
    "workitem",
    "project",
    "projects",
    "cycle",
    "module",
    "epic",
    "feature",
    "features",
    "userStory",
    "userStories",
}


@dataclass
class ChangeEvent:
    operation: str
    collection: Optional[str]
    full_document: Optional[Dict[str, Any]]
    document_key: Optional[Dict[str, Any]]


def load_env_and_login() -> None:
    load_dotenv()
    token = (
        os.getenv("HuggingFace_API_KEY")
        or os.getenv("HF_TOKEN")
        or os.getenv("HF_API_TOKEN")
        or os.getenv("HF_HUB_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    )
    if not token:
        return
    try:
        for name in (
            "HuggingFace_API_KEY",
            "HF_TOKEN",
            "HF_API_TOKEN",
            "HF_HUB_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACEHUB_API_TOKEN",
        ):
            os.environ.setdefault(name, token)
        try:
            login(token=token, add_to_git_credential=False)
        except TypeError:
            login(token)
    except Exception as exc:
        pass


def create_embedding_client() -> EmbeddingServiceClient:
    try:
        return EmbeddingServiceClient(os.getenv("EMBEDDING_SERVICE_URL"))
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_SERVICE_URL is required") from exc


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def flatten_payload(raw: bytes) -> Optional[Any]:
    try:
        decoded = raw.decode("utf-8")
    except Exception as exc:
        return None

    # Handle double-escaped JSON strings from MongoDB connector
    try:
        # First parse: might be a quoted JSON string
        first_parse = json.loads(decoded)

        # If it's a string, parse again (double-escaped case)
        if isinstance(first_parse, str):
            envelope = json.loads(first_parse)
        else:
            envelope = first_parse
    except Exception as exc:
        return None

    # Handle nested payload structure
    if isinstance(envelope, dict) and "payload" in envelope:
        payload = envelope.get("payload")
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception as exc:
                return None
        return payload

    return envelope


def parse_change_events(raw: bytes) -> List[ChangeEvent]:
    payload = flatten_payload(raw)
    if payload is None:
        return []

    if isinstance(payload, list):
        events: List[ChangeEvent] = []
        for item in payload:
            if isinstance(item, (dict, list)):
                events.extend(parse_change_events(json.dumps(item).encode("utf-8")))
        return events

    if not isinstance(payload, dict):
        return []

    op = payload.get("operationType") or payload.get("op") or "insert"
    op = str(op).lower()
    if op == "read":
        op = "insert"

    namespace = payload.get("ns") or {}
    collection = namespace.get("coll") or payload.get("collection") or payload.get("collectionName")

    full_document = payload.get("fullDocument")
    if isinstance(full_document, list) and full_document:
        events: List[ChangeEvent] = []
        for doc in full_document:
            if isinstance(doc, dict):
                events.append(
                    ChangeEvent(
                        operation=op,
                        collection=collection,
                        full_document=doc,
                        document_key=payload.get("documentKey"),
                    )
                )
        return events

    if op not in {"insert", "update", "replace", "delete"}:
        return []

    document_key = payload.get("documentKey")
    if not isinstance(document_key, dict):
        document_key = {"_id": payload.get("_id")}

    document = None
    if isinstance(full_document, dict):
        document = full_document
    elif op in {"insert", "replace"}:
        document = payload if payload.get("_id") else None

    return [ChangeEvent(operation=op, collection=collection, full_document=document, document_key=document_key)]


def delete_points_for_parent(client: QdrantClient, collection: str, parent_id: str) -> None:
    if not parent_id:
        return
    try:
        client.delete(
            collection_name=collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="parent_id",
                            match=qmodels.MatchValue(value=parent_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
    except Exception as exc:
        pass


def process_event(
    event: ChangeEvent,
    client: QdrantClient,
    collection_name: str,
    embedder: EmbeddingServiceClient,
    splade_encoder: Any,
) -> None:
    if event.collection not in RELEVANT_COLLECTIONS:
        return

    if event.operation == "delete":
        raw_id = (event.document_key or {}).get("_id")
        if raw_id is None:
            return
        mongo_id = normalize_mongo_id(raw_id)
        if not mongo_id:
            return
        delete_points_for_parent(client, collection_name, mongo_id)
        return

    if not event.full_document:
        return

    prepared, messages = prepare_document(event.collection, event.full_document)
    if not prepared:
        return

    chunks = chunk_prepared_document(prepared)
    mongo_id = prepared.mongo_id
    if not mongo_id:
        return

    delete_points_for_parent(client, collection_name, mongo_id)

    if not chunks:
        return

    points = generate_points(prepared, chunks, embedder, splade_encoder)
    if not points:
        return

    try:
        client.upsert(collection_name=collection_name, points=points, wait=True)
    except Exception as exc:
        raise


def main() -> None:
    load_env_and_login()

    embedder = create_embedding_client()
    splade_encoder = get_splade_encoder()
    try:
        embedding_dim = embedder.get_dimension()
    except EmbeddingServiceError as exc:
        raise RuntimeError(f"Failed to determine embedding dimension: {exc}") from exc
    log_level = get_env("LOG_LEVEL", "INFO")

    bootstrap = get_env("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    topic_pattern = get_env("KAFKA_TOPIC", "ProjectManagement\..*")
    group_id = get_env("KAFKA_GROUP_ID", "qdrant-consumer")
    qdrant_url = get_env("QDRANT_URL", "http://qdrant:6333")
    collection = get_env("QDRANT_COLLECTION", "ProjectManagement")
    batch_max_messages = int(get_env("BATCH_MAX_MESSAGES", "128"))
    batch_max_seconds = float(get_env("BATCH_MAX_SECONDS", "2"))

    client = None
    while client is None:
        try:
            client = QdrantClient(url=qdrant_url)
        except Exception as exc:
            time.sleep(2)

    ensure_collection_with_hybrid(client, collection, vector_size=embedding_dim)

    # Convert regex pattern to actual regex for subscription
    topic_regex = re.compile(topic_pattern)
    
    consumer: Optional[KafkaConsumer] = None
    while consumer is None:
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
                group_id=group_id,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
                value_deserializer=lambda m: m,
                key_deserializer=lambda m: m,
            )
            # Subscribe using pattern
            consumer.subscribe(pattern=topic_regex)
        except Exception as exc:
            time.sleep(2)

    batch_events: List[ChangeEvent] = []
    last_flush_ts = time.monotonic()
    processed_count = 0
    error_count = 0

    while True:
        try:
            now = time.monotonic()
            remaining_capacity = max(0, batch_max_messages - len(batch_events))
            poll_timeout_ms = 500
            max_records = remaining_capacity if remaining_capacity > 0 else None

            records_map = consumer.poll(timeout_ms=poll_timeout_ms, max_records=max_records)
            total_polled = sum(len(records) for records in (records_map or {}).values())

            for topic_partition, records in (records_map or {}).items():
                for msg in records:
                    events = parse_change_events(msg.value)
                    if events:
                        batch_events.extend(events)

            should_flush = False
            if len(batch_events) >= batch_max_messages:
                should_flush = True
            elif (now - last_flush_ts) >= batch_max_seconds and batch_events:
                should_flush = True

            if should_flush:
                batch_errors = 0
                for idx, event in enumerate(batch_events):
                    try:
                        process_event(event, client, collection, embedder, splade_encoder)
                        processed_count += 1
                    except Exception as exc:
                        batch_errors += 1
                        error_count += 1

                if batch_errors == 0:
                    consumer.commit()
                
                batch_events.clear()
                last_flush_ts = time.monotonic()

            if total_polled == 0 and not should_flush:
                time.sleep(0.1)

        except Exception as exc:
            time.sleep(5)
            try:
                consumer.close()
            except Exception:
                pass
            consumer = None
            while consumer is None:
                try:
                    consumer = KafkaConsumer(
                        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
                        group_id=group_id,
                        enable_auto_commit=False,
                        auto_offset_reset="earliest",
                        value_deserializer=lambda m: m,
                        key_deserializer=lambda m: m,
                    )
                    consumer.subscribe(pattern=topic_regex)
                except NoBrokersAvailable as broker_exc:
                    time.sleep(2)


if __name__ == "__main__":
    main()