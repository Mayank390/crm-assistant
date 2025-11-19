from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
from contextlib import asynccontextmanager
import uvicorn
from dotenv import load_dotenv
import logging
from generate.router import router as generate_router

# Load environment variables from .env file
load_dotenv()

# Configure logging - set to INFO to see RAG diagnostic messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from agent.agent import AgentExecutor
import os
from websocket_handler import handle_chat_websocket, ws_manager,user_id_global,business_id_global
from qdrant.initializer import RAGTool
from mongo.conversations import ensure_conversation_client_connected
from mongo.conversations import conversation_mongo_client, CONVERSATIONS_DB_NAME, CONVERSATIONS_COLLECTION_NAME ,TEMPLATES_COLLECTION_NAME
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

class WorkItemCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    project_identifier: Optional[str] = None
    project_id: Optional[str] = None
    created_by: Optional[str] = None

class WorkItemCreateResponse(BaseModel):
    id: str
    title: str
    description: str
    projectIdentifier: Optional[str] = None
    sequenceId: Optional[int] = None
    link: Optional[str] = None

class PageCreateRequest(BaseModel):
    title: str
    content: Dict[str, Any]
    project_id: Optional[str] = None
    created_by: Optional[str] = None

class PageCreateResponse(BaseModel):
    id: str
    title: str
    content: str  # stringified Editor.js JSON
    link: Optional[str] = None

class CycleCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    project_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    created_by: Optional[str] = None

class CycleCreateResponse(BaseModel):
    id: str
    title: str
    description: str
    projectId: Optional[str] = None
    link: Optional[str] = None

class ModuleCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    project_id: Optional[str] = None
    lead: Optional[str] = None
    members: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    created_by: Optional[str] = None

class ModuleCreateResponse(BaseModel):
    id: str
    title: str
    description: str
    projectId: Optional[str] = None
    link: Optional[str] = None


class EpicCreateRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    project_id: Optional[str] = None
    priority: Optional[str] = None
    state_name: Optional[str] = None
    assignee: Optional[str] = None
    labels: Optional[List[str]] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    created_by: Optional[str] = None


class EpicCreateResponse(BaseModel):
    id: str
    title: str
    description: str
    projectId: Optional[str] = None
    state: Optional[str] = None
    priority: Optional[str] = None
    link: Optional[str] = None



# Global agent instances
mongodb_agent = None
smart_filter_agent = None
template_generator = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifespan of the FastAPI application"""
    global mongodb_agent, smart_filter_agent , template_generator

    # Startup
    mongodb_agent = AgentExecutor()
    await mongodb_agent.connect()
    await RAGTool.initialize()

    # Initialize Smart Filter Tools (singleton)
    from smart_filter import tools as smart_filter_tools_module
    await smart_filter_tools_module.SmartFilterTools.initialize()

    # Initialize Smart Filter Agent after RAGTool
    from smart_filter.agent import SmartFilterAgent
    smart_filter_agent = SmartFilterAgent()
    set_smart_filter_agent_instance(smart_filter_agent)

    from template_generator.generator import TemplateGenerator
    template_generator = TemplateGenerator()
    set_template_generator_instance(template_generator)
    # Ensure conversation DB connection pool is ready
    try:
        await ensure_conversation_client_connected()
    except Exception as e:
        logger.error(f"Conversations DB not connected: {e}")
    yield

    # Shutdown
    await mongodb_agent.disconnect()

    # Close Redis conversation memory
    from agent.memory import conversation_memory
    await conversation_memory.close()

# Create FastAPI app
app = FastAPI(
    title="PMS Assistant API",
    description="Project Management System Assistant with MongoDB integration and WebSocket support",
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

# Include generation-related API routes
app.include_router(generate_router)

# Include template generator API routes
from template_generator.router import router as template_router, set_template_generator as set_template_generator_instance
app.include_router(template_router)

# Include smart filter API routes
from smart_filter.router import router as smart_filter_router, set_smart_filter_agent as set_smart_filter_agent_instance
app.include_router(smart_filter_router)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "PMS Assistant API", "status": "running"}

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
        # ✅ NEW: Pre-warm cache when user opens conversation
        from agent.memory import conversation_memory
        asyncio.create_task(
            conversation_memory.pre_warm_conversation(conversation_id)
        )

        # Note: Cache is populated automatically when conversation is used
        # No need to pre-load - it happens on-demand during get_recent_context()
        
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
            if m.get("type") == "work_item" and isinstance(m.get("workItem"), dict):
                entry["workItem"] = m.get("workItem")
            if m.get("type") == "page" and isinstance(m.get("page"), dict):
                entry["page"] = m.get("page")
            if m.get("type") == "cycle" and isinstance(m.get("cycle"), dict):
                entry["cycle"] = m.get("cycle")
            if m.get("type") == "module" and isinstance(m.get("module"), dict):
                entry["module"] = m.get("module")
            if m.get("type") == "epic" and isinstance(m.get("epic"), dict):
                entry["epic"] = m.get("epic")
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
                if m.get("type") == "work_item" and isinstance(m.get("workItem"), dict):
                    entry["workItem"] = m.get("workItem")
                if m.get("type") == "page" and isinstance(m.get("page"), dict):
                    entry["page"] = m.get("page")
                if m.get("type") == "cycle" and isinstance(m.get("cycle"), dict):
                    entry["cycle"] = m.get("cycle")
                if m.get("type") == "module" and isinstance(m.get("module"), dict):
                    entry["module"] = m.get("module")
                if m.get("type") == "epic" and isinstance(m.get("epic"), dict):
                    entry["epic"] = m.get("epic")
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



@app.post("/work-items", response_model=WorkItemCreateResponse)
async def create_work_item(req: WorkItemCreateRequest):
    """Create a minimal work item in MongoDB 'workItem' collection.

    Fields stored: title, description, project (identifier), sequenceId, createdAt/updatedAt.
    """
    try:
        if not mongodb_tools.client:
            # Ensure Mongo connected via direct client
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["workItem"]

        # Derive next sequence per project identifier (best-effort)
        seq: Optional[int] = None
        filt = {"project.identifier": req.project_identifier} if req.project_identifier else {}
        try:
            cursor = coll.find(filt, {"sequenceId": 1}).sort("sequenceId", -1).limit(1)
            top = await cursor.to_list(length=1)
            if top and isinstance(top[0], dict):
                seq_val = top[0].get("sequenceId")
                if isinstance(seq_val, int):
                    seq = seq_val + 1
            if seq is None:
                seq = 1
        except Exception:
            seq = None

        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()

        doc = {
            "title": (req.title or "").strip(),
            "description": (req.description or "").strip(),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        if req.project_identifier:
            doc["project"] = {"identifier": req.project_identifier}
        if seq is not None:
            doc["sequenceId"] = seq
        if req.created_by:
            doc["createdBy"] = {"name": req.created_by}

        result = await coll.insert_one(doc)

        return WorkItemCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            description=doc["description"],
            projectIdentifier=req.project_identifier,
            sequenceId=seq,
            link=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pages", response_model=PageCreateResponse)
async def create_page(req: PageCreateRequest):
    """Create a minimal page in MongoDB 'page' collection with Editor.js content."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["page"]

        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()

        import json as _json
        content_str = _json.dumps(req.content or {"blocks": []})

        doc: Dict[str, Any] = {
            "title": (req.title or "").strip() or "Untitled Page",
            "content": content_str,
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        if req.project_id:
            doc["project"] = {"id": req.project_id}
        if req.created_by:
            doc["createdBy"] = {"name": req.created_by}

        result = await coll.insert_one(doc)

        return PageCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            content=doc["content"],
            link=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cycles", response_model=CycleCreateResponse)
async def create_cycle(req: CycleCreateRequest):
    """Create a minimal cycle (sprint) in MongoDB 'cycle' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["cycle"]

        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "title": (req.title or "").strip() or "Untitled Cycle",
            "description": (req.description or "").strip(),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        if req.project_id:
            doc["project"] = {"id": req.project_id}
        if req.start_date:
            doc["startDate"] = req.start_date
        if req.end_date:
            doc["endDate"] = req.end_date
        if req.created_by:
            doc["createdBy"] = {"name": req.created_by}

        result = await coll.insert_one(doc)

        return CycleCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            description=doc["description"],
            projectId=req.project_id,
            link=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/modules", response_model=ModuleCreateResponse)
async def create_module(req: ModuleCreateRequest):
    """Create a minimal module in MongoDB 'module' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["module"]

        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "title": (req.title or "").strip() or "Untitled Module",
            "description": (req.description or "").strip(),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        if req.project_id:
            doc["project"] = {"id": req.project_id}
        if req.lead:
            doc["lead"] = {"name": req.lead}
        if req.members:
            doc["members"] = [{"name": m} for m in req.members]
        if req.start_date:
            doc["startDate"] = req.start_date
        if req.end_date:
            doc["endDate"] = req.end_date
        if req.created_by:
            doc["createdBy"] = {"name": req.created_by}

        result = await coll.insert_one(doc)

        return ModuleCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            description=doc["description"],
            projectId=req.project_id,
            link=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/epics", response_model=EpicCreateResponse)
async def create_epic(req: EpicCreateRequest):
    """Create a minimal epic in MongoDB 'epic' collection."""
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        coll = db["epic"]

        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()

        doc: Dict[str, Any] = {
            "title": (req.title or "").strip() or "Untitled Epic",
            "description": (req.description or "").strip(),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        if req.project_id:
            doc["project"] = {"id": req.project_id}
        if req.priority:
            doc["priority"] = req.priority
        if req.state_name:
            doc["state"] = {"name": req.state_name}
        if req.assignee:
            doc["assignee"] = {"name": req.assignee}
        if req.labels:
            cleaned_labels = [label.strip() for label in req.labels if isinstance(label, str) and label.strip()]
            if cleaned_labels:
                doc["label"] = [{"name": label} for label in cleaned_labels]
        if req.start_date:
            doc["startDate"] = req.start_date
        if req.due_date:
            doc["dueDate"] = req.due_date
        if req.created_by:
            doc["createdBy"] = {"name": req.created_by}

        result = await coll.insert_one(doc)

        return EpicCreateResponse(
            id=str(result.inserted_id),
            title=doc["title"],
            description=doc["description"],
            projectId=req.project_id,
            state=req.state_name,
            priority=req.priority,
            link=None,
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


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        forwarded_allow_ips="*"
        )
