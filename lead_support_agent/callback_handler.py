"""
Callback Handler for Lead Support Agent WebSocket streaming.

Handles real-time streaming of LLM responses and tool actions.
"""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


def _generate_lead_action_text(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Generate natural, human-like action statements for lead support tools."""
    import random
    
    try:
        if tool_name == "get_lead_context":
            phrases = [
                "📋 Gathering complete lead profile and history...",
                "🔍 Pulling together all information about this lead...",
                "📊 Compiling lead context and related data...",
                "📁 Loading lead details, tasks, meetings, and notes...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "compare_leads":
            count = len(tool_args.get("lead_ids", []))
            phrases = [
                f"📊 Comparing {count} leads side-by-side...",
                f"🔄 Analyzing {count} leads for comparison...",
                f"📈 Building comparison matrix for {count} leads...",
                f"⚖️ Evaluating {count} leads across key metrics...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "search_lead_content":
            query = tool_args.get("query", "")[:30]
            phrases = [
                f"🔍 Searching for: {query}...",
                f"📑 Looking through lead data for: {query}...",
                f"🔎 Finding related information about: {query}...",
                f"📂 Scanning records for: {query}...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "get_lead_stats":
            phrases = [
                "📊 Calculating lead engagement metrics...",
                "📈 Compiling activity statistics...",
                "🎯 Analyzing lead performance data...",
                "📉 Gathering engagement insights...",
            ]
            return random.choice(phrases)
        
        elif tool_name == "generate_lead_content":
            content_type = tool_args.get("content_type", "content")
            phrases = [
                f"✍️ Preparing to generate {content_type}...",
                f"📝 Creating {content_type} draft...",
                f"💬 Drafting personalized {content_type}...",
                f"📄 Building {content_type} based on lead context...",
            ]
            return random.choice(phrases)
        
        else:
            return "⚙️ Processing your request..."
            
    except Exception:
        return "⚙️ Processing..."


class LeadSupportCallbackHandler(AsyncCallbackHandler):
    """
    WebSocket streaming callback handler for Lead Support Agent.
    
    Sends real-time updates to the frontend including:
    - llm_start: When the LLM begins generating
    - token: Individual tokens as they're generated
    - llm_end: When generation completes
    - agent_action: Tool execution updates
    - status: General status messages
    """

    def __init__(self, websocket=None, session_id: Optional[str] = None):
        super().__init__()
        self.websocket = websocket
        self.session_id = session_id
        self.start_time = None
        self._step_counter = 0
        self._token_count = 0
        self._accumulated_content = ""

    async def _safe_send(self, data: dict) -> bool:
        """Safely send data to WebSocket, handling errors gracefully."""
        if not self.websocket:
            return False
        
        try:
            await self.websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning(f"WebSocket send failed: {e}")
            return False

    async def _emit_action(self, text: str) -> None:
        """Emit an action event to the WebSocket."""
        self._step_counter += 1
        
        await self._safe_send({
            "type": "agent_action",
            "text": text,
            "step": self._step_counter,
            "timestamp": datetime.now().isoformat(),
        })

    async def on_llm_start(self, *args, **kwargs):
        """Called when LLM starts generating."""
        self.start_time = time.time()
        self._token_count = 0
        self._accumulated_content = ""
        
        await self._safe_send({
            "type": "llm_start",
            "message": "Generating response...",
            "timestamp": datetime.now().isoformat()
        })

    async def on_llm_new_token(self, token: str, **kwargs):
        """Stream each token as it's generated."""
        if not token:
            return
            
        self._token_count += 1
        self._accumulated_content += token
        
        await self._safe_send({
            "type": "token",
            "content": token,
            "token_count": self._token_count,
            "timestamp": datetime.now().isoformat()
        })

    async def on_llm_end(self, *args, **kwargs):
        """Called when LLM finishes generating."""
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        
        await self._safe_send({
            "type": "llm_end",
            "token_count": self._token_count,
            "elapsed_time": round(elapsed_time, 2),
            "full_content": self._accumulated_content,
            "timestamp": datetime.now().isoformat()
        })

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """Called when a tool starts executing."""
        try:
            tool_name = serialized.get("name", "")
            if not tool_name:
                return
            
            # Parse tool arguments
            tool_args = {}
            try:
                if isinstance(input_str, str):
                    tool_args = json.loads(input_str)
                elif isinstance(input_str, dict):
                    tool_args = input_str
            except Exception:
                pass
            
            # Generate natural action text
            action_text = _generate_lead_action_text(tool_name, tool_args)
            await self._emit_action(action_text)
            
        except Exception as e:
            logger.warning(f"Error in on_tool_start: {e}")

    async def on_tool_end(self, output: str, **kwargs):
        """Called when a tool finishes executing."""
        # Send a brief confirmation that tool completed
        await self._safe_send({
            "type": "tool_complete",
            "timestamp": datetime.now().isoformat()
        })

    async def on_tool_error(self, error: Exception, **kwargs):
        """Called when a tool errors."""
        await self._safe_send({
            "type": "tool_error",
            "error": str(error),
            "timestamp": datetime.now().isoformat()
        })

    async def emit_status(self, status: str) -> None:
        """Emit a status message to the client."""
        await self._safe_send({
            "type": "status",
            "message": status,
            "timestamp": datetime.now().isoformat()
        })

    async def emit_thinking(self, thinking: str) -> None:
        """Emit a thinking/processing message to the client."""
        await self._safe_send({
            "type": "thinking",
            "message": thinking,
            "timestamp": datetime.now().isoformat()
        })

    def get_accumulated_content(self) -> str:
        """Get the accumulated content from streaming."""
        return self._accumulated_content
