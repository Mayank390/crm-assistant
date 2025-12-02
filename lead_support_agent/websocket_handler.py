"""
WebSocket Handler for Lead Support Agent.

Handles WebSocket connections for lead-specific support functionality.
"""

import json
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Global variables for business and user context (accessed by mongo constants)
business_id_global = None
user_id_global = None


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
    - query: General lead support query (supports natural language)
    - summarize: Summarize a specific lead
    - insights: Get AI insights about a lead
    - enrich: Enrich lead with additional data
    - next_steps: Get next best steps for a lead
    - compare: Compare multiple leads
    - draft_message: Draft a message for a lead
    - objection: Handle a sales objection
    - meeting_prep: Prepare for a meeting
    - qualification: Assess lead qualification using BANT framework
    - statistics: Get comprehensive lead statistics and engagement analysis
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
        logger.info("Lead Support WebSocket connection accepted")
        
        # Set handshake timeout (30 seconds)
        async def check_handshake_timeout():
            nonlocal authenticated
            await asyncio.sleep(30)
            if not authenticated:
                logger.warning("Handshake timeout - closing connection")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Handshake timeout. Please send member_id and business_id within 30 seconds.",
                        "timestamp": datetime.now().isoformat()
                    })
                    await websocket.close()
                except Exception:
                    pass
        
        handshake_timer = asyncio.create_task(check_handshake_timeout())
        
        # Main message loop
        while True:
            try:
                data_str = await websocket.receive_text()
                logger.debug(f"Received message: {data_str[:200]}...")
            except Exception as e:
                logger.info(f"WebSocket receive error: {e}")
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
            logger.info(f"Processing message type: {msg_type}")
            
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

                # Set global business_id and user_id for tools to access
                # Set in both root-level and LSA websocket handlers for mongo constants to access
                import websocket_handler as root_ws
                root_ws.business_id_global = user_context["business_id"]
                root_ws.user_id_global = user_context["user_id"]

                # Also set in LSA websocket handler
                import lead_support_agent.websocket_handler as lsa_ws
                lsa_ws.business_id_global = user_context["business_id"]
                lsa_ws.user_id_global = user_context["user_id"]

                # Cancel handshake timeout
                if handshake_timer:
                    handshake_timer.cancel()

                # Connect session
                await lead_support_ws_manager.connect(websocket, session_id)
                authenticated = True

                logger.info(f"Handshake complete: session={session_id}, business={user_context['business_id']}")

                await websocket.send_json({
                    "type": "handshake_ack",
                    "session_id": session_id,
                    "user_id": user_context["user_id"],
                    "business_id": user_context["business_id"],
                    "message": "Connected to Lead Support Agent",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Check authentication
            if not authenticated:
                await websocket.send_json({
                    "type": "error",
                    "message": "Handshake required. Please send member_id and business_id first.",
                    "timestamp": datetime.now().isoformat()
                })
                continue
            
            # Get common parameters
            lead_id = data.get("lead_id")
            query = data.get("query") or data.get("message", "")
            business_id = data.get("business_id") or user_context["business_id"]
            
            if msg_type in ["summarize", "insights", "enrich", "next_steps", "draft_message", "meeting_prep", "qualification", "statistics", "email"]:
                if not lead_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"lead_id is required for {msg_type}",
                        "timestamp": datetime.now().isoformat()
                    })
                    continue
            
            # Send acknowledgment
            await websocket.send_json({
                "type": "processing",
                "message_type": msg_type,
                "lead_id": lead_id,
                "timestamp": datetime.now().isoformat()
            })
            
            try:
                logger.info(f"Processing {msg_type} for lead_id={lead_id}, business_id={business_id}")
                
                # Route to appropriate handler based on message type
                if msg_type == "summarize":
                    async for chunk in lead_support_agent.summarize_lead(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass  # Streaming happens inside the generator via callback handler

                elif msg_type == "insights":
                    async for chunk in lead_support_agent.get_insights(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "enrich":
                    async for chunk in lead_support_agent.enrich_lead(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "next_steps":
                    async for chunk in lead_support_agent.get_next_steps(
                        lead_id=lead_id,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "compare":
                    lead_ids = data.get("lead_ids", [])
                    if not lead_ids:
                        await websocket.send_json({
                            "type": "error",
                            "message": "At least 1 lead_id required for comparison",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue

                    # If only one lead is provided, find similar leads to compare with
                    if len(lead_ids) == 1:
                        try:
                            # Get lead context and find similar leads
                            from lead_support_agent.tools import get_lead_context

                            # Get the current lead's data
                            lead_context = await get_lead_context.ainvoke({
                                "lead_id": lead_ids[0],
                                "include_tasks": False,
                                "include_meetings": False,
                                "include_notes": False,
                                "include_activities": False,
                                "include_calls": False,
                                "include_emails": False,
                            })

                            # Find similar leads based on company and industry
                            similar_query = f"""Find 2-3 other leads in the database that are similar to this lead based on:
- Same industry/company type
- Similar company size
- Similar lead status/stage
- Same geographic region

Return only the lead IDs separated by commas, no other text.

Lead context: {lead_context}"""

                            similar_result = await lead_support_agent.run(
                                query=similar_query,
                                lead_id=lead_ids[0],
                                business_id=business_id,
                            )

                            # Extract lead IDs from the response using regex
                            import re
                            found_ids = re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', similar_result)
                            if found_ids:
                                lead_ids.extend(found_ids[:3])  # Add up to 3 similar leads
                            else:
                                # If no similar leads found, still provide comparison with insights about this lead
                                pass  # Keep the single lead for analysis
                        except Exception as e:
                            logger.warning(f"Failed to find similar leads for comparison: {e}")

                    async for chunk in lead_support_agent.compare_leads_handler(
                        lead_ids=lead_ids,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "draft_message":
                    message_type = data.get("message_type", "message")
                    context = data.get("context")

                    async for chunk in lead_support_agent.draft_message(
                        lead_id=lead_id,
                        message_type=message_type,
                        context=context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass


                elif msg_type == "meeting_prep":
                    meeting_context = data.get("meeting_context")

                    async for chunk in lead_support_agent.prepare_meeting(
                        lead_id=lead_id,
                        meeting_context=meeting_context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "qualification":
                    qualification_context = data.get("qualification_context")

                    async for chunk in lead_support_agent.qualify_lead(
                        lead_id=lead_id,
                        qualification_context=qualification_context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "statistics":
                    statistics_context = data.get("statistics_context")

                    async for chunk in lead_support_agent.get_statistics(
                        lead_id=lead_id,
                        statistics_context=statistics_context,
                        websocket=websocket,
                        business_id=business_id,
                    ):
                        pass

                elif msg_type == "email":
                    context = data.get("context")

                    async for chunk in lead_support_agent.draft_message(
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
                    
                    if not query:
                        await websocket.send_json({
                            "type": "error",
                            "message": "query or message is required",
                            "timestamp": datetime.now().isoformat()
                        })
                        continue
                    
                    async for chunk in lead_support_agent.run_streaming(
                        query=query,
                        websocket=websocket,
                        lead_id=lead_id,
                        task_type=task_type,
                        session_id=session_id,
                        business_id=business_id,
                    ):
                        pass
                
                # Send completion message
                logger.info(f"Completed {msg_type} processing")
                await websocket.send_json({
                    "type": "complete",
                    "message_type": msg_type,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error processing {msg_type}: {e}")
                logger.error(traceback.format_exc())
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error processing request: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
        if handshake_timer:
            handshake_timer.cancel()
        if session_id:
            lead_support_ws_manager.disconnect(session_id)
    
    except Exception as e:
        logger.error(f"Lead support WebSocket error: {e}")
        logger.error(traceback.format_exc())
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
