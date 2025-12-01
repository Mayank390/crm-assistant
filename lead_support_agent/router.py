"""
REST API Router for Lead Support Agent.

Contains all REST endpoints for lead-related AI support functionality.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
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

class LeadEnrichRequest(BaseModel):
    lead_id: str
    business_id: Optional[str] = None

class LeadEnrichResponse(BaseModel):
    lead_id: str
    enriched_data: Dict[str, Any]
    missing_fields: List[str]
    recommendations: List[str]
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


@router.post("/enrich", response_model=LeadEnrichResponse)
async def enrich_lead(req: LeadEnrichRequest):
    """Enrich a lead with inferred data from available sources.
    
    Analyzes existing lead data and returns enriched information including:
    - Inferred company details from related data
    - Enhanced contact information
    - Missing field suggestions
    - Data completeness analysis
    - Enrichment recommendations
    
    Note: This endpoint does NOT update the database - it only returns enriched data.
    """
    try:
        agent = await get_agent()
        _set_business_context(req.business_id)
        
        # Get comprehensive lead context and stats
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
        
        # Run the agent for enrichment analysis
        enrich_prompt = """Analyze this lead's available data and provide enrichment information in the following structured format:

## Enriched Data
Provide inferred or enhanced information that can be derived from the available data:
- Company details (name, industry, website, size) - infer from notes, emails, meetings
- Contact information (email, phone, social profiles) - extract from communications
- Job title and role - infer from context
- Location and address - extract from available data
- Budget and decision-making authority - infer from interactions
- Technology stack or tools used - extract from activities and notes
- Pain points and needs - summarize from notes and activities

## Missing Fields
List all important fields that are missing or incomplete:
- [Field 1] - why it's important
- [Field 2] - why it's important

## Recommendations
Provide actionable recommendations for enriching this lead:
1. [Recommendation 1 - specific action to take]
2. [Recommendation 2 - data source to check]
3. [Recommendation 3 - follow-up question to ask]

Format your response clearly with sections marked by ## headers. Be specific and reference actual data points from the lead context."""
        
        full_response = await agent.run(
            query=enrich_prompt,
            lead_id=req.lead_id,
            lead_context=f"{lead_context}\n\n{lead_stats}",
        )
        
        # Parse the response into structured format
        enriched_data: Dict[str, Any] = {}
        missing_fields: List[str] = []
        recommendations: List[str] = []
        
        current_section = None
        lines = full_response.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Detect sections
            if "## Enriched Data" in line or "**Enriched Data**" in line:
                current_section = "enriched"
                continue
            elif "## Missing Fields" in line or "**Missing Fields**" in line:
                current_section = "missing"
                continue
            elif "## Recommendations" in line or "**Recommendations**" in line:
                current_section = "recommendations"
                continue
            elif line.startswith("##") or line.startswith("**"):
                # New section, stop current parsing
                if current_section == "enriched":
                    # Store accumulated enriched data as text for now
                    if "enriched_text" not in enriched_data:
                        enriched_data["enriched_text"] = ""
                current_section = None
                continue
            
            # Parse content based on section
            if current_section == "enriched":
                # Accumulate enriched data
                if "enriched_text" not in enriched_data:
                    enriched_data["enriched_text"] = ""
                enriched_data["enriched_text"] += line + "\n"
            elif current_section == "missing":
                if line.startswith("-") or line.startswith("•") or line.startswith("*"):
                    field = line.lstrip("-•* ").strip()
                    if field:
                        missing_fields.append(field)
            elif current_section == "recommendations":
                if line.startswith(("-", "•", "*", "1", "2", "3", "4", "5")):
                    rec = line.lstrip("-•*0123456789.) ").strip()
                    if rec:
                        recommendations.append(rec)
        
        # Fallbacks if parsing didn't work well
        if not enriched_data:
            enriched_data = {"enriched_text": full_response[:1000]}
        if not missing_fields:
            missing_fields = ["Review lead data for missing information"]
        if not recommendations:
            recommendations = ["Review the lead context for enrichment opportunities"]
        
        return LeadEnrichResponse(
            lead_id=req.lead_id,
            enriched_data=enriched_data,
            missing_fields=missing_fields[:10],  # Limit to top 10
            recommendations=recommendations[:10],  # Limit to top 10
            generated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error enriching lead: {e}")
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


@router.get("/{lead_id}/enrich", response_model=LeadEnrichResponse)
async def get_lead_enrich_simple(lead_id: str, business_id: Optional[str] = None):
    """Simple GET endpoint for lead enrichment."""
    req = LeadEnrichRequest(lead_id=lead_id, business_id=business_id)
    return await enrich_lead(req)
