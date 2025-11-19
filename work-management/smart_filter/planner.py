import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
import os
import logging
from dataclasses import dataclass
import copy
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary, BUSINESS_UUID, MEMBER_UUID, COLLECTIONS_WITH_DIRECT_BUSINESS
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
 
from langchain_groq import ChatGroq
# Orchestration utilities
from agent.orchestrator import Orchestrator, StepSpec, as_async

# OpenInference semantic conventions (optional)
try:
    from openinference.semconv.trace import SpanAttributes as OI
except Exception:  # Fallback when OpenInference isn't installed
    class _OI:
        INPUT_VALUE = "input.value"
        OUTPUT_VALUE = "output.value"
        TOOL_INPUT = "tool.input"
        TOOL_OUTPUT = "tool.output"
        ERROR_TYPE = "error.type"
        ERROR_MESSAGE = "error.message"

    OI = _OI()
from dotenv import load_dotenv
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError(
        "FATAL: GROQ_API_KEY environment variable not set.\n"
        "Please create a .env file and add your Groq API key to it."
    )

@dataclass
class QueryIntent:
    """Represents the parsed intent of a user query"""
    primary_entity: str  # Main collection/entity (e.g., "workItem", "project")
    filters: Dict[str, Any]  # Filter conditions
    aggregations: List[str]  # Aggregation operations (count, group, etc.)
    group_by: List[str]  # Grouping keys (e.g., ["cycle"]) when 'group by' present
    projections: List[str]  # Fields to return
    sort_order: Optional[Dict[str, int]]  # Sort specification
    limit: Optional[int]  # Result limit
    skip: Optional[int]  # Result offset for pagination
    wants_details: bool  # Prefer detailed documents over counts
    wants_count: bool  # Whether the user asked for a count
    fetch_one: bool  # Whether the user wants a single specific item


ALLOWED_FIELDS: Dict[str, Set[str]] = {
    "workItem": {
        "_id", "displayBugNo", "title", "description",
        "priority", "status",
        # Embedded state/cycle/module per production schema
        "state.name",
        "project._id", "project.name",
        "cycle._id", "cycle.name",
        "modules._id", "modules.name",
        "createdBy._id", "createdBy.name",
        "createdTimeStamp", "updatedTimeStamp", "dueDate",
        "assignee", "assignee._id", "assignee.name", "label.name",
        # Estimate and work logs
        "estimateSystem", "estimate", "estimate.hr", "estimate.min",
        "workLogs", "workLogs.user", "workLogs.user.name", "workLogs.hours", 
        "workLogs.minutes", "workLogs.description", "workLogs.loggedAt"
    }
}

def _serialize_pipeline_for_json(pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert datetime objects in pipeline to JSON-serializable format using MongoDB ISODate format"""
    if not pipeline:
        return pipeline

    def _convert_value(value: Any) -> Any:
        if isinstance(value, datetime):
            # Use MongoDB ISODate format: new ISODate("2025-09-27T01:22:58Z")
            iso_string = value.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if value.microsecond else value.strftime('%Y-%m-%dT%H:%M:%SZ')
            return {"$isodate": iso_string}  # Use a special marker that can be converted to JavaScript
        elif isinstance(value, dict):
            return {k: _convert_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_convert_value(item) for item in value]
        else:
            return value

    return [_convert_value(stage) for stage in pipeline]

def _format_pipeline_for_display(pipeline: List[Dict[str, Any]]) -> str:
    """Format pipeline as JavaScript code for display in MongoDB shell format"""
    if not pipeline:
        return "[]"

    def _format_value(value: Any) -> str:
        if isinstance(value, dict):
            if "$isodate" in value:
                return f'new ISODate("{value["$isodate"]}")'
            else:
                items = []
                for k, v in value.items():
                    formatted_value = _format_value(v)
                    # Don't quote string values that are not meant to be strings
                    if isinstance(v, str) and v in ("true", "false", "null"):
                        items.append(f'"{k}": {formatted_value}')
                    else:
                        items.append(f'"{k}": {formatted_value}')
                return "{" + ", ".join(items) + "}"
        elif isinstance(value, list):
            items = [_format_value(item) for item in value]
            return "[" + ", ".join(items) + "]"
        elif isinstance(value, str):
            return f'"{value}"'
        else:
            return str(value)

    def _format_stage(stage: Dict[str, Any]) -> str:
        stage_name = list(stage.keys())[0]
        stage_value = stage[stage_name]
        stage_content = _format_value(stage_value)
        return f'  {stage_name}: {stage_content}'

    formatted_stages = []
    for i, stage in enumerate(pipeline):
        formatted_stages.append(_format_stage(stage))
        if i < len(pipeline) - 1:
            formatted_stages.append("")

    return "[\n" + ",\n".join(formatted_stages) + "\n]"

class LLMIntentParser:
    """LLM-backed intent parser that produces a structured plan compatible with QueryIntent.

    The LLM proposes:
    - primary_entity (workItem)
    - filters (normalized keys: status, priority, project_status, cycle_status, page_visibility,
      project_name, cycle_name, assignee_name, module_name)
    - aggregations: ["count"|"group"|"summary"]
    - group_by tokens: ["cycle","project","assignee","status","priority","module"]
    - projections (subset of allow-listed fields for the primary entity)
    - sort_order (field -> 1|-1), supported keys: createdTimeStamp, priority, status
    - limit (int)
    - wants_details, wants_count

    Safety: we filter LLM output against ALLOWED_FIELDS before use.
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
        self.entities: List[str] = list("workItem")
        self.allowed_fields: Dict[str, List[str]] = {
            entity: sorted(list(ALLOWED_FIELDS.get(entity, set()))) for entity in self.entities
        }
        # Map common synonyms to canonical entity names to reduce LLM mistakes
        self.entity_synonyms = {
            "task": "workItem",
            "tasks": "workItem",
            "bug": "workItem",
            "bugs": "workItem",
            "issue": "workItem",
            "issues": "workItem",
            "tickets": "workItem",
            "ticket": "workItem",
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


    def _normalize_state_value(self, value: str) -> Optional[str]:
        """Normalize state values to match database enum"""
        state_map = {
            "open": "Open",
            "completed": "Completed",
            "backlog": "Backlog",
            "re-raised": "Re-Raised",
            "re raised": "Re-Raised",
            "reraised": "Re-Raised",
            "reopened": "Re-Raised",
            "re-opened": "Re-Raised",
            "re opened": "Re-Raised",
            "in-progress": "In-Progress",
            "in progress": "In-Progress",
            "wip": "In-Progress",
            "verified": "Verified"
        }
        return state_map.get(value.lower())

    def _normalize_priority_value(self, value: str) -> Optional[str]:
        """Normalize priority values to match database enum"""
        priority_map = {
            "urgent": "URGENT",
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
            "none": "NONE"
        }
        return priority_map.get(value.lower())


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

    async def parse(self, query: str) -> Optional[QueryIntent]:
        """Use the LLM to produce a structured intent. Returns None on failure."""
        system = (
            "You are an expert MongoDB query planner for work item management.\n"
            "Your task is to convert natural language queries into structured JSON intent objects.\n\n"

            "## DOMAIN CONTEXT\n"
            "This is a project management system with these main entities:\n"
            f"- {', '.join(self.entities)}\n\n"
            "Users ask questions in many different ways. Be flexible with their wording.\n"
            "Focus on understanding their intent, not exact keywords.\n\n"

            "## KEY RELATIONSHIPS\n"
            "- Work items belong to projects, cycles, and modules\n"
            "- Work items are assigned to team members\n"
            # "- Projects contain cycles and modules\n"
            # "- Cycles and modules belong to projects\n"
            # "- Epics contain multiple features and belong to a project lifecycle.\n\n"

            "## VERY IMPORTANT\n"
            "## AVAILABLE FILTERS (use these exact keys):\n"
            "- state: Open|Completed|Backlog|Re-Raised|In-Progress|Verified (for workItem)\n"
            "- priority: URGENT|HIGH|MEDIUM|LOW|NONE (for workItem)\n"
            "- project_name, business_name, assignee_name, module_name,cycle_name\n"
            "- status: Accepted\n"
            "- displayBugNo: (work item ID)\n"
            "- createdBy_name: (creator names)\n"
            "- label: (work item labels)\n"
            "- estimateSystem: TIME|POINTS|etc (for workItem)\n"
            "- estimate: object with hr/min fields (for workItem)\n"
            "- workLogs: array of work log entries with user, hours, minutes, description, loggedAt (for workItem)\n\n"

            "## TIME-BASED SORTING (CRITICAL)\n"
            "Infer sort_order from phrasing when the user implies recency or age.\n"
            "- 'recent', 'latest', 'newest', 'most recent' → {\"createdTimeStamp\": -1}\n"
            "- 'oldest', 'earliest', 'older first' → {\"createdTimeStamp\": 1}\n"
            "- If 'ascending/descending' is mentioned with created/time/date/timestamp, map to 1/-1 respectively on 'createdTimeStamp'.\n"
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
            "  - 'top N' with priority context → sort_order: {\"priority\": -1}\n"
            "  - 'top N' with date/recent context → sort_order: {\"createdTimeStamp\": -1}\n\n"

            "## NAME EXTRACTION RULES - CRITICAL\n"
            "ALWAYS extract ONLY the core entity name, NEVER include descriptive phrases:\n"
            "- Query: 'work items within PMS project' → project_name: 'PMS' (NOT 'PMS project')\n"
            "- Query: 'tasks from test module' → module_name: 'test' (NOT 'test module')\n"
            "- Query: 'bugs assigned to alice' → assignee_name: 'alice' (NOT 'alice assigned')\n"
            "- Query: 'items in upcoming cycle' → cycle_name: 'upcoming' (NOT 'upcoming cycle')\n"
            "❌ WRONG: {'project_name': 'PMS project'} - this breaks regex matching!\n"
            "✅ CORRECT: {'project_name': 'PMS'} - this works with regex matching\n\n"

            "## COMPOUND FILTER PARSING\n"
            "When users write queries like 'cycles where state.active = true':\n"
            "- 'state.open = true' should map to state: 'Open' for workItem entities\n"
            "- Parse 'entity.field = value' patterns and map to appropriate filter keys\n\n"

            "## COMMON QUERY PATTERNS\n"
            "- 'Show me X' → list/get details (aggregations: [])\n"
            "- 'How many X' → count (aggregations: ['count'])\n"
            "- 'Breakdown by X' → group results (aggregations: ['group'])\n"
            "- 'X assigned to Y' → filter by assignee name (Y = assignee_name)\n"
            "- 'X from/in/belonging to/associated with Y' → filter by project/cycle/module name (Y = project_name/cycle_name/module_name)\n"
            "- 'X in Y status' → filter by status/priority\n"
            "- 'work items with title containing Z' → filter by title field (Z = search term)\n"
            "- 'work items with label Z' → filter by label field (Z = exact label value)\n"
            "- 'find items containing X in title' → {\"primary_entity\": \"workItem\", \"filters\": {\"title\": \"X\"}, \"aggregations\": []}\n"
            "- 'search for Y in descriptions' → {\"primary_entity\": \"workItem\", \"filters\": {\"description\": \"Y\"}, \"aggregations\": []}\n"
            "- 'IMPORTANT: For \"containing\" queries, extract ONLY the search term (e.g., \"component\"), not the full phrase'\n"
            "- 'Y project' → if asking about work items: workItem with project_name filter\n"
            "  → Context matters: 'details of Y project' vs 'work items associated with Y project'\n"
            "- 'cycles that are active/currently active' → cycle with cycle_status: 'ACTIVE'\n"
            "- 'active cycles' → cycle with cycle_status: 'ACTIVE'\n"
            "- 'what is the email address for X' → members with name filter and email projection\n"
            "- 'member X' → members entity with name filter\n"
            "- 'project member X' → members entity with name filter\n"
            "- 'work items updated in the last 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}}\n"
            "- 'tasks created since last week' → {\"primary_entity\": \"workItem\", \"filters\": {\"createdTimeStamp_from\": \"last_week\"}}\n"
            "- 'issues modified after 2024-01-01' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"2024-01-01\"}}\n"
            "- 'workItem.last_date >= current_date - 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}}\n\n"
            
            "## OUTPUT FORMAT\n"
            "CRITICAL: Output ONLY the JSON object, nothing else.\n"
            "CRITICAL: The response must be parseable by json.loads().\n\n"
            "EXACT JSON structure:\n"
            "{\n"
            f' "primary_entity": "workItem",\n' 
            '  "filters": {},\n'
            '  "aggregations": [],\n'
            '  "group_by": [],\n'
            '  "projections": [],\n'
            '  "sort_order": null,\n'
            '  "limit": 50,\n'
            '  "skip": 0,\n'
            '  "wants_details": true,\n'
            '  "wants_count": false,\n'
            '  "fetch_one": false\n'
            "}\n\n"

            "## EXAMPLES\n"
            "- 'show me tasks assigned to alice' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_name\": \"alice\"}, \"aggregations\": []}\n"
            "- 'how many bugs are there' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"count\"]}\n"
            # "- 'count active projects' → {\"primary_entity\": \"project\", \"filters\": {\"project_status\": \"STARTED\"}, \"aggregations\": [\"count\"]}\n"
            "- 'group tasks by priority' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"group\"], \"group_by\": [\"priority\"]}\n"
            "- 'show work items with bug label' → {\"primary_entity\": \"workItem\", \"filters\": {\"label\": \"bug\"}, \"aggregations\": []}\n"
            "- 'find work items with title containing component' → {\"primary_entity\": \"workItem\", \"filters\": {\"title\": \"component\"}, \"aggregations\": []}\n"
            "- 'show recent tasks' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": -1}}\n"
            "- 'bugs in ascending created order' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": 1}}\n"
            "- 'work items updated in the last 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}, \"aggregations\": []}\n"
            "- 'tasks created since yesterday' → {\"primary_entity\": \"workItem\", \"filters\": {\"createdTimeStamp_from\": \"yesterday\"}, \"aggregations\": []}\n"
            "- 'issues from the last week' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"last_week\"}, \"aggregations\": []}\n"
            "- 'workItem.last_date >= current_date - 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}, \"aggregations\": []}\n"
            "- 'top 5 priority work items' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"priority\": -1}, \"limit\": 5}\n"
            "- 'show me a few bugs' → {\"primary_entity\": \"workItem\", \"filters\": {\"label\": \"bug\"}, \"aggregations\": [], \"limit\": 5}\n"
            "- 'show work items with estimates' → {\"primary_entity\": \"workItem\", \"projections\": [\"displayBugNo\", \"title\", \"estimate\", \"estimateSystem\"], \"aggregations\": []}\n"
            "- 'show work logs for tasks' → {\"primary_entity\": \"workItem\", \"projections\": [\"displayBugNo\", \"title\", \"workLogs\"], \"aggregations\": []}\n\n"

            "Always output valid JSON. No explanations, no thinking, just the JSON object."
        )

        user = f"Convert to JSON: {query}"

        try:
            ai = await self.llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = ai.content.strip()
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

            # Ensure we have valid JSON
            if not content or content.isspace():
                return None

            data = json.loads(content)
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
        # requested_primary = (data.get("primary_entity") or "").strip()
        primary = "workItem"

        # Simplified filter processing - keep valid filters, expanded to cover all collections
        raw_filters = data.get("filters") or {}
        filters: Dict[str, Any] = {}

        # Map legacy 'status' to 'state' for workItem if present
        if primary == "workItem" and "status" in raw_filters and "state" not in raw_filters:
            raw_filters["state"] = raw_filters.pop("status")


        if primary in ("workItem") and "label" in raw_filters:
            raw_filters["label_name"] = raw_filters["label"]
        # Normalize date filter key synonyms BEFORE validation so they are preserved
        # Examples the LLM might emit: createdAt_from, created_from, date_to, updated_since, etc.
        def _normalize_date_filter_keys(primary_entity: str, rf: Dict[str, Any]) -> Dict[str, Any]:
            normalized: Dict[str, Any] = {}
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
            "updatedBy_name","business_name",
            "endDate","createdTimeStamp",
            "updatedTimeStamp","durationInMinutes",
            "project_name","label_name","label_color","title",
            "priority","cycle_name",
            "module_name","workLogs_hours","workLogs_minutes",
            "workLogs_loggedAt","createdBy_name","state_name",
            "assignee_name","displayBugNo","startDate","status",
        }

        # Also accept any allow-listed primary fields directly
        known_filter_keys |= allowed_primary_fields
        # Add dynamic range keys for each date-like field
        for f in date_like_fields:
            known_filter_keys.add(f + "_from")
            known_filter_keys.add(f + "_to")
            # Also preserve relative window keys so timeline's timestamp_within is not dropped
            known_filter_keys.add(f + "_within")
            known_filter_keys.add(f + "_duration")

        for k, v in raw_filters.items():
            if k not in known_filter_keys or self._is_placeholder(v):
                continue
            # Normalize values where appropriate
            if k == "state" and isinstance(v, str):
                normalized_state = self._normalize_state_value(v.strip())
                if normalized_state:
                    filters[k] = normalized_state
            elif k == "priority" and isinstance(v, str):
                normalized_priority = self._normalize_priority_value(v.strip())
                if normalized_priority:
                    filters[k] = normalized_priority
            elif k in ["project_status", "cycle_status", "page_visibility"] and isinstance(v, str):
                normalized_status = self._normalize_status_value(k, v.strip())
                if normalized_status:
                    filters[k] = normalized_status
            elif k in ["isActive", "isArchived", "isDefault", "isFavourite", "locked"]:
                normalized_bool = self._normalize_boolean_value_from_any(v)
                if normalized_bool is not None:
                    filters[k] = normalized_bool
            elif k in ["project_name", "cycle_name", "module_name", "assignee_name", "createdBy_name", "lead_name", "business_name","label_name"] and isinstance(v, str):
                filters[k] = v.strip()
            elif isinstance(v, str) and k in {"title", "name", "displayBugNo", "projectDisplayId", "email"}:
                filters[k] = v.strip()
            else:
                # Keep other valid filters (including direct field filters and date range tokens)
                filters[k] = v

        
        # Heuristic enrichments from original query text (generalized)
        oq_text = (original_query or "").lower()

        # 1) Infer grouping from phrasing: "by X", "group by X", "breakdown by X", "per X"
        inferred_group_by: List[str] = []
        def _maybe_add_group(token: str):
            if token in {"project", "priority", "assignee", "cycle", "module", "state", "status", "business"}:
                if token not in inferred_group_by:
                    inferred_group_by.append(token)

        # Common phrasings
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+priority\b", oq_text):
            _maybe_add_group("priority")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+project\b", oq_text):
            _maybe_add_group("project")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+assignee\b", oq_text):
            _maybe_add_group("assignee")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+cycle\b", oq_text):
            _maybe_add_group("cycle")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+module\b", oq_text):
            _maybe_add_group("module")
        if re.search(r"\b(group\s+by|breakdown\s+by|distribution\s+by|by|per)\s+(state|status)\b", oq_text):
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

        # 2) Overdue semantics for work items: dueDate < now and not in done-like states
        if primary == "workItem" and re.search(r"\boverdue\b|\bpast\s+due\b|\blate\b", oq_text):
            # Only add if user didn't already specify a dueDate bound
            if "dueDate_to" not in filters:
                filters["dueDate_to"] = "now"
            # Exclude commonly done/closed states if user didn't explicitly filter state
            if "state" not in filters and "state_not" not in filters:
                filters["state_not"] = ["Completed", "Verified"]


        # Aggregations
        allowed_aggs = {"count", "group", "summary"}
        aggregations = [a for a in (data.get("aggregations") or []) if a in allowed_aggs]

        # Group by tokens
        # Extended to support status/visibility/business and date buckets
        allowed_group = {
            "cycle", "project", "assignee", "state", "priority", "module",
            "status", "visibility", "business",
            "created_day", "created_week", "created_month",
            "updated_day", "updated_week", "updated_month",
        }
        group_by = [g for g in (data.get("group_by") or []) if g in allowed_group]

        # If user grouped by cross-entity tokens, force workItem as base (entity lock)
        cross_tokens = {"assignee", "project", "cycle", "module", "business"}
        if any(g in cross_tokens for g in group_by):
            primary = "workItem"

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
            projections = []
            sort_order = None
        else:
            # For non-count queries, ensure consistency
            if group_by and wants_details_raw is None:
                wants_details = False
        
            # Infer missing time window for timeline when the query includes relative periods
            has_time_window = any(k in filters for k in [
                "timestamp_from", "timestamp_to", "timestamp_within", "timestamp_duration"
            ])
            if not has_time_window:
                if re.search(r"\btoday\b", oq):
                    filters["timestamp_within"] = "today"
                elif re.search(r"\byesterday\b", oq):
                    filters["timestamp_within"] = "yesterday"
                elif re.search(r"\bthis\s+week\b", oq):
                    filters["timestamp_within"] = "this_week"
                elif re.search(r"\blast\s+week\b", oq):
                    filters["timestamp_within"] = "last_week"
                elif re.search(r"\bthis\s+month\b", oq):
                    filters["timestamp_within"] = "this_month"
                elif re.search(r"\blast\s+month\b", oq):
                    filters["timestamp_within"] = "last_month"

        # If no explicit sort provided and no grouping/count, infer time-based sort from phrasing
        if not sort_order and not group_by and not wants_count:
            inferred_sort = self._infer_sort_order_from_query(original_query or "")
            if inferred_sort:
                # If timeline → map createdTimeStamp to timestamp
                if primary == "timeline" and "createdTimeStamp" in inferred_sort:
                    dirv = inferred_sort.get("createdTimeStamp", -1)
                    sort_order = {"timestamp": dirv}
                elif primary == "page" and "createdTimeStamp" in inferred_sort:
                    dirv = inferred_sort.get("createdTimeStamp", -1)
                    sort_order = {"createdAt": dirv}
                else:
                    sort_order = inferred_sort

        # Fetch one heuristic
        fetch_one = bool(data.get("fetch_one", False)) or (limit == 1)

        return QueryIntent(
            primary_entity=primary,
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
        )


    async def _aggregate_count(self, collection: str, match_filter: Dict[str, Any]) -> int:
        """Run a count via aggregation to avoid needing a dedicated count tool."""
        try:
            result = await mongodb_tools.execute_tool("aggregate_smart", {
                "database": DATABASE_NAME,
                "collection": collection,
                "pipeline": [{"$match": match_filter}, {"$count": "total"}]
            })
            if isinstance(result, list) and result and isinstance(result[0], dict) and "total" in result[0]:
                return int(result[0]["total"])  # type: ignore
        except Exception:
            pass
        return 0

class PipelineGenerator:
    """Generates MongoDB aggregation pipelines based on query intent and relationships"""

    def __init__(self):
        self.relationship_cache = {}  # Cache for computed relationship paths

    def generate_pipeline(self, intent: QueryIntent) -> List[Dict[str, Any]]:
        """Generate MongoDB aggregation pipeline for the given intent"""
        pipeline: List[Dict[str, Any]] = []

        # Start with the primary collection
        collection = intent.primary_entity

        # Add business scoping for collections that require it
        if collection in COLLECTIONS_WITH_DIRECT_BUSINESS:
            business_uuid = BUSINESS_UUID()
            if business_uuid:
                business_filter = {"business._id": uuid_str_to_mongo_binary(business_uuid)}
                # Add business filter as the first match stage
                pipeline.append({"$match": business_filter})

        # Build sanitized filters once
        primary_filters = self._extract_primary_filters(intent.filters, collection) if intent.filters else {}
        secondary_filters = self._extract_secondary_filters(intent.filters, collection) if intent.filters else {}

        # COUNT-ONLY: no group_by, no details → do not add lookups
        if (("count" in intent.aggregations) or intent.wants_count) and not intent.group_by and not intent.wants_details:
            # Combine all filters for optimal count query
            all_filters = {}

            # Include business scoping if added to pipeline
            if pipeline and pipeline[0].get("$match"):
                all_filters.update(pipeline[0]["$match"])

            if primary_filters:
                all_filters.update(primary_filters)
            if secondary_filters:
                all_filters.update(secondary_filters)

            if all_filters:
                return [{"$match": all_filters}, {"$count": "total"}]
            else:
                return [{"$count": "total"}]

        # Add filters for the primary collection
        if primary_filters:
            pipeline.append({"$match": primary_filters})

        # Add secondary filters (on joined collections) BEFORE normalizing fields
        if secondary_filters:
            pipeline.append({"$match": secondary_filters})

        # Add grouping if requested
        if intent.group_by:
            # Pre-group unwind for embedded arrays that are used as grouping keys
            # For workItem, assignee is an array subdocument; unwind to get per-assignee buckets
            if intent.primary_entity == 'workItem' and 'assignee' in intent.group_by:
                pipeline.append({
                    "$unwind": {"path": "$assignee", "preserveNullAndEmptyArrays": True}
                })
            group_id_expr: Any
            id_fields: Dict[str, Any] = {}
            for token in intent.group_by:
                resolved = self._resolve_group_field(intent.primary_entity, token)
                if resolved:
                    # Accept either a field path (str) or a full expression (dict)
                    if isinstance(resolved, str):
                        id_fields[token] = f"${resolved}"
                    else:
                        id_fields[token] = resolved
            if not id_fields:
                # Fallback: do nothing if we can't resolve
                pass
            else:
                group_id_expr = list(id_fields.values())[0] if len(id_fields) == 1 else id_fields

                group_stage: Dict[str, Any] = {
                    "$group": {
                        "_id": group_id_expr,
                        "count": {"$sum": 1},
                    }
                }
                if intent.wants_details:
                    group_stage["$group"]["items"] = {
                        "$push": {
                            "_id": "$_id",
                            "displayBugNo": "$displayBugNo",
                            "title": "$title",
                            "priority": "$priority",
                            "estimate": "$estimate",
                            "estimateSystem": "$estimateSystem",
                            "workLogs": "$workLogs",
                        }
                    }
                pipeline.append(group_stage)
                # Sorting for grouped results: default to metric desc (count or totalMinutes), allow sorting by grouped keys
                if intent.sort_order:
                    sort_key, sort_dir = next(iter(intent.sort_order.items()))
                    if sort_key in intent.group_by:
                        # Sort by the grouped key inside _id
                        if len(id_fields) == 1:
                            pipeline.append({"$sort": {"_id": sort_dir}})
                        else:
                            pipeline.append({"$sort": {f"_id.{sort_key}": sort_dir}})
                    else:
                        pass
                else:
                    pass
                # Present a tidy shape
                project_shape: Dict[str, Any] = {"count": 1}
                if intent.wants_details:
                    project_shape["items"] = 1
                project_shape["group"] = "$_id"
                # Respect limit on grouped results
                if intent.limit:
                    pipeline.append({"$limit": intent.limit})

        # Add aggregations like count (skip count when details are requested)
        if intent.aggregations and not intent.wants_details and not intent.group_by:
            for agg in intent.aggregations:
                if agg == 'count':
                    pipeline.append({"$count": "total"})
                    return pipeline  # Count is terminal

        # Determine projections for details (skip when grouping since we reshape after $group)
        effective_projections: List[str] = intent.projections
        if intent.wants_details and not intent.group_by and not effective_projections:
            effective_projections = self._get_default_projections(intent.primary_entity)

        # Add sorting (handle custom priority order) — skip if already grouped
        added_priority_rank = False
        if intent.sort_order and not intent.group_by:
            if 'priority' in intent.sort_order:
                # Only compute rank if priority is part of projections to avoid surprising invisible sorts
                if (effective_projections and 'priority' in effective_projections) or (not effective_projections):
                    added_priority_rank = True
                    pipeline.append({
                        "$addFields": {
                            "_priorityRank": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq": ["$priority", "URGENT"]}, "then": 5},
                                        {"case": {"$eq": ["$priority", "HIGH"]}, "then": 4},
                                        {"case": {"$eq": ["$priority", "MEDIUM"]}, "then": 3},
                                        {"case": {"$eq": ["$priority", "LOW"]}, "then": 2},
                                        {"case": {"$eq": ["$priority", "NONE"]}, "then": 1}
                                    ],
                                    "default": 0
                                }
                            }
                        }
                    })
                    # Use computed rank for sorting direction provided
                    direction = intent.sort_order.get('priority', -1)
                    pipeline.append({"$sort": {"_priorityRank": direction}})
                else:
                    pipeline.append({"$sort": intent.sort_order})
            elif 'state' in intent.sort_order and collection == 'workItem':
                # Sort by state via embedded state.name.
                pipeline.append({"$sort": {"state.name": intent.sort_order.get('state', 1)}})
            else:
                pipeline.append({"$sort": intent.sort_order})

        # Compute projected aliases for joined relations so projections include them when needed
        projected_aliases: Set[str] = set()

        # Add projections after sorting so computed fields can be hidden
        if effective_projections and not intent.group_by:
            projection = self._generate_projection(effective_projections, sorted(list(projected_aliases)), intent.primary_entity)
            # Ensure we exclude helper fields from output
            pipeline.append({"$project": projection})
        # Always remove priority rank helper if it was added
        if added_priority_rank:
            pipeline.append({"$unset": "_priorityRank"})

        # Add pagination: skip then limit (only for non-grouped queries; grouped handled above)
        if not intent.group_by:
            # Apply skip before limit
            try:
                if intent.skip and int(intent.skip) > 0:
                    pipeline.append({"$skip": int(intent.skip)})
            except Exception:
                pass
            effective_limit = 1 if intent.fetch_one else (intent.limit or None)
            if effective_limit:
                pipeline.append({"$limit": int(effective_limit)})

        return pipeline

    def _extract_primary_filters(self, filters: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Extract filters that apply to the primary collection"""
        primary_filters = {}

        # Handle direct _id filters first using $expr with $toObjectId for safety
        def _is_hex24(s: str) -> bool:
            try:
                return isinstance(s, str) and len(s) == 24 and all(c in '0123456789abcdefABCDEF' for c in s)
            except Exception:
                return False

        if "_id" in filters:
            val = filters.get("_id")
            if isinstance(val, str) and _is_hex24(val):
                primary_filters["$expr"] = {"$eq": ["$_id", {"$toObjectId": val}]}
            elif isinstance(val, list):
                ids = [v for v in val if isinstance(v, str) and _is_hex24(v)]
                if ids:
                    primary_filters["$expr"] = {
                        "$in": [
                            "$_id",
                            {"$map": {"input": ids, "as": "id", "in": {"$toObjectId": "$$id"}}}
                        ]
                    }

        def _apply_date_range(target: Dict[str, Any], field: str, f: Dict[str, Any]):
            # Resolve field aliases first
            from mongo.registry import resolve_field_alias
            resolved_field = resolve_field_alias(collection, field)

            # Support additional keys:
            # - {field}_within / {field}_duration: relative window like "last_7_days", "7d", {"last": {"days": 7}}
            # - allow {field}_from / {field}_to values like "now-7d" or ISO timestamps

            def _parse_relative_window(spec: Any) -> Optional[Dict[str, datetime]]:
                now = datetime.now(timezone.utc)
                start: Optional[datetime] = None
                end: datetime = now

                def _start_of_week(dt: datetime) -> datetime:
                    dow = dt.weekday()  # Monday=0
                    sod = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                    return sod - timedelta(days=dow)

                def _start_of_month(dt: datetime) -> datetime:
                    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)

                def _end_of_month(dt: datetime) -> datetime:
                    if dt.month == 12:
                        next_month = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
                    else:
                        next_month = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
                    return next_month - timedelta(microseconds=1)

                if isinstance(spec, dict) and spec.get("last"):
                    last_obj = spec.get("last") or {}
                    days = float(last_obj.get("days", 0) or 0)
                    hours = float(last_obj.get("hours", 0) or 0)
                    delta = timedelta(days=days, hours=hours)
                    if delta.total_seconds() > 0:
                        start = now - delta
                        return {"from": start, "to": end}
                    return None

                if not isinstance(spec, str):
                    return None

                s = spec.strip().lower().replace("-", "_")
                if s == "today":
                    sod = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
                    return {"from": sod, "to": end}
                if s == "yesterday":
                    sod_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
                    sod_y = sod_today - timedelta(days=1)
                    eod_y = sod_today - timedelta(microseconds=1)
                    return {"from": sod_y, "to": eod_y}
                if s == "this_week":
                    return {"from": _start_of_week(now), "to": end}
                if s == "last_week":
                    sow_this = _start_of_week(now)
                    sow_last = sow_this - timedelta(days=7)
                    eow_last = sow_this - timedelta(microseconds=1)
                    return {"from": sow_last, "to": eow_last}
                if s == "this_month":
                    return {"from": _start_of_month(now), "to": end}
                if s == "last_month":
                    som_this = _start_of_month(now)
                    if som_this.month == 1:
                        som_last = datetime(som_this.year - 1, 12, 1, tzinfo=timezone.utc)
                    else:
                        som_last = datetime(som_this.year, som_this.month - 1, 1, tzinfo=timezone.utc)
                    eom_last = _end_of_month(som_last)
                    return {"from": som_last, "to": eom_last}

                m = re.search(r"(last|past)?\s*([0-9]+)\s*(day|days|d|week|weeks|w|month|months|mo|hour|hours|h|year|years|y)", s)
                if m:
                    n = int(m.group(2))
                    unit = m.group(3)
                    if unit in {"day", "days", "d"}:
                        start = now - timedelta(days=n)
                    elif unit in {"week", "weeks", "w"}:
                        start = now - timedelta(weeks=n)
                    elif unit in {"month", "months", "mo"}:
                        start = now - timedelta(days=30 * n)
                    elif unit in {"hour", "hours", "h"}:
                        start = now - timedelta(hours=n)
                    elif unit in {"year", "years", "y"}:
                        start = now - timedelta(days=365 * n)
                    if start:
                        return {"from": start, "to": end}

                m2 = re.fullmatch(r"([0-9]+)\s*(d|h)", s)
                if m2:
                    n = int(m2.group(1))
                    unit = m2.group(2)
                    if unit == "d":
                        start = now - timedelta(days=n)
                    elif unit == "h":
                        start = now - timedelta(hours=n)
                    if start:
                        return {"from": start, "to": end}
                return None

            def _normalize_bound(val: Any) -> Any:
                if isinstance(val, (int, float)):
                    try:
                        if float(val) > 1e11:
                            return datetime.fromtimestamp(float(val) / 1000.0, tz=timezone.utc)
                        return datetime.fromtimestamp(float(val), tz=timezone.utc)
                    except Exception:
                        return val
                if isinstance(val, str):
                    s = val.strip().lower()
                    if s == "now":
                        return datetime.now(timezone.utc)
                    m = re.fullmatch(r"now\s*[-+]\s*([0-9]+)\s*(d|day|days|h|hour|hours)", s)
                    if m:
                        n = int(m.group(1))
                        unit = m.group(2)
                        if unit in {"d", "day", "days"}:
                            return datetime.now(timezone.utc) - timedelta(days=n)
                        if unit in {"h", "hour", "hours"}:
                            return datetime.now(timezone.utc) - timedelta(hours=n)
                    try:
                        return datetime.fromisoformat(val)
                    except Exception:
                        return val
                return val

            # Look for date range keys using the original field name
            within = f.get(f"{field}_within") or f.get(f"{field}_duration")
            gte_key = f.get(f"{field}_from")
            lte_key = f.get(f"{field}_to")

            if within is not None:
                rng = _parse_relative_window(within)
                if rng:
                    gte_key = gte_key or rng.get("from")
                    lte_key = lte_key or rng.get("to")

            # Also interpret relative tokens provided directly in _from/_to
            # e.g. createdTimeStamp_from: "last_week" or updatedTimeStamp_to: "yesterday"
            if isinstance(gte_key, str):
                rng_from = _parse_relative_window(gte_key)
                if rng_from:
                    gte_key = rng_from.get("from")
                    # If caller did not specify an upper bound, use the window's natural end
                    if lte_key is None:
                        lte_key = rng_from.get("to")
            if isinstance(lte_key, str):
                rng_to = _parse_relative_window(lte_key)
                if rng_to:
                    lte_key = rng_to.get("to")

            if gte_key is None and lte_key is None:
                return
            range_expr: Dict[str, Any] = {}
            if gte_key is not None:
                range_expr["$gte"] = _normalize_bound(gte_key)
            if lte_key is not None:
                range_expr["$lte"] = _normalize_bound(lte_key)
            if range_expr:
                target[resolved_field] = range_expr

        if collection == "workItem":
            if 'status' in filters:
                primary_filters['status'] = filters['status']
            if 'priority' in filters:
                primary_filters['priority'] = filters['priority']
            if 'state' in filters:
                # Map logical state filter to embedded field
                primary_filters['state.name'] = filters['state']
            # Exclude states (array) support, mapped to state.name not-in
            if 'state_not' in filters and isinstance(filters['state_not'], list) and filters['state_not']:
                primary_filters['state.name'] = primary_filters.get('state.name') or {}
                # If previously set to a scalar via 'state', turn into $nin with preservation
                if isinstance(primary_filters['state.name'], str):
                    primary_filters['state.name'] = {"$in": [primary_filters['state.name']]}
                # Merge not-in
                primary_filters['state.name']["$nin"] = filters['state_not']
            if 'label_name' in filters and isinstance(filters['label_name'], str):
                primary_filters['label.name'] = {'$regex': filters['label_name'], '$options': 'i'}
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'displayBugNo' in filters and isinstance(filters['displayBugNo'], str):
                primary_filters['displayBugNo'] = {'$regex': f"^{filters['displayBugNo']}", '$options': 'i'}
            if 'business_name' in filters and isinstance(filters['business_name'], str):
                primary_filters['business.name'] = {'$regex': filters['business_name'], '$options': 'i'}
            if 'assignee_name' in filters and isinstance(filters['assignee_name'], str):
                primary_filters['assignee.name'] = {'$regex': filters['assignee_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)
            # Support dueDate ranges uniformly
            _apply_date_range(primary_filters, 'dueDate', filters)

            # Optional duration-based filtering in days: duration_days_from/to
            dur_from = filters.get('duration_days_from')
            dur_to = filters.get('duration_days_to')
            if dur_from is not None or dur_to is not None:
                dur_bounds: List[Dict[str, Any]] = []
                dur_expr = {
                    "$divide": [
                        {"$subtract": [
                            {"$ifNull": ["$endDate", "$$NOW"]},
                            "$startDate"
                        ]},
                        86400000
                    ]
                }
                try:
                    if dur_from is not None:
                        dur_from_val = float(dur_from)
                        dur_bounds.append({"$gte": [dur_expr, dur_from_val]})
                except Exception:
                    pass
                try:
                    if dur_to is not None:
                        dur_to_val = float(dur_to)
                        dur_bounds.append({"$lte": [dur_expr, dur_to_val]})
                except Exception:
                    pass
                if dur_bounds:
                    expr = {"$and": dur_bounds} if len(dur_bounds) > 1 else dur_bounds[0]
                    if "$expr" in primary_filters:
                        existing = primary_filters["$expr"]
                        primary_filters["$expr"] = {"$and": [existing, expr]}
                    else:
                        primary_filters["$expr"] = expr

        return primary_filters

    def _extract_secondary_filters(self, filters: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Extract filters that apply to joined collections, guarded by available relations."""
        s: Dict[str, Any] = {}

        # Project name: allow both embedded project.name and joined alias projectDoc.name
        if 'project_name' in filters and collection == 'project':
            s['$or'] = [
                {'name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectDoc.name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectName': {'$regex': filters['project_name'], '$options': 'i'}},
            ]
        elif 'project_name' in filters:
            # For non-project collections, match on the joined project document
            s['$or'] = [
                {'project.name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectDoc.name': {'$regex': filters['project_name'], '$options': 'i'}},
            ]


        # Cycle name filter: prefer embedded cycle.name; support joined aliases
        if 'cycle_name' in filters:
            if collection == 'workItem':
                s['cycle.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}

        # Module name filter: prefer embedded modules.name; support joined aliases
        if 'module_name' in filters:
            if collection == 'workItem':
                s['modules.name'] = {'$regex': filters['module_name'], '$options': 'i'}


        return s


    def _generate_projection(self, projections: List[str], primary_entity: str) -> Dict[str, Any]:
        """Generate projection object"""
        projection = {"_id": 1}  # Always include ID

        # Add requested projections
        for field in projections:
            if field in ALLOWED_FIELDS.get(primary_entity, {}):
                projection[field] = 1

        return projection

    def _get_default_projections(self, primary_entity: str) -> List[str]:
        """Return sensible default fields for detail queries per collection.
        Only returns fields that are allow-listed for the given collection.

        For smart filter agent, return no projections to avoid MongoDB projection issues.
        """
        # For smart filter agent, don't use projections - let Python handle formatting
        if primary_entity == "workItem":
            return []

        defaults_map: Dict[str, List[str]] = {
            "workItem": [
                "displayBugNo", "title", "priority",
                "state.name", "assignee","label.name",
                "project.name", "cycle.name", "modules.name",
                "createdTimeStamp", "estimateSystem", "estimate", "workLogs"
            ],
        }

        candidates = defaults_map.get(primary_entity, ["_id"])  # fallback _id

        # Validate against allow-listed fields for safety
        allowed = ALLOWED_FIELDS.get(primary_entity, set())
        validated: List[str] = []
        for field in candidates:
            # Keep only fields that are explicitly allow-listed for primary entity
            if field in allowed:
                validated.append(field)

        # After computing validated, if it's empty, fall back to a minimal safe set
        if not validated:
            minimal = ["title", "priority", "createdTimeStamp"]
            validated = [f for f in minimal if f in allowed]
        return validated

    def _resolve_group_field(self, primary_entity: str, token: str) -> Optional[str]:
        """Map a grouping token to a concrete field path or Mongo expression.

        Returns either a string field path (relative to current doc) or a dict representing
        a MongoDB aggregation expression (e.g., for date bucketing).
        """
        # Date bucket helper
        def date_field_for(entity: str, which: str) -> Optional[str]:
            # Default to *TimeStamp for other entities
            return 'createdTimeStamp' if which == 'created' else 'updatedTimeStamp'

        def bucket_expr(entity: str, which: str, unit: str):
            field = date_field_for(entity, which)
            if not field:
                return None
            # Prefer $dateTrunc for week/month; for day we can also truncate
            if unit in {'week', 'month', 'day'}:
                return {"$dateTrunc": {"date": f"${field}", "unit": unit}}
            return None

        # Base mappings
        mapping: Dict[str, Dict[str, Any]] = {
            'workItem': {
                'project': 'project.name',
                'assignee': 'assignee.name',
                'cycle': 'cycle.name',
                'module': 'modules.name',
                'state': 'state.name',
                'label': 'label.name',
                'status': 'state.name',  # accept 'status' as synonym for state
                'priority': 'priority',
                'business': 'projectDoc.business.name',  # ensure join if needed
                'created_day': bucket_expr('workItem', 'created', 'day'),
                'created_week': bucket_expr('workItem', 'created', 'week'),
                'created_month': bucket_expr('workItem', 'created', 'month'),
                'updated_day': bucket_expr('workItem', 'updated', 'day'),
                'updated_week': bucket_expr('workItem', 'updated', 'week'),
                'updated_month': bucket_expr('workItem', 'updated', 'month'),
            },
        }
        entity_map = mapping.get(primary_entity, {})
        val = entity_map.get(token)
        # Some bucket_expr entries may be None if field not applicable
        return val if val is not None else None

class Planner:
    """Main query planner that orchestrates the entire process"""

    def __init__(self):
        self.generator = PipelineGenerator()
        self.llm_parser = LLMIntentParser()
        self.orchestrator = Orchestrator(tracer_name=__name__, max_parallel=5)

    async def plan_and_execute(self, query: str, project_id: str) -> Dict[str, Any]:
        """Plan and execute a natural language query using the Orchestrator."""
        try:
            # Define step coroutines as closures to capture self
            async def _ensure_connection(ctx: Dict[str, Any]) -> bool:
                await mongodb_tools.connect()
                return True

            async def _parse_intent(ctx: Dict[str, Any]) -> Optional[QueryIntent]:
                return await self.llm_parser.parse(ctx["query"])  # type: ignore[index]

            def _parse_validator(result: Any, _ctx: Dict[str, Any]) -> bool:
                return result is not None

            def _generate_pipeline(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
                return self.generator.generate_pipeline(ctx["intent"])  # type: ignore[index]

            async def _execute(ctx: Dict[str, Any]) -> Any:
                intent: QueryIntent = ctx["intent"]  # type: ignore[assignment]
                args = {
                    "database": DATABASE_NAME,
                    "collection": intent.primary_entity,
                    "pipeline": ctx["pipeline"],
                    "project_id": project_id,
                }
                return await mongodb_tools.execute_tool("aggregate_smart", args)

            steps: List[StepSpec] = [
                StepSpec(
                    name="ensure_connection",
                    coroutine=as_async(_ensure_connection),
                    requires=(),
                    provides="connected",
                    retries=2,
                    timeout_s=8.0,
                ),
                StepSpec(
                    name="parse_intent",
                    coroutine=as_async(_parse_intent),
                    requires=("query",),
                    provides="intent",
                    timeout_s=15.0,
                    retries=1,
                    validator=_parse_validator,
                ),
                StepSpec(
                    name="generate_pipeline",
                    coroutine=as_async(_generate_pipeline),
                    requires=("intent",),
                    provides="pipeline",
                    timeout_s=5.0,
                ),
                StepSpec(
                    name="execute_query",
                    coroutine=as_async(_execute),
                    requires=("intent", "pipeline"),
                    provides="result",
                    timeout_s=20.0,
                    retries=1,
                ),
            ]

            ctx = await self.orchestrator.run(
                steps,
                initial_context={"query": query},
                correlation_id=f"planner_{hash(query) & 0xFFFFFFFF:x}",
            )

            intent: QueryIntent = ctx["intent"]  # type: ignore[assignment]
            pipeline: List[Dict[str, Any]] = ctx["pipeline"]  # type: ignore[assignment]
            result = ctx.get("result")

            return {
                "success": True,
                "intent": intent.__dict__,
                "pipeline": _serialize_pipeline_for_json(pipeline),
                "pipeline_js": _format_pipeline_for_display(pipeline),
                "result": result,
                "planner": "llm",
            }
        except Exception as e:
            pass
            return {
                "success": False,
                "error": str(e),
                "query": query,
            }

# Global instance
query_planner = Planner()

async def plan_and_execute_query(query: str, project_id: str) -> Dict[str, Any]:
    """Convenience function to plan and execute queries"""
    return await query_planner.plan_and_execute(query, project_id=project_id)
