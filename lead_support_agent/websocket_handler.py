"""
WebSocket Handler for Lead Support Agent.

Handles WebSocket connections for lead-specific support functionality.
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class LeadSupportWebSocketManager:
    """Manages WebSocket connections for lead support sessions."""

    def __init__(self):
        self.active_sessions: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept and store a new WebSocket connection."""
        self.active_sessions[session_id] = websocket

    def disconnect(self, session_id: str):
        """Remove a WebSocket connection."""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

    def get_session(self, session_id: str) -> Optional[WebSocket]:
        """Get a WebSocket connection by session_id."""
        return self.active_sessions.get(session_id)


# Global WebSocket manager for lead support
lead_support_ws_manager = LeadSupportWebSocketManager()


async def handle_lead_support_websocket(
    websocket: WebSocket,
    lead_support_agent
):
    """
    Handle WebSocket connections for lead support agent.
    
    Message types supported:
    - handshake: Initialize session with business_id and user_id
    - ping: Keep-alive ping
    - query: General lead support query
    - summarize: Summarize a specific lead
    - next_steps: Get next best steps for a lead
    - compare: Compare multiple leads
    - draft_message: Draft a message for a lead
    - objection: Handle a sales objection
    - meeting_prep: Prepare for a meeting
    - email: Compose an email for a lead
    """
    session_id = None
    user_context = {
        "user_id": None,
        "business_id": None,
    }
    authenticated = False
    handshake_timer = None
    
    try:
        await websocket.accept()
        
        # Set handshake timeout (30 seconds)
        async def check_handshake_timeout():
            nonlocal authenticated
            await asyncio.sleep(30)
            if not authenticated:
                await websocket.send_json({
                    "type": "error",
                    "message": "Handshake timeout. Please send member_id and business_id within 30 seconds.",
                    "timestamp": datetime.now().isoformat()
                })
                await websocket.close()
        
        handshake_timer = asyncio.create_task(check_handshake_timeout())
        
        # Main message loop
        while True:
            try:
                data_str = await websocket.receive_text()
            except Exception:
                break
            
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            msg_type = data.get("type", "query")
            
            # Handle ping
            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Handle handshake
            if msg_type == "handshake":
                user_context["user_id"] = data.get("member_id")
                user_context["business_id"] = data.get("business_id")
                session_id = data.get("session_id") or f"lead_support_{user_context['user_id']}"
                
                # Cancel handshake timeout
                if handshake_timer:
                    handshake_timer.cancel()
                
                # Connect session
                await lead_support_ws_manager.connect(websocket, session_id)
                authenticated = True
                
                await websocket.send_json({
                    "type": "handshake_ack",
                    "session_id": session_id,
                    "user_id": user_context["user_id"],
                    "business_id": user_context["business_id"],
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Check authentication
            if not authenticated:
                await websocket.send_json({
                    "type": "error",
                    "message": "Handshake required. Please send member_id and business_id.",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Get common parameters
            lead_id = data.get("lead_id")
            query = data.get("query") or data.get("message", "")
            business_id = data.get("business_id") or user_context["business_id"]
            
            # Send acknowledgment
            await websocket.send_json({
                "type": "processing",
                "message_type": msg_type,
                "timestamp": datetime.now().isoformat()
            })
            
            try:
                # Route to appropriate handler based on message type
                if msg_type == "summarize":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for summarize",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    async for _ in lead_support_agent.summarize_lead(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "next_steps":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for next_steps",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    async for _ in lead_support_agent.get_next_steps(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "compare":
                    lead_ids = data.get("lead_ids", [])
                    if not lead_ids or len(lead_ids) < 2:
                        await websocket.send_json({
                            "type": "error",
                            "message": "At least 2 lead_ids required for comparison",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    async for _ in lead_support_agent.compare_leads_handler(
                        lead_ids=lead_ids,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "draft_message":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for draft_message",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    message_type = data.get("message_type", "message")
                    context = data.get("context")
                    
                    async for _ in lead_support_agent.draft_message(
                        lead_id=lead_id,
                        message_type=message_type,
                        context=context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "objection":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for objection handling",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    objection = data.get("objection", query)
                    if not objection:
                        await websocket.send_json({
                            "type": "error",
                            "message": "objection text is required",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    async for _ in lead_support_agent.handle_objection(
                        lead_id=lead_id,
                        objection=objection,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "meeting_prep":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for meeting_prep",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    meeting_context = data.get("meeting_context")
                    
                    async for _ in lead_support_agent.prepare_meeting(
                        lead_id=lead_id,
                        meeting_context=meeting_context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                elif msg_type == "email":
                    if not lead_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "lead_id is required for email composition",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    context = data.get("context")
                    
                    async for _ in lead_support_agent.draft_message(
                        lead_id=lead_id,
                        message_type="email",
                        context=context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass
                
                else:
                    # Default: general query handling
                    task_type = data.get("task_type")
                    
                    async for _ in lead_support_agent.run_streaming(
                        query=query,
                        websocket=websocket,
                        lead_id=lead_id,
                        task_type=task_type,
                        session_id=session_id,
                        business_id=business_id,
                    ):
                        pass
                
                # Send completion message
                await websocket.send_json({
                    "type": "complete",
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error processing lead support request: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                })
    
    except WebSocketDisconnect:
        if handshake_timer:
            handshake_timer.cancel()
        if session_id:
            lead_support_ws_manager.disconnect(session_id)
    
    except Exception as e:
        logger.error(f"Lead support WebSocket error: {e}")
        if handshake_timer:
            handshake_timer.cancel()
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
        except Exception:
            pass
        if session_id:
            lead_support_ws_manager.disconnect(session_id)
