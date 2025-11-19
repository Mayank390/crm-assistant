
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from mongo.registry import REL, ALLOWED_FIELDS
from mongo.constants import mongodb_tools, DATABASE_NAME
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from agent.planner import QueryIntent
 
from langchain_groq import ChatGroq
# Orchestration utilities
class LLMIntentParser:
    """LLM-backed intent parser that produces a structured plan compatible with QueryIntent.

    The LLM proposes:
    - primary_entity
    - target_entities (relations to join)
    - filters (normalized keys: status, priority, leadStatus, taskStatus, meetingStatus, noteStatus)
    - aggregations: ["count"|"group"|"summary"]
    - group_by tokens: ["leadStatus","taskStatus","meetingStatus","assignedName","priority","lead"]
    - projections (subset of allow-listed fields for the primary entity)
    - sort_order (field -> 1|-1), supported keys: createdTimeStamp, priority, status
    - limit (int)
    - wants_details, wants_count

    Safety: we filter LLM output against REL and ALLOWED_FIELDS before use.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.environ.get("QUERY_PLANNER_MODEL", "openai/gpt-oss-120b")
        # Keep the model reasonably deterministic for planning
        self.llm = ChatGroq(
            model=self.model_name,
            temperature=0,
            max_tokens=1024,
            top_p=0.8,
        )

        # Precompute compact schema context to keep prompts short
        self.entities: List[str] = list(REL.keys())
        self.entity_relations: Dict[str, List[str]] = {
            entity: list(REL.get(entity, {}).keys()) for entity in self.entities
        }
        self.allowed_fields: Dict[str, List[str]] = {
            entity: sorted(list(ALLOWED_FIELDS.get(entity, set()))) for entity in self.entities
        }
        # Map common synonyms to canonical entity names to reduce LLM mistakes
        self.entity_synonyms = {
            "lead": "Lead",
            "leads": "Lead",
            "prospect": "Lead",
            "prospects": "Lead",
            "customer": "Lead",
            "customers": "Lead",
            "contact": "Lead",
            "contacts": "Lead",
            "task": "task",
            "tasks": "task",
            "todo": "task",
            "todos": "task",
            "activity": "activity",
            "activities": "activity",
            "meeting": "meeting",
            "meetings": "meeting",
            "call": "meeting",
            "calls": "meeting",
            "note": "notes",
            "notes": "notes",
            "calllog": "callLog",
            "callLog": "callLog",
            "call_log": "callLog",
            "call_logs": "callLog",
            "mail": "mailInfo",
            "mailinfo": "mailInfo",
            "email": "mailInfo",
            "emails": "mailInfo",
            "segmentation": "segmentation",
            "segmentations": "segmentation",
            "segment": "segmentation",
            "segments": "segmentation",
            "leadscorerule": "leadScoreRule",
            "scorerule": "leadScoreRule",
            "scoring": "leadScoreRule",
            "score rule": "leadScoreRule",
            "lead score": "leadScoreRule",
            "leadscore": "leadScoreRule",
        }

    def _is_placeholder(self, v) -> bool:
        if v is None:
            return True
        if not isinstance(v, str):
            return False
        s = v.strip().lower()
        return (
            s == "" or
            "?" in s or
            s.startswith("string") or
            s in {"none?", "todo?", "n/a", "<none>", "<unknown>"}
        )


    def _normalize_priority_value(self, value: str) -> Optional[str]:
        """Normalize priority values to match database enum (TASK_PRIORITY: NEW, HIGH, MEDIUM, LOW)"""
        priority_map = {
            "new": "NEW",
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW"
        }
        return priority_map.get(value.lower())

    def _normalize_lead_status_value(self, value: str) -> Optional[str]:
        """Normalize lead status values to match LEAD_STATUS enum"""
        status_map = {
            "new": "NEW",
            "contacted": "CONTACTED",
            "qualified": "QUALIFIED",
            "engaged": "ENGAGED",
            "proposal": "PROPOSAL",
            "negotiation": "NEGOTIATION",
            "won": "WON",
            "lost": "LOST",
            "unqualified": "UNQUALIFIED",
            "follow_up": "FOLLOW_UP",
            "follow-up": "FOLLOW_UP",
            "follow up": "FOLLOW_UP",
            "call_back_request": "CALL_BACK_REQUEST",
            "call-back-request": "CALL_BACK_REQUEST",
            "call back request": "CALL_BACK_REQUEST",
            "not_interested": "NOT_INTERESTED",
            "not-interested": "NOT_INTERESTED",
            "not interested": "NOT_INTERESTED",
            "interested": "INTERESTED",
            "registered": "REGISTERED"
        }
        return status_map.get(value.lower())

    def _normalize_task_status_value(self, value: str) -> Optional[str]:
        """Normalize task status values to match TASK_STATUS enum"""
        status_map = {
            "new": "NEW",
            "not_started": "NOT_STARTED",
            "not-started": "NOT_STARTED",
            "not started": "NOT_STARTED",
            "in_progress": "IN_PROGRESS",
            "in-progress": "IN_PROGRESS",
            "inprogress": "IN_PROGRESS",
            "in progress": "IN_PROGRESS",
            "completed": "COMPLETED",
            "waiting_for_input": "WAITING_FOR_INPUT",
            "waiting-for-input": "WAITING_FOR_INPUT",
            "waiting for input": "WAITING_FOR_INPUT",
            "cancelled": "CANCELLED",
            "canceled": "CANCELLED"
        }
        return status_map.get(value.lower())

    def _normalize_meeting_status_value(self, value: str) -> Optional[str]:
        """Normalize meeting status values to match MEETING_STATUS enum"""
        status_map = {
            "new": "NEW",
            "scheduled": "SCHEDULED",
            "in_progress": "IN_PROGRESS",
            "in-progress": "IN_PROGRESS",
            "inprogress": "IN_PROGRESS",
            "in progress": "IN_PROGRESS",
            "completed": "COMPLETED",
            "cancelled": "CANCELLED",
            "canceled": "CANCELLED",
            "rescheduled": "RESCHEDULED"
        }
        return status_map.get(value.lower())

    def _normalize_call_status_value(self, value: str) -> Optional[str]:
        """Normalize call status values to match CALL_STATUS enum"""
        status_map = {
            "new": "NEW",
            "answered": "ANSWERED",
            "no_response": "NO_RESPONSE",
            "no-response": "NO_RESPONSE",
            "no response": "NO_RESPONSE",
            "do_not_call": "DO_NOT_CALL",
            "do-not-call": "DO_NOT_CALL",
            "do not call": "DO_NOT_CALL",
            "failed": "FAILED",
            "missed_call": "MISSED_CALL",
            "missed-call": "MISSED_CALL",
            "missed call": "MISSED_CALL",
            "completed": "COMPLETED",
            "scheduled": "SCHEDULED",
            "not_answered": "NOT_ANSWERED",
            "not-answered": "NOT_ANSWERED",
            "not answered": "NOT_ANSWERED"
        }
        return status_map.get(value.lower())

    def _normalize_activity_status_value(self, value: str) -> Optional[str]:
        """Normalize activity status values to match ACTIVITY_STATUS enum"""
        status_map = {
            "open": "OPEN",
            "close": "CLOSE",
            "closed": "CLOSE",
            "cancelled": "CANCELLED",
            "canceled": "CANCELLED"
        }
        return status_map.get(value.lower())

    def _normalize_meeting_type_value(self, value: str) -> Optional[str]:
        """Normalize meeting type values to match MEETING_TYPE enum"""
        type_map = {
            "physical": "PHYSICAL",
            "virtual": "VIRTUAL",
            "in_person": "PHYSICAL",
            "in-person": "PHYSICAL",
            "in person": "PHYSICAL"
        }
        return type_map.get(value.lower())

    def _normalize_call_type_value(self, value: str) -> Optional[str]:
        """Normalize call type values to match CALL_TYPE enum"""
        type_map = {
            "in_bound": "IN_BOUND",
            "in-bound": "IN_BOUND",
            "inbound": "IN_BOUND",
            "in bound": "IN_BOUND",
            "out_bound": "OUT_BOUND",
            "out-bound": "OUT_BOUND",
            "outbound": "OUT_BOUND",
            "out bound": "OUT_BOUND"
        }
        return type_map.get(value.lower())

    def _normalize_mail_type_value(self, value: str) -> Optional[str]:
        """Normalize mail type values to match MailType enum"""
        type_map = {
            "send": "SEND",
            "scheduled": "SCHEDULED",
            "drafts": "DRAFTS",
            "draft": "DRAFTS"
        }
        return type_map.get(value.lower())


    def _normalize_boolean_value(self, value: str) -> Optional[bool]:
        """Normalize string booleans to actual booleans"""
        if value.lower() in ["true", "1", "yes", "on"]:
            return True
        elif value.lower() in ["false", "0", "no", "off"]:
            return False
        return None

    def _normalize_boolean_value_from_any(self, value) -> Optional[bool]:
        """Normalize any type of value to boolean"""
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            return self._normalize_boolean_value(value)
        return None

    def _infer_sort_order_from_query(self, query_text: str) -> Optional[Dict[str, int]]:
        """Infer sorting preferences from free-form query text.

        Recognizes phrases like:
        - 'recent', 'latest', 'newest' → createdTimeStamp desc (-1)
        - 'oldest', 'earliest' → createdTimeStamp asc (1)
        - 'top N priority' → priority desc (-1)
        - 'highest priority' → priority desc (-1)
        - 'top N' with time context → createdTimeStamp desc (-1)
        """
        if not query_text:
            return None

        text = query_text.lower()

        # Priority-based sorting cues (highest priority first)
        if re.search(r'\b(?:top|highest|most|high)\s+\d*\s*priority\b', text):
            return {"priority": -1}
        if re.search(r'\bpriority\s+(?:top|highest|desc|descending)\b', text):
            return {"priority": -1}
        if re.search(r'\b(?:lowest|low)\s+priority\b', text):
            return {"priority": 1}
            
        # Direct recency/age cues
        if re.search(r"\b(recent|latest|newest|most\s+recent|newer\s+first)\b", text):
            return {"createdTimeStamp": -1}
        if re.search(r"\b(oldest|earliest|older\s+first)\b", text):
            return {"createdTimeStamp": 1}
            
        # "Top N" without explicit field → assume recent (most common use case)
        if re.search(r'\btop\s+\d+\b', text) and not re.search(r'\bpriority\b', text):
            return {"createdTimeStamp": -1}

        # Asc/Desc cues when paired with time/date/created terms
        mentions_time = re.search(r"\b(time|date|created|creation|timestamp|recent)\b", text) is not None
        if mentions_time:
            if re.search(r"\b(desc|descending|new\s*->\s*old|new\s+to\s+old)\b", text):
                return {"createdTimeStamp": -1}
            if re.search(r"\b(asc|ascending|old\s*->\s*new|old\s+to\s+new)\b", text):
                return {"createdTimeStamp": 1}

        return None

    def _infer_pagination_from_query(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Infer pagination preferences from free-form query text.

        Recognizes phrases like:
        - 'page 2', 'second page' → skip based on assumed page size
        - 'skip 10', 'offset 10' → skip: 10
        - 'next page' → skip increment (context-aware)
        - 'results 21-40' → skip: 20, limit: 20
        """
        if not query_text:
            return None

        text = query_text.lower()

        # Page-based pagination
        page_match = re.search(r'\b(?:page|pg)\s+(\d+)\b', text)
        if page_match:
            page_num = int(page_match.group(1))
            if page_num > 1:
                # Assume standard page size of 50 for page-based queries
                return {"skip": (page_num - 1) * 50, "limit": 50}

        # Direct skip/offset
        skip_match = re.search(r'\b(?:skip|offset)(?:\s+(?:the\s+)?(?:first\s+)?)?(\d+)\b', text)
        if skip_match:
            skip_value = int(skip_match.group(1))
            return {"skip": skip_value}

        # Range-based pagination (e.g., "results 21-40", "show 11 to 20")
        range_match = re.search(r'\b(?:results?|show)\s+(\d+)\s*(?:to|-)\s*(\d+)\b', text)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > 0 and end > start:
                return {"skip": start - 1, "limit": end - start + 1}

        # Next page (context-aware - assumes previous query had limit)
        if re.search(r'\bnext\s+page\b', text):
            # This would need context from previous queries, but for now we'll use a reasonable default
            return {"skip": 50, "limit": 50}  # Assume previous page was 0-50

        # Previous page
        if re.search(r'\bprevious\s+page\b|\blast\s+page\b', text):
            # For previous page, we'd need to track state, but for now return default
            return {"skip": 0, "limit": 50}

        return None


    async def parse(self, query: str) -> Optional[QueryIntent]:
        """Use the LLM to produce a structured intent. Returns None on failure."""
        system = (
            "You are an expert MongoDB query planner for a CRM System.\n"
            "Your task is to convert natural language queries into structured JSON intent objects.\n\n"

            "## DOMAIN CONTEXT\n"
            "This is a CRM (Customer Relationship Management) system with these main entities:\n"
            f"- {', '.join(self.entities)}\n\n"
            "Users ask questions about leads, customer interactions, and sales activities.\n"
            "Focus on understanding their intent about customer management, not exact keywords.\n\n"

            "## KEY RELATIONSHIPS\n"
            "- Leads are the central entity - they represent potential customers and their journey\n"
            "- Tasks track work items and follow-ups for leads (via leadId)\n"
            "- Activities log all customer interactions and engagement activities\n"
            "- Meetings schedule customer appointments and sales calls\n"
            "- Notes capture important information and conversation details for leads\n"
            "- CallLogs record phone conversations and call outcomes\n"
            "- MailInfo stores email communications and marketing campaigns\n"
            "- LeadScoreRule defines automated scoring criteria for lead qualification\n\n"

            "## VERY IMPORTANT\n"
            "## AVAILABLE FILTERS (use these exact keys):\n"
            "- leadStatus: NEW|CONTACTED|QUALIFIED|ENGAGED|PROPOSAL|NEGOTIATION|WON|LOST|UNQUALIFIED|FOLLOW_UP|CALL_BACK_REQUEST|NOT_INTERESTED|INTERESTED|REGISTERED (for Lead)\n"
            "- taskStatus: NEW|NOT_STARTED|IN_PROGRESS|COMPLETED|WAITING_FOR_INPUT|CANCELLED (for Task)\n"
            "- meetingStatus: NEW|SCHEDULED|IN_PROGRESS|COMPLETED|CANCELLED|RESCHEDULED (for Meeting)\n"
            "- activityStatus: OPEN|CLOSE|CANCELLED (for Activity)\n"
            "- callStatus: NEW|ANSWERED|NO_RESPONSE|DO_NOT_CALL|FAILED|MISSED_CALL|COMPLETED|SCHEDULED|NOT_ANSWERED (for CallLog)\n"
            "- priority: NEW|HIGH|MEDIUM|LOW (for Task)\n"
            "- status: (generic status field - use specific status fields when available)\n"
            "- assignedTo, assignedName: (assigned person)\n"
            "- createdById, createdByName: (creator)\n"
            "- leadId, leadName: (related lead)\n"
            "- personalInfo.name, personalInfo.email, personalInfo.mobile: (lead contact info)\n"
            "- score: (lead score - numeric)\n"
            "- emailCount, callCount: (activity counts for leads)\n"
            "- meetingType: PHYSICAL|VIRTUAL (for Meeting)\n"
            "- callType: IN_BOUND|OUT_BOUND (for CallLog)\n"
            "- mailType: SEND|SCHEDULED|DRAFTS (for MailInfo)\n"
            "- source: WEBSITE|COLD_CALL|REFERRAL|OTHER (for Lead - optional field)\n"
            "- type: LEAD|CUSTOMER (for Lead - optional field)\n"
            "- leadActiveType: ACTIVE|INACTIVE (for Lead - optional field)\n"
            "- customerType: INDIVIDUAL|BUSINESS (for Lead - optional field)\n"
            "- notes: (text search in lead notes - optional field)\n"
            "- staffId, staffName: (staff member assigned to lead - optional field)\n"
            "- description: (text search in task/meeting/callLog descriptions - optional field)\n"
            "- assignToMailId: (email address for task assignment - optional field)\n"
            "- notify: EMAIL|SMS|NONE (for Task - optional field)\n"
            "- reminderDays: (numeric - days until reminder for Task - optional field)\n"
            "- callDuration: (numeric or string - duration of call in CallLog - optional field, can be empty)\n"
            "- otherReason: (text search in CallLog - optional field, can be empty string)\n"
            "- meetingLink: (meeting URL/link - optional field, can be empty)\n"
            "- meetingLocated: (meeting location - optional field, can be empty)\n"
            "- remainder: (numeric - remainder count for Meeting/CallLog - optional field)\n"
            "- participantsRemainder: (numeric - participants remainder for Meeting - optional field)\n"
            "- taskId: (related task ID for Notes - optional field)\n"
            "NOTE: Optional fields may not always be present in documents. Handle empty/missing values gracefully.\n\n"
            "## ARRAY SIZE FILTERING (CRITICAL - MANDATORY DETECTION)\n"
            "YOU MUST ALWAYS DETECT array field quantity patterns and add the appropriate _count filter.\n"
            "This is NOT optional - if the user mentions array field quantities, you MUST add the filter.\n\n"
            "PATTERNS TO DETECT (MANDATORY):\n"
            "- 'multiple X' / 'more than one X' → MUST add: X_count: \">1\"\n"
            "- 'more than N X' → MUST add: X_count: \">N\" (where N is the number)\n"
            "- 'at least N X' → MUST add: X_count: \">=N\"\n"
            "- 'exactly N X' / 'N X' (when referring to count) → MUST add: X_count: \"N\"\n"
            "- 'no X' / 'unassigned' / 'without X' → MUST add: X_count: \"0\"\n"
            "- 'with X' / 'has X' (when X is an array field) → MUST add: X_count: \">=1\"\n\n"
            "ARRAY FIELD MAPPINGS (USE THESE EXACT KEYS):\n"
            "- fieldData → fieldData_count (for Lead)\n"
            "- participantsList → participantsList_count (for Meeting)\n"
            "- notesAttachments → notesAttachments_count (for Notes)\n"
            "- attachments → attachments_count (for MailInfo)\n"
            "- toMails → toMails_count (for MailInfo)\n"
            "- toCcMails → toCcMails_count (for MailInfo)\n"
            "- toBccMails → toBccMails_count (for MailInfo)\n"
            "- emailData → emailData_count (for Meeting)\n\n"
            "## TIME-SERIES ANALYSIS\n"
            "Support for time-based analytical operations:\n"
            "- 'sliding window of 7 days' → $setWindowFields for moving averages\n"
            "- 'rolling average over 30 days' → time window aggregations\n"
            "- 'trend analysis for last quarter' → period-over-period comparisons\n"
            "- 'anomaly detection in leads/tasks' → statistical outlier detection\n"
            "- 'time series forecasting' → trend projection and prediction\n"
            "- Express temporal analysis queries with sliding windows and trends\n"

            "## TIME-BASED SORTING (CRITICAL)\n"
            "Infer sort_order from phrasing when the user implies recency or age.\n"
            "- 'recent', 'latest', 'newest', 'most recent' → {\"createdTimeStamp\": -1}\n"
            "- 'oldest', 'earliest', 'older first' → {\"createdTimeStamp\": 1}\n"
            "- If 'ascending/descending' is mentioned with created/time/date/timestamp, map to 1/-1 respectively on 'createdTimeStamp'.\n"
            "- For CRM: 'recent leads' = most recently created leads\n"
            "- For CRM: 'oldest calls' = earliest call logs\n"
            "Only include sort_order when relevant; otherwise set it to null.\n\n"

            "## LIMIT EXTRACTION (CRITICAL)\n"
            "Extract the result limit intelligently from the user's query:\n"
            "- 'top N' / 'first N' / 'N items' → limit: N (e.g., 'top 5' → limit: 5)\n"
            "- 'all' / 'every' / 'list all' → limit: 1000 (high limit to get all results)\n"
            "- 'a few' / 'some' → limit: 5\n"
            "- 'several' → limit: 50\n"
            "- 'one' / 'single' / 'find X' (singular) → limit: 1, fetch_one: true\n"
            "- No specific mention → limit: 50 (reasonable default)\n"
            "- For count/aggregation queries → limit: null (no limit needed)\n"
            "IMPORTANT: When 'top N' is used, also infer appropriate sorting:\n"
            "  - 'top N' with score context → sort_order: {\"score\": -1}\n"
            "  - 'top N' with date/recent context → sort_order: {\"createdTimeStamp\": -1}\n"
            "  - 'top N' with activity context → sort_order: {\"emailCount\": -1} or {\"callCount\": -1}\n\n"

            "## PAGINATION CONTROL (IMPORTANT)\n"
            "This system supports full pagination control with skip and limit:\n"
            "- limit: Controls how many results to return (default: 50, max: 1000)\n"
            "- skip: Controls how many results to skip (for pagination, default: 0)\n"
            "- Use skip and limit together for proper pagination: skip = (page_number - 1) * limit\n"
            "\n"
            "PAGINATION EXTRACTION RULES:\n"
            "- 'page 2', 'second page', 'next page' → skip: previous_limit, limit: previous_limit\n"
            "- 'skip 10', 'offset 10' → skip: 10\n"
            "- 'show 20 results' → limit: 20\n"
            "- 'show results 21-40' → skip: 20, limit: 20\n"
            "- Default behavior: skip: 0, limit: 50\n"
            "- For large datasets: Consider using pagination hints in responses\n"
            "\n"
            "PAGINATION EXAMPLES:\n"
            "- 'show me page 2 of leads' → skip: 50, limit: 50 (assuming page 1 was limit: 50)\n"
            "- 'skip the first 100 tasks' → skip: 100, limit: 50\n"
            "- 'show next 25 meetings' → skip: previous_skip + previous_limit, limit: 25\n\n"

            "## SYSTEM CAPABILITIES\n"
            "This CRM system supports:\n"
            "- Filtering, sorting, and aggregation\n"
            "- Pagination with skip/limit for large result sets\n"
            "- Multi-entity joins and complex queries\n"
            "- Time-series analysis and forecasting\n"
            "\n"
            "PAGINATION WORKS WITH ALL QUERY TYPES:\n"
            "- List queries: Use skip/limit for browsing large datasets\n"
            "- Count queries: Usually don't need pagination (limit: null)\n"
            "- Grouped queries: Pagination applied after grouping\n"
            "- Detail queries: Pagination ensures manageable response sizes\n"
            "\n"
            "When users mention 'page', 'next', 'previous', or 'skip', always set appropriate skip and limit values.\n\n"

            "## NAME EXTRACTION RULES - CRITICAL\n"
            "ALWAYS extract ONLY the core entity name, NEVER include descriptive phrases:\n"
            "- Query: 'tasks for John Smith lead' → leadName: 'John Smith' (NOT 'John Smith lead')\n"
            "- Query: 'meetings with TechCorp customer' → leadName: 'TechCorp' (NOT 'TechCorp customer')\n"
            "- Query: 'activities assigned to alice' → assignedName: 'alice' (NOT 'alice assigned')\n"
            "- Query: 'calls for qualified leads' → leadStatus: 'QUALIFIED' (NOT status filter)\n"
            "❌ WRONG: {'leadName': 'ABC Corp lead'} - this breaks regex matching!\n"
            "✅ CORRECT: {'leadName': 'ABC Corp'} - this works with regex matching\n\n"

            "## COMPOUND FILTER PARSING\n"
            "When users write queries like 'leads where leadStatus = WON':\n"
            "- 'leadStatus = WON' should map to leadStatus: 'WON' for Lead entities\n"
            "- 'taskStatus = COMPLETED' should map to taskStatus: 'COMPLETED' for Task entities\n"
            "- 'activityStatus = CLOSE' should map to activityStatus: 'CLOSE' for Activity entities\n"
            "- 'meetingStatus.scheduled = true' should map to meetingStatus: 'SCHEDULED' for Meeting entities\n"
            "- Parse 'entity.field = value' patterns and map to appropriate filter keys\n\n"

            "## COMMON QUERY PATTERNS\n"
            "- 'Show me X' → list/get details (aggregations: [])\n"
            "- 'How many X' → count (aggregations: ['count'])\n"
            "- 'Breakdown by X' → group results (aggregations: ['group'])\n"
            "- 'X assigned to Y' → filter by assignee name (Y = assignedName)\n"
            "- 'X from/in/belonging to/associated with Y' → filter by lead name (Y = leadName)\n"
            "- 'X in Y status' → filter by status/leadStatus/taskStatus/etc\n"
            "- 'leads with name containing Z' → filter by personalInfo.name field (Z = search term)\n"
            "- 'leads with email Z' → filter by personalInfo.email field (Z = exact email)\n"
            "- 'find leads containing X in notes' → {\"primary_entity\": \"Lead\", \"filters\": {\"notes\": \"X\"}, \"aggregations\": []}\n"
            "- 'search for Y in lead names' → {\"primary_entity\": \"Lead\", \"filters\": {\"personalInfo.name\": \"Y\"}, \"aggregations\": []}\n"
            "- 'IMPORTANT: For \"containing\" queries, extract ONLY the search term, not the full phrase'\n"
            "- 'Y lead' → if asking about tasks: Task with leadName filter\n"
            "  → Context matters: 'details of Y lead' vs 'tasks for Y lead'\n"
            "- 'leads that are active/currently active' → Lead with leadActiveType: 'ACTIVE'\n"
            "- 'active leads' → Lead with leadActiveType: 'ACTIVE'\n"
            "- 'what is the email address for lead X' → Lead with name filter and personalInfo.email projection\n"
            "- 'lead X' → Lead entity with name filter\n"
            "- 'customer X' → Lead entity with name filter\n"
            "- 'leads updated in the last 30 days' → {\"primary_entity\": \"Lead\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}}\n"
            "- 'tasks created since last week' → {\"primary_entity\": \"Task\", \"filters\": {\"createdTimeStamp_from\": \"last_week\"}}\n"
            "- 'meetings scheduled after 2024-01-01' → {\"primary_entity\": \"Meeting\", \"filters\": {\"createdTimeStamp_from\": \"2024-01-01\"}}\n"
            "- 'Lead.last_date >= current_date - 30 days' → {\"primary_entity\": \"Lead\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}}\n\n"
            
            "## NEGATIVE FILTERS (CRITICAL)\n"
            "When users use negative language (not, without, haven't, hasn't, excluding, don't have, etc.), use the _not suffix:\n"
            "- Format: Use `field_not: [value]` or `field_not: [value1, value2]` for multiple exclusions\n"
            "- 'leads who have not purchased' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"WON\"]}}\n"
            "- 'leads who haven't purchased' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"WON\"]}}\n"
            "- 'leads without contact' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"CONTACTED\"]}}\n"
            "- 'leads who did not convert' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"WON\"]}}\n"
            "- 'tasks not completed' → {\"primary_entity\": \"Task\", \"filters\": {\"taskStatus_not\": [\"COMPLETED\"]}}\n"
            "- 'tasks without assignee' → {\"primary_entity\": \"Task\", \"filters\": {\"assignedTo_not\": [null]}}\n"
            "- 'meetings not scheduled' → {\"primary_entity\": \"Meeting\", \"filters\": {\"meetingStatus_not\": [\"SCHEDULED\"]}}\n"
            "- 'activities not closed' → {\"primary_entity\": \"Activity\", \"filters\": {\"activityStatus_not\": [\"CLOSE\"]}}\n"
            "- 'call logs not answered' → {\"primary_entity\": \"CallLog\", \"filters\": {\"callStatus_not\": [\"ANSWERED\"]}}\n"
            "- 'leads excluding won and lost' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"WON\", \"LOST\"]}}\n"
            "- Pattern: For any status field, 'not X' → `{statusField}_not: [\"X\"]`\n"
            "- Pattern: 'X without Y' → `{field}_not: [\"Y\"]`\n"
            "- Pattern: 'X excluding Y' → `{field}_not: [\"Y\"]`\n\n"
            
            "## DATE/TIME RANGE FILTERS (ALL UNITS)\n"
            "Support all time units: days (d), weeks (w), months (m), years (y)\n"
            "- Format: `{dateField}_from: \"now-N{unit}\"` where unit is d/w/m/y\n"
            "- 'leads from the last 6 months' → {\"primary_entity\": \"Lead\", \"filters\": {\"updatedTimeStamp_from\": \"now-6m\"}}\n"
            "- 'leads created in the last 3 months' → {\"primary_entity\": \"Lead\", \"filters\": {\"createdTimeStamp_from\": \"now-3m\"}}\n"
            "- 'tasks from the past 2 weeks' → {\"primary_entity\": \"Task\", \"filters\": {\"createdTimeStamp_from\": \"now-2w\"}}\n"
            "- 'meetings in the last year' → {\"primary_entity\": \"Meeting\", \"filters\": {\"updatedTimeStamp_from\": \"now-1y\"}}\n"
            "- 'leads updated in the last 30 days' → {\"primary_entity\": \"Lead\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}}\n"
            "- 'activities from the past week' → {\"primary_entity\": \"Activity\", \"filters\": {\"createdTimeStamp_from\": \"now-1w\"}}\n"
            "- Pattern: 'last N {days|weeks|months|years}' → `updatedTimeStamp_from: \"now-N{unit}\"`\n"
            "- Pattern: 'past N {days|weeks|months|years}' → `createdTimeStamp_from: \"now-N{unit}\"`\n"
            "- Pattern: 'in the last N {unit}' → `updatedTimeStamp_from: \"now-N{unit}\"`\n\n"
            
            "## COMPLEX FILTER COMBINATIONS\n"
            "You can combine multiple filters together:\n"
            "- 'leads not won in the last 6 months' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus_not\": [\"WON\"], \"updatedTimeStamp_from\": \"now-6m\"}}\n"
            "- 'tasks not completed in the past week' → {\"primary_entity\": \"Task\", \"filters\": {\"taskStatus_not\": [\"COMPLETED\"], \"createdTimeStamp_from\": \"now-1w\"}}\n"
            "- 'meetings not scheduled assigned to John' → {\"primary_entity\": \"Meeting\", \"filters\": {\"meetingStatus_not\": [\"SCHEDULED\"], \"assignedName\": \"John\"}}\n\n"
            
            "## OUTPUT FORMAT\n"
            "CRITICAL: Output ONLY the JSON object, nothing else.\n"
            "CRITICAL: The response must be parseable by json.loads().\n\n"
            "EXACT JSON structure:\n"
            "{\n"
            f'  "primary_entity": "",\n'  # Use a valid default
            '  "target_entities": [],\n'
            '  "filters": {},\n'
            '  "aggregations": [],\n'
            '  "group_by": [],\n'
            '  "projections": [],\n'
            '  "sort_order": null,\n'
            '  "limit": 50,\n'
            '  "skip": 0,\n'
            '  "wants_details": true,\n'
            '  "wants_count": false,\n'
            '  "fetch_one": false,\n'
            '  "window_field": null,\n'
            '  "window_size": null,\n'
            '  "window_unit": null,\n'
            '  "trend_field": null,\n'
            '  "trend_period": null,\n'
            '  "trend_metric": null,\n'
            '  "anomaly_field": null,\n'
            '  "anomaly_metric": null,\n'
            '  "anomaly_threshold": null,\n'
            '  "forecast_field": null,\n'
            '  "forecast_periods": null\n'
            "}\n\n"

            "## EXAMPLES\n"
            "- 'show me tasks for john' → {\"primary_entity\": \"Task\", \"filters\": {\"leadName\": \"john\"}, \"aggregations\": []}\n"
            "- 'how many leads are there' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"count\"]}\n"
            "- 'count active leads' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadActiveType\": \"ACTIVE\"}, \"aggregations\": [\"count\"]}\n"
            "- 'group leads by status' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"group\"], \"group_by\": [\"leadStatus\"]}\n"
            "- 'show qualified leads' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus\": \"QUALIFIED\"}, \"aggregations\": []}\n"
            "- 'find leads with high score' → {\"primary_entity\": \"Lead\", \"filters\": {\"score\": {\"$gte\": 80}}, \"aggregations\": []}\n"
            "- 'find leads with name containing john' → {\"primary_entity\": \"Lead\", \"filters\": {\"personalInfo.name\": \"john\"}, \"aggregations\": []}\n"
            "- 'who is assigned to this lead' → {\"primary_entity\": \"Lead\", \"filters\": {\"staffName\": \"assigned_person\"}, \"aggregations\": []}\n"
            "- 'find active meetings' → {\"primary_entity\": \"Meeting\", \"filters\": {\"meetingStatus\": \"SCHEDULED\"}, \"aggregations\": []}\n"
            "- 'show completed meetings' → {\"primary_entity\": \"Meeting\", \"filters\": {\"meetingStatus\": \"COMPLETED\"}, \"aggregations\": []}\n"
            "- 'count closed activities' → {\"primary_entity\": \"Activity\", \"filters\": {\"activityStatus\": \"CLOSE\"}, \"aggregations\": [\"count\"]}\n"
            "- 'what is the email address for lead John' → {\"primary_entity\": \"Lead\", \"filters\": {\"personalInfo.name\": \"John\"}, \"projections\": [\"personalInfo.email\"], \"aggregations\": []}\n"
            "- 'show activities for ABC Corp' → {\"primary_entity\": \"Activity\", \"filters\": {\"leadName\": \"ABC Corp\"}, \"aggregations\": []}\n\n"
            "- 'show recent leads' → {\"primary_entity\": \"Lead\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": -1}}\n"
            "- 'list oldest tasks' → {\"primary_entity\": \"Task\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": 1}}\n"
            "- 'calls in ascending created order' → {\"primary_entity\": \"CallLog\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": 1}}\n"
            "- 'leads updated in the last 30 days' → {\"primary_entity\": \"Lead\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}, \"aggregations\": []}\n"
            "- 'tasks created since yesterday' → {\"primary_entity\": \"Task\", \"filters\": {\"createdTimeStamp_from\": \"yesterday\"}, \"aggregations\": []}\n"
            "- 'meetings from the last week' → {\"primary_entity\": \"Meeting\", \"filters\": {\"createdTimeStamp_from\": \"last_week\"}, \"aggregations\": []}\n"
            "- 'top 5 scoring leads' → {\"primary_entity\": \"Lead\", \"aggregations\": [], \"sort_order\": {\"score\": -1}, \"limit\": 5}\n"
            "- 'first 10 meetings' → {\"primary_entity\": \"Meeting\", \"aggregations\": [], \"limit\": 10}\n"
            "- 'all active leads' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadActiveType\": \"ACTIVE\"}, \"aggregations\": [], \"limit\": 1000}\n"
            "- 'show me a few qualified leads' → {\"primary_entity\": \"Lead\", \"filters\": {\"leadStatus\": \"QUALIFIED\"}, \"aggregations\": [], \"limit\": 5}\n"
            "- 'find one lead named John' → {\"primary_entity\": \"Lead\", \"filters\": {\"personalInfo.name\": \"John\"}, \"aggregations\": [], \"limit\": 1, \"fetch_one\": true}\n"
            "- 'show leads with contact info' → {\"primary_entity\": \"Lead\", \"projections\": [\"personalInfo.name\", \"personalInfo.email\", \"personalInfo.mobile\"], \"aggregations\": []}\n"
            "- 'show activity history for leads' → {\"primary_entity\": \"Lead\", \"projections\": [\"personalInfo.name\", \"emailCount\", \"callCount\"], \"aggregations\": []}\n\n"
            "## ARRAY SIZE EXAMPLES (MUST FOLLOW THESE PATTERNS)\n"
            "- 'how many meetings have multiple participants?' → {\"primary_entity\": \"Meeting\", \"filters\": {\"participantsList_count\": \">1\"}, \"aggregations\": [\"count\"]}\n"
            "- 'show meetings with more than 2 participants' → {\"primary_entity\": \"Meeting\", \"filters\": {\"participantsList_count\": \">2\"}, \"aggregations\": []}\n"
            "- 'leads with at least 2 email communications' → {\"primary_entity\": \"Lead\", \"filters\": {\"emailCount\": \">=2\"}, \"aggregations\": []}\n"
            "- 'find leads with exactly 3 calls' → {\"primary_entity\": \"Lead\", \"filters\": {\"callCount\": \"3\"}, \"aggregations\": []}\n"
            "- 'unassigned tasks' → {\"primary_entity\": \"Task\", \"filters\": {\"assignedTo\": null}, \"aggregations\": []}\n"
            "- 'tasks with no assignee' → {\"primary_entity\": \"Task\", \"filters\": {\"assignedTo\": null}, \"aggregations\": []}\n"
            "- 'leads with email addresses' → {\"primary_entity\": \"Lead\", \"filters\": {\"personalInfo.email\": {\"$ne\": null}}, \"aggregations\": []}\n"
            "- 'meetings with 2 participants' → {\"primary_entity\": \"Meeting\", \"filters\": {\"participantsList_count\": \"2\"}, \"aggregations\": []}\n"
            "- 'find notes with attachments' → {\"primary_entity\": \"Notes\", \"filters\": {\"notesAttachments_count\": \">=1\"}, \"aggregations\": []}\n"
            "- 'emails with multiple recipients' → {\"primary_entity\": \"MailInfo\", \"filters\": {\"toMails_count\": \">1\"}, \"aggregations\": []}\n"
            "- 'count emails with multiple recipients' → {\"primary_entity\": \"MailInfo\", \"filters\": {\"toMails_count\": \">1\"}, \"aggregations\": [\"count\"]}\n"
            "- 'epics with at least 3 custom properties' → {\"primary_entity\": \"epic\", \"filters\": {\"customProperties_count\": \">=3\"}, \"aggregations\": []}\n\n"
            "CRITICAL: When you see phrases like 'multiple', 'more than', 'at least', 'exactly', 'no', 'unassigned', 'with X', 'has X' combined with array field names (assignees, labels, dependencies, etc.), you MUST add the corresponding _count filter.\n\n"
            "## ADVANCED OPERATOR EXAMPLES (MUST FOLLOW THESE PATTERNS)\n"
            "- Query: 'meetings with participants matching role Manager'\n"
            "  → filters: {\"participantsList_elemMatch\": {\"role\": \"Manager\"}}\n"
            "- Query: 'meetings with participants matching name John and department Sales'\n"
            "  → filters: {\"participantsList_elemMatch\": {\"name\": \"John\", \"department\": \"Sales\"}}\n\n"
            "CRITICAL: When users mention 'matching X', 'participants matching', etc., you MUST add the appropriate $elemMatch filter.\n\n"
            "## TIME-SERIES EXAMPLES\n"
            "- '7-day rolling average of leads' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"timeWindow\"], \"window_field\": \"createdTimeStamp\", \"window_size\": \"7d\", \"window_unit\": \"day\"}\n"
            "- 'trend analysis for last month' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"trend\"], \"trend_field\": \"createdTimeStamp\", \"trend_period\": \"month\", \"trend_metric\": \"count\"}\n"
            "- 'detect anomalies in lead creation' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"anomaly\"], \"anomaly_field\": \"createdTimeStamp\", \"anomaly_metric\": \"count\", \"anomaly_threshold\": 2.0}\n"
            "- 'forecast lead creation for next week' → {\"primary_entity\": \"Lead\", \"aggregations\": [\"forecast\"], \"forecast_field\": \"createdTimeStamp\", \"forecast_periods\": 7, \"forecast_metric\": \"count\"}\n\n"

            "Always output valid JSON. No explanations, no thinking, just the JSON object."
        )

        user = f"Convert to JSON: {query}"

        try:
            ai = await self.llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = ai.content.strip()
            
            # DEBUG: Log raw LLM response
            logger.debug(f"Raw LLM response for query '{query[:100]}': {content[:500]}")
            
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
            content = re.sub(r'<think>.*', '', content, flags=re.DOTALL)  # Handle incomplete tags

            # Some models wrap JSON in code fences; strip if present
            if content.startswith("```"):
                content = content.strip("`\n").split("\n", 1)[-1]
                if content.startswith("json\n"):
                    content = content[5:]

            # Try to find JSON in the response (look for { to } pattern)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            
            # Try to fix common JSON issues before parsing
            # Fix unterminated strings by closing them
            def fix_unterminated_strings(json_str: str) -> str:
                """Try to fix unterminated strings in JSON"""
                # Count quotes to detect unterminated strings
                in_string = False
                escape_next = False
                fixed = []
                i = 0
                while i < len(json_str):
                    char = json_str[i]
                    if escape_next:
                        fixed.append(char)
                        escape_next = False
                    elif char == '\\':
                        fixed.append(char)
                        escape_next = True
                    elif char == '"':
                        fixed.append(char)
                        in_string = not in_string
                    else:
                        fixed.append(char)
                    i += 1
                
                # If we ended in a string, close it
                result = ''.join(fixed)
                if in_string:
                    result += '"'
                
                return result
            
            # Ensure we have valid JSON
            if not content or content.isspace():
                return None

            # Try to parse JSON, with fallback to fixing common issues
            try:
                data = json.loads(content)
            except json.JSONDecodeError as je:
                # Try to fix unterminated strings and other common issues
                try:
                    fixed_content = fix_unterminated_strings(content)
                    # Also try to fix trailing commas
                    fixed_content = re.sub(r',\s*}', '}', fixed_content)
                    fixed_content = re.sub(r',\s*]', ']', fixed_content)
                    data = json.loads(fixed_content)
                    logger.warning(f"Fixed JSON parsing error for query '{query[:100]}': {je}")
                except json.JSONDecodeError:
                    # If fixing didn't work, try to extract a valid subset
                    logger.error(f"LLM parsing exception (unfixable JSON): {je}")
                    logger.error(f"Problematic JSON content (first 500 chars): {content[:500]}")
                    # Try to extract just the essential fields manually
                    try:
                        # Fallback: try to extract key fields using regex as last resort
                        primary_match = re.search(r'"primary_entity"\s*:\s*"([^"]+)"', content)
                        filters_match = re.search(r'"filters"\s*:\s*(\{[^}]*\})', content, re.DOTALL)
                        
                        data = {}
                        if primary_match:
                            data["primary_entity"] = primary_match.group(1)
                        if filters_match:
                            try:
                                data["filters"] = json.loads(filters_match.group(1))
                            except:
                                data["filters"] = {}
                        else:
                            data["filters"] = {}
                        
                        # Set defaults for required fields
                        data.setdefault("aggregations", [])
                        data.setdefault("group_by", [])
                        data.setdefault("projections", [])
                        data.setdefault("wants_details", False)
                        data.setdefault("wants_count", False)
                        
                        logger.warning(f"Extracted partial intent from malformed JSON: {data}")
                    except Exception as fallback_error:
                        logger.error(f"Failed to extract partial intent: {fallback_error}")
                        return None
            
            # DEBUG: Log parsed JSON data
            logger.debug(f"Parsed JSON data for query '{query[:100]}': filters={data.get('filters', {})}")
        except Exception as e:
            logger.error(f"LLM parsing exception: {e}")
            return None

        try:
            # Normalize primary entity synonyms before sanitization
            if isinstance(data, dict):
                pe = (data.get("primary_entity") or "").strip()
                if pe:
                    data["primary_entity"] = self.entity_synonyms.get(pe.lower(), pe)
            return await self._sanitize_intent(data, query)
        except Exception:
            return None

    async def _sanitize_intent(self, data: Dict[str, Any], original_query: str = "") -> QueryIntent:
        # Primary entity - trust the LLM's choice unless it's completely invalid
        requested_primary = (data.get("primary_entity") or "").strip()
        primary = requested_primary if requested_primary in self.entities else "Lead"

        # Allowed relations for primary
        allowed_rels = set(self.entity_relations.get(primary, []))
        target_entities: List[str] = []
        for rel in (data.get("target_entities") or []):
            if isinstance(rel, str) and rel.split(".")[0] in allowed_rels:
                target_entities.append(rel)

        # Simplified filter processing - keep valid filters, expanded to cover all collections
        raw_filters = data.get("filters") or {}
        
        # DEBUG: Log raw filters before sanitization
        logger.debug(f"Raw filters before sanitization for query '{original_query[:100] if original_query else 'unknown'}': {raw_filters}")
        
        filters: Dict[str, Any] = {}
        # Normalize date filter key synonyms BEFORE validation so they are preserved
        # Examples the LLM might emit: createdAt_from, created_from, date_to, updated_since, etc.
        def _normalize_date_filter_keys(primary_entity: str, rf: Dict[str, Any]) -> Dict[str, Any]:
            normalized: Dict[str, Any] = {}
            # Determine canonical created/updated fields per entity
            if primary_entity == "members":
                # members commonly use joiningDate
                created_field = "joiningDate"
                updated_field = None
            elif primary_entity in ("leadScoreRule", "segmentation"):
                # LeadScoreRule and Segmentation use createdAt/updatedAt
                created_field = "createdAt"
                updated_field = "updatedAt"
            else:
                # CRM entities use createdTimeStamp/updatedTimeStamp
                created_field = "createdTimeStamp"
                updated_field = "updatedTimeStamp"

            # Supported suffixes indicating range/window semantics
            suffixes = ("_from", "_to", "_within", "_duration")
            # Bases that imply created vs updated
            created_bases = {"created", "createdat", "created_time", "creation", "date", "timestamp"}
            updated_bases = {"updated", "updatedat", "last_date", "modified", "updated_time"}

            for key, val in rf.items():
                k = str(key)
                lk = k.lower()
                matched_suffix = next((s for s in suffixes if lk.endswith(s)), None)
                if matched_suffix:
                    base = lk[: -len(matched_suffix)]
                    if base in created_bases and created_field:
                        normalized[f"{created_field}{matched_suffix}"] = val
                        continue
                    if base in updated_bases and updated_field:
                        normalized[f"{updated_field}{matched_suffix}"] = val
                        continue
                # Also normalize plain created/updated without suffix if value looks like a window
                if lk in created_bases and created_field:
                    normalized[f"{created_field}_from"] = val
                    continue
                if lk in updated_bases and updated_field:
                    normalized[f"{updated_field}_from"] = val
                    continue
                # Keep as-is when not a recognized synonym
                normalized[k] = val

            return normalized

        raw_filters = _normalize_date_filter_keys(primary, raw_filters)

        # Build dynamic known keys from allow-listed fields and common tokens
        allowed_primary_fields = set(self.allowed_fields.get(primary, []))
        # Recognize date-like fields for range filters
        date_like_fields = {f for f in allowed_primary_fields if any(t in f.lower() for t in ["date", "timestamp", "createdat", "updatedat"]) }

        # Base normalized keys across collections
        known_filter_keys = {
            # normalized enums/booleans
            "priority", "status", "access", "isActive", "isArchived", "isDefault", "isFavourite",
            "visibility", "locked",
            # name/title/id style queries
            "label_name", "title", "name", "email",
            # entity name filters (secondary lookups)
            "assignee_name", "member_role",
            # actor/name filters
            "createdBy_name", "lead_name", "leadMail", "business_name",
            "defaultAssignee_name", "defaultAsignee_name", "staff_name",
            # members specific
            "role", "type", "joiningDate", "joiningDate_from", "joiningDate_to",
            # Array size filters (CRITICAL - must be in known_filter_keys)
            "assignee_count", "label_count", "customProperties_count",
            # Advanced MongoDB operator filters (CRITICAL - must be in known_filter_keys)
            "$text",  # Full-text search
            # Note: _elemMatch is handled dynamically via suffix matching

        }
        
        # Also accept any allow-listed primary fields directly
        known_filter_keys |= allowed_primary_fields
        
        # Also accept $elemMatch operator filters with suffix (_elemMatch)
        # These are dynamically detected based on field names + suffix
        for key in list(raw_filters.keys()):
            if key.endswith('_elemMatch'):
                # Extract base field name
                base_field = key[:-len('_elemMatch')]
                # Add to known_filter_keys if base field is valid
                if base_field in allowed_primary_fields or base_field in {"assignee", "label", "description", "_id"}:
                    known_filter_keys.add(key)
        
        # Also accept negative filters with suffix (_not)
        # These are dynamically detected based on field names + suffix
        for key in list(raw_filters.keys()):
            if key.endswith('_not'):
                # Extract base field name
                base_field = key[:-len('_not')]
                # Add to known_filter_keys if base field is valid
                if base_field in allowed_primary_fields or base_field in known_filter_keys:
                    known_filter_keys.add(key)
        # Add dynamic range keys for each date-like field
        for f in date_like_fields:
            known_filter_keys.add(f + "_from")
            known_filter_keys.add(f + "_to")
            # Also preserve relative window keys for date range filters
            known_filter_keys.add(f + "_within")
            known_filter_keys.add(f + "_duration")

        for k, v in raw_filters.items():
            if k not in known_filter_keys or self._is_placeholder(v):
                # Log warning when filters are dropped (except for placeholders)
                if not self._is_placeholder(v):
                    logger.warning(f"Filter '{k}' dropped during sanitization (not in known_filter_keys) for query: '{original_query[:100] if original_query else 'unknown'}'")
                continue
            # Normalize values where appropriate
            if k == "priority" and isinstance(v, str):
                normalized_priority = self._normalize_priority_value(v.strip())
                if normalized_priority:
                    filters[k] = normalized_priority
            elif k == "leadStatus" and isinstance(v, str):
                normalized = self._normalize_lead_status_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "taskStatus" and isinstance(v, str):
                normalized = self._normalize_task_status_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "meetingStatus" and isinstance(v, str):
                normalized = self._normalize_meeting_status_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "callStatus" and isinstance(v, str):
                normalized = self._normalize_call_status_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "activityStatus" and isinstance(v, str):
                normalized = self._normalize_activity_status_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "meetingType" and isinstance(v, str):
                normalized = self._normalize_meeting_type_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "callType" and isinstance(v, str):
                normalized = self._normalize_call_type_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k == "mailType" and isinstance(v, str):
                normalized = self._normalize_mail_type_value(v.strip())
                if normalized:
                    filters[k] = normalized
            elif k in ["isActive", "isArchived", "isDefault", "isFavourite", "locked"]:
                normalized_bool = self._normalize_boolean_value_from_any(v)
                if normalized_bool is not None:
                    filters[k] = normalized_bool
            elif k in ["assignee_name", "createdBy_name", "lead_name", "business_name", "label_name"] and isinstance(v, str):
                filters[k] = v.strip()
            elif isinstance(v, str) and k in {"title", "name", "email"}:
                filters[k] = v.strip()
            elif k.endswith("_count") and isinstance(v, (str, int)):
                # Array size filters: keep as-is (values like ">1", ">=2", "0", "3", etc.)
                filters[k] = str(v).strip() if isinstance(v, str) else str(v)
            elif k == "$text" and isinstance(v, str):
                # Full-text search: keep as-is
                filters[k] = v.strip()
            elif k.endswith("_elemMatch") and isinstance(v, dict):
                # $elemMatch operator filters: keep as-is (values are objects)
                filters[k] = v
            elif k.endswith("_not"):
                # Negative filters: keep as-is (values are arrays or single values to exclude)
                # Convert single values to arrays for consistency
                if isinstance(v, list):
                    filters[k] = v
                else:
                    filters[k] = [v]
            else:
                # Keep other valid filters (including direct field filters and date range tokens)
                filters[k] = v

        
        # Heuristic enrichments from original query text (generalized)
        oq_text = (original_query or "").lower()

        # 1) Infer grouping from phrasing: "by X", "group by X", "breakdown by X", "per X"
        inferred_group_by: List[str] = []
        def _maybe_add_group(token: str):
            if token in {"priority", "assignee", "status", "business"}:
                if token not in inferred_group_by:
                    inferred_group_by.append(token)

        # Common phrasings
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+priority\b", oq_text):
            _maybe_add_group("priority")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+assignee\b", oq_text):
            _maybe_add_group("assignee")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+status\b", oq_text):
            # For CRM entities, map "status" to entity-specific status field
            if primary == "Lead":
                _maybe_add_group("status")  # or "leadStatus" depending on field name
            elif primary == "task":
                _maybe_add_group("taskStatus")
            elif primary == "meeting":
                _maybe_add_group("meetingStatus")
            elif primary == "activity":
                _maybe_add_group("activityStatus")
            elif primary == "callLog":
                _maybe_add_group("callStatus")
            else:
                _maybe_add_group("status")  # Generic fallback
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+state\b", oq_text):
            _maybe_add_group("state")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+business\b", oq_text):
            _maybe_add_group("business")

        # Merge with LLM-provided group_by if any
        if inferred_group_by:
            existing_group_by = [g for g in (data.get("group_by") or [])]
            # keep order: inferred first, then any unique extras
            merged = inferred_group_by + [g for g in existing_group_by if g not in inferred_group_by]
            data["group_by"] = merged

            # If grouping by priority explicitly, drop conflicting exact priority filters to avoid collapsing buckets
            if "priority" in merged and "by priority" in oq_text and "priority" in filters:
                filters.pop("priority", None)

        # 2) Overdue semantics for tasks: dueDate < now and not in done-like states
        if primary == "task" and re.search(r"\boverdue\b|\bpast\s+due\b|\blate\b", oq_text):
            # Only add if user didn't already specify a dueDate bound
            if "dueDate_to" not in filters:
                filters["dueDate_to"] = "now"
            # Exclude commonly done/closed states if user didn't explicitly filter state
            if "taskStatus" not in filters and "taskStatus_not" not in filters:
                filters["taskStatus_not"] = ["COMPLETED", "DONE"]

        # 3) Advanced feature detection from query text (heuristic fallback)
        
        
        # Time window detection (rolling/moving averages)
        if re.search(r"\b(\d+)[\s-]?day\s+rolling\s+averages?\b|\brolling\s+averages?\s+.*\b(\d+)\s+days?\b|\bmoving\s+averages?\s+.*\b(\d+)\s+days?\b|\b(\d+)[\s-]?day\s+window\b", oq_text):
            if "timeWindow" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("timeWindow")
                data["aggregations"] = aggregations
            # Extract window size
            window_match = re.search(r"\b(\d+)[\s-]?day", oq_text)
            if window_match and not data.get("window_size"):
                data["window_size"] = f"{window_match.group(1)}d"
            # Infer window field from context
            if not data.get("window_field"):
                if "created" in oq_text or "creation" in oq_text:
                    data["window_field"] = "createdTimeStamp"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["window_field"] = "updatedTimeStamp"
        
        # Trend detection
        if re.search(r"\btrends?\b|\bmonthly\s+trends?\b|\bweekly\s+trends?\b|\bquarterly\s+trends?\b|\bperiod\s+over\s+period\b", oq_text):
            if "trend" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("trend")
                data["aggregations"] = aggregations
            # Infer trend period
            if not data.get("trend_period"):
                if re.search(r"\bmonthly\b|\bmonth\b", oq_text):
                    data["trend_period"] = "month"
                elif re.search(r"\bweekly\b|\bweek\b", oq_text):
                    data["trend_period"] = "week"
                elif re.search(r"\bquarterly\b|\bquarter\b", oq_text):
                    data["trend_period"] = "quarter"
            # Infer trend field
            if not data.get("trend_field"):
                if "created" in oq_text or "creation" in oq_text:
                    data["trend_field"] = "createdTimeStamp"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["trend_field"] = "updatedTimeStamp"
        
        # Anomaly detection
        if re.search(r"\banomal(?:y|ies)\b|\bunusual\b|\boutlier\b|\bspike\b|\bdetect.*\banomal\b", oq_text):
            if "anomaly" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("anomaly")
                data["aggregations"] = aggregations
            # Infer anomaly field
            if not data.get("anomaly_field"):
                if "created" in oq_text or "creation" in oq_text:
                    data["anomaly_field"] = "createdTimeStamp"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["anomaly_field"] = "updatedTimeStamp"
                elif "completion" in oq_text:
                    data["anomaly_field"] = "updatedTimeStamp"
        
        # Forecasting detection
        if re.search(r"\bforecast\b|\bpredict\b|\bprojection\b|\bprojected\b|\bnext\s+\d+\s+days?\b|\bnext\s+week\b|\bnext\s+month\b", oq_text):
            if "forecast" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("forecast")
                data["aggregations"] = aggregations
            # Extract forecast periods
            forecast_match = re.search(r"\bnext\s+(\d+)\s+days?\b|\b(\d+)\s+days?\s+ahead\b", oq_text)
            if forecast_match and not data.get("forecast_periods"):
                periods = forecast_match.group(1) or forecast_match.group(2)
                if periods:
                    data["forecast_periods"] = int(periods)
            elif re.search(r"\bnext\s+week\b", oq_text) and not data.get("forecast_periods"):
                data["forecast_periods"] = 7
            elif re.search(r"\bnext\s+month\b", oq_text) and not data.get("forecast_periods"):
                data["forecast_periods"] = 30
            # Infer forecast field
            if not data.get("forecast_field"):
                if "created" in oq_text or "creation" in oq_text:
                    data["forecast_field"] = "createdTimeStamp"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["forecast_field"] = "updatedTimeStamp"
        
        # Pattern analysis detection - automatically detect when queries need pattern analysis
        # Keywords: "most common", "frequent", "patterns", "trends", "influence", "factors", "why", "what causes"
        # Question types: "What objections are most common?", "What factors influence win rates?", "Why do deals slip?"
        # Analysis requests: "analyze patterns", "identify trends", "find correlations"
        pattern_keywords = [
            r"\bmost\s+common\b", r"\bfrequent\b", r"\bpatterns?\b", r"\binfluence\b", r"\bfactors?\b",
            r"\bwhy\b", r"\bwhat\s+causes?\b", r"\bwhat\s+factors?\b", r"\bcorrelations?\b",
            r"\bidentify\s+patterns?\b", r"\banalyze\s+patterns?\b", r"\bfind\s+patterns?\b",
            r"\bcommon\s+reasons?\b", r"\bmost\s+frequent\b", r"\btypical\b", r"\busually\b",
            r"\bwhat\s+leads\s+to\b", r"\bwhat\s+drives\b", r"\bwhat\s+affects\b", r"\bwhat\s+impacts\b"
        ]
        needs_pattern_analysis = any(re.search(pattern, oq_text, re.IGNORECASE) for pattern in pattern_keywords)
        
        # Also detect question patterns that typically need pattern analysis
        question_patterns = [
            r"what\s+(objections?|reasons?|factors?|issues?)\s+(are|is)\s+(most\s+)?(common|frequent)",
            r"what\s+(factors?|reasons?)\s+(influence|affect|impact|drive)",
            r"why\s+do\s+(deals?|leads?|customers?)\s+",
            r"what\s+causes?\s+",
            r"what\s+are\s+the\s+(most\s+)?(common|frequent|typical)\s+"
        ]
        if not needs_pattern_analysis:
            needs_pattern_analysis = any(re.search(pattern, oq_text, re.IGNORECASE) for pattern in question_patterns)
        
        data["needs_pattern_analysis"] = needs_pattern_analysis

        # Aggregations - include new advanced aggregation types
        allowed_aggs = {
            "count", "group", "summary",
            "timeWindow", "trend", "anomaly", "forecast"
        }
        aggregations = [a for a in (data.get("aggregations") or []) if a in allowed_aggs]

        # Group by tokens
        # Extended to support status/visibility/business and date buckets
        allowed_group = {
            "assignee", "state", "priority",
            "status", "visibility", "business",
            "created_day", "created_week", "created_month",
            "updated_day", "updated_week", "updated_month",
        }
        group_by = [g for g in (data.get("group_by") or []) if g in allowed_group]

        # If user grouped by cross-entity tokens, force Lead as base (entity lock)
        cross_tokens = {"assignee", "business"}
        if any(g in cross_tokens for g in group_by) and primary not in self.entities:
            primary = "Lead"

        # Aggregations & group_by coherence
        if group_by and "group" not in aggregations:
            aggregations.insert(0, "group")
        if not group_by:
            # drop stray 'group'
            aggregations = [a for a in aggregations if a != "group"]

        # Projections limited to allow-listed fields for primary
        allowed_projection_set = set(self.allowed_fields.get(primary, []))
        projections = [p for p in (data.get("projections") or []) if p in allowed_projection_set][:10]

        # Sort order
        sort_order = None
        so = data.get("sort_order") or {}
        if isinstance(so, dict) and so:
            key, val = next(iter(so.items()))
            # Accept synonyms and normalize
            key_map = {
                "created": "createdTimeStamp",
                "createdAt": "createdTimeStamp",
                "created_time": "createdTimeStamp",
                "time": "createdTimeStamp",
                "date": "createdTimeStamp",
                "timestamp": "createdTimeStamp",
            }
            norm_key = key_map.get(key, key)

            def _norm_dir(v: Any) -> Optional[int]:
                if v in (1, -1):
                    return int(v)
                if isinstance(v, str):
                    s = v.strip().lower()
                    if s in {"asc", "ascending", "old->new", "old to new", "old_to_new"}:
                        return 1
                    if s in {"desc", "descending", "new->old", "new to old", "new_to_old"}:
                        return -1
                return None

            norm_dir = _norm_dir(val)
            if norm_key in {"createdTimeStamp", "createdAt", "updatedAt", "timestamp", "priority", "state", "status"} and norm_dir in (1, -1):
                sort_order = {norm_key: norm_dir}

        # Limit - intelligent handling based on query type
        limit_val = data.get("limit")
        try:
            # For count/aggregation-only queries, no limit needed unless specifically requested
            if aggregations and not wants_details and limit_val is None:
                limit = None
            elif limit_val is None or limit_val == 50:
                # Use default limit when LLM doesn't provide a specific limit
                limit = 50
            else:
                limit = int(limit_val)
                if limit <= 0:
                    limit = 50
                # Cap at 1000 to prevent runaway queries (instead of 100)
                limit = min(limit, 1000)
        except Exception:
            # Last resort fallback: use default limit
            limit = 50

        # Skip (offset)
        skip_val = data.get("skip")
        try:
            skip = int(skip_val) if skip_val is not None else 0
            if skip < 0:
                skip = 0
        except Exception:
            skip = 0

        # Details vs count (mutually exclusive) + heuristic for "how many"
        oq = (original_query or "").lower()
        wants_details_raw = data.get("wants_details")
        wants_count_raw = data.get("wants_count")
        wants_details = bool(wants_details_raw) if wants_details_raw is not None else False
        wants_count = bool(wants_count_raw) if wants_count_raw is not None else False
        wants_count = wants_count or ("how many" in oq)

        # Simplified count query handling
        if wants_count:
            # For count queries, keep it simple
            aggregations = ["count"]
            wants_details = False
            group_by = []
            target_entities = []
            projections = []
            sort_order = None
        else:
            # For non-count queries, ensure consistency
            if group_by and wants_details_raw is None:
                wants_details = False

        # Infer pagination from query text if not explicitly set by LLM
        if not data.get("skip") or data.get("skip") == 0:
            inferred_pagination = self._infer_pagination_from_query(original_query or "")
            if inferred_pagination:
                # Only override if LLM didn't provide explicit pagination
                if "skip" in inferred_pagination and not data.get("skip"):
                    data["skip"] = inferred_pagination["skip"]
                if "limit" in inferred_pagination and not data.get("limit"):
                    data["limit"] = inferred_pagination["limit"]

        # If no explicit sort provided and no grouping/count, infer time-based sort from phrasing
        if not sort_order and not group_by and not wants_count:
            inferred_sort = self._infer_sort_order_from_query(original_query or "")
            if inferred_sort:
                sort_order = inferred_sort

        # Fetch one heuristic
        fetch_one = bool(data.get("fetch_one", False)) or (limit == 1)

        # Extract advanced aggregation fields
        
        # Time-series analysis fields
        window_field = data.get("window_field")
        window_size = data.get("window_size")
        window_unit = data.get("window_unit")
        trend_field = data.get("trend_field")
        trend_period = data.get("trend_period")
        trend_metric = data.get("trend_metric")
        anomaly_field = data.get("anomaly_field")
        anomaly_metric = data.get("anomaly_metric")
        anomaly_threshold = data.get("anomaly_threshold")
        forecast_field = data.get("forecast_field")
        forecast_periods = data.get("forecast_periods")

        needs_pattern_analysis = bool(data.get("needs_pattern_analysis", False))
        
        return QueryIntent(
            primary_entity=primary,
            target_entities=target_entities,
            filters=filters,
            aggregations=aggregations,
            group_by=group_by,
            projections=projections,
            sort_order=sort_order,
            limit=limit,
            skip=skip,
            wants_details=wants_details,
            wants_count=wants_count,
            fetch_one=fetch_one,
            window_field=window_field if window_field else None,
            window_size=window_size if window_size else None,
            window_unit=window_unit if window_unit else None,
            trend_field=trend_field if trend_field else None,
            trend_period=trend_period if trend_period else None,
            trend_metric=trend_metric if trend_metric else None,
            anomaly_field=anomaly_field if anomaly_field else None,
            anomaly_metric=anomaly_metric if anomaly_metric else None,
            anomaly_threshold=float(anomaly_threshold) if anomaly_threshold is not None else None,
            forecast_field=forecast_field if forecast_field else None,
            forecast_periods=int(forecast_periods) if forecast_periods is not None else None,
            needs_pattern_analysis=needs_pattern_analysis,
        )

    async def _disambiguate_name_entity(self, proposed: Dict[str, str]) -> Optional[str]:
        """Use DB counts across collections to decide which name filter is most plausible.

        Preference order on ties: assignee.
        Returns the chosen filter key or None if inconclusive.
        """
        # Build candidate lookups: mapping filter key -> (collection, field)
        candidates = {
            "assignee_name": ("members", "name"),
        }
        counts: Dict[str, int] = {}
        for key, (collection, field) in candidates.items():
            if key not in proposed:
                continue
            value = proposed[key]
            try:
                cnt = await self._aggregate_count(collection, {field: {"$regex": value, "$options": "i"}})
            except Exception:
                cnt = 0
            counts[key] = cnt

        if not counts:
            return None

        # Pick the key with the highest positive count
        positive = {k: v for k, v in counts.items() if v and v > 0}
        if not positive:
            # No evidence; prefer assignee if proposed
            if "assignee_name" in proposed:
                return "assignee_name"
            return None

        # Sort keys by count desc then by preference order
        preference = {"assignee_name": 0}
        chosen = sorted(positive.items(), key=lambda kv: (-kv[1], preference.get(kv[0], 99)))[0][0]
        return chosen

    async def _aggregate_count(self, collection: str, match_filter: Dict[str, Any]) -> int:
        """Run a count via aggregation to avoid needing a dedicated count tool."""
        try:
            result = await mongodb_tools.execute_tool("aggregate", {
                "database": DATABASE_NAME,
                "collection": collection,
                "pipeline": [{"$match": match_filter}, {"$count": "total"}]
            })
            if isinstance(result, list) and result and isinstance(result[0], dict) and "total" in result[0]:
                return int(result[0]["total"])  # type: ignore
        except Exception:
            pass
        return 0
