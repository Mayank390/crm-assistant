"""
Lead Support Agent - A focused helper agent for lead-related support functionality.

This agent provides specialized support for:
- Lead summarization
- Next best steps recommendations
- Lead comparison
- Message drafting
- Objection handling
- Meeting prep
- Email composition

It operates as a smaller, focused agent within the larger CRM system.
"""

from lead_support_agent.agent import LeadSupportAgent
from lead_support_agent.router import router as lead_support_router

__all__ = ["LeadSupportAgent", "lead_support_router"]
