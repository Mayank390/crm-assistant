from __future__ import annotations

"""Reusable helpers for Project Management ? Qdrant indexing."""

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
    "page": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "work_item": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "project": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "cycle": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "module": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "epic": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "feature": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
    "user_story": {"max_words": 220, "overlap_words": 40, "min_words_to_chunk": 220},
}


PROJECT_COLLECTIONS: Dict[str, str] = {
    "page": "page",
    "workitem": "work_item",
    "project": "project",
    "projects": "project",
    "cycle": "cycle",
    "module": "module",
    "epic": "epic",
    "feature": "feature",
    "userstory": "user_story",
}


COLLECTION_ALIASES: Dict[str, str] = {
    "page": "page",
    "pages": "page",
    "Page": "page",
    "Project": "project",
    "Projects": "project",
    "workItem": "workitem",
    "workitem": "workitem",
    "work_item": "workitem",
    "workitems": "workitem",
    "project": "project",
    "projects": "project",
    "cycle": "cycle",
    "cycles": "cycle",
    "module": "module",
    "modules": "module",
    "epic": "epic",
    "epics": "epic",
    "feature": "feature",
    "features": "feature",
    "userStory": "userstory",
    "userStories": "userstory",
    "userstory": "userstory",
    "userstories": "userstory",
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
            ("project_name", qmodels.PayloadSchemaType.KEYWORD),
            ("projectDisplayId", qmodels.PayloadSchemaType.KEYWORD),
            ("title", qmodels.PayloadSchemaType.TEXT),
            ("full_text", qmodels.PayloadSchemaType.TEXT),
            ("status", qmodels.PayloadSchemaType.KEYWORD),
            ("priority", qmodels.PayloadSchemaType.KEYWORD),
            ("state_name", qmodels.PayloadSchemaType.KEYWORD),
            ("stateMaster_name", qmodels.PayloadSchemaType.KEYWORD),
            ("assignee_name", qmodels.PayloadSchemaType.KEYWORD),
            ("business_name", qmodels.PayloadSchemaType.KEYWORD),
            ("labels", qmodels.PayloadSchemaType.KEYWORD),
            ("createdAt", qmodels.PayloadSchemaType.DATETIME),
            ("updatedAt", qmodels.PayloadSchemaType.DATETIME),
            ("startDate", qmodels.PayloadSchemaType.DATETIME),
            ("endDate", qmodels.PayloadSchemaType.DATETIME),
            ("releaseDate", qmodels.PayloadSchemaType.DATETIME),
            ("chunk_index", qmodels.PayloadSchemaType.INTEGER),
            ("parent_id", qmodels.PayloadSchemaType.KEYWORD),
            ("project_id", qmodels.PayloadSchemaType.KEYWORD),
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


def parse_editorjs_blocks(content_str: str) -> Tuple[List[Dict[str, Any]], str]:
    if not content_str or not content_str.strip():
        return [], ""
    try:
        content_json = json.loads(content_str)
        blocks = content_json.get("blocks", [])
    except Exception as exc:
        logger.warning(f"Failed to parse EditorJS content: {exc}")
        return [], ""

    extracted: List[str] = []
    for block in blocks:
        btype = (block or {}).get("type") or ""
        data = (block or {}).get("data") or {}

        if btype in {"paragraph", "header", "quote"}:
            text = html_to_text(data.get("text", ""))
            caption = html_to_text(data.get("caption", "")) if btype == "quote" else ""
            line = text if not caption else f"{text} - {caption}"
            if line:
                extracted.append(line)
        elif btype == "list":
            items = data.get("items") or []
            style = (data.get("style") or "").lower()
            lines: List[str] = []
            for idx, item in enumerate(items, 1):
                item_text = html_to_text(item if isinstance(item, str) else str(item))
                if not item_text:
                    continue
                prefix = f"{idx}. " if style == "ordered" else "- "
                lines.append(prefix + item_text)
            if lines:
                extracted.append("\n".join(lines))
        elif btype == "checklist":
            items = data.get("items") or []
            lines: List[str] = []
            for item in items:
                text = html_to_text((item or {}).get("text", ""))
                if not text:
                    continue
                checked = bool((item or {}).get("checked", False))
                prefix = "[x] " if checked else "[ ] "
                lines.append(prefix + text)
            if lines:
                extracted.append("\n".join(lines))
        elif btype == "table":
            table = data.get("content") or []
            rows: List[str] = []
            for row in table:
                cells = [html_to_text(cell) for cell in (row or [])]
                rows.append(" | ".join(cells).strip())
            if rows:
                extracted.append("\n".join(rows))
        elif btype == "code":
            code = data.get("code", "").strip()
            if code:
                extracted.append(code)
        elif btype in {"image", "embed", "linkTool", "raw", "delimiter"}:
            parts: List[str] = []
            if data.get("caption"):
                parts.append(html_to_text(data.get("caption", "")))
            if btype == "linkTool":
                link = (data.get("link") or "").strip()
                meta = data.get("meta") or {}
                title = html_to_text(meta.get("title", "")) if isinstance(meta, dict) else ""
                description = (
                    html_to_text(meta.get("description", ""))
                    if isinstance(meta, dict)
                    else ""
                )
                parts.extend([p for p in [title, description, link] if p])
            text = " - ".join([p for p in parts if p])
            if text:
                extracted.append(text)
        else:
            text = html_to_text(data.get("text", ""))
            if text:
                extracted.append(text)

    combined_text = "\n\n".join([t for t in extracted if t]).strip()
    return blocks, combined_text


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
    config = CHUNKING_CONFIG.get(content_type, CHUNKING_CONFIG["work_item"])
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

    content_type = PROJECT_COLLECTIONS.get(canonical_collection)
    if not content_type:
        return None, [f"INFO: skipping unsupported collection '{collection_name}'"]

    try:
        if content_type == "page":
            return _prepare_page(doc)
        if content_type == "work_item":
            return _prepare_work_item(doc)
        if content_type == "project":
            return _prepare_project(doc)
        if content_type == "cycle":
            return _prepare_cycle(doc)
        if content_type == "module":
            return _prepare_module(doc)
        if content_type == "epic":
            return _prepare_epic(doc)
        if content_type == "feature":
            return _prepare_feature(doc)
        if content_type == "user_story":
            return _prepare_user_story(doc)
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


def _prepare_page(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    title = doc.get("title", "")
    _, combined_text = parse_editorjs_blocks(doc.get("content", ""))

    warnings: List[str] = []

    if combined_text:
        for field_name, field_value in doc.items():
            if field_name in {
                "_id",
                "title",
                "content",
                "visibility",
                "isFavourite",
                "createdAt",
                "updatedAt",
                "createdTimeStamp",
                "updatedTimeStamp",
                "project",
                "createdBy",
                "business",
            }:
                continue
            if isinstance(field_value, str) and len(field_value.strip()) > 20:
                combined_text += " " + field_value.strip()

    if not combined_text and title:
        combined_text = title
        warnings.append(
            f"WARN: page '{title}' ({mongo_id}) lacked content; title used as fallback"
        )

    if not combined_text:
        raise SkipDocument(f"WARN: skipping page {mongo_id} - empty title/content")

    metadata: Dict[str, Any] = {
        "visibility": doc.get("visibility"),
        "isFavourite": doc.get("isFavourite", False),
        "locked": doc.get("locked"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))
        if project.get("projectDisplayId"):
            metadata["projectDisplayId"] = project.get("projectDisplayId")

    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    linked_cycle = doc.get("linkedCycle")
    if isinstance(linked_cycle, list):
        cycle_names = []
        cycle_ids = []
        for entry in linked_cycle:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if name:
                cycle_names.append(name)
            if entry.get("_id") is not None:
                cycle_ids.append(normalize_mongo_id(entry.get("_id")))
        if cycle_names:
            metadata["linked_cycle_names"] = cycle_names
        if cycle_ids:
            metadata["linked_cycle_ids"] = cycle_ids

    linked_module = doc.get("linkedModule")
    if isinstance(linked_module, list):
        module_names = []
        module_ids = []
        for entry in linked_module:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if name:
                module_names.append(name)
            if entry.get("_id") is not None:
                module_ids.append(normalize_mongo_id(entry.get("_id")))
        if module_names:
            metadata["linked_module_names"] = module_names
        if module_ids:
            metadata["linked_module_ids"] = module_ids

    linked_pages = doc.get("linkedPages")
    if isinstance(linked_pages, list):
        page_titles = []
        page_ids = []
        for entry in linked_pages:
            if not isinstance(entry, dict):
                continue
            title_ref = entry.get("title") or entry.get("name")
            if title_ref:
                page_titles.append(title_ref)
            if entry.get("_id") is not None:
                page_ids.append(normalize_mongo_id(entry.get("_id")))
        if page_titles:
            metadata["linked_page_titles"] = page_titles
        if page_ids:
            metadata["linked_page_ids"] = page_ids

    linked_members = doc.get("linkedMembers")
    if isinstance(linked_members, list):
        member_names = []
        member_ids = []
        for member in linked_members:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                member_names.append(name)
            if member.get("_id") is not None:
                member_ids.append(normalize_mongo_id(member.get("_id")))
        if member_names:
            metadata["linked_member_names"] = member_names
        if member_ids:
            metadata["linked_member_ids"] = member_ids

    prepared = PreparedDocument(
        content_type="page",
        mongo_id=mongo_id,
        title=title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, warnings


def _prepare_work_item(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    title_clean = html_to_text(doc.get("title", ""))
    desc_clean = html_to_text(doc.get("description", ""))

    worklogs_descriptions: List[str] = []
    worklogs = doc.get("workLogs")
    if isinstance(worklogs, list):
        for log in worklogs:
            if isinstance(log, dict) and log.get("description"):
                worklogs_descriptions.append(html_to_text(log.get("description", "")))

    combined_text = " ".join(
        filter(None, [title_clean, desc_clean, " ".join(worklogs_descriptions)])
    ).strip()

    if not combined_text:
        raise SkipDocument(
            f"WARN: skipping work item {mongo_id} - no substantial text content"
        )

    metadata: Dict[str, Any] = {
        "displayBugNo": doc.get("displayBugNo"),
        "priority": doc.get("priority"),
        "status": doc.get("status"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
        "estimate": doc.get("estimate"),
        "type": doc.get("type"),
    }

    state = doc.get("state")
    if isinstance(state, dict):
        metadata["state_name"] = state.get("name")
        if state.get("_id") is not None:
            metadata["state_id"] = normalize_mongo_id(state.get("_id"))

    state_master = doc.get("stateMaster")
    if isinstance(state_master, dict):
        metadata["stateMaster_name"] = state_master.get("name")
        if state_master.get("_id") is not None:
            metadata["stateMaster_id"] = normalize_mongo_id(state_master.get("_id"))

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))
        if project.get("projectDisplayId"):
            metadata["projectDisplayId"] = project.get("projectDisplayId")

    cycle = doc.get("cycle")
    if isinstance(cycle, dict):
        metadata["cycle_name"] = cycle.get("name")
        if cycle.get("_id") is not None:
            metadata["cycle_id"] = normalize_mongo_id(cycle.get("_id"))

    modules = doc.get("modules")
    if isinstance(modules, dict):
        metadata["module_name"] = modules.get("name")
        if modules.get("_id") is not None:
            metadata["module_id"] = normalize_mongo_id(modules.get("_id"))

    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))

    user_story = doc.get("userStory")
    if isinstance(user_story, dict):
        metadata["user_story_name"] = user_story.get("name")
        if user_story.get("_id") is not None:
            metadata["user_story_id"] = normalize_mongo_id(user_story.get("_id"))

    feature = doc.get("feature")
    if isinstance(feature, dict):
        metadata["feature_name"] = feature.get("name")
        if feature.get("_id") is not None:
            metadata["feature_id"] = normalize_mongo_id(feature.get("_id"))

    epic = doc.get("epic")
    if isinstance(epic, dict):
        metadata["epic_name"] = epic.get("name")
        if epic.get("_id") is not None:
            metadata["epic_id"] = normalize_mongo_id(epic.get("_id"))

    assignee = doc.get("assignee")
    if isinstance(assignee, list):
        assignee_names: List[str] = []
        assignee_ids: List[str] = []
        for member in assignee:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                assignee_names.append(name)
            if member.get("_id") is not None:
                assignee_ids.append(normalize_mongo_id(member.get("_id")))
        if assignee_names:
            metadata["assignee_name"] = assignee_names[0]
            metadata["assignee_names"] = assignee_names
        if assignee_ids:
            metadata["assignee_ids"] = assignee_ids
    elif isinstance(assignee, dict):
        metadata["assignee_name"] = assignee.get("name")
        if assignee.get("_id") is not None:
            metadata["assignee_id"] = normalize_mongo_id(assignee.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    labels = doc.get("label")
    if isinstance(labels, list):
        label_names = [html_to_text((label or {}).get("name", "")) for label in labels]
        label_names = [name for name in label_names if name]
        if label_names:
            metadata["labels"] = label_names

    updated_by = doc.get("updatedBy")
    if isinstance(updated_by, list):
        updater_names: List[str] = []
        for member in updated_by:
            if isinstance(member, dict) and member.get("name"):
                updater_names.append(member.get("name"))
        if updater_names:
            metadata["updated_by_names"] = updater_names

    prepared = PreparedDocument(
        content_type="work_item",
        mongo_id=mongo_id,
        title=doc.get("title", ""),
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_project(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    name = doc.get("name", "")
    description = (doc.get("description") or "").strip()

    text_parts: List[str] = []
    if name:
        text_parts.append(name)
    if description and len(description) > 10:
        text_parts.append(description)

    excluded = {
        "_id",
        "name",
        "description",
        "createdAt",
        "updatedAt",
        "createdTimeStamp",
        "updatedTimeStamp",
        "business",
    }
    text_parts.extend(_aggregate_text_parts(doc, excluded_fields=excluded))

    combined_text = " ".join(text_parts).strip()
    if not combined_text:
        raise SkipDocument(
            f"WARN: skipping project {mongo_id} - no substantial text content"
        )

    metadata: Dict[str, Any] = {
        "projectDisplayId": doc.get("projectDisplayId"),
        "status": doc.get("status"),
        "access": doc.get("access"),
        "isActive": doc.get("isActive"),
        "isArchived": doc.get("isArchived"),
        "favourite": doc.get("favourite"),
        "leadMail": doc.get("leadMail"),
        "imageUrl": doc.get("imageUrl"),
        "icon": doc.get("icon"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }

    metadata.update(_build_metadata_with_business(doc))

    lead = doc.get("lead")
    if isinstance(lead, dict):
        metadata["lead_name"] = lead.get("name")
        if lead.get("_id") is not None:
            metadata["lead_id"] = normalize_mongo_id(lead.get("_id"))

    default_assignee = doc.get("defaultAsignee")
    if isinstance(default_assignee, dict):
        metadata["default_assignee_name"] = default_assignee.get("name")
        if default_assignee.get("_id") is not None:
            metadata["default_assignee_id"] = normalize_mongo_id(default_assignee.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    prepared = PreparedDocument(
        content_type="project",
        mongo_id=mongo_id,
        title=name,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_cycle(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    name = doc.get("name") or doc.get("title") or ""
    description = (doc.get("description") or "").strip()

    text_parts: List[str] = []
    if name:
        text_parts.append(name)
    if description and len(description) > 10:
        text_parts.append(description)

    excluded = {
        "_id",
        "name",
        "title",
        "description",
        "createdAt",
        "updatedAt",
        "createdTimeStamp",
        "updatedTimeStamp",
        "business",
    }
    text_parts.extend(_aggregate_text_parts(doc, excluded_fields=excluded))

    combined_text = " ".join(text_parts).strip()
    if not combined_text:
        raise SkipDocument(
            f"WARN: skipping cycle {mongo_id} - no substantial text content"
        )

    metadata: Dict[str, Any] = {
        "status": doc.get("status"),
        "startDate": doc.get("startDate"),
        "endDate": doc.get("endDate"),
        "isDefault": doc.get("isDefault"),
        "isFavourite": doc.get("isFavourite"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }

    metadata.update(_build_metadata_with_business(doc))

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    prepared = PreparedDocument(
        content_type="cycle",
        mongo_id=mongo_id,
        title=name,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_module(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    name = doc.get("name") or doc.get("title") or ""
    description = (doc.get("description") or "").strip()

    text_parts: List[str] = []
    if name:
        text_parts.append(name)
    if description and len(description) > 10:
        text_parts.append(description)

    excluded = {
        "_id",
        "name",
        "title",
        "description",
        "createdAt",
        "updatedAt",
        "createdTimeStamp",
        "updatedTimeStamp",
        "business",
    }
    text_parts.extend(_aggregate_text_parts(doc, excluded_fields=excluded))

    combined_text = " ".join(text_parts).strip()
    if not combined_text:
        raise SkipDocument(
            f"WARN: skipping module {mongo_id} - no substantial text content"
        )

    metadata: Dict[str, Any] = {
        "isFavourite": doc.get("isFavourite"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }

    metadata.update(_build_metadata_with_business(doc))

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))

    epic = doc.get("epic")
    if isinstance(epic, dict):
        metadata["epic_name"] = epic.get("name")
        if epic.get("_id") is not None:
            metadata["epic_id"] = normalize_mongo_id(epic.get("_id"))

    lead = doc.get("lead")
    if isinstance(lead, dict):
        metadata["lead_name"] = lead.get("name")
        if lead.get("_id") is not None:
            metadata["lead_id"] = normalize_mongo_id(lead.get("_id"))

    assignee = doc.get("assignee")
    if isinstance(assignee, list):
        assignee_names: List[str] = []
        assignee_ids: List[str] = []
        for member in assignee:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                assignee_names.append(name)
            if member.get("_id") is not None:
                assignee_ids.append(normalize_mongo_id(member.get("_id")))
        if assignee_names:
            metadata["assignee_names"] = assignee_names
            metadata["assignee_name"] = assignee_names[0]
        if assignee_ids:
            metadata["assignee_ids"] = assignee_ids
    elif isinstance(assignee, dict):
        metadata["assignee_name"] = assignee.get("name")
        if assignee.get("_id") is not None:
            metadata["assignee_id"] = normalize_mongo_id(assignee.get("_id"))

    prepared = PreparedDocument(
        content_type="module",
        mongo_id=mongo_id,
        title=name,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_epic(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    title_clean = html_to_text(doc.get("title", ""))
    desc_clean = html_to_text(doc.get("description", ""))
    combined_text = " ".join(filter(None, [title_clean, desc_clean])).strip()

    if not combined_text:
        raise SkipDocument(f"WARN: skipping epic {mongo_id} - no substantial text content")

    metadata: Dict[str, Any] = {
        "bugNo": doc.get("bugNo"),
        "priority": doc.get("priority"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }

    state = doc.get("state")
    if isinstance(state, dict):
        metadata["state_name"] = state.get("name")
        if state.get("_id") is not None:
            metadata["state_id"] = normalize_mongo_id(state.get("_id"))

    state_master = doc.get("stateMaster")
    if isinstance(state_master, dict):
        metadata["stateMaster_name"] = state_master.get("name")
        if state_master.get("_id") is not None:
            metadata["stateMaster_id"] = normalize_mongo_id(state_master.get("_id"))

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))
        if project.get("projectDisplayId"):
            metadata["projectDisplayId"] = project.get("projectDisplayId")

    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))

    assignee = doc.get("assignee")
    if isinstance(assignee, list):
        assignee_names: List[str] = []
        assignee_ids: List[str] = []
        for member in assignee:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                assignee_names.append(name)
            if member.get("_id") is not None:
                assignee_ids.append(normalize_mongo_id(member.get("_id")))
        if assignee_names:
            metadata["assignee_name"] = assignee_names[0]
            metadata["assignee_names"] = assignee_names
        if assignee_ids:
            metadata["assignee_ids"] = assignee_ids
    elif isinstance(assignee, dict):
        metadata["assignee_name"] = assignee.get("name")
        if assignee.get("_id") is not None:
            metadata["assignee_id"] = normalize_mongo_id(assignee.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    labels = doc.get("label")
    if isinstance(labels, list):
        label_names = [html_to_text((label or {}).get("name", "")) for label in labels]
        label_names = [name for name in label_names if name]
        if label_names:
            metadata["labels"] = label_names

    modules_list = doc.get("modulesList")
    if isinstance(modules_list, list):
        module_names = []
        module_ids = []
        for module_entry in modules_list:
            if not isinstance(module_entry, dict):
                continue
            name = module_entry.get("name")
            if name:
                module_names.append(name)
            if module_entry.get("_id") is not None:
                module_ids.append(normalize_mongo_id(module_entry.get("_id")))
        if module_names:
            metadata["module_names"] = module_names
        if module_ids:
            metadata["module_ids"] = module_ids

    prepared = PreparedDocument(
        content_type="epic",
        mongo_id=mongo_id,
        title=doc.get("title", ""),
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, []


def _prepare_feature(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    basic = doc.get("basicInfo") or {}
    title = html_to_text(basic.get("title", "") or doc.get("title", ""))

    text_parts: List[str] = []
    if title:
        text_parts.append(title)
    _extend_with_text(text_parts, doc.get("displayBugNo"))
    _extend_with_text(text_parts, basic.get("description"))
    _extend_with_text(text_parts, basic.get("status"))

    problem_info = doc.get("problemInfo") or {}
    _extend_with_text(text_parts, problem_info.get("statement"))
    _extend_with_text(text_parts, problem_info.get("objective"))
    _extend_with_text(text_parts, problem_info.get("successCriteria"))

    requirements = doc.get("requirements") or {}
    _extend_with_text(text_parts, requirements.get("functionalRequirements"))
    _extend_with_text(text_parts, requirements.get("nonFunctionalRequirements"))

    risk = doc.get("riskAndDependencies") or {}
    _extend_with_text(text_parts, risk.get("dependencies"))
    _extend_with_text(text_parts, risk.get("risks"))

    _extend_with_text(text_parts, doc.get("scope"))
    _extend_with_text(text_parts, doc.get("goals"))
    _extend_with_text(text_parts, doc.get("painPoints"))
    _extend_with_text(text_parts, doc.get("description"))

    work_items = doc.get("workItems")
    if isinstance(work_items, list):
        for item in work_items:
            if isinstance(item, dict):
                name = html_to_text(item.get("name", ""))
                if name:
                    text_parts.append(name)

    linked_stories = doc.get("userStories")
    if isinstance(linked_stories, list):
        for item in linked_stories:
            if isinstance(item, dict):
                name = html_to_text(item.get("name", ""))
                if name:
                    text_parts.append(name)

    links = doc.get("addLink")
    if isinstance(links, list):
        for entry in links:
            if not isinstance(entry, dict):
                continue
            display_title = html_to_text(entry.get("displayTitle", ""))
            if display_title:
                text_parts.append(display_title)
            url = entry.get("url")
            if isinstance(url, str) and url:
                text_parts.append(url)

    combined_text = " ".join(part for part in text_parts if part).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping feature {mongo_id} - no substantial text content")

    metadata: Dict[str, Any] = {
        "displayBugNo": doc.get("displayBugNo"),
        "priority": doc.get("priority"),
        "status": basic.get("status"),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "startDate": doc.get("startDate"),
        "endDate": doc.get("endDate"),
        "releaseDate": doc.get("releaseDate"),
    }

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))
        if project.get("projectDisplayId"):
            metadata["projectDisplayId"] = project.get("projectDisplayId")

    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))

    state = doc.get("state")
    if isinstance(state, dict):
        metadata["state_name"] = state.get("name")
        if state.get("_id") is not None:
            metadata["state_id"] = normalize_mongo_id(state.get("_id"))

    state_master = doc.get("stateMaster")
    if isinstance(state_master, dict):
        metadata["stateMaster_name"] = state_master.get("name")
        if state_master.get("_id") is not None:
            metadata["stateMaster_id"] = normalize_mongo_id(state_master.get("_id"))

    cycle = doc.get("cycle")
    if isinstance(cycle, dict):
        metadata["cycle_name"] = cycle.get("name")
        if cycle.get("_id") is not None:
            metadata["cycle_id"] = normalize_mongo_id(cycle.get("_id"))

    modules = doc.get("modules")
    if isinstance(modules, dict):
        metadata["module_name"] = modules.get("name")
        if modules.get("_id") is not None:
            metadata["module_id"] = normalize_mongo_id(modules.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    assignee = doc.get("assignee")
    if isinstance(assignee, list):
        assignee_names: List[str] = []
        assignee_ids: List[str] = []
        for member in assignee:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                assignee_names.append(name)
            if member.get("_id") is not None:
                assignee_ids.append(normalize_mongo_id(member.get("_id")))
        if assignee_names:
            metadata["assignee_name"] = assignee_names[0]
            metadata["assignee_names"] = assignee_names
        if assignee_ids:
            metadata["assignee_ids"] = assignee_ids
    elif isinstance(assignee, dict):
        metadata["assignee_name"] = assignee.get("name")
        if assignee.get("_id") is not None:
            metadata["assignee_id"] = normalize_mongo_id(assignee.get("_id"))

    epic = doc.get("epic")
    if isinstance(epic, dict):
        metadata["epic_name"] = epic.get("name")
        if epic.get("_id") is not None:
            metadata["epic_id"] = normalize_mongo_id(epic.get("_id"))

    labels = doc.get("label")
    if isinstance(labels, list):
        label_names = [html_to_text((label or {}).get("name", "")) for label in labels]
        label_names = [name for name in label_names if name]
        if label_names:
            metadata["labels"] = label_names
            text_parts.extend(label_names)

    linked_work_items = doc.get("workItems")
    if isinstance(linked_work_items, list):
        work_item_names = []
        work_item_ids = []
        for item in linked_work_items:
            if not isinstance(item, dict):
                continue
            name = html_to_text(item.get("name", ""))
            if name:
                work_item_names.append(name)
            if item.get("_id") is not None:
                work_item_ids.append(normalize_mongo_id(item.get("_id")))
        if work_item_names:
            metadata["work_item_names"] = work_item_names
        if work_item_ids:
            metadata["work_item_ids"] = work_item_ids

    linked_user_stories = doc.get("userStories")
    if isinstance(linked_user_stories, list):
        story_names = []
        story_ids = []
        for story in linked_user_stories:
            if not isinstance(story, dict):
                continue
            name = html_to_text(story.get("name", ""))
            if name:
                story_names.append(name)
            if story.get("_id") is not None:
                story_ids.append(normalize_mongo_id(story.get("_id")))
        if story_names:
            metadata["user_story_names"] = story_names
        if story_ids:
            metadata["user_story_ids"] = story_ids

    prepared_title = title or doc.get("displayBugNo", "") or mongo_id
    warnings: List[str] = []
    if not title:
        warnings.append(f"WARN: feature {mongo_id} missing title; using identifier fallback")

    prepared = PreparedDocument(
        content_type="feature",
        mongo_id=mongo_id,
        title=prepared_title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, warnings


def _prepare_user_story(doc: Dict[str, Any]) -> Tuple[PreparedDocument, List[str]]:
    mongo_id = normalize_mongo_id(doc.get("_id"))
    title = html_to_text(doc.get("title", ""))

    text_parts: List[str] = []
    if title:
        text_parts.append(title)
    _extend_with_text(text_parts, doc.get("displayBugNo"))
    _extend_with_text(text_parts, doc.get("demographics"))
    _extend_with_text(text_parts, doc.get("description"))
    _extend_with_text(text_parts, doc.get("summary"))
    _extend_with_text(text_parts, doc.get("acceptanceCriteria"))
    _extend_with_text(text_parts, doc.get("notes"))

    excluded = {
        "_id",
        "displayBugNo",
        "title",
        "description",
        "demographics",
        "project",
        "business",
        "state",
        "stateMaster",
        "createdAt",
        "updatedAt",
        "createdBy",
        "priority",
        "assignee",
        "label",
    }
    text_parts.extend(_aggregate_text_parts(doc, excluded_fields=excluded))

    combined_text = " ".join(part for part in text_parts if part).strip()
    if not combined_text:
        raise SkipDocument(f"WARN: skipping user story {mongo_id} - no substantial text content")

    metadata: Dict[str, Any] = {
        "displayBugNo": doc.get("displayBugNo"),
        "demographics": doc.get("demographics"),
        "priority": doc.get("priority"),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "persona": doc.get("persona"),
        "userGoal": doc.get("userGoal"),
    }

    project = doc.get("project")
    if isinstance(project, dict):
        metadata["project_name"] = project.get("name")
        if project.get("_id") is not None:
            metadata["project_id"] = normalize_mongo_id(project.get("_id"))
        if project.get("projectDisplayId"):
            metadata["projectDisplayId"] = project.get("projectDisplayId")

    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))

    state = doc.get("state")
    if isinstance(state, dict):
        metadata["state_name"] = state.get("name")
        if state.get("_id") is not None:
            metadata["state_id"] = normalize_mongo_id(state.get("_id"))

    state_master = doc.get("stateMaster")
    if isinstance(state_master, dict):
        metadata["stateMaster_name"] = state_master.get("name")
        if state_master.get("_id") is not None:
            metadata["stateMaster_id"] = normalize_mongo_id(state_master.get("_id"))

    feature = doc.get("feature")
    if isinstance(feature, dict):
        metadata["feature_name"] = feature.get("name")
        if feature.get("_id") is not None:
            metadata["feature_id"] = normalize_mongo_id(feature.get("_id"))

    epic = doc.get("epic")
    if isinstance(epic, dict):
        metadata["epic_name"] = epic.get("name")
        if epic.get("_id") is not None:
            metadata["epic_id"] = normalize_mongo_id(epic.get("_id"))

    modules = doc.get("modules")
    if isinstance(modules, dict):
        metadata["module_name"] = modules.get("name")
        if modules.get("_id") is not None:
            metadata["module_id"] = normalize_mongo_id(modules.get("_id"))

    created_by = doc.get("createdBy")
    if isinstance(created_by, dict):
        metadata["created_by_name"] = created_by.get("name")
        if created_by.get("_id") is not None:
            metadata["created_by_id"] = normalize_mongo_id(created_by.get("_id"))

    assignee = doc.get("assignee")
    if isinstance(assignee, list):
        assignee_names: List[str] = []
        assignee_ids: List[str] = []
        for member in assignee:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            if name:
                assignee_names.append(name)
            if member.get("_id") is not None:
                assignee_ids.append(normalize_mongo_id(member.get("_id")))
        if assignee_names:
            metadata["assignee_name"] = assignee_names[0]
            metadata["assignee_names"] = assignee_names
        if assignee_ids:
            metadata["assignee_ids"] = assignee_ids
    elif isinstance(assignee, dict):
        metadata["assignee_name"] = assignee.get("name")
        if assignee.get("_id") is not None:
            metadata["assignee_id"] = normalize_mongo_id(assignee.get("_id"))

    labels = doc.get("label")
    if isinstance(labels, list):
        label_names = [html_to_text((label or {}).get("name", "")) for label in labels]
        label_names = [name for name in label_names if name]
        if label_names:
            metadata["labels"] = label_names
            text_parts.extend(label_names)

    linked_work_items = doc.get("workItems")
    if isinstance(linked_work_items, list):
        work_item_names = []
        work_item_ids = []
        for item in linked_work_items:
            if not isinstance(item, dict):
                continue
            name = html_to_text(item.get("name", ""))
            if name:
                work_item_names.append(name)
            if item.get("_id") is not None:
                work_item_ids.append(normalize_mongo_id(item.get("_id")))
        if work_item_names:
            metadata["work_item_names"] = work_item_names
        if work_item_ids:
            metadata["work_item_ids"] = work_item_ids

    prepared_title = title or doc.get("displayBugNo", "") or mongo_id
    warnings: List[str] = []
    if not title:
        warnings.append(f"WARN: user story {mongo_id} missing title; using identifier fallback")

    prepared = PreparedDocument(
        content_type="user_story",
        mongo_id=mongo_id,
        title=prepared_title,
        combined_text=combined_text,
        metadata=metadata,
    )

    return prepared, warnings


def _aggregate_text_parts(doc: Dict[str, Any], *, excluded_fields: set[str]) -> List[str]:
    text_parts: List[str] = []
    for field_name, field_value in doc.items():
        if field_name in excluded_fields:
            continue
        if isinstance(field_value, str) and len(field_value.strip()) > 20:
            text_parts.append(field_value.strip())
    return text_parts


def _build_metadata_with_business(doc: Dict[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    business = doc.get("business")
    if isinstance(business, dict):
        metadata["business_name"] = business.get("name")
        if business.get("_id") is not None:
            metadata["business_id"] = normalize_mongo_id(business.get("_id"))
    return metadata