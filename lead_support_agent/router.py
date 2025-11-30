"""
REST API Router for Lead Support Agent.

Contains all REST endpoints for lead-related AI support functionality.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(
    prefix="/lead-support",
    tags=["Lead Support Agent"],
)

# ============================================================================
# Request/Response Models
# ============================================================================

class LeadSummaryRequest(BaseModel):
    lead_id: str
    business_id: Optional[str] = None

class LeadSummaryResponse(BaseModel):
    lead_id: str
    summary: str
    generated_at: str

class LeadInsightsRequest(BaseModel):
    lead_id: str
    business_id: Optional[str] = None

class LeadInsightsResponse(BaseModel):
    lead_id: str
    overview: str
    key_insights: List[str]
    engagement_score: Optional[str] = None
    recommended_actions: List[str]
    risk_factors: List[str]
    generated_at: str

class LeadNextStepsRequest(BaseModel):
    lead_id: str
    business_id: Optional[str] = None

class LeadNextStepsResponse(BaseModel):
    lead_id: str
    next_steps: str
    generated_at: str

class LeadCompareRequest(BaseModel):
    lead_ids: List[str]
    business_id: Optional[str] = None

class LeadCompareResponse(BaseModel):
    lead_ids: List[str]
    comparison: str
    generated_at: str

class DraftMessageRequest(BaseModel):
    lead_id: str
    message_type: Optional[str] = "email"  # email, sms, follow_up
    context: Optional[str] = None
    business_id: Optional[str] = None

class DraftMessageResponse(BaseModel):
    lead_id: str
    message_type: str
    draft: str
    generated_at: str

class ObjectionHandlingRequest(BaseModel):
    lead_id: str
    objection: str
    business_id: Optional[str] = None

class ObjectionHandlingResponse(BaseModel):
    lead_id: str
    objection: str
    response: str
    generated_at: str

class MeetingPrepRequest(BaseModel):
    lead_id: str
    meeting_context: Optional[str] = None
    business_id: Optional[str] = None

class MeetingPrepResponse(BaseModel):
    lead_id: str
    prep_document: str
    generated_at: str


# ============================================================================
# Agent Instance Management
# ============================================================================

_lead_support_agent = None

async def get_agent():
    """Get or create the lead support agent instance."""
    global _lead_support_agent
    if _lead_support_agent is None:
        from lead_support_agent.agent import LeadSupportAgent
        _lead_support_agent = LeadSupportAgent()
        await _lead_support_agent.connect()
    return _lead_support_agent

def set_agent(agent):
    """Set the lead support agent instance (called from main.py lifespan)."""
    global _lead_support_agent
    _lead_support_agent = agent

def _set_business_context(business_id: Optional[str]):
    """Set business context for filtering."""
    if business_id:
        try:
            import websocket_handler
            websocket_handler.business_id_global = business_id
        except Exception:
            pass


# ============================================================================
# REST API Endpoints
# ============================================================================

@router.post("/summary", response_model=LeadSummaryResponse)
async def get_lead_ai_summary(req: LeadSummaryRequest):
    """Get an AI-generated summary of a lead.
    
    Provides a comprehensive summary including:
    - Lead profile overview
    - Current status and stage
    - Recent interactions and history
    - Key opportunities and concerns
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        summary = await agent.run(
            query="Provide a comprehensive summary of this lead including profile, status, recent interactions, and key opportunities.",
            lead_id=req.lead_id,
            task_type="summarize",
        )
        
        return LeadSummaryResponse(
            lead_id=req.lead_id,
            summary=summary,
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error generating lead summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insights", response_model=LeadInsightsResponse)
async def get_lead_ai_insights(req: LeadInsightsRequest):
    """Get AI-generated insights about a lead.
    
    Provides detailed insights including:
    - Lead overview
    - Key insights and patterns
    - Engagement score assessment
    - Recommended actions
    - Risk factors to watch
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        # Get lead context first for structured insights
        from lead_support_agent.tools import get_lead_context, get_lead_stats
        
        lead_context = await get_lead_context.ainvoke({
            "lead_id": req.lead_id,
            "include_tasks": True,
            "include_meetings": True,
            "include_notes": True,
            "include_activities": True,
            "include_calls": True,
            "include_emails": True,
        })
        
        lead_stats = await get_lead_stats.ainvoke({"lead_id": req.lead_id})
        
        # Run the agent for insights analysis
        insights_prompt = """Analyze this lead and provide structured insights in the following format:

## Overview
[2-3 sentence overview of the lead]

## Key Insights
- [Insight 1]
- [Insight 2]
- [Insight 3]

## Engagement Assessment
[Assessment of engagement level: High/Medium/Low with brief explanation]

## Recommended Actions
1. [Action 1]
2. [Action 2]
3. [Action 3]

## Risk Factors
- [Risk 1 if any]
- [Risk 2 if any]

Be specific and actionable based on the lead data provided."""
        
        full_response = await agent.run(
            query=insights_prompt,
            lead_id=req.lead_id,
            lead_context=f"{lead_context}\n\n{lead_stats}",
        )
        
        # Parse the response into structured format
        overview = ""
        key_insights = []
        engagement_score = None
        recommended_actions = []
        risk_factors = []
        
        current_section = None
        lines = full_response.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Detect sections
            if "## Overview" in line or "**Overview**" in line:
                current_section = "overview"
                continue
            elif "## Key Insights" in line or "**Key Insights**" in line:
                current_section = "insights"
                continue
            elif "## Engagement" in line or "**Engagement**" in line:
                current_section = "engagement"
                continue
            elif "## Recommended Actions" in line or "**Recommended Actions**" in line:
                current_section = "actions"
                continue
            elif "## Risk Factors" in line or "**Risk Factors**" in line:
                current_section = "risks"
                continue
            elif line.startswith("##") or line.startswith("**"):
                current_section = None
                continue
            
            # Parse content based on section
            if current_section == "overview":
                overview += line + " "
            elif current_section == "insights":
                if line.startswith("-") or line.startswith("•"):
                    key_insights.append(line.lstrip("-•* ").strip())
            elif current_section == "engagement":
                if not engagement_score:
                    engagement_score = line
            elif current_section == "actions":
                if line.startswith(("-", "•", "1", "2", "3", "4", "5")):
                    action = line.lstrip("-•*0123456789.) ").strip()
                    if action:
                        recommended_actions.append(action)
            elif current_section == "risks":
                if line.startswith("-") or line.startswith("•"):
                    risk = line.lstrip("-•* ").strip()
                    if risk and risk.lower() not in ["none", "n/a", "no significant risks"]:
                        risk_factors.append(risk)
        
        # Fallbacks if parsing didn't work well
        if not overview:
            overview = full_response[:500]
        if not key_insights:
            key_insights = ["See full analysis above"]
        if not recommended_actions:
            recommended_actions = ["Review lead details for specific actions"]
        
        return LeadInsightsResponse(
            lead_id=req.lead_id,
            overview=overview.strip(),
            key_insights=key_insights[:5],
            engagement_score=engagement_score,
            recommended_actions=recommended_actions[:5],
            risk_factors=risk_factors[:3],
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error generating lead insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/next-steps", response_model=LeadNextStepsResponse)
async def get_lead_next_steps(req: LeadNextStepsRequest):
    """Get AI-recommended next best steps for a lead.
    
    Provides prioritized action recommendations:
    - Immediate actions (within 24 hours)
    - Short-term actions (this week)
    - Follow-up strategy
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        next_steps = await agent.run(
            query="What are the recommended next best steps for this lead?",
            lead_id=req.lead_id,
            task_type="next_steps",
        )
        
        return LeadNextStepsResponse(
            lead_id=req.lead_id,
            next_steps=next_steps,
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error generating next steps: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare", response_model=LeadCompareResponse)
async def compare_leads_api(req: LeadCompareRequest):
    """Compare multiple leads side-by-side with AI analysis.
    
    Compares leads across:
    - Qualification metrics
    - Engagement levels
    - Potential value
    - Recommended prioritization
    """
    try:
        if len(req.lead_ids) < 2:
            raise HTTPException(status_code=400, detail="At least 2 lead_ids required for comparison")
        
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        # Use the compare tool directly and then analyze
        from lead_support_agent.tools import compare_leads
        comparison_data = await compare_leads.ainvoke({"lead_ids": req.lead_ids})
        
        # Get AI analysis of the comparison
        analysis = await agent.run(
            query=f"Based on this comparison data, provide a clear recommendation on which lead(s) to prioritize and why:\n\n{comparison_data}",
            task_type="compare",
        )
        
        return LeadCompareResponse(
            lead_ids=req.lead_ids,
            comparison=f"{comparison_data}\n\n## AI Recommendation\n{analysis}",
            generated_at=datetime.utcnow().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/draft-message", response_model=DraftMessageResponse)
async def draft_lead_message(req: DraftMessageRequest):
    """Draft a personalized message for a lead.
    
    Supports different message types:
    - email: Professional email
    - sms: Short text message
    - follow_up: Follow-up message
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        query = f"Draft a {req.message_type} for this lead"
        if req.context:
            query += f". Context: {req.context}"
        
        task_type = "email_compose" if req.message_type == "email" else "draft_message"
        
        draft = await agent.run(
            query=query,
            lead_id=req.lead_id,
            task_type=task_type,
        )
        
        return DraftMessageResponse(
            lead_id=req.lead_id,
            message_type=req.message_type,
            draft=draft,
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error drafting message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/objection", response_model=ObjectionHandlingResponse)
async def handle_lead_objection(req: ObjectionHandlingRequest):
    """Get AI-powered response to a sales objection.
    
    Provides structured objection handling:
    - Acknowledgment
    - Clarification questions
    - Response points
    - Evidence/proof points
    - Redirect to next steps
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        response = await agent.run(
            query=f"Help me respond to this objection from the lead: '{req.objection}'",
            lead_id=req.lead_id,
            task_type="objection_handling",
        )
        
        return ObjectionHandlingResponse(
            lead_id=req.lead_id,
            objection=req.objection,
            response=response,
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error handling objection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/meeting-prep", response_model=MeetingPrepResponse)
async def prepare_lead_meeting(req: MeetingPrepRequest):
    """Get AI-generated meeting preparation document.
    
    Includes:
    - Lead context summary
    - Conversation history
    - Agenda suggestions
    - Talking points
    - Potential objections
    - Meeting goals
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        query = "Prepare me for a meeting with this lead"
        if req.meeting_context:
            query += f". Meeting context: {req.meeting_context}"
        
        prep_document = await agent.run(
            query=query,
            lead_id=req.lead_id,
            task_type="meeting_prep",
        )
        
        return MeetingPrepResponse(
            lead_id=req.lead_id,
            prep_document=prep_document,
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error preparing meeting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Simple GET Endpoints (for quick access)
# ============================================================================

@router.get("/{lead_id}/summary", response_model=LeadSummaryResponse)
async def get_lead_summary_simple(lead_id: str, business_id: Optional[str] = None):
    """Simple GET endpoint for lead AI summary."""
    req = LeadSummaryRequest(lead_id=lead_id, business_id=business_id)
    return await get_lead_ai_summary(req)


@router.get("/{lead_id}/insights", response_model=LeadInsightsResponse)
async def get_lead_insights_simple(lead_id: str, business_id: Optional[str] = None):
    """Simple GET endpoint for lead AI insights."""
    req = LeadInsightsRequest(lead_id=lead_id, business_id=business_id)
    return await get_lead_ai_insights(req)


@router.get("/{lead_id}/next-steps", response_model=LeadNextStepsResponse)
async def get_lead_next_steps_simple(lead_id: str, business_id: Optional[str] = None):
    """Simple GET endpoint for lead next steps."""
    req = LeadNextStepsRequest(lead_id=lead_id, business_id=business_id)
    return await get_lead_next_steps(req)
