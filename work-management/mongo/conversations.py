from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import asyncio
import contextlib
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from dotenv import load_dotenv

try:
    from openinference.semconv.trace import SpanAttributes as OI
except Exception:
    class _OI:
        TOOL_INPUT = "tool.input"
        TOOL_OUTPUT = "tool.output"
        ERROR_TYPE = "error.type"
        ERROR_MESSAGE = "error.message"
    OI = _OI()


# Ensure environment variables are loaded when running locally
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


class ConversationMongoClient:
    """Dedicated MongoDB client for conversations using separate connection string"""

    def __init__(self, connection_string: str):
        self.client = None
        self.connected = False
        self._connect_lock = asyncio.Lock()
        self.connection_string = connection_string

    async def connect(self):
        """Initialize MongoDB connection for conversations"""
        span_cm = contextlib.nullcontext()
        with span_cm as span:
            try:
                async with self._connect_lock:
                    if self.connected and self.client:
                        return

                    # ✅ OPTIMIZED: Create Motor client with enhanced connection pool settings
                    self.client = AsyncIOMotorClient(
                        self.connection_string,
                        maxPoolSize=50,          # Increased pool size for better concurrency
                        minPoolSize=10,          # Keep more minimum connections alive
                        maxIdleTimeMS=60000,     # Keep idle connections for 60s (increased)
                        waitQueueTimeoutMS=5000, # Faster timeout for queue
                        serverSelectionTimeoutMS=5000,  # Faster server selection
                        connectTimeoutMS=10000,  # Connection timeout
                        socketTimeoutMS=20000,   # Socket timeout
                        retryWrites=True,        # Enable retry writes for better reliability
                        retryReads=True,         # Enable retry reads
                    )

                    # Test connection
                    await self.client.admin.command('ping')

                    self.connected = True

            except Exception as e:
                logger.error(f"Failed to connect to Conversations MongoDB: {e}")
                raise

    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
        self.connected = False
        self.client = None

    async def get_collection(self, db_name: str, collection_name: str):
        """Get a collection from the conversations database"""
        if not self.client:
            await self.connect()
        return self.client[db_name][collection_name]


# Initialize conversations client with the provided connection string
CONVERSATIONS_CONNECTION_STRING = os.getenv(
    "CONVERSATIONS_MONGODB_URI",
    os.getenv("MONGODB_URI", "mongodb://WebsiteBuilderAdmin:JfOCiOKMVgSIMPOBUILDERGkli8@13.90.63.91:27017,172.171.192.172:27017/ProjectManagement?authSource=admin&replicaSet=rs0"),
)
conversation_mongo_client = ConversationMongoClient(CONVERSATIONS_CONNECTION_STRING)


CONVERSATIONS_DB_NAME = os.getenv("CONVERSATIONS_DB_NAME", "ProjectManagement")
CONVERSATIONS_COLLECTION_NAME = os.getenv("CONVERSATIONS_COLLECTION_NAME", "conversations")
TEMPLATES_COLLECTION_NAME = os.getenv("TEMPLATES_COLLECTION_NAME", "Templates")


async def ensure_conversation_client_connected():
    """Ensure the conversation MongoDB client is connected"""
    if not conversation_mongo_client.connected:
        await conversation_mongo_client.connect()


async def cleanup_conversation_client():
    """Cleanup the conversation MongoDB client connection"""
    await conversation_mongo_client.disconnect()


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _ensure_message_shape(message: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(message)
    if "id" not in enriched:
        enriched["id"] = str(uuid.uuid4())
    if "timestamp" not in enriched:
        enriched["timestamp"] = _now_iso()
    return enriched


def _resolve_business_and_member_ids() -> Dict[str, Any]:
    """Resolve business and member identifiers from runtime websocket context or environment.

    Returns keys: 'businessId' and 'memberId' with Binary (MongoDB UUID) or string values.
    Converts UUID strings from websocket context to MongoDB Binary format for proper storage.
    """
    business_id: Any = None
    member_id: Any = None

    # Prefer runtime websocket context if available (set by websocket_handler)
    try:
        import websocket_handler as _ws_ctx  # dynamic import to avoid circular dependency at module import time
        from .constants import uuid_str_to_mongo_binary  # Fixed: use relative import
        ws_business = getattr(_ws_ctx, "business_id_global", None)
        ws_member = getattr(_ws_ctx, "user_id_global", None)
        if isinstance(ws_business, str) and ws_business.strip():
            try:
                business_id = uuid_str_to_mongo_binary(ws_business)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to convert business_id '{ws_business}' to MongoDB Binary: {e}")
                # Keep as string if conversion fails
                business_id = ws_business
        if isinstance(ws_member, str) and ws_member.strip():
            try:
                member_id = uuid_str_to_mongo_binary(ws_member)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to convert member_id '{ws_member}' to MongoDB Binary: {e}")
                # Keep as string if conversion fails
                member_id = ws_member
    except Exception as e:
        # Log the error for debugging
        logger.warning(f"Failed to resolve IDs from websocket context: {e}")
        # Best-effort: fall back to environment below
        pass

    # Fall back to environment variables when not present in runtime context
    if not business_id:
        env_business = os.getenv("BUSINESS_UUID") or os.getenv("BUSINESS_ID") or ""
        if env_business:
            try:
                from .constants import uuid_str_to_mongo_binary
                business_id = uuid_str_to_mongo_binary(env_business)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to convert env business_id to MongoDB Binary: {e}")
                business_id = env_business
    if not member_id:
        env_member = os.getenv("MEMBER_UUID") or os.getenv("STAFF_ID") or ""
        if env_member:
            try:
                from .constants import uuid_str_to_mongo_binary
                member_id = uuid_str_to_mongo_binary(env_member)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to convert env member_id to MongoDB Binary: {e}")
                member_id = env_member

    return {"businessId": business_id, "memberId": member_id}


async def _get_collection():
    return await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME)


async def append_message(conversation_id: str, message: Dict[str, Any], project_id: Optional[str] = None) -> None:
    coll = await _get_collection()
    safe_message = _ensure_message_shape(message)
    # Resolve business/member identifiers and persist them at the document level
    ctx_ids = _resolve_business_and_member_ids()

    set_on_insert: Dict[str, Any] = {
        "conversationId": conversation_id,
        "createdAt": _now_iso(),
    }

    set_fields: Dict[str, Any] = {"updatedAt": _now_iso()}
    # Also set/refresh IDs in case they were missing on existing docs
    if ctx_ids.get("businessId"):
        set_fields["businessId"] = ctx_ids["businessId"]
    if ctx_ids.get("memberId"):
        set_fields["memberId"] = ctx_ids["memberId"]
    
    # ✅ NEW: Add project_id support
    if project_id:
        try:
            from .constants import uuid_str_to_mongo_binary
            project_bin = uuid_str_to_mongo_binary(project_id)
            set_fields["project_id"] = project_bin
        except Exception as e:
            logger.warning(f"Failed to convert project_id to MongoDB Binary: {e}")
            set_fields["project_id"] = project_id

    await coll.update_one(
        {"conversationId": conversation_id},
        {
            "$setOnInsert": set_on_insert,
            "$push": {"messages": safe_message},
            "$set": set_fields,
        },
        upsert=True,
    )


async def save_user_message(conversation_id: str, content: str, project_id: Optional[str] = None) -> None:
    await append_message(
        conversation_id,
        {
            "type": "user",
            "content": content or "",
        },
        project_id=project_id,
    )


async def save_assistant_message(conversation_id: str, content: str) -> None:
    await append_message(
        conversation_id,
        {
            "type": "assistant",
            "content": content or "",
        },
    )


async def save_action_event(
    conversation_id: str,
    kind: str,
    text: str,
    *,
    step: Optional[int] = None,
    tool_name: Optional[str] = None,
) -> None:
    if kind != "action":
        return
    await append_message(
        conversation_id,
        {
            "type": "action",
            "content": text or "",
            "step": step,
            "toolName": tool_name,
        },
    )


async def save_generated_work_item(conversation_id: str, work_item: Dict[str, Any]) -> None:
    """Persist a generated work item as a conversation message.

    Expects a minimal payload: {title, description?, projectIdentifier?, sequenceId?, link?}
    """
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "work_item",
            "content": "",  # keep content empty; UI renders from structured field
            "workItem": {
                "title": (work_item.get("title") or "Work item"),
                "description": (work_item.get("description") or ""),
                **({"projectIdentifier": work_item.get("projectIdentifier")} if work_item.get("projectIdentifier") is not None else {}),
                **({"sequenceId": work_item.get("sequenceId")} if work_item.get("sequenceId") is not None else {}),
                **({"link": work_item.get("link")} if work_item.get("link") is not None else {}),
            },
        })
    )


async def save_generated_page(conversation_id: str, page: Dict[str, Any]) -> None:
    """Persist a generated page as a conversation message.

    Expects payload: {title, blocks: {blocks: [...]}}
    """
    blocks = page.get("blocks") if isinstance(page, dict) else None
    if not isinstance(blocks, dict) or not isinstance(blocks.get("blocks"), list):
        blocks = {"blocks": []}

    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "page",
            "content": "",
            "page": {
                "title": (page.get("title") if isinstance(page, dict) else None) or "Generated Page",
                "blocks": blocks,
            },
        })
    )


async def save_generated_cycle(conversation_id: str, cycle: Dict[str, Any]) -> None:
    """Persist a generated cycle (sprint) as a conversation message.

    Expects a minimal payload: {title, description?}
    """
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "cycle",
            "content": "",  # keep content empty; UI renders from structured field
            "cycle": {
                "title": (cycle.get("title") or "Cycle"),
                "description": (cycle.get("description") or ""),
            },
        })
    )


async def save_generated_module(conversation_id: str, module: Dict[str, Any]) -> None:
    """Persist a generated module as a conversation message.

    Expects a minimal payload: {title, description?}
    """
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "module",
            "content": "",  # keep content empty; UI renders from structured field
            "module": {
                "title": (module.get("title") or "Module"),
                "description": (module.get("description") or ""),
            },
        })
    )


async def save_generated_epic(conversation_id: str, epic: Dict[str, Any]) -> None:
    """Persist a generated epic as a conversation message.

    Expects a minimal payload: {title, description?, priority?, state?, assignee?, labels?}
    """
    epic_payload: Dict[str, Any] = {
        "title": (epic.get("title") or "Epic"),
        "description": (epic.get("description") or ""),
    }

    if isinstance(epic.get("priority"), str) and epic["priority"].strip():
        epic_payload["priority"] = epic["priority"].strip()
    state_val = epic.get("state") or epic.get("stateName")
    if isinstance(state_val, str) and state_val.strip():
        epic_payload["state"] = state_val.strip()
    assignee_val = epic.get("assignee") or epic.get("assigneeName")
    if isinstance(assignee_val, str) and assignee_val.strip():
        epic_payload["assignee"] = assignee_val.strip()
    if isinstance(epic.get("labels"), list) and epic["labels"]:
        label_names = []
        for label in epic["labels"]:
            if isinstance(label, str) and label.strip():
                label_names.append(label.strip())
            elif isinstance(label, dict):
                name = label.get("name")
                if isinstance(name, str) and name.strip():
                    label_names.append(name.strip())
        if label_names:
            epic_payload["labels"] = label_names
    if isinstance(epic.get("projectId"), str) and epic["projectId"].strip():
        epic_payload["projectId"] = epic["projectId"].strip()
    if isinstance(epic.get("startDate"), str) and epic["startDate"].strip():
        epic_payload["startDate"] = epic["startDate"].strip()
    if isinstance(epic.get("dueDate"), str) and epic["dueDate"].strip():
        epic_payload["dueDate"] = epic["dueDate"].strip()
    if isinstance(epic.get("link"), str) and epic["link"].strip():
        epic_payload["link"] = epic["link"].strip()

    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "epic",
            "content": "",
            "epic": epic_payload,
        })
    )


async def update_message_reaction(
    conversation_id: str,
    message_id: str,
    liked: Optional[bool] = None,
    feedback: Optional[str] = None,
) -> bool:
    """Update reaction fields for a specific message in a conversation.

    When `liked` is True/False we set `messages.$.liked` accordingly.
    When `liked` is None we UNSET the `messages.$.liked` field (clear reaction).
    Optionally updates `messages.$.feedback` when provided.
    Returns True if a document was modified, False otherwise.
    """
    coll = await _get_collection()

    update_doc: Dict[str, Any] = {}

    if liked is None:
        # Clear the reaction field
        update_doc["$unset"] = {"messages.$.liked": ""}
    else:
        update_doc["$set"] = {"messages.$.liked": liked}

    if feedback is not None:
        # Ensure $set exists if we also need to update feedback
        update_doc.setdefault("$set", {})["messages.$.feedback"] = feedback

    result = await coll.update_one(
        {"conversationId": conversation_id, "messages.id": message_id},
        update_doc,
    )
    return getattr(result, "modified_count", 0) > 0

