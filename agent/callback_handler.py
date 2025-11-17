from langchain_groq import ChatGroq
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage
from langchain_core.callbacks import AsyncCallbackHandler
import asyncio
import contextlib
from typing import Dict, Any, List, AsyncGenerator, Optional
from agent.memory import conversation_memory
from typing import Tuple
from agent import tools as agent_tools
from datetime import datetime
import time
from collections import defaultdict, deque
import os

# Import tools list
try:
    tools_list = agent_tools.tools
except AttributeError:
    tools_list = []
import os
from langchain_groq import ChatGroq
from mongo.constants import DATABASE_NAME, mongodb_tools
from mongo.conversations import save_assistant_message, save_action_event


def _generate_natural_action_text(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Generate natural, human-like action statements that reflect agent reasoning.
    
    Uses varied vocabulary and contextual understanding to create realistic,
    conversational action descriptions.
    """
    import random
    
    try:
        if tool_name == "mongo_query":
            query = str(tool_args.get("query", "")).strip()
            query_lower = query.lower() if query else ""
            
            # Extract intent patterns for more contextual actions
            if not query:
                phrases = [
                    "Digging into the database to find what you need",
                    "Exploring the data to gather insights",
                    "Scanning through records to locate relevant information",
                    "Investigating the database for your answer"
                ]
                return random.choice(phrases)
            
            # Count-related queries
            if any(word in query_lower for word in ["count", "how many", "number of", "total"]):
                phrases = [
                    f"Counting records matching: {query[:45]}",
                    f"Tallying up the numbers for: {query[:45]}",
                    f"Calculating totals based on: {query[:45]}",
                    f"Running the numbers for: {query[:45]}"
                ]
                return random.choice(phrases)
            
            # Group/breakdown queries
            elif any(word in query_lower for word in ["group", "breakdown", "by", "grouped", "categorized"]):
                phrases = [
                    f"Analyzing data breakdown for: {query[:45]}",
                    f"Organizing results by categories: {query[:45]}",
                    f"Segmenting the data to show: {query[:45]}",
                    f"Grouping records to reveal patterns in: {query[:45]}"
                ]
                return random.choice(phrases)
            
            # List/show queries
            elif any(word in query_lower for word in ["list", "show", "find", "get", "retrieve", "fetch"]):
                phrases = [
                    f"Retrieving records for: {query[:45]}",
                    f"Fetching the data you requested: {query[:45]}",
                    f"Pulling up information about: {query[:45]}",
                    f"Gathering details on: {query[:45]}"
                ]
                return random.choice(phrases)
            
            # Filter/search queries
            elif any(word in query_lower for word in ["filter", "where", "with", "having", "that"]):
                phrases = [
                    f"Filtering through records: {query[:45]}",
                    f"Narrowing down results for: {query[:45]}",
                    f"Searching with specific criteria: {query[:45]}",
                    f"Applying filters to find: {query[:45]}"
                ]
                return random.choice(phrases)
            
            # Default query phrases
            else:
                phrases = [
                    f"Querying the database: {query[:45]}",
                    f"Running a search for: {query[:45]}",
                    f"Looking up information on: {query[:45]}",
                    f"Checking the data for: {query[:45]}"
                ]
                return random.choice(phrases)
        
        elif tool_name == "rag_search":
            query = str(tool_args.get("query", "")).strip()
            content_type = tool_args.get("content_type")
            
            if not query:
                phrases = [
                    "Searching through content and documentation",
                    "Exploring available resources",
                    "Scanning through relevant materials"
                ]
                return random.choice(phrases)
            
            # Format content type for display
            if content_type:
                type_label = content_type.replace("_", " ").title()
                type_variants = {
                    "work_item": ["work items", "tasks", "issues", "items"],
                    "page": ["pages", "documents", "docs", "notes"],
                    "cycle": ["cycles", "sprints", "iterations"],
                    "module": ["modules", "components", "features"],
                    "epic": ["epics", "initiatives", "large features"],
                    "project": ["projects", "initiatives"],
                    "user_story": ["user stories", "stories"],
                    "feature": ["features", "capabilities"]
                }
                type_display = type_variants.get(content_type, [type_label.lower()])[0]
                
                phrases = [
                    f"Searching through {type_display} for: {query[:45]}",
                    f"Looking through {type_display} content: {query[:45]}",
                    f"Scanning {type_display} to find: {query[:45]}",
                    f"Exploring {type_display} related to: {query[:45]}"
                ]
                return random.choice(phrases)
            else:
                phrases = [
                    f"Searching through all content: {query[:45]}",
                    f"Exploring documentation and materials: {query[:45]}",
                    f"Scanning through available resources: {query[:45]}",
                    f"Looking through content for: {query[:45]}"
                ]
                return random.choice(phrases)
        
        elif tool_name == "generate_content":
            content_type = str(tool_args.get("content_type", "content")).replace("_", " ")
            prompt = str(tool_args.get("prompt", "")).strip()
            
            # Map content types to natural descriptions
            type_descriptions = {
                "work_item": ["work item", "task", "issue", "item"],
                "page": ["page", "document", "doc", "note"],
                "cycle": ["cycle", "sprint", "iteration"],
                "module": ["module", "component"],
                "epic": ["epic", "initiative"]
            }
            
            type_label = type_descriptions.get(content_type, [content_type])[0]
            
            if prompt:
                phrases = [
                    f"Creating a new {type_label}: {prompt[:45]}",
                    f"Drafting a {type_label} for: {prompt[:45]}",
                    f"Generating a {type_label} based on: {prompt[:45]}",
                    f"Putting together a {type_label}: {prompt[:45]}"
                ]
                return random.choice(phrases)
            else:
                phrases = [
                    f"Creating a new {type_label}",
                    f"Drafting a {type_label}",
                    f"Generating a {type_label}",
                    f"Putting together a {type_label}"
                ]
                return random.choice(phrases)
        
        else:
            phrases = [
                "Processing your request",
                "Working on that for you",
                "Handling that now",
                "Taking care of that"
            ]
            return random.choice(phrases)
            
    except Exception:
        return "Processing your request..."


class AgentCallbackHandler(AsyncCallbackHandler):
    """WebSocket streaming callback handler for Phoenix events + DB logging"""

    def __init__(self, websocket=None, conversation_id: Optional[str] = None):
        super().__init__()
        self.websocket = websocket
        self.conversation_id = conversation_id
        self.start_time = None
        # Tool events are suppressed from frontend to avoid noise in chat UI
        # Internal step counter for lightweight progress (not exposed directly)
        self._step_counter = 0
        # Whether a dynamic, high-level action statement was already emitted for this step
        self._dynamic_action_emitted = False

    def _safe_extract(self, input_str: str) -> dict:
        """Best-effort parse of tool arg string to a dict without raising.

        Avoids revealing internals; used only to craft short, user-facing action text.
        """
        try:
            import json as _json
            if isinstance(input_str, str):
                # Try JSON first
                return _json.loads(input_str)
        except Exception:
            pass
        try:
            import ast as _ast
            if isinstance(input_str, str):
                val = _ast.literal_eval(input_str)
                if isinstance(val, dict):
                    return val
        except Exception:
            pass
        return {}

    async def _emit_action(self, text: str) -> None:
        self._step_counter += 1
        
        # Send to WebSocket first (if available)
        if self.websocket:
            payload = {
                "type": "agent_action",
                "text": text,
                "step": self._step_counter,
                "timestamp": datetime.now().isoformat(),
            }
            await self.websocket.send_json(payload)
        
        # Fire-and-forget DB save (don't block UI)
        if self.conversation_id:
            try:
                asyncio.create_task(
                    save_action_event(self.conversation_id, "action", text, step=self._step_counter)
                )
            except Exception:
                pass

    async def _emit_result(self, text: str) -> None:
        # No-op: disable sending and persisting 'result' events
        return

    async def on_llm_start(self, *args, **kwargs):
        """Called when LLM starts generating"""
        self.start_time = time.time()
        # Reset dynamic action emission flag at the beginning of a reasoning step
        self._dynamic_action_emitted = False
        if self.websocket:
            await self.websocket.send_json({
                "type": "llm_start",
                "timestamp": datetime.now().isoformat()
            })

    async def on_llm_new_token(self, token: str, **kwargs):
        """Stream each token as it's generated"""
        if self.websocket:
            await self.websocket.send_json({
                "type": "token",
                "content": token,
                "timestamp": datetime.now().isoformat()
            })

    async def on_llm_end(self, *args, **kwargs):
        """Called when LLM finishes generating"""
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        if self.websocket:
            await self.websocket.send_json({
                "type": "llm_end",
                "elapsed_time": elapsed_time,
                "timestamp": datetime.now().isoformat()
            })

    async def on_tool_end(self, output: str, **kwargs):
        """Called when a tool finishes executing.

        Suppressed: We no longer send tool_end events to the frontend socket.
        """
        return

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """Called when a tool starts executing.
        
        Now emits real-time, natural action events to the frontend as tools actually start.
        Each tool emits its own action, allowing multiple parallel tools to show their progress.
        """
        try:
            tool_name = serialized.get("name", "")
            if not tool_name:
                return
            
            # Parse tool arguments from input_str
            tool_args = self._safe_extract(input_str)
            
            # Generate natural, human-like action text based on tool and args
            action_text = _generate_natural_action_text(tool_name, tool_args)
            
            # Emit action immediately - this is fast (~1ms)
            await self._emit_action(action_text)
        except Exception as e:
            # Fallback to simple action if generation fails
            try:
                tool_name = serialized.get("name", "tool")
                await self._emit_action(f"Executing {tool_name}...")
            except Exception:
                pass

    def cleanup(self):
        """Clean up Phoenix span collector"""
        pass

    async def emit_dynamic_action(self, text: str) -> None:
        """Emit a single, user-facing dynamic action line and mark it as emitted.

        This prevents fallback action emissions inside on_tool_start for the same step.
        """
        try:
            await self._emit_action(text)
        finally:
            # Ensure we don't emit fallback messages during this step
            self._dynamic_action_emitted = True
