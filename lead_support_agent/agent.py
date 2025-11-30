"""
Lead Support Agent - A focused helper agent for lead-related support functionality.

This agent is smaller and more focused than the main CRM agent, specifically designed
for lead support tasks like summarization, next steps, comparisons, message drafting,
objection handling, meeting prep, and email composition.
"""

import asyncio
import logging
import os
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime

from langchain_groq import ChatGroq
from langchain_core.messages import (
    HumanMessage, 
    AIMessage, 
    ToolMessage, 
    BaseMessage, 
    SystemMessage
)
from dotenv import load_dotenv

from lead_support_agent.prompts import get_prompt_for_task, BASE_SYSTEM_PROMPT
from lead_support_agent.tools import tools as lead_tools
from lead_support_agent.callback_handler import LeadSupportCallbackHandler

load_dotenv()
logger = logging.getLogger(__name__)


class LeadSupportAgent:
    """
    Lead Support Agent - A focused agent for lead-related support tasks.
    
    Capabilities:
    - Summarize leads with all related context
    - Recommend next best steps based on lead data
    - Compare multiple leads side-by-side
    - Draft personalized messages and emails
    - Handle sales objections with context
    - Prepare for meetings with lead insights
    - Generate follow-up strategies
    
    This agent is designed to be:
    - Faster (fewer tools, focused context)
    - Simpler (single-purpose design)
    - Lead-centric (all tools relate to lead support)
    """

    def __init__(
        self,
        max_steps: int = 5,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ):
        """
        Initialize the Lead Support Agent.
        
        Args:
            max_steps: Maximum reasoning steps (default: 5, smaller than main agent)
            model: LLM model to use (defaults to env var or fast model)
            temperature: LLM temperature (slightly higher for creative tasks)
        """
        self.max_steps = max_steps
        self.model_name = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.temperature = temperature
        self.connected = False
        
        # Initialize LLM with tools bound
        self.llm = ChatGroq(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "2048")),
            streaming=True,
        )
        
        # Bind tools to LLM
        self.llm_with_tools = self.llm.bind_tools(lead_tools)
        
        # Tool lookup
        self._tools_by_name = {tool.name: tool for tool in lead_tools}

    async def connect(self):
        """Initialize connections (MongoDB, RAG, etc)."""
        if self.connected:
            return
        
        try:
            from mongo.constants import mongodb_tools
            await mongodb_tools.connect()
            self.connected = True
            logger.info("Lead Support Agent connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect Lead Support Agent: {e}")
            raise

    async def disconnect(self):
        """Cleanup connections."""
        self.connected = False

    def _build_messages(
        self,
        query: str,
        lead_context: Optional[str] = None,
        task_type: Optional[str] = None,
        conversation_history: Optional[List[BaseMessage]] = None
    ) -> List[BaseMessage]:
        """Build the message list for the LLM call."""
        messages: List[BaseMessage] = []
        
        # Add system prompt (task-specific if provided)
        if task_type:
            system_prompt = get_prompt_for_task(task_type)
        else:
            system_prompt = BASE_SYSTEM_PROMPT
        
        messages.append(SystemMessage(content=system_prompt))
        
        # Add lead context if provided
        if lead_context:
            context_message = f"""
## Lead Context (Pre-loaded)
{lead_context}

Use this context to answer the user's query. Do not fetch it again unless asked for different data.
"""
            messages.append(SystemMessage(content=context_message))
        
        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user query
        messages.append(HumanMessage(content=query))
        
        return messages

    async def _execute_tool(
        self,
        tool_call: Dict[str, Any]
    ) -> ToolMessage:
        """Execute a single tool call and return the result."""
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id", "")
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
        tool = self._tools_by_name.get(tool_name)
        if not tool:
            return ToolMessage(
                content=f"Tool '{tool_name}' not found.",
                tool_call_id=tool_id
            )
        
        try:
            result = await tool.ainvoke(tool_args)
            return ToolMessage(
                content=str(result) if result else "Tool returned no result",
                tool_call_id=tool_id
            )
        except Exception as e:
            logger.error(f"Tool execution error for {tool_name}: {e}")
            return ToolMessage(
                content=f"Tool execution error: {str(e)}",
                tool_call_id=tool_id
            )

    async def run(
        self,
        query: str,
        lead_id: Optional[str] = None,
        task_type: Optional[str] = None,
        lead_context: Optional[str] = None,
        conversation_history: Optional[List[BaseMessage]] = None,
    ) -> str:
        """
        Run the lead support agent synchronously (non-streaming).
        
        Args:
            query: User's question or request
            lead_id: Optional lead ID to focus on
            task_type: Optional task type for specialized prompt
            lead_context: Optional pre-loaded lead context
            conversation_history: Optional previous messages
        
        Returns:
            Agent's response as a string
        """
        if not self.connected:
            await self.connect()
        
        # If lead_id provided but no context, pre-fetch it
        if lead_id and not lead_context:
            try:
                from lead_support_agent.tools import get_lead_context
                lead_context = await get_lead_context.ainvoke({
                    "lead_id": lead_id,
                    "include_tasks": True,
                    "include_meetings": True,
                    "include_notes": True,
                    "include_activities": True,
                    "include_calls": True,
                    "include_emails": True,
                })
            except Exception as e:
                logger.warning(f"Could not pre-fetch lead context: {e}")
        
        messages = self._build_messages(query, lead_context, task_type, conversation_history)
        
        steps = 0
        last_response = None
        
        while steps < self.max_steps:
            response = await self.llm_with_tools.ainvoke(messages)
            last_response = response
            
            # Check if we have tool calls
            if not getattr(response, "tool_calls", None):
                # No tool calls, this is the final response
                return response.content
            
            # Execute tool calls
            messages.append(AIMessage(content="", tool_calls=response.tool_calls))
            
            for tool_call in response.tool_calls:
                tool_message = await self._execute_tool(tool_call)
                messages.append(tool_message)
            
            steps += 1
        
        # Max steps reached
        return last_response.content if last_response else "Max steps reached without response."

    async def run_streaming(
        self,
        query: str,
        websocket=None,
        lead_id: Optional[str] = None,
        task_type: Optional[str] = None,
        lead_context: Optional[str] = None,
        conversation_history: Optional[List[BaseMessage]] = None,
        session_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Run the lead support agent with streaming support.
        
        Args:
            query: User's question or request
            websocket: WebSocket connection for streaming
            lead_id: Optional lead ID to focus on
            task_type: Optional task type for specialized prompt
            lead_context: Optional pre-loaded lead context
            conversation_history: Optional previous messages
            session_id: Session identifier
            business_id: Business ID for filtering
        
        Yields:
            Tokens as they are generated
        """
        if not self.connected:
            await self.connect()
        
        # Set business context if provided
        if business_id:
            try:
                import websocket_handler
                websocket_handler.business_id_global = business_id
            except Exception:
                pass
        
        # Create callback handler
        callback_handler = LeadSupportCallbackHandler(websocket, session_id)
        
        # If lead_id provided but no context, pre-fetch it
        if lead_id and not lead_context:
            try:
                await callback_handler.emit_status("Loading lead context...")
                from lead_support_agent.tools import get_lead_context
                lead_context = await get_lead_context.ainvoke({
                    "lead_id": lead_id,
                    "include_tasks": True,
                    "include_meetings": True,
                    "include_notes": True,
                    "include_activities": True,
                    "include_calls": True,
                    "include_emails": True,
                })
            except Exception as e:
                logger.warning(f"Could not pre-fetch lead context: {e}")
        
        messages = self._build_messages(query, lead_context, task_type, conversation_history)
        
        steps = 0
        last_response = None
        need_synthesis = False
        
        while steps < self.max_steps:
            # Determine if we should stream
            should_stream = need_synthesis or steps == 0
            
            if need_synthesis:
                # Add synthesis instruction
                synthesis_msg = SystemMessage(content=(
                    "Synthesize the tool outputs into a clear, actionable response. "
                    "Format your response using markdown for readability. "
                    "Focus on providing value to the sales professional."
                ))
                invoke_messages = messages + [synthesis_msg]
            else:
                invoke_messages = messages
            
            # Call LLM
            response = await self.llm_with_tools.ainvoke(
                invoke_messages,
                config={"callbacks": [callback_handler] if should_stream else []}
            )
            last_response = response
            
            # Check if we have tool calls
            if not getattr(response, "tool_calls", None):
                # No tool calls, this is the final response
                yield response.content
                return
            
            # Execute tool calls
            messages.append(AIMessage(content="", tool_calls=response.tool_calls))
            
            # Execute tools (can be parallelized)
            if len(response.tool_calls) > 1:
                # Emit actions for all tools first
                for tool_call in response.tool_calls:
                    await callback_handler.on_tool_start(
                        {"name": tool_call["name"]},
                        str(tool_call.get("args", {}))
                    )
                
                # Execute in parallel
                tasks = [self._execute_tool(tc) for tc in response.tool_calls]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in results:
                    if isinstance(result, Exception):
                        messages.append(ToolMessage(
                            content=f"Error: {result}",
                            tool_call_id=""
                        ))
                    else:
                        messages.append(result)
            else:
                # Single tool execution
                for tool_call in response.tool_calls:
                    await callback_handler.on_tool_start(
                        {"name": tool_call["name"]},
                        str(tool_call.get("args", {}))
                    )
                    tool_message = await self._execute_tool(tool_call)
                    messages.append(tool_message)
            
            need_synthesis = True
            steps += 1
        
        # Max steps reached
        yield last_response.content if last_response else "Max steps reached."

    async def summarize_lead(
        self,
        lead_id: str,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to summarize a specific lead."""
        async for chunk in self.run_streaming(
            query="Provide a comprehensive summary of this lead.",
            lead_id=lead_id,
            task_type="summarize",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk

    async def get_next_steps(
        self,
        lead_id: str,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to get next best steps for a lead."""
        async for chunk in self.run_streaming(
            query="What are the recommended next best steps for this lead?",
            lead_id=lead_id,
            task_type="next_steps",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk

    async def compare_leads_handler(
        self,
        lead_ids: List[str],
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to compare multiple leads."""
        query = f"Compare these leads and recommend which to prioritize: {', '.join(lead_ids)}"
        async for chunk in self.run_streaming(
            query=query,
            task_type="compare",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk

    async def draft_message(
        self,
        lead_id: str,
        message_type: str = "email",
        context: Optional[str] = None,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to draft a message for a lead."""
        query = f"Draft a {message_type} for this lead"
        if context:
            query += f". Context: {context}"
        
        async for chunk in self.run_streaming(
            query=query,
            lead_id=lead_id,
            task_type="draft_message" if message_type != "email" else "email_compose",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk

    async def handle_objection(
        self,
        lead_id: str,
        objection: str,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to handle a sales objection."""
        query = f"Help me respond to this objection from the lead: '{objection}'"
        async for chunk in self.run_streaming(
            query=query,
            lead_id=lead_id,
            task_type="objection_handling",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk

    async def prepare_meeting(
        self,
        lead_id: str,
        meeting_context: Optional[str] = None,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to prepare for a meeting with a lead."""
        query = "Prepare me for a meeting with this lead"
        if meeting_context:
            query += f". Meeting context: {meeting_context}"
        
        async for chunk in self.run_streaming(
            query=query,
            lead_id=lead_id,
            task_type="meeting_prep",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk
