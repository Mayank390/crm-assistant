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
        
        # Initialize LLM with streaming enabled
        self.llm = ChatGroq(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "4096")),
            streaming=True,
        )
        
        # LLM with tools bound (for tool calling)
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
        if lead_context and "Lead not found" not in lead_context and "Error" not in lead_context:
            context_message = f"""
## Lead Context (Pre-loaded Data)

The following lead information has been gathered for you. Use this data to provide your response.
DO NOT call any tools to fetch this data again - it is already provided below.

---
{lead_context}
---

IMPORTANT INSTRUCTIONS:
1. Use the lead context above to provide a detailed, actionable response
2. Reference specific details from the lead's profile, history, and activities
3. DO NOT call the get_lead_context tool - the context is already provided above
4. Be specific and mention actual names, dates, and details from the context
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
                logger.info(f"Pre-fetching lead context for lead_id: {lead_id}")
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
                logger.info(f"Pre-fetched lead context: {len(lead_context) if lead_context else 0} chars")
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
                logger.info(f"Pre-fetching lead context for streaming, lead_id: {lead_id}")
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
                logger.info(f"Pre-fetched lead context ({len(lead_context) if lead_context else 0} chars)")
                
                # Check if lead was found
                if lead_context and "Lead not found" in lead_context:
                    await callback_handler.emit_status(f"⚠️ {lead_context}")
                    # Still continue - the agent can work with limited info
            except Exception as e:
                logger.warning(f"Could not pre-fetch lead context: {e}")
                await callback_handler.emit_status(f"Warning: Could not load lead context: {e}")
        
        messages = self._build_messages(query, lead_context, task_type, conversation_history)
        
        steps = 0
        accumulated_content = ""
        
        while steps < self.max_steps:
            logger.info(f"Streaming step {steps + 1}/{self.max_steps}")
            
            # Call LLM with tools to see if we need tool calls
            response = await self.llm_with_tools.ainvoke(messages)
            
            # Check if we have tool calls
            if getattr(response, "tool_calls", None) and response.tool_calls:
                logger.info(f"Tool calls requested: {[tc.get('name') for tc in response.tool_calls]}")
                
                # Execute tool calls
                messages.append(AIMessage(content=response.content or "", tool_calls=response.tool_calls))
                
                for tool_call in response.tool_calls:
                    # Emit tool action
                    await callback_handler.on_tool_start(
                        {"name": tool_call.get("name", "unknown")},
                        str(tool_call.get("args", {}))
                    )
                    
                    # Execute the tool
                    tool_message = await self._execute_tool(tool_call)
                    messages.append(tool_message)
                    
                    await callback_handler.on_tool_end(tool_message.content)
                
                steps += 1
                continue
            
            # No tool calls - this is the final response, stream it
            logger.info("No tool calls - streaming final response")
            
            # Add synthesis instruction for better output
            synthesis_instruction = SystemMessage(content=(
                "Now provide your final response based on all the information gathered. "
                "Be comprehensive, specific, and actionable. "
                "Format your response using markdown:\n"
                "- Use **bold** for key points\n"
                "- Use bullet points and numbered lists\n"
                "- Use headers (##, ###) for sections\n"
                "- Reference specific details from the lead context"
            ))
            
            final_messages = messages + [synthesis_instruction]
            
            # Send llm_start event
            await callback_handler.on_llm_start()
            
            try:
                # Stream the response
                logger.info("Starting to stream response...")
                async for chunk in self.llm.astream(final_messages):
                    token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    if token:
                        accumulated_content += token
                        await callback_handler.on_llm_new_token(token)
                
                logger.info(f"Streaming complete. Total tokens: {len(accumulated_content)}")
                
                # Send llm_end event
                await callback_handler.on_llm_end()
                
                yield accumulated_content
                return
                
            except Exception as e:
                logger.error(f"Streaming error: {e}", exc_info=True)
                
                # Fallback to non-streaming response
                if response.content:
                    await callback_handler.on_llm_new_token(response.content)
                    await callback_handler.on_llm_end()
                    yield response.content
                else:
                    error_msg = f"I encountered an error while generating the response: {str(e)}"
                    await callback_handler.on_llm_new_token(error_msg)
                    await callback_handler.on_llm_end()
                    yield error_msg
                return
        
        # Max steps reached
        max_steps_msg = "I've reached the maximum number of reasoning steps. Please try a more specific question."
        await callback_handler.on_llm_new_token(max_steps_msg)
        await callback_handler.on_llm_end()
        yield max_steps_msg

    async def summarize_lead(
        self,
        lead_id: str,
        websocket=None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Convenience method to summarize a specific lead."""
        query = """Provide a comprehensive summary of this lead including:
1. Lead profile (name, company, contact info)
2. Current status and lead score
3. Recent interactions and engagement
4. Key opportunities and next steps
5. Any concerns or blockers to address"""
        
        async for chunk in self.run_streaming(
            query=query,
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
        query = """Based on this lead's current status, history, and engagement patterns, provide:
1. Immediate actions (next 24 hours)
2. Short-term actions (this week)
3. Follow-up strategy (next 2-4 weeks)
Prioritize by urgency and potential impact."""
        
        async for chunk in self.run_streaming(
            query=query,
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
        query = f"""Compare these leads side-by-side and provide:
1. A comparison table with key metrics
2. Analysis of strengths and weaknesses for each
3. Clear prioritization recommendation
Lead IDs to compare: {', '.join(lead_ids)}"""
        
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
        query = f"""Draft a professional {message_type} for this lead that:
1. Opens with a personalized hook based on their profile
2. Provides clear value proposition
3. Includes a specific call-to-action
4. Maintains appropriate tone"""
        
        if context:
            query += f"\n\nAdditional context: {context}"
        
        async for chunk in self.run_streaming(
            query=query,
            lead_id=lead_id,
            task_type="email_compose" if message_type == "email" else "draft_message",
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
        query = f"""Help me respond to this objection from the lead:

"{objection}"

Provide:
1. Acknowledgment of their concern
2. Thoughtful response addressing the objection
3. Supporting evidence or examples
4. Way to redirect the conversation positively
5. Suggested follow-up"""
        
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
        query = """Prepare me for a meeting with this lead. Include:
1. Lead context summary
2. Key talking points
3. Questions to ask
4. Anticipated objections and responses
5. Meeting goals and desired next steps"""
        
        if meeting_context:
            query += f"\n\nMeeting context: {meeting_context}"
        
        async for chunk in self.run_streaming(
            query=query,
            lead_id=lead_id,
            task_type="meeting_prep",
            websocket=websocket,
            business_id=business_id,
        ):
            yield chunk
