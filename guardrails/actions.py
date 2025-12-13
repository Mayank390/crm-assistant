"""
NeMo Guardrails Actions for Prompt Injection Detection

Custom actions that integrate Llama Guard via Groq to detect and block
attempts to extract internal agent details or perform prompt injection.
"""

from nemoguardrails.actions import action
from typing import Optional, List
from guardrails.llama_gaurd_client import llama_guard_client, get_blocked_response


@action(is_system=True)
async def call_llama_guard_4(context: dict, user_message: str) -> bool:
    """
    Check if user message is attempting prompt injection or internal extraction.
    
    Uses Llama Guard to detect attempts to:
    - Extract system prompts or instructions
    - Reveal internal implementation details
    - Get raw/unprocessed responses
    - Bypass safety guidelines (jailbreaks)
    
    Args:
        context: NeMo Guardrails context containing conversation events.
        user_message: The current user message to validate.
        
    Returns:
        bool: True if message is safe, False if prompt injection detected.
    """
    # Extract conversation history from NeMo context
    events = context.get("events", [])
    conversation_history = _format_events_to_history(events)
    
    # Check for prompt injection attempts
    response = await llama_guard_client.check_prompt_injection(
        user_message=user_message,
        conversation_history=conversation_history
    )
    
    # Store blocked response in context if unsafe
    if not response.is_safe:
        # This can be used by the dialog flow to provide the blocked response
        context["_blocked_response"] = response.blocked_reason
        context["_blocked_category"] = response.category
    
    return response.is_safe


@action(is_system=True)
async def get_safety_blocked_response(context: dict) -> str:
    """
    Get the appropriate blocked response when unsafe content is detected.
    
    This is called by the dialog flow to get a user-friendly response
    that doesn't reveal internal details.
    
    Args:
        context: NeMo Guardrails context.
        
    Returns:
        str: User-friendly blocked response.
    """
    category = context.get("_blocked_category")
    return get_blocked_response(category)


def _format_events_to_history(events: List[dict]) -> List[dict]:
    """
    Convert NeMo Guardrails events to conversation history format.
    
    Args:
        events: List of NeMo event dictionaries.
        
    Returns:
        List of dicts with 'role' and 'content' keys.
    """
    history = []
    
    for event in events:
        event_type = event.get("type", "")
        text = event.get("text", "")
        
        if event_type == "UserMessage" and text:
            history.append({"role": "user", "content": text})
        elif event_type == "BotMessage" and text:
            history.append({"role": "assistant", "content": text})
    
    return history