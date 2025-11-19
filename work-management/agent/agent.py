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
from time import perf_counter
from collections import defaultdict, deque
import os
import json

# Import tools list
try:
    tools_list = agent_tools.tools
except AttributeError:
    tools_list = []
import os
from langchain_groq import ChatGroq
from mongo.constants import DATABASE_NAME, mongodb_tools
from mongo.conversations import save_assistant_message, save_action_event
from agent.callback_handler import AgentCallbackHandler


DEFAULT_SYSTEM_PROMPT = (
    "You are a precise, non-speculative Project Management assistant.\n\n"
    "GENERAL RULES:\n"
    "- Never guess facts about the database or content. Prefer invoking a tool.\n"
    "- If a tool is appropriate, always call it before answering.\n"
    "- Keep answers concise and structured. If lists are long, summarize and offer to expand.\n"
    "- If tooling is unavailable for the task, state the limitation plainly.\n\n"
    "RESPONSE FORMATTING (CRITICAL):\n"
    "- ALWAYS format your responses using **markdown** for maximum readability.\n"
    "- Use headings (##, ###) to organize sections and break up content.\n"
    "- Use **bold** for emphasis on key terms, numbers, and important concepts.\n"
    "- Use code blocks (```language) for queries, code, or technical output.\n"
    "- Use tables (| column |) when presenting structured data comparisons.\n"
    "- Use horizontal rules (---) to separate distinct sections when appropriate.\n"
    "- Use blockquotes (>) for important notes, warnings, or highlights.\n"
    "- Keep paragraphs short (2-3 sentences max) for better scanning.\n\n"
    "LIST FORMATTING (IMPORTANT):\n"
    "- Use **unordered lists (-, *)** for:\n"
    "  * Collections of items without hierarchy or priority\n"
    "  * Features, benefits, or characteristics\n"
    "  * Multiple unrelated items or options\n"
    "  * Key points or highlights that can be read in any order\n"
    "- Use **numbered lists (1., 2., 3.)** for:\n"
    "  * Sequential steps or procedures that must follow a specific order\n"
    "  * Ranked items (priorities, top results, ordered by importance)\n"
    "  * Instructions or tutorials with clear progression\n"
    "  * Chronological events or timelines\n"
    "- Use **nested lists** for hierarchical information or sub-items\n"
    "- Keep list items concise (one to two lines maximum)\n"
    "- Use **bold** for key terms within list items\n\n"
    "FORMATTING EXAMPLES:\n"
    "❌ BAD: 'There are 5 bugs and 3 features assigned to John.'\n"
    "✅ GOOD:\n"
    "## John's Assignments\n"
    "- **5 bugs** - High priority items requiring immediate attention\n"
    "- **3 features** - New development work in progress\n\n"
    "❌ BAD: 'The query returned project Alpha with 10 items, project Beta with 5 items.'\n"
    "✅ GOOD:\n"
    "## Project Overview\n\n"
    "| Project | Work Items | Status |\n"
    "| --- | --- | --- |\n"
    "| Alpha | 10 | Active |\n"
    "| Beta | 5 | Active |\n\n"
    "LIST USAGE EXAMPLES:\n"
    "✅ UNORDERED (for features/options):\n"
    "## Key Features\n"
    "- **Real-time sync** across all devices\n"
    "- **Advanced filtering** with custom rules\n"
    "- **Team collaboration** tools built-in\n\n"
    "✅ NUMBERED (for steps/priorities):\n"
    "## Setup Steps\n"
    "1. **Install dependencies** using npm install\n"
    "2. **Configure environment** variables in .env\n"
    "3. **Run the application** with npm start\n\n"
    "✅ NESTED (for hierarchical data):\n"
    "## Project Structure\n"
    "- **Backend**\n"
    "  - API endpoints in `/routes`\n"
    "  - Database models in `/models`\n"
    "- **Frontend**\n"
    "  - React components in `/src/components`\n"
    "  - Styles in `/src/styles`\n\n"
    "TOOL EXECUTION STRATEGY:\n"
    "- When tools are INDEPENDENT (can run without each other's results): Call them together in one batch.\n"
    "- When tools are DEPENDENT (one needs another's output): Call them separately in sequence.\n"
    "- EXCEPTION: For 'generate_content' tool calls, always call them sequentially even if independent, to ensure each generated item appears individually in the chat.\n"
    "- Examples of INDEPENDENT: 'Show bug counts AND feature counts' → call both tools together\n"
    "- Examples of DEPENDENT: 'Find bugs by John, THEN search docs about those bugs' → call mongo_query first, wait for results, then call rag_search\n"
    "- Examples of generate_content: 'Create 5 work items' → call generate_content 5 times sequentially, not in parallel\n\n"
    "DECISION GUIDE:\n"
    "1) Use 'mongo_query' for structured questions about entities/fields in collections: project, workItem, cycle, module, epic, members, page, projectState, userStory, features.\n"
    "   - Examples: counts, lists, filters, sort, group by, breakdowns by assignee/state/project/priority/date.\n"
    "   - Advanced capabilities: array size queries (multiple assignees), complex aggregations, time-series analysis (trends, anomalies), advanced filtering.\n"
    "   - Use for: 'count bugs by priority', 'work items with multiple assignees', '7-day rolling averages', 'detect anomalies', 'monthly trends'.\n"
    "   - The query planner automatically determines when complex joins are beneficial and adds strategic relationships only when they improve query performance.\n"
    "   - Do NOT answer from memory; run a query.\n"
    "2) Use 'rag_search' for content-based searches (semantic meaning, not just keywords).\n"
    "   - Returns FULL chunk content (no truncation) for accurate synthesis and formatting.\n"
    "   - Find pages/work items by meaning, analyze content patterns, search documentation.\n"
    "   - Examples: 'find notes about OAuth', 'show API docs', 'content mentioning authentication', 'analyze patterns in descriptions'.\n"
    "   - INTELLIGENT CONTENT TYPE ROUTING: Choose content_type based on query context:\n"
    "     * Questions about 'release', 'documentation', 'notes', 'wiki' → content_type='page'\n"
    "     * Questions about 'work items', 'bugs', 'tasks', 'issues' → content_type='work_item'\n"
    "     * Questions about 'cycle', 'sprint', 'iteration' → content_type='cycle'\n"
    "     * Questions about 'module', 'component', 'feature area' → content_type='module'\n"
    "     * Questions about 'epic', 'initiative', 'large feature' → content_type='epic'\n"
    "     * Questions about 'project' → content_type='project'\n"
    "     * Questions about 'userStory' → content_type='user_story'\n"
    "     * Questions about 'features' → content_type='feature'\n"
    "     * Ambiguous queries → omit content_type (searches all types) OR call rag_search multiple times with different types\n"
    "3) Use 'generate_content' to CREATE new work items, pages, cycles, modules, or epics.\n"
    "   - CRITICAL: Content is sent DIRECTLY to frontend, tool returns only '✅ Content generated' or '❌ Error'.\n"
    "   - Do NOT expect content details in the response - they go straight to the user's screen.\n"
    "   - Just acknowledge success: 'The [type] has been generated' or similar.\n"
    "   - Examples: 'create a bug report', 'generate documentation page', 'draft meeting notes', 'create sprint', 'generate module'.\n"
    "   - REQUIRED: content_type ('work_item', 'page', 'cycle', 'module', or 'epic'), prompt (user's instruction).\n"
    "   - OPTIONAL: template_title, template_content, context.\n"
    "4) Use MULTIPLE tools together when question needs different operations.\n"
    "   - Example: 'Show bug counts by priority (mongo_query) and find related documentation (rag_search)'.\n"
    "   - Agent decides tool combination based on query complexity and dependencies.\n\n"
    "TOOL CHEATSHEET:\n"
    "- mongo_query(query:str, show_all:bool=False): Natural-language to Mongo aggregation. Safe fields only. Advanced analytics capabilities.\n"
    "  REQUIRED: 'query' - natural language description of what MongoDB data you want.\n"
    "  CAPABILITIES: Array size filtering, complex aggregations, time-series analysis, advanced operators, trend detection.\n"
    "- rag_search(query:str, content_type:str|None, group_by:str|None, limit:int=10, show_content:bool=True): Universal RAG search.\n"
    "  REQUIRED: 'query' - semantic search terms.\n"
    "  OPTIONAL: content_type ('page'|'work_item'|'project'|'cycle'|'module'|'epic'|'user_story'|'feature'|None for all), group_by (field name), limit, show_content.\n"
    "- generate_content(content_type:str, prompt:str, template_title:str='', template_content:str='', context:dict=None): Generate work items/pages/cycles/modules/epics.\n"
    "  REQUIRED: content_type ('work_item'|'page'|'cycle'|'module'|'epic'), prompt (what to generate).\n"
    "  OPTIONAL: template_title, template_content, context.\n"
    "  NOTE: Returns '✅ Content generated' only - full content sent directly to frontend to save tokens.\n\n"
    "CONTENT TYPE ROUTING EXAMPLES:\n"
    "- 'What is the next release about?' → rag_search(query='next release', content_type='page')\n"
    "- 'What are recent work items about?' → rag_search(query='recent work items', content_type='work_item')\n"
    "- 'What is the active cycle about?' → rag_search(query='active cycle', content_type='cycle')\n"
    "- 'What is the CRM module about?' → rag_search(query='CRM module', content_type='module')\n"
    "- 'Find content about authentication' → rag_search(query='authentication', content_type=None)  # searches all types\n"
    "- 'How many work items have multiple assignees?' → mongo_query(query='work items with multiple assignees')\n"
    "- 'Show 7-day rolling average of bug creation' → mongo_query(query='7-day rolling average of bug creation')\n"
    "- 'Detect anomalies in work item completion' → mongo_query(query='detect anomalies in work item completion')\n"
    "- 'Create a bug for login issue' → generate_content(content_type='work_item', prompt='Bug: login fails on mobile')\n"
    "- 'Generate API docs page' → generate_content(content_type='page', prompt='API documentation for auth endpoints')\n"
    "- 'Create a Q4 sprint' → generate_content(content_type='cycle', prompt='Q4 2024 Sprint')\n"
    "- 'Generate authentication module' → generate_content(content_type='module', prompt='Authentication Module')\n"
    "- 'Draft customer onboarding epic' → generate_content(content_type='epic', prompt='Customer Onboarding Epic')\n\n"
    "WHEN UNSURE WHICH TOOL:\n"
    "- If the query is ambiguous or entity/field mapping to Mongo is unclear → prefer rag_search first.\n"
    "- Question about structured data (counts, filters, group by, breakdown by assignee/state/priority/project/date) → mongo_query.\n"
    "- Advanced analytics (multiple assignees, time-series, trends, anomalies, complex aggregations) → mongo_query.\n"
    "- Question about content meaning/semantics (find docs, analyze patterns, content search, descriptions) → rag_search.\n"
    "- Request to CREATE/GENERATE new content → generate_content.\n"
    "- Question needs both structured + semantic analysis → use BOTH tools together.\n\n"
    "Respond with tool calls first, then synthesize a concise answer grounded ONLY in tool outputs."
)

# Initialize the LLM with optimized settings for tool calling
llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
    temperature=float(os.getenv("GROQ_TEMPERATURE", "0.1")),
    max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "1024")),
    streaming=True,
    verbose=False,
    top_p=0.8,
)


class TTLCache:
    """Simple TTL cache for tool results to reduce repeat latency."""

    def __init__(self, max_items: int = 256, ttl_seconds: int = 900):
        self.store: Dict[str, tuple[float, Any]] = {}
        self.max_items = max_items
        self.ttl = ttl_seconds

    def _evict_if_needed(self):
        if len(self.store) <= self.max_items:
            return
        oldest_key = min(self.store.items(), key=lambda kv: kv[1][0])[0]
        self.store.pop(oldest_key, None)

    def get(self, key: str) -> Optional[Any]:
        rec = self.store.get(key)
        if not rec:
            return None
        ts, value = rec
        if time.time() - ts > self.ttl:
            self.store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self.store[key] = (time.time(), value)
        self._evict_if_needed()


# ✅ OPTIMIZED: LLM response cache for efficient call management
_llm_response_cache = TTLCache(max_items=100, ttl_seconds=300)  # 5 min cache for LLM responses

def _hash_messages(messages: List[BaseMessage]) -> str:
    """Create a hash key from message list for caching."""
    import hashlib
    # Create a simple hash from message contents
    content_parts = []
    for msg in messages:
        content = getattr(msg, "content", "")
        msg_type = msg.__class__.__name__
        content_parts.append(f"{msg_type}:{content[:200]}")  # Limit content length for hashing
    combined = "|".join(content_parts)
    return hashlib.md5(combined.encode()).hexdigest()

# Simple per-query tool router: restrict RAG unless content/context is requested
_TOOLS_BY_NAME = {getattr(t, "name", str(i)): t for i, t in enumerate(tools_list)}

def _select_tools_for_query(user_query: str):
    """Return tools exposed to the LLM for this query.

    Enhanced policy:
    - Always expose all available tools (mongo_query, rag_search, generate_content).
    - Let the LLM decide routing based on instructions; no keyword gating.
    - Add query analysis hints for complex join decisions.
    """
    allowed_names = ["mongo_query", "rag_search", "generate_content"]
    selected_tools = [tool for name, tool in _TOOLS_BY_NAME.items() if name in allowed_names]
    if not selected_tools and "mongo_query" in _TOOLS_BY_NAME:
        selected_tools = [_TOOLS_BY_NAME["mongo_query"]]
    return selected_tools, allowed_names

class AgentExecutor:
    """MongoDB Agent using Tool Calling with LLM-Controlled Execution
    
    Features:
    - LLM-controlled execution: The LLM decides whether tools should run in parallel
      or sequentially based on dependencies. When the LLM calls multiple tools together,
      they execute in parallel. When tools need sequential execution, the LLM will
      make separate calls.
    - Parallel execution: When the LLM calls multiple independent tools together,
      they execute concurrently using asyncio.gather() for improved performance.
    - Sequential execution: When tools have dependencies, the LLM naturally handles
      this by calling them in separate rounds.
    - Full tracing support: All tool executions (parallel or sequential) are properly traced
      with Phoenix/OpenTelemetry.
    - Conversation memory: Maintains context across multiple turns.
    
    Args:
        max_steps: Maximum number of reasoning steps (default: 8)
        system_prompt: Custom system prompt or None to use default
        enable_parallel_tools: Enable parallel tool execution (default: True)
    """

    def __init__(self, max_steps: int = 8, system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT, enable_parallel_tools: bool = True):
        # Base LLM; tools will be bound per-query via router
        self.llm_base = llm
        self.connected = False
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.tracing_enabled = False
        self.enable_parallel_tools = enable_parallel_tools
        conversation_cache_ttl = int(os.getenv("AGENT_CONVERSATION_CACHE_TTL", "300"))
        conversation_cache_size = int(os.getenv("AGENT_CONVERSATION_CACHE_SIZE", "256"))
        self._conversation_context_cache = TTLCache(
            max_items=conversation_cache_size,
            ttl_seconds=conversation_cache_ttl,
        )
        self._conversation_cache_tasks: Dict[str, asyncio.Task] = {}

    async def _get_conversation_context_cached(self, conversation_id: str) -> List[BaseMessage]:
        cached = self._conversation_context_cache.get(conversation_id)
        if cached is not None:
            return list(cached)
        context = await conversation_memory.get_recent_context(conversation_id)
        self._conversation_context_cache.set(conversation_id, list(context))
        return context

    def _append_conversation_cache(self, conversation_id: str, message: BaseMessage) -> None:
        cached = self._conversation_context_cache.get(conversation_id)
        if cached is None:
            return
        updated = list(cached)
        updated.append(message)
        self._conversation_context_cache.set(conversation_id, updated)

    def _schedule_conversation_cache_refresh(self, conversation_id: str) -> None:
        existing = self._conversation_cache_tasks.get(conversation_id)
        if existing and not existing.done():
            return

        async def _refresh():
            try:
                context = await conversation_memory.get_recent_context(conversation_id)
                self._conversation_context_cache.set(conversation_id, list(context))
            except Exception as exc:
                logger.error("Failed to refresh conversation cache for %s: %s", conversation_id, exc)
            finally:
                self._conversation_cache_tasks.pop(conversation_id, None)

        task = asyncio.create_task(_refresh())
        self._conversation_cache_tasks[conversation_id] = task

    async def _add_message_to_memory(self, conversation_id: str, message: BaseMessage) -> None:
        await conversation_memory.add_message(conversation_id, message)
        self._append_conversation_cache(conversation_id, message)
        self._schedule_conversation_cache_refresh(conversation_id)

    async def _execute_single_tool(
        self, 
        tool, 
        tool_call: Dict[str, Any], 
        selected_tools: List[Any],
        tracer=None
    ) -> tuple[ToolMessage, bool]:
        """Execute a single tool with tracing support.
        
        Returns:
            tuple: (ToolMessage, success_flag)
        """
        tool_cm = None
        tool_start_time = perf_counter()
        with contextlib.nullcontext() as tool_span:
            # Enforce router: only allow selected tools
            actual_tool = next((t for t in selected_tools if t.name == tool_call["name"]), None)
            if not actual_tool:
                error_msg = ToolMessage(
                    content=f"Tool '{tool_call['name']}' not found.",
                    tool_call_id=tool_call["id"],
                )
                return error_msg, False

            try:
                result = await actual_tool.ainvoke(tool_call["args"])
                success = True
            except Exception as tool_exc:
                result = f"Tool execution error: {tool_exc}"
                success = False

            tool_message = ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
            tool_elapsed_ms = (perf_counter() - tool_start_time) * 1000
            print(f"Tool '{tool_call['name']}' executed in {tool_elapsed_ms:.2f} ms")
            return tool_message, success

    async def connect(self):
        """Connect to MongoDB MCP server"""
        # Tracing initialization removed - method does not exist
        span = None
        try:
            await mongodb_tools.connect()
            self.connected = True
            if span:
                pass
        except Exception as e:
            if span:
                pass
            raise
        finally:
            pass

    async def disconnect(self):
        """Disconnect from MongoDB MCP server"""
        await mongodb_tools.disconnect()
        self.connected = False
        # Tracing removed: nothing to clean up
        pass


    async def run_streaming(self, query: str, websocket=None, conversation_id: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Run the agent with streaming support and conversation context"""
        if not self.connected:
            await self.connect()

        try:
            tracer = None
            if tracer is not None:
                span_cm = tracer.start_as_current_span(
                    "agent_run_streaming",
                    # kind=trace.SpanKind.INTERNAL,  # Tracing removed
                    attributes={
                        "query_preview": query[:80],
                        "query_length": len(query or ""),
                        "database.name": DATABASE_NAME,
                    },
                )
            else:
                span_cm = None

            with (span_cm if span_cm is not None else contextlib.nullcontext()):
                # Use default conversation ID if none provided
                if not conversation_id:
                    conversation_id = f"conv_{int(time.time())}"

                # Get conversation history (cached per session with async refresh)
                conversation_context = await conversation_memory.get_recent_context(conversation_id)

                # Build messages with optional system instruction
                messages: List[BaseMessage] = []
                if self.system_prompt:
                    messages.append(SystemMessage(content=self.system_prompt))

                messages.extend(conversation_context)

                # Add current user message
                human_message = HumanMessage(content=query)
                messages.append(human_message)

                callback_handler = AgentCallbackHandler(websocket, conversation_id)

                # Persist the human message
                await conversation_memory.add_message(conversation_id, human_message)

                steps = 0
                last_response: Optional[AIMessage] = None
                need_finalization: bool = False

                while steps < self.max_steps:
                    # Choose tools for this query iteration
                    selected_tools, allowed_names = _select_tools_for_query(query)
                    llm_with_tools = self.llm_base.bind_tools(selected_tools)
                    llm_cm = None

                    with (llm_cm if llm_cm is not None else contextlib.nullcontext()) as llm_span:
                        pass
                        routing_instructions = SystemMessage(content=(
                            "PLANNING & ROUTING:\n"
                            "- Break the user request into logical steps.\n"
                            "- For INDEPENDENT operations: Call multiple tools together.\n"
                            "- For DEPENDENT operations: Call tools separately (wait for results before next call).\n"
                            "- EXCEPTION: For 'generate_content' tool calls, always call them sequentially even if independent, to ensure each generated item appears individually in the chat.\n"
                            "- Examples of generate_content: 'Create 5 work items' → call generate_content 5 times sequentially, not in parallel\n\n"
                            "RESPONSE FORMATTING (CRITICAL):\n"
                            "- ALWAYS format your responses using **markdown** for maximum readability.\n"
                            "- Use headings (##, ###) to organize sections and break up content.\n"
                            "- Use **bold** for emphasis on key terms, numbers, and important concepts.\n"
                            "- Use code blocks (```language) for queries, code, or technical output.\n"
                            "- Use tables (| column |) when presenting structured data comparisons.\n"
                            "- Use horizontal rules (---) to separate distinct sections when appropriate.\n"
                            "- Use blockquotes (>) for important notes, warnings, or highlights.\n"
                            "- Keep paragraphs short (2-3 sentences max) for better scanning.\n\n"
                            "LIST FORMATTING (IMPORTANT):\n"
                            "- Use **unordered lists (-)** for collections, features, or items without hierarchy\n"
                            "- Use **numbered lists (1., 2., 3.)** for sequential steps, priorities, or ranked items\n"
                            "- Use **nested lists** for hierarchical information\n"
                            "- Keep list items concise and use **bold** for key terms\n\n"
                            "DECISION GUIDE:\n"
                            "1) Use 'mongo_query' for structured questions about entities/fields in collections: project, workItem, cycle, module, epic, members, page, projectState, userStory, features.\n"
                            "   - Examples: counts, lists, filters, sort, group by, breakdowns by assignee/state/project/priority/date.\n"
                            "   - Use for: 'count bugs by priority', 'list work items by assignee', 'group projects by business', 'show breakdown by state'.\n"
                            "   - The query planner automatically determines when complex joins are beneficial and adds strategic relationships only when they improve query performance.\n"
                            "   - Do NOT answer from memory; run a query.\n"
                            "2) Use 'rag_search' for content-based searches (semantic meaning, not just keywords).\n"
                            "   - Returns FULL chunk content for synthesis - analyze and format the actual content in your response.\n"
                            "   - Find pages/work items by meaning, analyze content patterns, search documentation.\n"
                            "   - Examples: 'find notes about OAuth', 'show API docs', 'content mentioning authentication', 'analyze patterns in descriptions'.\n"
                            "   - SMART CONTENT TYPE SELECTION: Choose appropriate content_type based on query semantics:\n"
                            "     • 'release', 'documentation', 'notes', 'wiki' keywords → content_type='page'\n"
                            "     • 'work items', 'bugs', 'tasks', 'issues' keywords → content_type='work_item'\n"
                            "     • 'cycle', 'sprint', 'iteration' keywords → content_type='cycle'\n"
                            "     • 'module', 'component' keywords → content_type='module'\n"
                            "     • 'epic', 'initiative' keywords → content_type='epic'\n"
                            "     • 'project' keyword → content_type='project'\n"
                            "     • 'user story', 'story' keywords → content_type='user_story'\n"
                            "     • 'features', 'feature', 'new feature' keywords → content_type='feature'\n"
                            "     • Unclear/multi-type query → content_type=None (all) OR multiple rag_search calls\n"
                            "3) Use 'generate_content' to CREATE new work items, pages, cycles, modules, or epics.\n"
                            "   - CRITICAL: Content sent DIRECTLY to frontend, returns only '✅ Content generated'.\n"
                            "   - Do NOT expect details - just acknowledge success to user.\n"
                            "   - Examples: 'create a bug report', 'generate documentation', 'draft meeting notes', 'create sprint', 'generate module'.\n"
                            "   - REQUIRED: content_type ('work_item'|'page'|'cycle'|'module'|'epic'), prompt.\n"
                            "   - OPTIONAL: template_title, template_content, context.\n"
                            "4) Use MULTIPLE tools together when question needs different operations.\n"
                            "   - Example: 'Show bug counts by priority (mongo_query) and find related documentation (rag_search)'.\n"
                            "   - Agent decides tool combination based on query complexity and dependencies.\n\n"
                            "TOOL CHEATSHEET:\n"
                            "- mongo_query(query:str, show_all:bool=False): Natural-language to Mongo aggregation. Safe fields only.\n"
                            "  REQUIRED: 'query' - natural language description of what MongoDB data you want.\n"
                            "- rag_search(query:str, content_type:str|None, group_by:str|None, limit:int=10, show_content:bool=True): Universal RAG search.\n"
                            "  REQUIRED: 'query' - semantic search terms.\n"
                            "  OPTIONAL: content_type ('page'|'work_item'|'project'|'cycle'|'module'|'epic'|'user_story'|'feature'|None), group_by (field), limit, show_content.\n"
                            "- generate_content(content_type:str, prompt:str, template_title:str='', template_content:str='', context:dict=None): Generate work items/pages/cycles/modules/epics.\n"
                            "  REQUIRED: content_type ('work_item'|'page'|'cycle'|'module'|'epic'), prompt.\n"
                            "  OPTIONAL: template_title, template_content, context.\n"
                            "  NOTE: Returns '✅ Content generated' only - content goes directly to frontend.\n\n"
                            "CONTENT TYPE EXAMPLES:\n"
                            "- 'What is next release about?' → rag_search(query='next release', content_type='page')\n"
                            "- 'Recent work items about auth?' → rag_search(query='recent work items auth', content_type='work_item')\n"
                            "- 'Active cycle details?' → rag_search(query='active cycle', content_type='cycle')\n"
                            "- 'CRM module overview?' → rag_search(query='CRM module', content_type='module')\n"
                            "- 'Epic roadmap for onboarding?' → rag_search(query='onboarding epic', content_type='epic')\n"
                            "- 'Create bug for login' → generate_content(content_type='work_item', prompt='Bug: login fails on mobile')\n"
                            "- 'Generate API docs' → generate_content(content_type='page', prompt='API documentation for auth')\n"
                            "- 'Create Q4 sprint' → generate_content(content_type='cycle', prompt='Q4 2024 Sprint')\n"
                            "- 'Generate auth module' → generate_content(content_type='module', prompt='Authentication Module')\n"
                            "- 'Draft onboarding epic' → generate_content(content_type='epic', prompt='Customer Onboarding Epic')\n\n"
                            "WHEN UNSURE WHICH TOOL:\n"
                            "- If the query is ambiguous or entity/field mapping to Mongo is unclear → prefer rag_search first.\n"
                            "- Question about structured data (counts, filters, group by, breakdown by assignee/state/priority/project/date) → mongo_query.\n"
                            "- Question about content meaning/semantics (find docs, analyze patterns, content search, descriptions) → rag_search.\n"
                            "- Request to CREATE/GENERATE content → generate_content.\n"
                            "- Question needs both structured + semantic analysis → use BOTH tools together.\n\n"
                            "IMPORTANT: Use valid args: mongo_query needs 'query'; rag_search needs 'query' (optional: content_type, group_by, limit, show_content); generate_content needs content_type + prompt."
                        ))
                        # Determine if this is a finalization turn BEFORE calling LLM
                        is_finalizing = need_finalization  # ✅ Save the state BEFORE modifying it

                        if need_finalization:
                            finalization_instructions = SystemMessage(content=(
                                "FINALIZATION: Write a concise answer in your own words based on the tool outputs above. "
                                "Do not paste tool outputs verbatim or include banners/emojis. "
                                "If the user asked to browse or see examples, summarize briefly and offer to expand. "
                                "For work items, present canonical fields succinctly."
                            ))
                            # Emit a natural action statement to indicate synthesis/finalization
                            try:
                                import random
                                synth_phrases = [
                                    "Putting together the findings into a clear answer",
                                    "Synthesizing the information I gathered",
                                    "Compiling the results into a comprehensive response",
                                    "Organizing the data into a coherent answer",
                                    "Bringing everything together for you"
                                ]
                                synth_action = random.choice(synth_phrases)
                                if callback_handler:
                                    # Emit synchronously for real-time delivery
                                    await callback_handler.emit_dynamic_action(synth_action)
                            except Exception:
                                pass
                            invoke_messages = messages + [routing_instructions, finalization_instructions]
                            need_finalization = False
                        else:
                            invoke_messages = messages + [routing_instructions]

                        # Only stream tokens during finalization, NOT during tool planning
                        # During tool planning, we'll emit action events instead
                        should_stream = is_finalizing  # ✅ Use the saved state
                        main_llm_start_time = perf_counter()
                        # ✅ OPTIMIZED: Check LLM response cache before making API call
                        cache_key = _hash_messages(invoke_messages)
                        cached_response = _llm_response_cache.get(cache_key)
                        
                        if cached_response and not should_stream:
                            # Use cached response for non-streaming calls (tool planning)
                            response = cached_response
                        else:
                            # Make LLM call
                            response = await llm_with_tools.ainvoke(
                                invoke_messages,
                                config={"callbacks": [callback_handler] if should_stream else []},
                            )
                            main_llm_elapsed_ms = (perf_counter() - main_llm_start_time) * 1000
                            log_msg_type = "Final Synthesis" if is_finalizing else "Tool Planning"
                            print(f"Main Agent LLM call ({log_msg_type}) took {main_llm_elapsed_ms:.2f} ms")
                            # Cache response for non-streaming calls (tool planning)
                            if not should_stream:
                                _llm_response_cache.set(cache_key, response)
                        if llm_span and getattr(response, "content", None):
                            try:
                                preview = str(response.content)[:500]
                                llm_span.set_attribute('output.value', preview)
                                llm_span.add_event("llm_response", {"preview_len": len(preview)})
                            except Exception:
                                pass
                    last_response = response

                    # Only persist assistant messages when there are NO tool calls (final response)
                    # Intermediate reasoning should not be saved as assistant messages
                    if not getattr(response, "tool_calls", None):
                        # This is a final response, save it
                        await conversation_memory.add_message(conversation_id, response)
                        try:
                            await save_assistant_message(conversation_id, getattr(response, "content", "") or "")
                        except Exception as e:
                            logger.error(f"Failed to save assistant message: {e}")
                        yield response.content
                        return
                    else:
                        # ✅ NEW: Keep intermediate response WITH reasoning in conversation history
                        # This helps LLM maintain context, but don't persist to DB (not shown to user)
                        await conversation_memory.add_message(conversation_id, response)
                        # Note: NOT calling save_assistant_message() - only actions are saved to DB

                    # Execute requested tools with streaming callbacks
                    # The LLM decides execution order by how it calls tools
                    clean_response = AIMessage(
                        content="",  # Clear content for clean message handling
                        tool_calls=response.tool_calls,  # Keep tool calls for execution
                    )
                    messages.append(clean_response)
                    did_any_tool = False
                    if len(response.tool_calls) > 1:
                        # ✅ EMIT ACTIONS FIRST - Before tool execution starts
                        for tool_call in response.tool_calls:
                            if callback_handler:
                                try:
                                    await callback_handler.on_tool_start(
                                        {"name": tool_call["name"]}, 
                                        str(tool_call.get("args", {}))
                                    )
                                except Exception:
                                    pass
                        
                        # NOW build and execute tool tasks in parallel
                        tool_tasks = [
                            self._execute_single_tool(None, tool_call, selected_tools, None)
                            for tool_call in response.tool_calls
                        ]
                        
                        tool_results = await asyncio.gather(*tool_tasks, return_exceptions=True)
                        
                        # Process results and send tool_end events
                        for i, result in enumerate(tool_results):
                            if isinstance(result, Exception):
                                # Handle exception from tool execution
                                error_msg = ToolMessage(
                                    content=f"Tool execution error: {result}",
                                    tool_call_id=response.tool_calls[i].get("id", ""),
                                )
                                if callback_handler:
                                    await callback_handler.on_tool_end(error_msg.content)
                                messages.append(error_msg)
                                await conversation_memory.add_message(conversation_id, error_msg)
                            else:
                                tool_message, success = result
                                if callback_handler:
                                    await callback_handler.on_tool_end(tool_message.content)
                                messages.append(tool_message)
                                await conversation_memory.add_message(conversation_id, tool_message)
                                if success:
                                    did_any_tool = True
                    else:
                        # Single tool execution - this part is already correct
                        for tool_call in response.tool_calls:
                            if callback_handler:
                                try:
                                    await callback_handler.on_tool_start(
                                        {"name": tool_call["name"]}, 
                                        str(tool_call.get("args", {}))
                                    )
                                except Exception:
                                    pass
                            
                            tool_message, success = await self._execute_single_tool(None, tool_call, selected_tools, None)
                            if callback_handler:
                                await callback_handler.on_tool_end(tool_message.content)
                            messages.append(tool_message)
                            await self._add_message_to_memory(conversation_id, tool_message)
                            if success:
                                did_any_tool = True
                    
                    steps += 1

                    # After executing any tools, force the next LLM turn to synthesize
                    if did_any_tool:
                        need_finalization = True

                # Step cap reached; send best available response
                if last_response is not None:
                    # Register turn and update summary if needed
                    await conversation_memory.register_turn(conversation_id)
                    if await conversation_memory.should_update_summary(conversation_id, every_n_turns=3):
                        try:
                            asyncio.create_task(
                                conversation_memory.update_summary_async(conversation_id, self.llm_base)
                            )
                        except Exception as e:
                            logger.error(f"Failed to update summary: {e}")
                    yield last_response.content
                else:
                    yield "Reached maximum reasoning steps without a final answer."
                return

        except Exception as e:
            yield f"Error running streaming agent: {str(e)}"

# ProjectManagement Insights Examples
async def main():
    """Example usage of the ProjectManagement Insights Agent"""
    agent = AgentExecutor()
    await agent.connect()
    await agent.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
