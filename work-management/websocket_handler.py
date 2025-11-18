
"""WebSocket handler for streaming chat responses"""
from fastapi import WebSocket, WebSocketDisconnect , status , WebSocketException
from typing import Dict, Any, AsyncGenerator
import json
import asyncio
from datetime import datetime
import uuid
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.callbacks import AsyncCallbackHandler
import time
import re
from dotenv import load_dotenv
import logging
from mongo.constants import DATABASE_NAME
from agent.planner import plan_and_execute_query
from mongo.conversations import save_user_message
import os
import contextlib
from time import perf_counter
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

class StreamingCallbackHandler(AsyncCallbackHandler):
    """Callback handler for streaming LLM responses"""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.start_time = None
        # Optional: allow showing raw tool outputs if explicitly enabled
        import os as _os
        self.stream_tool_outputs = _os.getenv("STREAM_TOOL_OUTPUTS", "false").lower() == "true"

    async def on_llm_start(self, *args, **kwargs):
        """Called when LLM starts generating"""
        self.start_time = time.time()
        await self.websocket.send_json({
            "type": "llm_start",
            "timestamp": datetime.now().isoformat()
        })

    async def on_llm_new_token(self, token: str, **kwargs):
        """Stream each token as it's generated"""
        await self.websocket.send_json({
            "type": "token",
            "content": token,
            "timestamp": datetime.now().isoformat()
        })

    async def on_llm_end(self, *args, **kwargs):
        """Called when LLM finishes generating"""
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        await self.websocket.send_json({
            "type": "llm_end",
            "elapsed_time": elapsed_time,
            "timestamp": datetime.now().isoformat()
        })

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """Called when a tool starts executing"""
        tool_name = serialized.get("name", "Unknown Tool")
        await self.websocket.send_json({
            "type": "tool_start",
            "tool_name": tool_name,
            "input": input_str,
            "timestamp": datetime.now().isoformat()
        })

    async def on_tool_end(self, output: str, **kwargs):
        """Called when a tool finishes executing"""
        # Suppress raw tool outputs unless explicitly enabled
        if self.stream_tool_outputs:
            payload = {
                "type": "tool_end",
                "output": output,
                "timestamp": datetime.now().isoformat()
            }
        else:
            payload = {
                "type": "tool_end",
                "output_preview": str(output)[:120],
                "hidden": True,
                "timestamp": datetime.now().isoformat()
            }
        await self.websocket.send_json(payload)

class WebSocketManager:
    """Manages WebSocket connections"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept and store a new WebSocket connection"""
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        """Remove a WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    def get_connection(self, user_id: str) -> WebSocket | None:
        """Get a WebSocket connection by user_id"""
        return self.active_connections.get(user_id)

    async def send_message(self, user_id: str, message: dict):
        """Send a message to a specific client"""
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        for user_id, connection in self.active_connections.items():
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")

# Global WebSocket manager instance
ws_manager = WebSocketManager()

user_id_global = None
business_id_global = None

async def handle_chat_websocket(websocket: WebSocket, mongodb_agent):
    """Handle WebSocket chat connections with streaming"""
    global user_id_global, business_id_global
    user_id = None
    try:
        await websocket.accept()

        # Initialize context variables
        user_context = {
            "user_id": None,
            "businessId": None,
            "preferences": None,  # Cached user preferences
        }

        # Set a timeout for handshake completion (30 seconds)
        import asyncio
        handshake_timeout = 30
        handshake_timer = None
        authenticated = False

        async def check_handshake_timeout():
            nonlocal authenticated
            await asyncio.sleep(handshake_timeout)
            if not authenticated:
                await websocket.send_json({
                    "type": "error",
                    "message": "Handshake timeout. Please send member_id and business_id within 30 seconds.",
                    "timestamp": datetime.now().isoformat()
                })
                # Close the connection on timeout
                await websocket.close()

        handshake_timer = asyncio.create_task(check_handshake_timeout())

        # === MAIN MESSAGE LOOP ===
        while True:
            # Send connected message only after handshake is received
            if authenticated and user_context["user_id"] and user_context["businessId"]:
                await websocket.send_json({
                    "type": "connected",
                    "user_id": user_context["user_id"],
                    "business_id": user_context["businessId"],
                    "timestamp": datetime.now().isoformat()
                })

            try:
                data_str = await websocket.receive_text()
            except Exception:
                # Connection closed
                break
            data = json.loads(data_str)

            if data.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                })
                continue

            # Handle project_data_loaded message
            if data.get("type") == "project_data_loaded":
                await websocket.send_json({
                    "type": "project_data_loaded",
                    "message": data.get("message", "Project data loaded"),
                    "timestamp": datetime.now().isoformat()
                })
                continue

            # Handle handshake message to set user context
            if data.get("type") == "handshake":
                user_context["user_id"] = data.get("member_id")
                user_context["businessId"] = data.get("business_id")

                # Cancel handshake timeout since we received the handshake
                if handshake_timer:
                    handshake_timer.cancel()

                # Set globals for access in other files
                user_id_global = user_context["user_id"]
                business_id_global = user_context["businessId"]

                # Connect with the actual user_id (no placeholder "connecting" needed)
                await ws_manager.connect(websocket, user_context["user_id"])

                # ✅ NEW: Load user preferences from MongoDB/KG
                if user_context["user_id"] and user_context["businessId"]:
                    try:
                        from mongo.user_preferences import user_preferences
                        prefs_data = await user_preferences.get_preferences(
                            user_context["user_id"],
                            user_context["businessId"]
                        )
                        user_context["preferences"] = prefs_data.get("preferences", {})
                        
                        # If preferences are sent in handshake, update them
                        if data.get("preferences"):
                            await user_preferences.update_preferences(
                                user_context["user_id"],
                                user_context["businessId"],
                                data.get("preferences")
                            )
                            user_context["preferences"] = data.get("preferences")
                            
                            # ✅ NEW: Queue preference update for Mem0 learning
                            try:
                                from agent.knowledge_graph.learning import queue_preference_to_mem0
                                queue_preference_to_mem0(
                                    user_id=user_context["user_id"],
                                    business_id=user_context["businessId"],
                                    preferences=data.get("preferences", {})
                                )
                            except Exception as e:
                                logger.debug(f"Failed to queue preference to Mem0: {e}")
                    except Exception as e:
                        logger.warning(f"Failed to load user preferences: {e}")
                        user_context["preferences"] = {}

                # Mark as authenticated now that handshake is complete
                authenticated = True

                # ✅ NEW: Pre-warm conversation when user connects
                from agent.memory import conversation_memory
                conversation_id = data.get("conversation_id")
                if conversation_id:
                    asyncio.create_task(
                        conversation_memory.pre_warm_conversation(conversation_id)
                    )

                await websocket.send_json({
                    "type": "handshake_ack",
                    "user_id": user_context["user_id"],
                    "business_id": user_context["businessId"],
                    "timestamp": datetime.now().isoformat()
                })
                continue

            # Check if handshake has been completed
            if not authenticated:
                await websocket.send_json({
                    "type": "error",
                    "message": "Handshake required. Please send member_id and business_id.",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            message_start_time = perf_counter()
            # Use the trusted context for all operations
            user_id = data.get("member_id") or user_context["user_id"]
            business_id = data.get("business_id") or user_context["businessId"]

            # Update global context if new values are provided
            if data.get("member_id") and user_id != user_context["user_id"]:
                user_context["user_id"] = user_id
                user_id_global = user_id

            if data.get("business_id") and business_id != user_context["businessId"]:
                user_context["businessId"] = business_id
                business_id_global = business_id

            message = data.get("message", "")
            conversation_id = data.get("conversation_id") or f"conv_{user_id}"
            force_planner = data.get("planner", False)
            
            # ✅ NEW: Handle preferences update in message
            if data.get("preferences") and user_context["user_id"] and user_context["businessId"]:
                try:
                    from mongo.user_preferences import user_preferences
                    await user_preferences.update_preferences(
                        user_context["user_id"],
                        user_context["businessId"],
                        data.get("preferences")
                    )
                    user_context["preferences"] = data.get("preferences")
                    
                    # ✅ NEW: Queue preference update for Mem0 learning
                    try:
                        from agent.knowledge_graph.learning import queue_preference_to_mem0
                        queue_preference_to_mem0(
                            user_id=user_context["user_id"],
                            business_id=user_context["businessId"],
                            preferences=data.get("preferences", {})
                        )
                    except Exception as e:
                        logger.debug(f"Failed to queue preference to Mem0: {e}")
                except Exception as e:
                    logger.warning(f"Failed to update preferences: {e}")

            # ✅ NEW: Handle new vs existing conversations
            from agent.memory import conversation_memory

            if not data.get("conversation_id"):
                # New conversation - mark to skip DB lookups
                conversation_memory.mark_as_new_conversation(conversation_id)
            else:
                # Existing conversation - ensure it's pre-warmed
                asyncio.create_task(
                    conversation_memory.pre_warm_conversation(conversation_id)
                )

            await websocket.send_json({
                "type": "user_message",
                "content": message,
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat()
            })

            # ✅ OPTIMIZED: Persist user message to ProjectManagement.conversations (fire-and-forget)
            try:
                # Fire-and-forget: don't block request processing
                # ✅ NEW: Include project_id when saving message
                asyncio.create_task(save_user_message(conversation_id, message, project_id=project_id))
                
                # ✅ NEW: Queue conversation for Mem0 learning (non-blocking)
                try:
                    from agent.knowledge_graph.learning import queue_conversation_to_mem0
                    from agent.memory import conversation_memory
                    
                    # Get recent messages for learning
                    recent_messages = await conversation_memory.get_recent_context(conversation_id, max_tokens=2000)
                    messages_data = [
                        {
                            "type": msg.__class__.__name__,
                            "content": msg.content if hasattr(msg, "content") else str(msg)
                        }
                        for msg in recent_messages[-10:]  # Last 10 messages
                    ]
                    
                    queue_conversation_to_mem0(
                        user_id=user_id,
                        business_id=business_id,
                        conversation_id=conversation_id,
                        messages=messages_data,
                        project_id=project_id
                    )
                except Exception as e:
                    logger.debug(f"Failed to queue conversation for Mem0 learning: {e}")
            except Exception as e:
                # Non-fatal: log error, continue processing
                logger.error(f"Failed to save user message: {e}")

            # Create a root span per user message and keep all work nested (disabled if DISABLE_TRACING)
            tracer = None
            user_span_cm = contextlib.nullcontext()
            with user_span_cm as user_span:
                # Route ONLY when explicitly forced; default to streaming agent
                if force_planner:
                    try:
                        planner_span_cm = contextlib.nullcontext()
                        with planner_span_cm as planner_span:
                            try:
                                planner_span.set_attribute("input.value", (message or "")[:1000])
                            except Exception:
                                pass
                            plan_result = await plan_and_execute_query(message)
                            if planner_span:
                                try:
                                    planner_span.set_attribute("planner.success", plan_result.get("success", False))
                                except Exception:
                                    pass
                        await websocket.send_json({
                            "type": "planner_result",
                            "success": plan_result.get("success", False),
                            "intent": plan_result.get("intent"),
                            "pipeline": plan_result.get("pipeline"),
                            "pipeline_js": plan_result.get("pipeline_js"),
                            "result": plan_result.get("result"),
                            "timestamp": datetime.now().isoformat()
                        })
                    except Exception as e:
                        if user_span:
                            try:
                                # user_span.set_status(Status(StatusCode.ERROR, str(e)))  # Tracing removed
                                pass
                            except Exception:
                                pass
                        await websocket.send_json({
                            "type": "planner_error",
                            "message": str(e),
                            "timestamp": datetime.now().isoformat()
                        })
                else:
                    # Set websocket for content generation tool (direct streaming to frontend)
                    from agent.tools import set_generation_context
                    # Provide websocket + conversation context for persisting generated artifacts
                    set_generation_context(websocket, conversation_id)
                    
                    # Use regular LLM with tool calling
                    agent_span_cm = contextlib.nullcontext()
                    with agent_span_cm as agent_span:
                        if agent_span:
                            try:
                                agent_span.set_attribute("input.value", (message or "")[:1000])
                            except Exception:
                                pass
                        async for _ in mongodb_agent.run_streaming(
                            query=message,
                            websocket=websocket,
                            conversation_id=conversation_id,
                            user_id=user_id,
                            business_id=business_id
                        ):
                            # The streaming is handled internally by the callback handler
                            # Just iterate through the generator to complete the streaming
                            pass
                    
                    # Clean up websocket reference after completion
                    from agent.tools import set_generation_websocket
                    set_generation_websocket(None)
            total_elapsed_ms = (perf_counter() - message_start_time) * 1000
            print(f"Total message handling for conv '{conversation_id}' took {total_elapsed_ms:.2f} ms")
            await websocket.send_json({
                "type": "complete",
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat()
            })

    except WebSocketDisconnect:
        # Cancel handshake timer if it exists
        if handshake_timer:
            handshake_timer.cancel()
        if user_context["user_id"]:
            ws_manager.disconnect(user_context["user_id"])
    except Exception as e:
        # Cancel handshake timer if it exists
        if handshake_timer:
            handshake_timer.cancel()
        if not websocket.client_state.name == 'DISCONNECTED':
            await websocket.send_json({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
        if user_context["user_id"]:
            ws_manager.disconnect(user_context["user_id"])
