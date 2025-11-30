from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
from contextlib import asynccontextmanager
import uvicorn
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Configure logging - set to INFO to see RAG diagnostic messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from agent.agent import AgentExecutor
import os
from websocket_handler import handle_chat_websocket, ws_manager, user_id_global, business_id_global
from qdrant.initializer import RAGTool
from lead_support_agent.agent import LeadSupportAgent
from lead_support_agent.websocket_handler import handle_lead_support_websocket
from mongo.conversations import ensure_conversation_client_connected
from mongo.conversations import conversation_mongo_client, CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME, TEMPLATES_COLLECTION_NAME
from mongo.conversations import update_message_reaction
from mongo.constants import mongodb_tools, DATABASE_NAME

# Pydantic models for API requests/responses
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    timestamp: str

class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None

class Message(BaseModel):
    id: str
    type: str  # "user", "assistant", "tool", "thought"
    content: str
    timestamp: str
    tool_name: Optional[str] = None
    tool_output: Optional[Any] = None


class ReactionRequest(BaseModel):
    conversation_id: str
    message_id: str
    liked: Optional[bool] = None
    feedback: Optional[str] = None

class LeadCreateRequest(BaseModel):
    name: str
    email: Optional[str] = None
    mobile: Optional[str] = None
    leadStatus: Optional[str] = "New"
    referenceNo: Optional[str] = None
    created_by: Optional[str] = None

class LeadCreateResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    mobile: Optional[str] = None
    leadStatus: str
    referenceNo: Optional[str] = None

class TaskCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    priority: Optional[str] = "MEDIUM"
    taskStatus: Optional[str] = "NEW"
    dueDate: Optional[str] = None
    leadId: Optional[str] = None
    assignedTo: Optional[str] = None
    created_by: Optional[str] = None

class TaskCreateResponse(BaseModel):
    id: str
    name: str
    description: str
    priority: str
    taskStatus: str
    leadId: Optional[str] = None

class MeetingCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    meetingStatus: Optional[str] = "SCHEDULED"
    meetingType: Optional[str] = "VIRTUAL"
    leadId: Optional[str] = None
    meetingLink: Optional[str] = None
    participantsList: Optional[List[str]] = None
    created_by: Optional[str] = None

class MeetingCreateResponse(BaseModel):
    id: str
    title: str
    description: str
    meetingStatus: str
    leadId: Optional[str] = None

class NoteCreateRequest(BaseModel):
    subject: str
    description: str
    leadId: Optional[str] = None
    created_by: Optional[str] = None

class NoteCreateResponse(BaseModel):
    id: str
    subject: str
    description: str
    leadId: Optional[str] = None


# Global agent instances
mongodb_agent = None
lead_support_agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifespan of the FastAPI application"""
    global mongodb_agent, lead_support_agent

    # Startup
    mongodb_agent = AgentExecutor()
    await mongodb_agent.connect()
    await RAGTool.initialize()
    
    # Initialize Lead Support Agent
    lead_support_agent = LeadSupportAgent()
    await lead_support_agent.connect()
    logger.info("Lead Support Agent initialized")
    
    # Ensure conversation DB connection pool is ready
    try:
        await ensure_conversation_client_connected()
    except Exception as e:
        logger.error(f"Conversations DB not connected: {e}")
    yield

    # Shutdown
    await mongodb_agent.disconnect()
    await lead_support_agent.disconnect()

    # Close Redis conversation memory
    from agent.memory import conversation_memory
    await conversation_memory.close()

# Create FastAPI app
app = FastAPI(
    title="CRM Assistant API",
    description="CRM System Assistant with MongoDB integration and WebSocket support",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI at /docs
    redoc_url="/redoc",  # ReDoc at /redoc
    openapi_url="/openapi.json",  # OpenAPI schema at /openapi.json
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Vite dev server
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "CRM Assistant API", "status": "running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/conversations")
async def list_conversations(user_id: Optional[str] = None, business_id: Optional[str] = None):
    """List conversation ids and titles from Mongo.
    
    Query parameters:
    - user_id: Optional member/user ID to filter conversations
    - business_id: Optional business ID to filter conversations
    """
    try:
        from bson.binary import Binary
        from mongo.constants import mongo_binary_to_uuid_str, uuid_str_to_mongo_binary
        
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME)
        
        # Build query filter
        query_filter = {}
        
        # Convert string UUIDs to Binary format for filtering
        if user_id:
            try:
                member_binary = uuid_str_to_mongo_binary(user_id)
                query_filter["memberId"] = member_binary
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid user_id UUID format: {e}")
        
        if business_id:
            try:
                business_binary = uuid_str_to_mongo_binary(business_id)
                query_filter["businessId"] = business_binary
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid business_id UUID format: {e}")
        
        cursor = coll.find(query_filter, {
            "conversationId": 1, 
            "messages": {"$slice": -1}, 
            "updatedAt": 1,
            "memberId": 1,
            "businessId": 1
        }).sort("updatedAt", -1).limit(100)
        
        results = []
        async for doc in cursor:
            conv_id = doc.get("conversationId")
            last = (doc.get("messages") or [{}])[-1] if doc.get("messages") else None
            title = None
            if last and isinstance(last, dict):
                content = str(last.get("content") or "").strip()
                if content:
                    title = content[:60]
            
            # Convert Binary IDs to UUID strings
            member_id = None
            business_id_str = None
            
            member_binary = doc.get("memberId")
            if isinstance(member_binary, Binary):
                try:
                    member_id = mongo_binary_to_uuid_str(member_binary)
                except Exception:
                    pass
            
            business_binary = doc.get("businessId")
            if isinstance(business_binary, Binary):
                try:
                    business_id_str = mongo_binary_to_uuid_str(business_binary)
                except Exception:
                    pass
            
            results.append({
                "id": conv_id,
                "title": title or f"Conversation {conv_id}",
                "updatedAt": doc.get("updatedAt"),
                "memberId": member_id,
                "businessId": business_id_str,
            })
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get a conversation's messages and cache it in Redis for fast access."""
    try:
        # Pre-warm cache when user opens conversation
        from agent.memory import conversation_memory
        asyncio.create_task(
            conversation_memory.pre_warm_conversation(conversation_id)
        )
        
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME)
        doc = await coll.find_one({"conversationId": conversation_id})
        if not doc:
            return {"id": conversation_id, "messages": []}
        messages = doc.get("messages") or []
        # Normalize
        norm = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            entry = {
                "id": m.get("id") or "",
                "type": m.get("type") or "assistant",
                "content": m.get("content") or "",
                "timestamp": m.get("timestamp") or "",
                "liked": m.get("liked"),
                "feedback": m.get("feedback"),
            }
            # Pass through structured generated artifacts when present
            if m.get("type") == "lead" and isinstance(m.get("lead"), dict):
                entry["lead"] = m.get("lead")
            if m.get("type") == "task" and isinstance(m.get("task"), dict):
                entry["task"] = m.get("task")
            if m.get("type") == "meeting" and isinstance(m.get("meeting"), dict):
                entry["meeting"] = m.get("meeting")
            if m.get("type") == "note" and isinstance(m.get("note"), dict):
                entry["note"] = m.get("note")
            norm.append(entry)
        return {"id": conversation_id, "messages": norm}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/conversations/{user_id}/{business_id}")
async def get_conversations_by_ids(user_id: str, business_id: str):
    """Get all conversations' messages for a given member_id and business_id."""
    try:
        from mongo.constants import uuid_str_to_mongo_binary
        
        coll = await conversation_mongo_client.get_collection(
            CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME
        )

        # Convert string UUIDs to Binary format for MongoDB query
        try:
            member_binary = uuid_str_to_mongo_binary(user_id)
            business_binary = uuid_str_to_mongo_binary(business_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {e}")

        # Find all matching conversations using Binary IDs
        cursor = coll.find({"memberId": member_binary, "businessId": business_binary})
        docs = await cursor.to_list(length=None)

        if not docs:
            return {"id": user_id, "businessId": business_id, "conversations": []}

        all_conversations = []

        for doc in docs:
            messages = doc.get("messages") or []
            norm = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                entry = {
                    "id": m.get("id") or "",
                    "type": m.get("type") or "assistant",
                    "content": m.get("content") or "",
                    "timestamp": m.get("timestamp") or "",
                    "liked": m.get("liked"),
                    "feedback": m.get("feedback"),
                }
                # Pass through structured generated artifacts when present
                if m.get("type") == "lead" and isinstance(m.get("lead"), dict):
                    entry["lead"] = m.get("lead")
                if m.get("type") == "task" and isinstance(m.get("task"), dict):
                    entry["task"] = m.get("task")
                if m.get("type") == "meeting" and isinstance(m.get("meeting"), dict):
                    entry["meeting"] = m.get("meeting")
                if m.get("type") == "note" and isinstance(m.get("note"), dict):
                    entry["note"] = m.get("note")
                norm.append(entry)

            all_conversations.append({
                "conversationId": doc.get("conversationId"),
                "messages": norm,
            })

        return {
            "id": user_id,
            "businessId": business_id,
            "conversations": all_conversations,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/leads", response_model=LeadCreateResponse)
async def create_lead(req: LeadCreateRequest):
    """Create a minimal lead in MongoDB 'Lead' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["Lead"]

        from datetime import datetime
        from mongo.constants import uuid_str_to_mongo_binary
        
        now_iso = datetime.utcnow().isoformat()

        doc = {
            "personalInfo": {
                "name": (req.name or "").strip(),
            },
            "leadStatus": req.leadStatus or "New",
            "createdTimeStamp": now_iso,
            "updatedTimeStamp": now_iso,
        }
        
        if req.email:
            doc["personalInfo"]["email"] = req.email
        if req.mobile:
            doc["personalInfo"]["mobile"] = req.mobile
        if req.referenceNo:
            doc["referenceNo"] = req.referenceNo
        if req.created_by:
            try:
                doc["createdById"] = uuid_str_to_mongo_binary(req.created_by)
                doc["createdByName"] = req.created_by
            except Exception:
                pass

        result = await coll.insert_one(doc)

        return LeadCreateResponse(
            id=str(result.inserted_id),
            name=doc["personalInfo"]["name"],
            email=doc["personalInfo"].get("email"),
            mobile=doc["personalInfo"].get("mobile"),
            leadStatus=doc["leadStatus"],
            referenceNo=doc.get("referenceNo"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks", response_model=TaskCreateResponse)
async def create_task(req: TaskCreateRequest):
    """Create a minimal task in MongoDB 'Task' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["task"]

        from datetime import datetime
        from mongo.constants import uuid_str_to_mongo_binary
        
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "name": (req.name or "").strip(),
            "description": (req.description or "").strip(),
            "priority": req.priority or "MEDIUM",
            "taskStatus": req.taskStatus or "NEW",
            "createdTimeStamp": now_iso,
            "updatedTimeStamp": now_iso,
        }
        
        if req.leadId:
            try:
                doc["parentId"] = uuid_str_to_mongo_binary(req.leadId)
            except Exception:
                pass
        if req.dueDate:
            doc["dueDate"] = req.dueDate
        if req.assignedTo:
            try:
                doc["assignedTo"] = uuid_str_to_mongo_binary(req.assignedTo)
            except Exception:
                pass
        if req.created_by:
            try:
                doc["createdById"] = uuid_str_to_mongo_binary(req.created_by)
                doc["createdByName"] = req.created_by
            except Exception:
                pass

        result = await coll.insert_one(doc)

        return TaskCreateResponse(
            id=str(result.inserted_id),
            name=doc["name"],
            description=doc["description"],
            priority=doc["priority"],
            taskStatus=doc["taskStatus"],
            leadId=req.leadId,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/meetings", response_model=MeetingCreateResponse)
async def create_meeting(req: MeetingCreateRequest):
    """Create a minimal meeting in MongoDB 'Meeting' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["meeting"]

        from datetime import datetime
        from mongo.constants import uuid_str_to_mongo_binary
        
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "title": (req.title or "").strip(),
            "description": (req.description or "").strip(),
            "meetingStatus": req.meetingStatus or "SCHEDULED",
            "meetingType": req.meetingType or "VIRTUAL",
            "createdTimeStamp": now_iso,
            "updatedTimeStamp": now_iso,
        }
        
        if req.leadId:
            try:
                doc["leadId"] = uuid_str_to_mongo_binary(req.leadId)
            except Exception:
                pass
        if req.meetingLink:
            doc["meetingLink"] = req.meetingLink
        if req.participantsList:
            doc["participantsList"] = req.participantsList
        if req.created_by:
            try:
                doc["createdById"] = uuid_str_to_mongo_binary(req.created_by)
                doc["createdByName"] = req.created_by
            except Exception:
                pass

        result = await coll.insert_one(doc)

        return MeetingCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            description=doc["description"],
            meetingStatus=doc["meetingStatus"],
            leadId=req.leadId,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notes", response_model=NoteCreateResponse)
async def create_note(req: NoteCreateRequest):
    """Create a minimal note in MongoDB 'Notes' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["notes"]

        from datetime import datetime
        from mongo.constants import uuid_str_to_mongo_binary
        
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "subject": (req.subject or "").strip(),
            "description": (req.description or "").strip(),
            "createdTimeStamp": now_iso,
        }
        
        if req.leadId:
            try:
                doc["leadId"] = uuid_str_to_mongo_binary(req.leadId)
            except Exception:
                pass
        if req.created_by:
            try:
                doc["createdById"] = uuid_str_to_mongo_binary(req.created_by)
                doc["createdByName"] = req.created_by
            except Exception:
                pass

        result = await coll.insert_one(doc)

        return NoteCreateResponse(
            id=str(result.inserted_id),
            subject=doc["subject"],
            description=doc["description"],
            leadId=req.leadId,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/conversations/reaction")
async def set_reaction(req: ReactionRequest):
    """Set like/dislike and optional feedback on an assistant message."""
    try:
        ok = await update_message_reaction(
            conversation_id=req.conversation_id,
            message_id=req.message_id,
            liked=req.liked,
            feedback=req.feedback,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Message not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming chat with MongoDB Agent."""
    global mongodb_agent

    # Initialize agent if not already done (for testing/development)
    if not mongodb_agent:
        mongodb_agent = AgentExecutor()
        await mongodb_agent.connect()

    await handle_chat_websocket(websocket, mongodb_agent)


@app.websocket("/ws/lead-support")
async def websocket_lead_support(websocket: WebSocket):
    """WebSocket endpoint for Lead Support Agent.
    
    This is a focused helper agent specifically for lead-related support tasks:
    - Lead summarization
    - Next best steps recommendations
    - Lead comparison
    - Message drafting
    - Objection handling
    - Meeting prep
    - Email composition
    
    Message types:
    - handshake: Initialize session with member_id and business_id
    - ping: Keep-alive
    - summarize: Summarize a specific lead (requires lead_id)
    - next_steps: Get next best steps for a lead (requires lead_id)
    - compare: Compare multiple leads (requires lead_ids array)
    - draft_message: Draft a message (requires lead_id, optional message_type, context)
    - objection: Handle an objection (requires lead_id, objection text)
    - meeting_prep: Prepare for meeting (requires lead_id, optional meeting_context)
    - email: Compose email (requires lead_id, optional context)
    - query: General lead support query (optional lead_id, task_type)
    """
    global lead_support_agent

    # Initialize agent if not already done (for testing/development)
    if not lead_support_agent:
        lead_support_agent = LeadSupportAgent()
        await lead_support_agent.connect()

    await handle_lead_support_websocket(websocket, lead_support_agent)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        forwarded_allow_ips="*"
    )

