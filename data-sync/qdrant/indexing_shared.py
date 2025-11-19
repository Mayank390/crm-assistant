from __future__ import annotations

"""Reusable helpers for CRM ? Qdrant indexing."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import base64
import html as html_lib
import json
import re
import uuid
import logging
from datetime import datetime, timezone

from bson.binary import Binary
from bson.objectid import ObjectId
from qdrant_client.http import models as qmodels

# Configure logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class PreparedDocument:
    content_type: str
    mongo_id: str
    title: str
    combined_text: str
    metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


CHUNKING_CONFIG: Dict[str, Dict[str, int]] = {
    "lead": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "task": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "activity": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "meeting": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "notes": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "callLog": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "mailInfo": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "leadScoreRule": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "segmentation": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
}


CRM_COLLECTIONS: Dict[str, str] = {
    "lead": "lead",
    "task": "task",
    "activity": "activity",
    "meeting": "meeting",
    "notes": "notes",
    "calllog": "callLog",
    "mailinfo": "mailInfo",
    "leadscorerule": "leadScoreRule",
    "segmentation": "segmentation",
}


COLLECTION_ALIASES: Dict[str, str] = {
    "lead": "lead",
    "Lead": "lead",
    "leads": "lead",
    "task": "task",
    "Task": "task",
    "tasks": "task",
    "activity": "activity",
    "Activity": "activity",
    "activities": "activity",
    "meeting": "meeting",
    "Meeting": "meeting",
    "meetings": "meeting",
    "notes": "notes",
    "Notes": "notes",
    "note": "notes",
    "Note": "notes",
    "calllog": "calllog",
    "CallLog": "calllog",
    "callLog": "calllog",
    "call_log": "calllog",
    "mailinfo": "mailinfo",
    "MailInfo": "mailinfo",
    "mail_info": "mailinfo",
    "leadscorerule": "leadscorerule",
    "LeadScoreRule": "leadscorerule",
    "lead_score_rule": "leadscorerule",
    "segmentation": "segmentation",
    "Segmentation": "segmentation",
    "segmentations": "segmentation",
}


def canonicalize_collection_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None

    trimmed = name.strip()
    if not trimmed:
        return None

    if trimmed in COLLECTION_ALIASES:
        return COLLECTION_ALIASES[trimmed]

    lowered = trimmed.lower()
    if lowered in COLLECTION_ALIASES:
        return COLLECTION_ALIASES[lowered]

    condensed = re.sub(r"[\s_\-]", "", lowered)
    for alias, canonical in COLLECTION_ALIASES.items():
        alias_condensed = re.sub(r"[\s_\-]", "", alias.lower())
        if alias_condensed == condensed:
            return canonical

    return None


# ---------------------------------------------------------------------------
# Qdrant collection helpers
# ---------------------------------------------------------------------------


def ensure_collection_with_hybrid(
    client: Any,
    collection_name: str,
    *,
    vector_size: int = 768,
    force_recreate: bool = False,
) -> None:
    """Ensure the collection exists with dense + sparse vector support."""

    try:
        should_create = False
        try:
            existing_names = [c.name for c in client.get_collections().collections]
            should_create = collection_name not in existing_names
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Could not list collections: {exc}")
            should_create = True

        if force_recreate:
            client.recreate_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=vector_size, distance=qmodels.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(),
                },
            )
        elif should_create:
            client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=vector_size, distance=qmodels.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(),
                },
            )
        try:
            client.update_collection(
                collection_name=collection_name,
                optimizer_config=qmodels.OptimizersConfigDiff(indexing_threshold=1),
            )
        except Exception as exc:
            logger.error(f"Failed to update optimizer config: {exc}")

        indexed_fields = [
            ("content_type", qmodels.PayloadSchemaType.KEYWORD),
            ("business_id", qmodels.PayloadSchemaType.KEYWORD),
            ("title", qmodels.PayloadSchemaType.TEXT),
            ("full_text", qmodels.PayloadSchemaType.TEXT),
            ("leadStatus", qmodels.PayloadSchemaType.KEYWORD),
            ("taskStatus", qmodels.PayloadSchemaType.KEYWORD),
            ("activityStatus", qmodels.PayloadSchemaType.KEYWORD),
            ("meetingStatus", qmodels.PayloadSchemaType.KEYWORD),
            ("callStatus", qmodels.PayloadSchemaType.KEYWORD),
            ("priority", qmodels.PayloadSchemaType.KEYWORD),
            ("type", qmodels.PayloadSchemaType.KEYWORD),
            ("mailType", qmodels.PayloadSchemaType.KEYWORD),
            ("callType", qmodels.PayloadSchemaType.KEYWORD),
            ("meetingType", qmodels.PayloadSchemaType.KEYWORD),
            ("createdByName", qmodels.PayloadSchemaType.KEYWORD),
            ("assignedName", qmodels.PayloadSchemaType.KEYWORD),
            ("leadName", qmodels.PayloadSchemaType.KEYWORD),
            ("createdTimeStamp", qmodels.PayloadSchemaType.DATETIME),
            ("updatedTimeStamp", qmodels.PayloadSchemaType.DATETIME),
            ("createdAt", qmodels.PayloadSchemaType.DATETIME),
            ("updatedAt", qmodels.PayloadSchemaType.DATETIME),
            ("startDateTime", qmodels.PayloadSchemaType.DATETIME),
            ("endDateTime", qmodels.PayloadSchemaType.DATETIME),
            ("dueDate", qmodels.PayloadSchemaType.DATETIME),
            ("chunk_index", qmodels.PayloadSchemaType.INTEGER),
            ("parent_id", qmodels.PayloadSchemaType.KEYWORD),
            ("mongo_id", qmodels.PayloadSchemaType.KEYWORD),
        ]

        for field_name, schema in indexed_fields:
            try:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema,
                )
            except Exception as exc:
                if "already exists" not in str(exc):
                    logger.error(f"Failed to ensure index on '{field_name}': {exc}")

    except Exception as exc:  # pragma: no cover - top-level guard
        logger.error(f"Could not ensure collection '{collection_name}': {exc}")


def _decode_uuid_bytes(data: bytes) -> Optional[str]:
    if len(data) == 16:
        try:
            return str(uuid.UUID(bytes=data))
        except Exception:
            return None
    return None


def _coerce_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            # Mongo extended JSON stores epoch millis
            dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        if isinstance(value, str):
            # Already ISO / RFC3339 string
            # Attempt to parse to normalise format, fallback to original string
            try:
                dt = datetime.fromisoformat(value.rstrip("Z"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            except ValueError:
                return value
    except Exception:
        return None
    return None


def normalize_mongo_id(mongo_id: Any) -> str:
    if mongo_id is None:
        return ""
    if isinstance(mongo_id, ObjectId):
        return str(mongo_id)
    if isinstance(mongo_id, Binary):
        if mongo_id.subtype in (3, 4) and len(mongo_id) == 16:
            try:
                return str(uuid.UUID(bytes=mongo_id))
            except Exception:
                pass
        return mongo_id.hex()
    if isinstance(mongo_id, dict):
        for key in ("$oid", "oid", "$uuid", "uuid", "value"):
            if key in mongo_id and mongo_id[key] is not None:
                try:
                    return str(mongo_id[key])
                except Exception:
                    continue

        # Extended JSON binary variations
        if "$binary" in mongo_id:
            binary_section = mongo_id.get("$binary")
            subtype = (
                mongo_id.get("$type")
                or mongo_id.get("type")
                or mongo_id.get("subType")
                or mongo_id.get("subtype")
            )

            base64_value: Optional[str] = None

            if isinstance(binary_section, dict):
                base64_value = (
                    binary_section.get("base64")
                    or binary_section.get("$base64")
                    or binary_section.get("data")
                )
                subtype = (
                    binary_section.get("subType")
                    or binary_section.get("subtype")
                    or binary_section.get("$type")
                    or subtype
                )
            elif isinstance(binary_section, str):
                base64_value = binary_section

            if base64_value:
                try:
                    data = base64.b64decode(base64_value)
                    uuid_str = _decode_uuid_bytes(data)
                    if uuid_str:
                        return uuid_str
                    # For non-UUID binary payloads fall back to hex
                    return data.hex()
                except Exception:
                    pass

            if subtype and isinstance(subtype, str):
                subtype_lower = subtype.lower()
                if subtype_lower in {"03", "3", "04", "4"} and base64_value:
                    try:
                        data = base64.b64decode(base64_value)
                        uuid_str = _decode_uuid_bytes(data)
                        if uuid_str:
                            return uuid_str
                    except Exception:
                        pass

        # Legacy Mongo export occasionally uses {"binary": "...", "type": "03"}
        if "binary" in mongo_id and isinstance(mongo_id["binary"], str):
            try:
                data = base64.b64decode(mongo_id["binary"])
                uuid_str = _decode_uuid_bytes(data)
                if uuid_str:
                    return uuid_str
            except Exception:
                pass

        return json.dumps(mongo_id, sort_keys=True)
    return str(mongo_id)


def _is_id_like_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    if key == "_id":
        return True
    lowered = key.lower()
    if lowered == "id":
        return True
    if lowered.endswith("_id"):
        return True
    if key.endswith("Id") or key.endswith("ID"):
        return True
    if lowered.endswith("uuid"):
        return True
    return False


def _looks_like_extended_id(value: Dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    lowered_keys = {str(k).lower() for k in value.keys()}
    if {"$oid", "oid"} & lowered_keys:
        return True
    if {"$uuid", "uuid"} & lowered_keys:
        return True
    if "$binary" in lowered_keys or "binary" in lowered_keys:
        return True
    return False


def normalize_document_ids(obj: Any) -> Any:
    if isinstance(obj, (ObjectId, Binary)):
        return normalize_mongo_id(obj)
    if isinstance(obj, datetime):
        # Convert datetime objects to ISO format strings
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat().replace("+00:00", "Z")

    if isinstance(obj, dict):
        # Handle extended JSON date / numeric wrappers
        if "$date" in obj and len(obj) == 1:
            normalized_date = _coerce_date(obj.get("$date"))
            if normalized_date is not None:
                return normalized_date
        if "$numberLong" in obj and len(obj) == 1:
            try:
                return int(obj.get("$numberLong"))
            except Exception:
                pass
        if "$numberInt" in obj and len(obj) == 1:
            try:
                return int(obj.get("$numberInt"))
            except Exception:
                pass
        if "$numberDouble" in obj and len(obj) == 1:
            try:
                return float(obj.get("$numberDouble"))
            except Exception:
                pass

        if _looks_like_extended_id(obj):
            return normalize_mongo_id(obj)

        normalized: Dict[str, Any] = {}
        for key, value in obj.items():
            if _is_id_like_key(key):
                normalized[key] = normalize_mongo_id(value)
            else:
                normalized[key] = normalize_document_ids(value)
        return normalized

    if isinstance(obj, list):
        return [normalize_document_ids(item) for item in obj]

    return obj


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<(br|BR)\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def point_id_from_seed(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def chunk_text(
    text: str,
    *,
    max_words: int,
    overlap_words: int,
    min_words_to_chunk: Optional[int] = None,
) -> List[str]:
    if not text:
        return []

    words = text.split()
    threshold = min_words_to_chunk if min_words_to_chunk is not None else max_words

    if len(words) <= threshold:
        return [text]

    chunks: List[str] = []
    step = max(1, max_words - overlap_words)
    for start in range(0, len(words), step):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
    return chunks


def get_chunks_for_content(text: str, content_type: str) -> List[str]:
    config = CHUNKING_CONFIG.get(content_type, CHUNKING_CONFIG["lead"])
    return chunk_text(
        text,
        max_words=config["max_words"],
        overlap_words=config["overlap_words"],
        min_words_to_chunk=config.get("min_words_to_chunk", config["max_words"]),
    )


# ---------------------------------------------------------------------------
# Document preparation / chunking / point generation
# ---------------------------------------------------------------------------


def prepare_document(collection_name: str, doc: Dict[str, Any]) -> Tuple[Optional[PreparedDocument], List[str]]:
    """Convert a Mongo document into a normalized representation."""

    if not doc:
        return None, ["WARN: received empty document"]

    doc = normalize_document_ids(doc)

    canonical_collection = canonicalize_collection_name(collection_name)
    if canonical_collection is None:
        return None, [f"INFO: skipping unsupported collection '{collection_name}'"]

    content_type = CRM_COLLECTIONS.get(canonical_collection)
    if not content_type:
        return None, [f"INFO: skipping unsupported collection '{collection_name}'"]

    try:
        if content_type == "lead":
            return _prepare_lead(doc)
        if content_type == "task":
            return _prepare_task(doc)
        if content_type == "activity":
            return _prepare_activity(doc)
        if content_type == "meeting":
            return _prepare_meeting(doc)
        if content_type == "notes":
            return _prepare_notes(doc)
        if content_type == "callLog":
            return _prepare_callLog(doc)
        if content_type == "mailInfo":
            return _prepare_mailInfo(doc)
        if content_type == "leadScoreRule":
            return _prepare_leadScoreRule(doc)
        if content_type == "segmentation":
            return _prepare_segmentation(doc)
    except SkipDocument as exc:
        return None, [str(exc)]
    except Exception as exc:  # pragma: no cover - defensive logging
        return None, [f"ERROR: failed to prepare document from '{collection_name}': {exc}"]

    return None, [f"INFO: no handler for collection '{collection_name}'"]


def chunk_prepared_document(prepared: PreparedDocument) -> List[str]:
    if not prepared.combined_text:
        return []
    chunks = get_chunks_for_content(prepared.combined_text, prepared.content_type)
    return chunks or [prepared.combined_text]


def generate_points(
    prepared: PreparedDocument,
    chunks: Iterable[str],
    embedder: Any,
    splade_encoder: Any,
) -> List[qmodels.PointStruct]:
    chunk_list = list(chunks)
    if not chunk_list:
        return []

    vectors = embedder.encode(chunk_list)
    if hasattr(vectors, "tolist"):
        vectors = vectors.tolist()

    if len(vectors) != len(chunk_list):
        raise ValueError("embedding dimension mismatch with chunk count")

    points: List[qmodels.PointStruct] = []
    for idx, chunk in enumerate(chunk_list):
        vector = vectors[idx]
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        if not isinstance(vector, list):
            vector = [float(x) for x in vector]

        full_text = f"{prepared.title} {chunk}".strip()

        payload: Dict[str, Any] = {
            "mongo_id": prepared.mongo_id,
            "parent_id": prepared.mongo_id,
            "chunk_index": idx,
            "chunk_count": len(chunk_list),
            "title": prepared.title,
            "content": chunk,
            "full_text": full_text,
            "content_type": prepared.content_type,
        }
        payload.update({k: v for k, v in prepared.metadata.items() if v is not None})

        vector_map: Dict[str, Any] = {"dense": [float(x) for x in vector]}

        if splade_encoder is not None:
            splade_vec = splade_encoder.encode_text(full_text)
            if splade_vec.get("indices"):
                vector_map["sparse"] = qmodels.SparseVector(
                    indices=splade_vec["indices"], values=splade_vec["values"]
                )

        point_id = point_id_from_seed(f"{prepared.mongo_id}/{prepared.content_type}/{idx}")
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=vector_map,
                payload=payload,
            )
        )

    return points


# ---------------------------------------------------------------------------
# Internal helpers per content type
# ---------------------------------------------------------------------------


class SkipDocument(RuntimeError):
    pass


def _extend_with_text(parts: List[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = html_to_text(value)
        if text:
            parts.append(text)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _extend_with_text(parts, item)
    elif isinstance(value, dict):
        for item in value.values():
            _extend_with_text(parts, item)
    else:
        text = str(value)
        if text and text.lower() not in {"none", "null"}:
            parts.append(text)


def _prepare_lead(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    # Personal info
    if doc.get("personalInfo") and isinstance(doc["personalInfo"], dict):
        pi = doc["personalInfo"]
        if pi.get("name"):
            text_parts.append(f"Name: {pi['name']}")
        if pi.get("email"):
            text_parts.append(f"Email: {pi['email']}")
        if pi.get("mobile"):
            text_parts.append(f"Mobile: {pi['mobile']}")

    # Notes
    if doc.get("notes"):
        text_parts.append(f"Notes: {doc['notes']}")

    # More info
    if doc.get("moreInfo") and isinstance(doc["moreInfo"], dict):
        for key, value in doc["moreInfo"].items():
            if isinstance(value, str) and value.strip():
                text_parts.append(f"{key}: {value}")

    # Company info
    if doc.get("company") and isinstance(doc["company"], dict):
        if doc["company"].get("name"):
            text_parts.append(f"Company: {doc['company']['name']}")

    # Field data
    if doc.get("fieldData") and isinstance(doc["fieldData"], list):
        for field in doc["fieldData"]:
            if isinstance(field, dict) and field.get("fieldValue"):
                field_name = field.get("fieldName", "")
                field_value = str(field.get("fieldValue", ""))
                if field_value.strip():
                    text_parts.append(f"{field_name}: {field_value}")

    combined_text = " ".join(text_parts).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping lead {mongo_id} - no substantial text content")

    title = doc.get("referenceNo", f"Lead {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "referenceNo": doc.get("referenceNo"),
        "leadStatus": doc.get("leadStatus"),
        "type": doc.get("type"),
        "customerType": doc.get("customerType"),
        "source": doc.get("source"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    if doc.get("pipeline") and isinstance(doc["pipeline"], dict):
        metadata["pipeline_name"] = doc["pipeline"].get("name")

    if doc.get("createdByName"):
        metadata["created_by_name"] = doc["createdByName"]

    if doc.get("staffName"):
        metadata["staff_name"] = doc["staffName"]

    prepared = PreparedDocument(
        content_type="lead",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_task(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("name"):
        text_parts.append(doc["name"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("parentName"):
        text_parts.append(f"Parent: {doc['parentName']}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping task {mongo_id} - no substantial text content")

    title = doc.get("name", f"Task {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "priority": doc.get("priority"),
        "taskStatus": doc.get("taskStatus"),
        "dueDate": _coerce_date(doc.get("dueDate")),
        "parentName": doc.get("parentName"),
        "assignedName": doc.get("assignedName"),
        "createdByName": doc.get("createdByName"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="task",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_activity(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("type"):
        text_parts.append(f"Type: {doc['type']}")
    if doc.get("data"):
        data = doc["data"]
        if isinstance(data, str):
            text_parts.append(data)
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and value.strip():
                    text_parts.append(f"{key}: {value}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping activity {mongo_id} - no substantial text content")

    title = doc.get("type", f"Activity {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "type": doc.get("type"),
        "activityStatus": doc.get("activityStatus"),
        "createdByName": doc.get("createdByName"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="activity",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_meeting(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("title"):
        text_parts.append(doc["title"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("leadName"):
        text_parts.append(f"Lead: {doc['leadName']}")
    if doc.get("participantsList") and isinstance(doc["participantsList"], list):
        participants = []
        for p in doc["participantsList"]:
            if isinstance(p, dict) and p.get("leadName"):
                participants.append(p["leadName"])
        if participants:
            text_parts.append(f"Participants: {', '.join(participants)}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping meeting {mongo_id} - no substantial text content")

    title = doc.get("title", f"Meeting {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "meetingStatus": doc.get("meetingStatus"),
        "meetingType": doc.get("meetingType"),
        "leadName": doc.get("leadName"),
        "assignedName": doc.get("assignedName"),
        "createdByName": doc.get("createdByName"),
        "startDateTime": _coerce_date(doc.get("startDateTime")),
        "endDateTime": _coerce_date(doc.get("endDateTime")),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="meeting",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_notes(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("subject"):
        text_parts.append(doc["subject"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("leadName"):
        text_parts.append(f"Lead: {doc['leadName']}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping notes {mongo_id} - no substantial text content")

    title = doc.get("subject", f"Note {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "leadName": doc.get("leadName"),
        "createdByName": doc.get("createdByName"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="notes",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_callLog(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("title"):
        text_parts.append(doc["title"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("callPurpose"):
        text_parts.append(f"Purpose: {doc['callPurpose']}")
    if doc.get("otherReason"):
        text_parts.append(f"Reason: {doc['otherReason']}")
    if doc.get("leadName"):
        text_parts.append(f"Lead: {doc['leadName']}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping call log {mongo_id} - no substantial text content")

    title = doc.get("title", f"Call Log {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "callStatus": doc.get("callStatus"),
        "callType": doc.get("callType"),
        "callPurpose": doc.get("callPurpose"),
        "leadName": doc.get("leadName"),
        "createdByName": doc.get("createdByName"),
        "startDateTime": _coerce_date(doc.get("startDateTime")),
        "callDuration": doc.get("callDuration"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="callLog",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_mailInfo(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("subject"):
        text_parts.append(doc["subject"])
    if doc.get("body"):
        body_clean = html_to_text(doc["body"])
        if body_clean:
            text_parts.append(body_clean)
    if doc.get("toMails"):
        if isinstance(doc["toMails"], list):
            text_parts.append(f"To: {', '.join(doc['toMails'])}")
        elif isinstance(doc["toMails"], str):
            text_parts.append(f"To: {doc['toMails']}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping mail info {mongo_id} - no substantial text content")

    title = doc.get("subject", f"Mail {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "mailType": doc.get("mailType"),
        "createdByName": doc.get("createdByName"),
        "createdTimeStamp": _coerce_date(doc.get("createdTimeStamp")),
        "updatedTimeStamp": _coerce_date(doc.get("updatedTimeStamp")),
    }

    if doc.get("businessId"):
        try:
            metadata["business_id"] = normalize_mongo_id(doc["businessId"])
        except Exception:
            pass

    prepared = PreparedDocument(
        content_type="mailInfo",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_leadScoreRule(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("name"):
        text_parts.append(doc["name"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("field"):
        text_parts.append(f"Field: {doc['field']}")
    if doc.get("operator"):
        text_parts.append(f"Operator: {doc['operator']}")
    if doc.get("value"):
        text_parts.append(f"Value: {doc['value']}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping lead score rule {mongo_id} - no substantial text content")

    title = doc.get("name", f"Lead Score Rule {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "score": doc.get("score"),
        "change": doc.get("change"),
        "isActive": doc.get("isActive"),
        "field": doc.get("field"),
        "operator": doc.get("operator"),
        "value": doc.get("value"),
        "createdAt": _coerce_date(doc.get("createdAt")),
        "updatedAt": _coerce_date(doc.get("updatedAt")),
    }

    if doc.get("business") and isinstance(doc["business"], dict):
        if doc["business"].get("_id"):
            try:
                metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
            except Exception:
                pass

    prepared = PreparedDocument(
        content_type="leadScoreRule",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_segmentation(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    text_parts: List[str] = []

    if doc.get("name"):
        text_parts.append(doc["name"])
    if doc.get("description"):
        text_parts.append(doc["description"])
    if doc.get("conditions"):
        if isinstance(doc["conditions"], dict):
            conditions_text = json.dumps(doc["conditions"], indent=2)
            text_parts.append(f"Conditions: {conditions_text}")
        elif isinstance(doc["conditions"], str):
            text_parts.append(f"Conditions: {doc['conditions']}")
    if doc.get("tags") and isinstance(doc["tags"], list):
        text_parts.append(f"Tags: {', '.join(doc['tags'])}")

    combined_text = " ".join(filter(None, text_parts)).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping segmentation {mongo_id} - no substantial text content")

    title = doc.get("name", f"Segmentation {mongo_id[:8]}")

    metadata: Dict[str, Any] = {
        "isActive": doc.get("isActive"),
        "createdAt": _coerce_date(doc.get("createdAt")),
        "updatedAt": _coerce_date(doc.get("updatedAt")),
    }

    if doc.get("tags") and isinstance(doc["tags"], list):
        metadata["tags"] = doc["tags"]

    if doc.get("business") and isinstance(doc["business"], dict):
        if doc["business"].get("_id"):
            try:
                metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
            except Exception:
                pass

    prepared = PreparedDocument(
        content_type="segmentation",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []

