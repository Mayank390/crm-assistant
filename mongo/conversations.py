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
    os.getenv("MONGODB_URI", "mongodb://BeeOSAdmin:Proficornlabs%401118@172.214.123.233:27017/?authSource=admin"),
)
conversation_mongo_client = ConversationMongoClient(CONVERSATIONS_CONNECTION_STRING)


CONVERSATIONS_DB_NAME = os.getenv("CONVERSATIONS_DB_NAME", "ProspectIQ")
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


async def append_message(conversation_id: str, message: Dict[str, Any], lead_id: Optional[str] = None) -> None:
    coll = await _get_collection()
    safe_message = _ensure_message_shape(message)

    # ✅ NEW: Resolve business and member IDs from websocket context
    ctx_ids = _resolve_business_and_member_ids()

    set_on_insert: Dict[str, Any] = {
        "conversationId": conversation_id,
        "createdAt": _now_iso(),
    }
    
    # Add businessId and memberId to setOnInsert so they're set when conversation is first created
    if ctx_ids.get("businessId"):
        set_on_insert["businessId"] = ctx_ids["businessId"]
    if ctx_ids.get("memberId"):
        set_on_insert["memberId"] = ctx_ids["memberId"]

    set_fields: Dict[str, Any] = {"updatedAt": _now_iso()}
    
    # ✅ NEW: Add lead_id support for CRM
    if lead_id:
        try:
            from .constants import uuid_str_to_mongo_binary
            lead_bin = uuid_str_to_mongo_binary(lead_id)
            set_fields["lead_id"] = lead_bin
        except Exception as e:
            logger.warning(f"Failed to convert lead_id to MongoDB Binary: {e}")
            set_fields["lead_id"] = lead_id

    await coll.update_one(
        {"conversationId": conversation_id},
        {
            "$setOnInsert": set_on_insert,
            "$push": {"messages": safe_message},
            "$set": set_fields,
        },
        upsert=True,
    )


async def save_user_message(conversation_id: str, content: str, lead_id: Optional[str] = None) -> None:
    await append_message(
        conversation_id,
        {
            "type": "user",
            "content": content or "",
        },
        lead_id=lead_id,
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


async def save_generated_lead(conversation_id: str, lead: Dict[str, Any]) -> None:
    """Persist a generated lead as a conversation message."""
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "lead",
            "content": "",
            "lead": {
                "referenceNo": lead.get("referenceNo") or "",
                "name": lead.get("name") or "",
                "email": lead.get("email") or "",
                "mobile": lead.get("mobile") or "",
                "leadStatus": lead.get("leadStatus") or "New",
            },
        })
    )


async def save_generated_task(conversation_id: str, task: Dict[str, Any]) -> None:
    """Persist a generated task as a conversation message."""
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "task",
            "content": "",
            "task": {
                "name": task.get("name") or "",
                "description": task.get("description") or "",
                "priority": task.get("priority") or "MEDIUM",
                "taskStatus": task.get("taskStatus") or "NEW",
                "dueDate": task.get("dueDate"),
            },
        })
    )


async def save_generated_meeting(conversation_id: str, meeting: Dict[str, Any]) -> None:
    """Persist a generated meeting as a conversation message."""
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "meeting",
            "content": "",
            "meeting": {
                "title": meeting.get("title") or "",
                "description": meeting.get("description") or "",
                "meetingStatus": meeting.get("meetingStatus") or "SCHEDULED",
                "meetingType": meeting.get("meetingType") or "VIRTUAL",
            },
        })
    )


async def save_generated_note(conversation_id: str, note: Dict[str, Any]) -> None:
    """Persist a generated note as a conversation message."""
    await append_message(
        conversation_id,
        _ensure_message_shape({
            "type": "note",
            "content": "",
            "note": {
                "subject": note.get("subject") or "",
                "description": note.get("description") or "",
            },
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

