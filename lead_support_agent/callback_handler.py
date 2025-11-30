"""
Simplified Callback Handler for Lead Support Agent.

Handles WebSocket streaming and action events for the lead support agent.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


def _generate_lead_action_text(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Generate natural, human-like action statements for lead support tools."""
    import random
    
    try:
        if tool_name == "get_lead_context":
            lead_id = tool_args.get("lead_id", "")[:8]
            phrases = [
                f"Gathering complete lead profile and history...",
                f"Pulling together all information about this lead...",
                f"Compiling lead context and related data...",
                f"Loading lead details, tasks, meetings, and notes...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "compare_leads":
            count = len(tool_args.get("lead_ids", []))
            phrases = [
                f"Comparing {count} leads side-by-side...",
                f"Analyzing {count} leads for comparison...",
                f"Building comparison matrix for {count} leads...",
                f"Evaluating {count} leads across key metrics...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "search_lead_content":
            query = tool_args.get("query", "")[:30]
            phrases = [
                f"Searching for relevant content: {query}",
                f"Looking through lead data for: {query}",
                f"Finding related information about: {query}",
                f"Scanning records for: {query}",
            ]
            return random.choice(phrases)
        
        elif tool_name == "get_lead_stats":
            phrases = [
                "Calculating lead engagement metrics...",
                "Compiling activity statistics...",
                "Analyzing lead performance data...",
                "Gathering engagement insights...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "generate_lead_content":
            content_type = tool_args.get("content_type", "content")
            phrases = [
                f"Preparing to generate {content_type}...",
                f"Creating {content_type} draft...",
                f"Drafting personalized {content_type}...",
                f"Building {content_type} based on lead context...",
            ]
            return random.choice(phrases)
        
        else:
            return "Processing your request..."
            
    except Exception:
        return "Processing..."


class LeadSupportCallbackHandler(AsyncCallbackHandler):
    """Simplified WebSocket streaming callback handler for lead support agent."""

    def __init__(self, websocket=None, session_id: Optional[str] = None):
        super().__init__()
        self.websocket = websocket
        self.session_id = session_id
        self.start_time = None
        self._step_counter = 0

    async def _emit_action(self, text: str) -> None:
        """Emit an action event to the WebSocket."""
        self._step_counter += 1
        
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "agent_action",
                    "text": text,
                    "step": self._step_counter,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.warning(f"Failed to emit action: {e}")

    async def on_llm_start(self, *args, **kwargs):
        """Called when LLM starts generating."""
        import time
        self.start_time = time.time()
        
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "llm_start",
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to send llm_start: {e}")

    async def on_llm_new_token(self, token: str, **kwargs):
        """Stream each token as it's generated."""
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "token",
                    "content": token,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to stream token: {e}")

    async def on_llm_end(self, *args, **kwargs):
        """Called when LLM finishes generating."""
        import time
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "llm_end",
                    "elapsed_time": elapsed_time,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to send llm_end: {e}")

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """Called when a tool starts executing."""
        try:
            tool_name = serialized.get("name", "")
            if not tool_name:
                return
            
            # Parse tool arguments
            tool_args = {}
            try:
                import json
                tool_args = json.loads(input_str) if isinstance(input_str, str) else {}
            except Exception:
                pass
            
            # Generate natural action text
            action_text = _generate_lead_action_text(tool_name, tool_args)
            await self._emit_action(action_text)
            
        except Exception as e:
            logger.warning(f"Error in on_tool_start: {e}")

    async def on_tool_end(self, output: str, **kwargs):
        """Called when a tool finishes executing (suppressed for cleaner UX)."""
        pass

    async def emit_status(self, status: str) -> None:
        """Emit a status message to the client."""
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "status",
                    "message": status,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.warning(f"Failed to emit status: {e}")
