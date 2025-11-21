import os
import sys
import json
import uuid
import logging
from itertools import islice
from bson.binary import Binary
from bson.objectid import ObjectId
from qdrant_client.http.models import (
    PointStruct,
    PayloadSchemaType,
    Distance,
    VectorParams,
    OptimizersConfigDiff,
    SparseVectorParams,
    SparseVector,
)
# from embedding.service_client import EmbeddingServiceClient, Exception
from collections import defaultdict
from typing import List, Dict, Any, Optional

# Add the parent directory to sys.path so we can import from qdrant
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qdrant.dbconnection import (
    lead_collection,
    task_collection,
    activity_collection,
    meeting_collection,
    notes_collection,
    callLog_collection,
    mailInfo_collection,
    leadScoreRule_collection,
    segmentation_collection,
    qdrant_client,
    QDRANT_COLLECTION
)
from dotenv import load_dotenv
from huggingface_hub import login
import re
import html as html_lib
from qdrant.encoder import get_splade_encoder
from sentence_transformers import SentenceTransformer

# Load .env file and authenticate HuggingFace
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

hf_token = os.getenv("HuggingFace_API_KEY")
try:
    if hf_token:
        login(hf_token)
except Exception as e:
    logger.error(f"HuggingFace login failed: {e}")

# Load embedding model once, with fallback to a public model
try:
    embedder = SentenceTransformer(os.getenv("EMBEDDING_MODEL"))
    EMBEDDING_DIMENSION = 768
except ( ValueError) as exc:
    raise RuntimeError(f"Failed to initialize embedding service: {exc}") from exc

class ChunkingStats:
    """Track and display chunking statistics during indexing."""
    
    def __init__(self):
        self.by_type = defaultdict(lambda: {
            "total_docs": 0,
            "single_chunk": 0,
            "multi_chunk": 0,
            "total_chunks": 0,
            "chunk_distribution": defaultdict(int),
            "total_words": 0,
            "max_chunks": 0,
            "max_chunks_doc": None,
        })
    
    def record(self, content_type: str, doc_id: str, title: str, chunk_count: int, word_count: int):
        """Record chunking info for a document."""
        stats = self.by_type[content_type]
        stats["total_docs"] += 1
        stats["total_chunks"] += chunk_count
        stats["total_words"] += word_count
        stats["chunk_distribution"][chunk_count] += 1
        
        if chunk_count == 1:
            stats["single_chunk"] += 1
        else:
            stats["multi_chunk"] += 1
        
        if chunk_count > stats["max_chunks"]:
            stats["max_chunks"] = chunk_count
            stats["max_chunks_doc"] = (doc_id, title[:50])
    

# Global stats instance
_stats = ChunkingStats()

def ensure_collection_with_hybrid(
    collection_name: str,
    vector_size: int = 768,
    force_recreate: bool = False,
):
    """Ensure Qdrant collection supports dense + sparse (SPLADE) hybrid search without data loss.

    Behavior:
    - If the collection does not exist → create it with named dense and sparse vectors.
    - If the collection exists → do NOT drop it (unless force_recreate=True).
    - Always ensure optimizer and payload indexes idempotently.
    """
    try:
        should_create = False
        try:
            # Determine existence via list to avoid 404 exceptions
            existing_names = [c.name for c in qdrant_client.get_collections().collections]
            should_create = collection_name not in existing_names
        except Exception as e:
            # If listing fails, fallback to creation attempt path
            logger.error(f"Could not list collections: {e}")
            should_create = True

        if force_recreate:
            qdrant_client.recreate_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(size=vector_size, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )
        elif should_create:
            qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(size=vector_size, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )

        try:
            qdrant_client.update_collection(
                collection_name=collection_name,
                optimizer_config=OptimizersConfigDiff(indexing_threshold=1),
            )
        except Exception as e:
            logger.error(f"Failed to update optimizer config: {e}")

        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index on 'content_type': {e}")

        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name="business_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index on 'business_id': {e}")

        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name="project_name",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index on 'project_name': {e}")

        for text_field in ["title", "full_text"]:
            try:
                qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name=text_field,
                    field_schema=PayloadSchemaType.TEXT,
                )
            except Exception as e:
                if "already exists" not in str(e):
                    logger.error(f"Failed to ensure text index on '{text_field}': {e}")

        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name="chunk_index",
                field_schema=PayloadSchemaType.INTEGER,
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index on 'chunk_index': {e}")

        for field_name in ["parent_id", "project_id", "mongo_id"]:
            try:
                qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                if "already exists" not in str(e):
                    logger.error(f"Failed to ensure index on '{field_name}': {e}")
    except Exception as e:
        logger.error(f"Error ensuring collection '{collection_name}': {e}")

def normalize_mongo_id(mongo_id) -> str:
    """Convert Mongo _id (ObjectId or Binary UUID) into a safe string."""
    if isinstance(mongo_id, ObjectId):
        return str(mongo_id)
    elif isinstance(mongo_id, Binary) and mongo_id.subtype == 3:
        return str(uuid.UUID(bytes=mongo_id))
    return str(mongo_id)

def html_to_text(html: str) -> str:
    """Convert basic HTML to plain text, preserving simple line breaks and decoding entities."""
    if not html:
        return ""
    # Normalize common breaks to newlines
    text = re.sub(r"<(br|BR)\s*/?>", "\n", html)
    # Remove all other tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = html_lib.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def parse_editorjs_blocks(content_str: str):
    """Extract blocks from EditorJS JSON and produce a rich combined plain-text representation."""
    if not content_str or not content_str.strip():
        return [], ""
    try:
        content_json = json.loads(content_str)
        blocks = content_json.get("blocks", [])
        extracted: list[str] = []
        for block in blocks:
            btype = block.get("type") or ""
            data = block.get("data") or {}
            if btype in ("paragraph", "header", "quote"):
                text = html_to_text(data.get("text", ""))
                caption = html_to_text(data.get("caption", "")) if btype == "quote" else ""
                line = text if not caption else f"{text} — {caption}"
                if line:
                    extracted.append(line)
            elif btype == "list":
                items = data.get("items") or []
                style = (data.get("style") or "").lower()
                lines = []
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
                lines = []
                for item in items:
                    text = html_to_text((item or {}).get("text", ""))
                    checked = (item or {}).get("checked", False)
                    if text:
                        lines.append(("[x] " if checked else "[ ] ") + text)
                if lines:
                    extracted.append("\n".join(lines))
            elif btype == "table":
                table = data.get("content") or []
                rows = []
                for row in table:
                    cells = [html_to_text(cell) for cell in (row or [])]
                    rows.append(" | ".join(cells).strip())
                if rows:
                    extracted.append("\n".join(rows))
            elif btype == "code":
                code = data.get("code", "").strip()
                if code:
                    extracted.append(code)
            elif btype in ("image", "embed", "linkTool", "raw", "delimiter"):
                # Prefer human text fields; skip binary/media noise
                parts = []
                if data.get("caption"):
                    parts.append(html_to_text(data.get("caption", "")))
                if btype == "linkTool":
                    link = (data.get("link") or "").strip()
                    meta = data.get("meta") or {}
                    title = html_to_text(meta.get("title", "")) if isinstance(meta, dict) else ""
                    desc = html_to_text(meta.get("description", "")) if isinstance(meta, dict) else ""
                    parts.extend([p for p in [title, desc, link] if p])
                text = " - ".join([p for p in parts if p])
                if text:
                    extracted.append(text)
            else:
                # Fallback: try common 'text' field
                text = html_to_text(data.get("text", ""))
                if text:
                    extracted.append(text)

        # Separate blocks with newlines to retain structure
        combined_text = "\n\n".join([t for t in extracted if t]).strip()
        return blocks, combined_text
    except Exception as e:
        logger.error(f"Failed to parse content: {e}")
        return [], ""

def point_id_from_seed(seed: str) -> str:
    """Create a deterministic UUID from a seed string for Qdrant point IDs."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

# Chunking settings per content type
# Adjust these values to control chunking behavior
CHUNKING_CONFIG = {
    "lead": {
        "max_words": 220,
        "overlap_words": 40,
        "min_words_to_chunk": 220,
    },
    "task": {
        "max_words": 220,
        "overlap_words": 40,
        "min_words_to_chunk": 220,
    },
    "activity": {
        "max_words": 200,
        "overlap_words": 40,
        "min_words_to_chunk": 200,
    },
    "meeting": {
        "max_words": 220,
        "overlap_words": 40,
        "min_words_to_chunk": 220,
    },
    "notes": {
        "max_words": 220,
        "overlap_words": 40,
        "min_words_to_chunk": 220,
    },
    "callLog": {
        "max_words": 200,
        "overlap_words": 40,
        "min_words_to_chunk": 200,
    },
    "mailInfo": {
        "max_words": 220,
        "overlap_words": 40,
        "min_words_to_chunk": 220,
    },
    "leadScoreRule": {
        "max_words": 200,
        "overlap_words": 40,
        "min_words_to_chunk": 200,
    },
    "segmentation": {
        "max_words": 200,
        "overlap_words": 40,
        "min_words_to_chunk": 200,
    },
}

# For more aggressive chunking (more multi-chunk documents), use:
# CHUNKING_CONFIG = {
#     "page": {"max_words": 200, "overlap_words": 40, "min_words_to_chunk": 100},
#     "work_item": {"max_words": 150, "overlap_words": 30, "min_words_to_chunk": 80},
#     "project": {"max_words": 150, "overlap_words": 30, "min_words_to_chunk": 80},
#     "cycle": {"max_words": 150, "overlap_words": 30, "min_words_to_chunk": 80},
#     "module": {"max_words": 150, "overlap_words": 30, "min_words_to_chunk": 80},
# }

def chunk_text(text: str, max_words: int = 300, overlap_words: int = 60, min_words_to_chunk: int = None):
    """Split long text into overlapping word chunks suitable for embeddings.

    Args:
        text: Input text to chunk.
        max_words: Target words per chunk.
        overlap_words: Overlap words between consecutive chunks.
        min_words_to_chunk: Minimum words needed to trigger chunking (default: max_words).

    Returns:
        List of chunk strings.
    """
    if not text:
        return []
    
    words = text.split()
    min_threshold = min_words_to_chunk if min_words_to_chunk is not None else max_words
    
    # Don't chunk if below minimum threshold
    if len(words) <= min_threshold:
        return [text]
    
    chunks = []
    step = max(1, max_words - overlap_words)
    for start in range(0, len(words), step):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
    return chunks

def get_chunks_for_content(text: str, content_type: str):
    """Get chunks for a specific content type using its configuration.
    
    Args:
        text: Text to chunk
        content_type: Type of content (page, work_item, etc.)
        
    Returns:
        List of chunk strings
    """
    config = CHUNKING_CONFIG.get(content_type, CHUNKING_CONFIG["lead"])
    return chunk_text(
        text,
        max_words=config["max_words"],
        overlap_words=config["overlap_words"],
        min_words_to_chunk=config.get("min_words_to_chunk", config["max_words"])
    )

def batch_iterable(iterable, batch_size):
    """Yield successive batches from a list or iterable."""
    it = iter(iterable)
    while batch := list(islice(it, batch_size)):
        yield batch

def upload_in_batches(points, collection_name, batch_size=20):
    """Upload list of points to Qdrant in smaller batches."""
    total_indexed = 0
    for batch in batch_iterable(points, batch_size):
        try:
            qdrant_client.upsert(collection_name=collection_name, points=batch)
            total_indexed += len(batch)
        except Exception as e:
            logger.error(f"Failed to upload batch: {e}")
    return total_indexed

def _serialize_text_fields(data: Optional[Dict], prefix_map: Dict[str, str]) -> str:
    """Serializes a dictionary into a 'Key: Value' string format."""
    if not data or not isinstance(data, dict):
        return ""
    parts = []
    for key, prefix in prefix_map.items():
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{prefix}: {value.strip()}")
        elif isinstance(value, list) and value:
            list_text = "; ".join([str(v) for v in value if v])
            if list_text:
                parts.append(f"{prefix}: {list_text}")
    return ". ".join(parts)

def _serialize_list_of_strings_or_dicts(items: Optional[List], title_key: str = "title") -> str:
    """Serializes a list of strings or dicts (extracting 'title_key') into a text block."""
    if not items or not isinstance(items, list):
        return ""
    item_texts = []
    for item in items:
        if isinstance(item, str) and item.strip():
            item_texts.append(item.strip())
        elif isinstance(item, dict):
            title = item.get(title_key)
            if title and isinstance(title, str) and title.strip():
                item_texts.append(title.strip())
    return "; ".join(item_texts)

def _get_worklog_text(work_logs: Optional[List]) -> str:
    """Extracts and concatenates all worklog descriptions."""
    if not work_logs or not isinstance(work_logs, list):
        return ""
    descriptions = [
        log.get("description", "").strip()
        for log in work_logs
        if isinstance(log, dict) and log.get("description")
    ]
    return " ".join(descriptions)

def _serialize_risks(risks: Optional[List]) -> str:
    """Serializes the complex 'risks' list into readable text."""
    if not risks or not isinstance(risks, list):
        return ""
    risk_items: List[str] = []
    for r in risks:
        if isinstance(r, dict):
            parts: List[str] = []
            if r.get("description"):
                parts.append(r["description"])
            if r.get("problemLevel"):
                parts.append(f"(Problem: {r['problemLevel']}")
            if r.get("impactLevel"):
                parts.append(f"Impact: {r['impactLevel']})")
            if r.get("strategy"):
                parts.append(f"Strategy: {r['strategy']}")
            if parts:
                risk_items.append(" ".join(parts))
        elif isinstance(r, str) and r.strip():
            risk_items.append(r.strip())
    return "Risks: " + "; ".join(risk_items) if risk_items else ""

def _get_nested_val(data: Dict, key_path: str, default: Any = None) -> Any:
    """Safely get a nested value from a dict using dot notation."""
    keys = key_path.split('.')
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current

def _get_common_metadata(doc: Dict) -> Dict:
    """Extracts common metadata fields from any document."""
    metadata = {
        "priority": doc.get("priority"),
        "createdAt": doc.get("createdAt") or doc.get("createdTimeStamp"),
        "updatedAt": doc.get("updatedAt") or doc.get("updatedTimeStamp"),
    }
    
    if doc.get("state"):
        if isinstance(doc["state"], dict):
            metadata["state_name"] = doc["state"].get("name")
    elif doc.get("stateName"):
         metadata["state_name"] = doc.get("stateName")

    if doc.get("project"):
        if isinstance(doc["project"], dict):
            metadata["project_name"] = doc["project"].get("name")
            metadata["project_id"] = normalize_mongo_id(doc["project"].get("_id")) if doc["project"].get("_id") else None
    elif doc.get("projectName"):
        metadata["project_name"] = doc.get("projectName")

    if doc.get("business"):
        if isinstance(doc["business"], dict):
            metadata["business_name"] = doc["business"].get("name")
            if doc["business"].get("_id") is not None:
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["business"].get("_id"))
                except Exception:
                    pass
    
    assignee = doc.get("assignees") or doc.get("assignee")
    if assignee:
        if isinstance(assignee, list) and assignee and isinstance(assignee[0], dict):
            metadata["assignee_name"] = assignee[0].get("name")
        elif isinstance(assignee, dict):
            metadata["assignee_name"] = assignee.get("name")

    if doc.get("createdBy"):
        if isinstance(doc["createdBy"], dict):
            metadata["created_by_name"] = doc["createdBy"].get("name")
            
    if doc.get("label"):
        if isinstance(doc["label"], dict):
            metadata["label_name"] = doc["label"].get("name")

    return metadata

# ------------------ CRM Indexing Functions ------------------

def index_leads_to_qdrant():
    try:

        # Ensure collection and indexes for hybrid search
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)

        # Ensure payload index exists
        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception as e:
            if "already exists" in str(e):
                pass
            else:
                logger.error(f"Failed to ensure index: {e}")

        documents = lead_collection.find({}, {
            "_id": 1, "referenceNo": 1, "leadStatus": 1, "personalInfo": 1, 
            "notes": 1, "moreInfo": 1, "fieldData": 1, "company": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1,
            "createdById": 1, "createdByName": 1, "staffId": 1, "staffName": 1,
            "pipeline": 1, "source": 1, "type": 1, "customerType": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content from various fields
            text_parts = []
            
            # Personal info
            if doc.get("personalInfo"):
                pi = doc["personalInfo"]
                if isinstance(pi, dict):
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
                continue
            
            # Extract metadata
            metadata = {
                "referenceNo": doc.get("referenceNo"),
                "leadStatus": doc.get("leadStatus"),
                "type": doc.get("type"),
                "customerType": doc.get("customerType"),
                "source": doc.get("source"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            # Business ID
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Pipeline
            if doc.get("pipeline") and isinstance(doc["pipeline"], dict):
                metadata["pipeline_name"] = doc["pipeline"].get("name")
            
            # Created by
            if doc.get("createdByName"):
                metadata["created_by_name"] = doc["createdByName"]
            
            if doc.get("staffName"):
                metadata["staff_name"] = doc["staffName"]
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "lead")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("lead", mongo_id, doc.get("referenceNo", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("referenceNo", f"Lead {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "lead"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/lead/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid leads to index.")
            return {"status": "warning", "message": "No valid leads found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} lead chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during lead indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_tasks_to_qdrant():
    """Index Task collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index: {e}")

        documents = task_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "priority": 1, "taskStatus": 1,
            "dueDate": 1, "parentId": 1, "parentName": 1, "assignedTo": 1, "assignedName": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("name"):
                text_parts.append(doc["name"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("parentName"):
                text_parts.append(f"Parent: {doc['parentName']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "priority": doc.get("priority"),
                "taskStatus": doc.get("taskStatus"),
                "dueDate": doc.get("dueDate"),
                "parentName": doc.get("parentName"),
                "assignedName": doc.get("assignedName"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "task")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("task", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Task {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "task"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/task/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid tasks to index.")
            return {"status": "warning", "message": "No valid tasks found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} task chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during task indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_activities_to_qdrant():
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)

        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception as e:
            if "already exists" in str(e):
                pass
            else:
                logger.error(f"Failed to ensure index: {e}")

        documents = activity_collection.find({}, {
            "_id": 1, "type": 1, "activityStatus": 1, "data": 1,
            "leadId": 1, "parentId": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1, "createdById": 1, "createdByName": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content from data field (often JSON string)
            text_parts = []
            if doc.get("type"):
                text_parts.append(f"Type: {doc['type']}")
            if doc.get("data"):
                data = doc["data"]
                if isinstance(data, str):
                    text_parts.append(data)
                elif isinstance(data, dict):
                    # Serialize dict to text
                    for key, value in data.items():
                        if isinstance(value, str) and value.strip():
                            text_parts.append(f"{key}: {value}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "type": doc.get("type"),
                "activityStatus": doc.get("activityStatus"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "activity")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("activity", mongo_id, doc.get("type", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("type", f"Activity {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "activity"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/activity/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid activities to index.")
            return {"status": "warning", "message": "No valid activities found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} activity chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during activity indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_meetings_to_qdrant():
    """Index Meeting collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = meeting_collection.find({}, {
            "_id": 1, "title": 1, "description": 1, "meetingStatus": 1, "meetingType": 1,
            "leadId": 1, "leadName": 1, "startDateTime": 1, "endDateTime": 1,
            "assignedTo": 1, "assignedName": 1, "participantsList": 1, "meetingLink": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("title"):
                text_parts.append(doc["title"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("leadName"):
                text_parts.append(f"Lead: {doc['leadName']}")
            if doc.get("participantsList") and isinstance(doc["participantsList"], list):
                participants = []
                for p in doc["participantsList"]:
                    if isinstance(p, dict):
                        if p.get("leadName"):
                            participants.append(p["leadName"])
                if participants:
                    text_parts.append(f"Participants: {', '.join(participants)}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "meetingStatus": doc.get("meetingStatus"),
                "meetingType": doc.get("meetingType"),
                "leadName": doc.get("leadName"),
                "assignedName": doc.get("assignedName"),
                "createdByName": doc.get("createdByName"),
                "startDateTime": doc.get("startDateTime"),
                "endDateTime": doc.get("endDateTime"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "meeting")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("meeting", mongo_id, doc.get("title", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("title", f"Meeting {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "meeting"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/meeting/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid meetings to index.")
            return {"status": "warning", "message": "No valid meetings found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} meeting chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during meeting indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_notes_to_qdrant():
    """Index Notes collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = notes_collection.find({}, {
            "_id": 1, "subject": 1, "description": 1, "leadId": 1, "leadName": 1,
            "taskId": 1, "createdById": 1, "createdByName": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("subject"):
                text_parts.append(doc["subject"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("leadName"):
                text_parts.append(f"Lead: {doc['leadName']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "leadName": doc.get("leadName"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "notes")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("notes", mongo_id, doc.get("subject", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("subject", f"Note {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "notes"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/notes/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid notes to index.")
            return {"status": "warning", "message": "No valid notes found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} notes chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during notes indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_callLogs_to_qdrant():
    """Index CallLog collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = callLog_collection.find({}, {
            "_id": 1, "title": 1, "description": 1, "callPurpose": 1, "callStatus": 1,
            "callType": 1, "leadId": 1, "leadName": 1, "startDateTime": 1, "callDuration": 1,
            "otherReason": 1, "createdById": 1, "createdByName": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
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
                continue
            
            # Extract metadata
            metadata = {
                "callStatus": doc.get("callStatus"),
                "callType": doc.get("callType"),
                "callPurpose": doc.get("callPurpose"),
                "leadName": doc.get("leadName"),
                "createdByName": doc.get("createdByName"),
                "startDateTime": doc.get("startDateTime"),
                "callDuration": doc.get("callDuration"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "callLog")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("callLog", mongo_id, doc.get("title", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("title", f"Call Log {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "callLog"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/callLog/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid call logs to index.")
            return {"status": "warning", "message": "No valid call logs found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} call log chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during call log indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_mailInfos_to_qdrant():
    """Index MailInfo collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = mailInfo_collection.find({}, {
            "_id": 1, "subject": 1, "body": 1, "mailType": 1, "leadId": 1,
            "toMails": 1, "toCcMails": 1, "toBccMails": 1, "attachments": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1,
            "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
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
                continue
            
            # Extract metadata
            metadata = {
                "mailType": doc.get("mailType"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "mailInfo")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("mailInfo", mongo_id, doc.get("subject", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("subject", f"Mail {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "mailInfo"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/mailInfo/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid mail infos to index.")
            return {"status": "warning", "message": "No valid mail infos found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} mail info chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during mail info indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_leadScoreRules_to_qdrant():
    """Index LeadScoreRule collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = leadScoreRule_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "score": 1, "change": 1,
            "isActive": 1, "field": 1, "operator": 1, "value": 1,
            "business": 1, "createdAt": 1, "updatedAt": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
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
                continue
            
            # Extract metadata
            metadata = {
                "score": doc.get("score"),
                "change": doc.get("change"),
                "isActive": doc.get("isActive"),
                "field": doc.get("field"),
                "operator": doc.get("operator"),
                "value": doc.get("value"),
                "createdAt": doc.get("createdAt"),
                "updatedAt": doc.get("updatedAt"),
            }
            
            if doc.get("business") and isinstance(doc["business"], dict):
                if doc["business"].get("_id"):
                    try:
                        metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
                    except Exception:
                        pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "leadScoreRule")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("leadScoreRule", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Lead Score Rule {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "leadScoreRule"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/leadScoreRule/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid lead score rules to index.")
            return {"status": "warning", "message": "No valid lead score rules found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} lead score rule chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during lead score rule indexing: {e}")
        return {"status": "error", "message": str(e)}

def index_segmentations_to_qdrant():
    """Index Segmentation collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = segmentation_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "conditions": 1, "tags": 1,
            "isActive": 1, "business": 1, "createdAt": 1, "updatedAt": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("name"):
                text_parts.append(doc["name"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("conditions"):
                if isinstance(doc["conditions"], dict):
                    # Serialize conditions dict
                    conditions_text = json.dumps(doc["conditions"], indent=2)
                    text_parts.append(f"Conditions: {conditions_text}")
                elif isinstance(doc["conditions"], str):
                    text_parts.append(f"Conditions: {doc['conditions']}")
            if doc.get("tags") and isinstance(doc["tags"], list):
                text_parts.append(f"Tags: {', '.join(doc['tags'])}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "isActive": doc.get("isActive"),
                "createdAt": doc.get("createdAt"),
                "updatedAt": doc.get("updatedAt"),
            }
            
            if doc.get("tags") and isinstance(doc["tags"], list):
                metadata["tags"] = doc["tags"]
            
            if doc.get("business") and isinstance(doc["business"], dict):
                if doc["business"].get("_id"):
                    try:
                        metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
                    except Exception:
                        pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "segmentation")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("segmentation", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise ("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Segmentation {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "segmentation"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/segmentation/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid segmentations to index.")
            return {"status": "warning", "message": "No valid segmentations found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} segmentation chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during segmentation indexing: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    index_leads_to_qdrant()
    index_tasks_to_qdrant()
    index_activities_to_qdrant()
    index_meetings_to_qdrant()
    index_notes_to_qdrant()
    index_callLogs_to_qdrant()
    index_mailInfos_to_qdrant()
    index_leadScoreRules_to_qdrant()
    index_segmentations_to_qdrant()
    
