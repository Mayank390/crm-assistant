
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
    - filters (normalized keys: status, priority, project_status, cycle_status, page_visibility,
      project_name, cycle_name, assignee_name, module_name)
    - aggregations: ["count"|"group"|"summary"]
    - group_by tokens: ["cycle","project","assignee","status","priority","module"]
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
            "member": "members",
            "members": "members",
            "team": "members",
            "teammate": "members",
            "teammates": "members",
            "assignee": "members",
            "assignees": "members",
            "user": "members",
            "users": "members",
            "staff": "members",
            "personnel": "members",
            "task": "workItem",
            "tasks": "workItem",
            "bug": "workItem",
            "bugs": "workItem",
            "issue": "workItem",
            "issues": "workItem",
            "tickets": "workItem",
            "ticket": "workItem",
            "epic" : "epic",
            "features":"features",
            "feature":"features",
            "userstory":"userStory",
            "story":"userStory",
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

    def _normalize_status_value(self, filter_key: str, value: str) -> Optional[str]:
        """Normalize status values based on filter type"""
        if filter_key == "project_status":
            status_map = {
                "not_started": "NOT_STARTED",
                "not started": "NOT_STARTED",
                "started": "STARTED",
                "completed": "COMPLETED",
                "overdue": "OVERDUE"
            }
        elif filter_key == "cycle_status":
            status_map = {
                "active": "ACTIVE",
                "upcoming": "UPCOMING",
                "completed": "COMPLETED"
            }
        elif filter_key == "page_visibility":
            status_map = {
                "public": "PUBLIC",
                "private": "PRIVATE",
                "archived": "ARCHIVED"
            }
        else:
            return None

        return status_map.get(value.lower())

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
            "You are an expert MongoDB query planner for a Project Management System.\n"
            "Your task is to convert natural language queries into structured JSON intent objects.\n\n"

            "## DOMAIN CONTEXT\n"
            "This is a project management system with these main entities:\n"
            f"- {', '.join(self.entities)}\n\n"
            "Users ask questions in many different ways. Be flexible with their wording.\n"
            "Focus on understanding their intent, not exact keywords.\n\n"

            "## KEY RELATIONSHIPS\n"
            "- Work items belong to projects, cycles, and modules\n"
            "- Work items are assigned to team members\n"
            "- Projects contain cycles and modules\n"
            "- Cycles and modules belong to projects\n"
            "- Epics contain multiple features and belong to a project lifecycle.\n\n"
            "- Features are new developments to the product."
            "- User stories are short, simple descriptions of a feature told from the perspective of the person who desires the new capability, usually a user or customer.\n\n"

            "## VERY IMPORTANT\n"
            "## AVAILABLE FILTERS (use these exact keys):\n"
            "- state: Open|Completed|Backlog|Re-Raised|In-Progress|Verified (for workItem)\n"
            "- priority: URGENT|HIGH|MEDIUM|LOW|NONE (for workItem)\n"
            "- status: (varies by collection - use appropriate values)\n"
            "- project_status: NOT_STARTED|STARTED|COMPLETED|OVERDUE (for project)\n"
            "- cycle_status: ACTIVE|UPCOMING|COMPLETED (for cycle)\n"
            "- page_visibility: PUBLIC|PRIVATE|ARCHIVED (for page)\n"
            "- access: (project access levels)\n"
            "- isActive: true|false (for projects)\n"
            "- isArchived: true|false (for projects)\n"
            "- isDefault: true|false (for cycles)\n"
            "- isFavourite: true|false (for various entities)\n"
            "- type: (member types)\n"
            "- role: (member roles)\n"
            "- visibility: PUBLIC|PRIVATE|ARCHIVED (for pages)\n"
            "- project_name, cycle_name, assignee_name, module_name\n"
            "- createdBy_name: (creator names)\n"
            "- label: (work item labels)\n"
            "- estimateSystem: TIME|POINTS|etc (for workItem)\n"
            "- estimate: object with hr/min fields (for workItem)\n"
            "- workLogs: array of work log entries with user, hours, minutes, description, loggedAt (for workItem)\n\n"
            "- state_name: Backlog|New|Started|Unstarted|Completed (for epic)\n"
            "- priority: URGENT|HIGH|MEDIUM|LOW (for epic)\n\n"
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
            "- assignee/assignees → assignee_count\n"
            "- label/labels → label_count\n"
            "- dependency/dependencies → dependencies_count (for features/epics)\n"
            "- custom property/properties → customProperties_count (for epics)\n"
            "- risk/risks → risks_count (for features)\n"
            "- goal/goals → goals_count (for features)\n"
            "- pain point/points → painPoints_count (for features)\n"
            "- requirement/requirements → functionalRequirements_count (for features)\n"
            "- workItems → workItems_count (for features)\n"
            "- userStories → userStories_count (for features)\n\n"
            "## ADVANCED AGGREGATION STAGES\n"
            "Support for complex aggregation operations:\n"
            "- 'break down by priority and status' → $facet for multiple aggregations\n"
            "- 'auto-group by priority' → $bucketAuto for automatic range grouping\n"
            "- 'combine with other collection' → $unionWith to merge collections\n"
            "- 'graph traversal queries' → $graphLookup for hierarchical data\n"
            "- Use natural language to express these complex analytical queries\n\n"
            "## TIME-SERIES ANALYSIS\n"
            "Support for time-based analytical operations:\n"
            "- 'sliding window of 7 days' → $setWindowFields for moving averages\n"
            "- 'rolling average over 30 days' → time window aggregations\n"
            "- 'trend analysis for last quarter' → period-over-period comparisons\n"
            "- 'anomaly detection in work items' → statistical outlier detection\n"
            "- 'time series forecasting' → trend projection and prediction\n"
            "- Express temporal analysis queries with sliding windows and trends\n"

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
            "- 'state.active = true' should map to cycle_status: 'ACTIVE' for cycle entities\n"
            "- 'state.open = true' should map to state: 'Open' for workItem entities\n"
            "- 'status.completed = true' should map to project_status: 'COMPLETED' for project entities\n"
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
            '  "facet_fields": null,\n'
            '  "bucket_field": null,\n'
            '  "union_collection": null,\n'
            '  "graph_from": null,\n'
            '  "graph_start": null,\n'
            '  "graph_connect_from": null,\n'
            '  "graph_connect_to": null,\n'
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
            "- 'show me tasks assigned to alice' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_name\": \"alice\"}, \"aggregations\": []}\n"
            "- 'how many bugs are there' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"count\"]}\n"
            "- 'count active projects' → {\"primary_entity\": \"project\", \"filters\": {\"project_status\": \"STARTED\"}, \"aggregations\": [\"count\"]}\n"
            "- 'group tasks by priority' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"group\"], \"group_by\": [\"priority\"]}\n"
            "- 'show archived projects' → {\"primary_entity\": \"project\", \"filters\": {\"isArchived\": true}, \"aggregations\": []}\n"
            "- 'find favourite modules' → {\"primary_entity\": \"module\", \"filters\": {\"isFavourite\": true}, \"aggregations\": []}\n"
            "- 'show work items with bug label' → {\"primary_entity\": \"workItem\", \"filters\": {\"label\": \"bug\"}, \"aggregations\": []}\n"
            "- 'find work items with title containing component' → {\"primary_entity\": \"workItem\", \"filters\": {\"title\": \"component\"}, \"aggregations\": []}\n"
            "- 'who created this project' → {\"primary_entity\": \"project\", \"filters\": {\"createdBy_name\": \"john\"}, \"aggregations\": []}\n"
            "- 'find active cycles' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"ACTIVE\"}, \"aggregations\": []}\n"
            "- 'list cycles where state.active = true' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"ACTIVE\"}, \"aggregations\": []}\n"
            "- 'list all cycles that currently active' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"ACTIVE\"}, \"aggregations\": []}\n"
            "- 'show upcoming cycles' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"UPCOMING\"}, \"aggregations\": []}\n"
            "- 'count completed cycles' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"COMPLETED\"}, \"aggregations\": [\"count\"]}\n"
            "- 'what is the email address for the project member Vikas' → {\"primary_entity\": \"members\", \"filters\": {\"name\": \"Vikas\"}, \"projections\": [\"email\"], \"aggregations\": []}\n"
            "- 'what is the role of Vikas in Simpo Builder project' → {\"primary_entity\": \"members\", \"target_entities\": [\"project\"], \"filters\": {\"name\": \"Vikas\", \"business_name\": \"Simpo.ai\"}, \"aggregations\": []}\n"
            "- 'show members in Simpo project' → {\"primary_entity\": \"members\", \"target_entities\": [\"project\"], \"filters\": {\"project_name\": \"Simpo\"}, \"aggregations\": []}\n\n"
            "- 'show recent tasks' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": -1}}\n"
            "- 'list oldest projects' → {\"primary_entity\": \"project\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": 1}}\n"
            "- 'bugs in ascending created order' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"createdTimeStamp\": 1}}\n"
            "- 'work items updated in the last 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}, \"aggregations\": []}\n"
            "- 'tasks created since yesterday' → {\"primary_entity\": \"workItem\", \"filters\": {\"createdTimeStamp_from\": \"yesterday\"}, \"aggregations\": []}\n"
            "- 'issues from the last week' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"last_week\"}, \"aggregations\": []}\n"
            "- 'workItem.last_date >= current_date - 30 days' → {\"primary_entity\": \"workItem\", \"filters\": {\"updatedTimeStamp_from\": \"now-30d\"}, \"aggregations\": []}\n"
            "- 'top 5 priority work items' → {\"primary_entity\": \"workItem\", \"aggregations\": [], \"sort_order\": {\"priority\": -1}, \"limit\": 5}\n"
            "- 'first 10 projects' → {\"primary_entity\": \"project\", \"aggregations\": [], \"limit\": 10}\n"
            "- 'all active cycles' → {\"primary_entity\": \"cycle\", \"filters\": {\"cycle_status\": \"ACTIVE\"}, \"aggregations\": [], \"limit\": 1000}\n"
            "- 'show me a few bugs' → {\"primary_entity\": \"workItem\", \"filters\": {\"label\": \"bug\"}, \"aggregations\": [], \"limit\": 5}\n"
            "- 'find one project named X' → {\"primary_entity\": \"project\", \"filters\": {\"name\": \"X\"}, \"aggregations\": [], \"limit\": 1, \"fetch_one\": true}\n"
            "- 'show work items with estimates' → {\"primary_entity\": \"workItem\", \"projections\": [\"displayBugNo\", \"title\", \"estimate\", \"estimateSystem\"], \"aggregations\": []}\n"
            "- 'show work logs for tasks' → {\"primary_entity\": \"workItem\", \"projections\": [\"displayBugNo\", \"title\", \"workLogs\"], \"aggregations\": []}\n\n"
            "## ARRAY SIZE EXAMPLES (MUST FOLLOW THESE PATTERNS)\n"
            "- 'how many work items have multiple assignees?' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_count\": \">1\"}, \"aggregations\": [\"count\"]}\n"
            "- 'show work items with more than 2 assignees' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_count\": \">2\"}, \"aggregations\": []}\n"
            "- 'work items with at least 2 labels' → {\"primary_entity\": \"workItem\", \"filters\": {\"label_count\": \">=2\"}, \"aggregations\": []}\n"
            "- 'find work items with exactly 3 labels' → {\"primary_entity\": \"workItem\", \"filters\": {\"label_count\": \"3\"}, \"aggregations\": []}\n"
            "- 'unassigned work items' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_count\": \"0\"}, \"aggregations\": []}\n"
            "- 'work items with no assignees' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_count\": \"0\"}, \"aggregations\": []}\n"
            "- 'work items with labels' → {\"primary_entity\": \"workItem\", \"filters\": {\"label_count\": \">=1\"}, \"aggregations\": []}\n"
            "- 'work items with 2 assignees' → {\"primary_entity\": \"workItem\", \"filters\": {\"assignee_count\": \"2\"}, \"aggregations\": []}\n"
            "- 'find epics with custom properties' → {\"primary_entity\": \"epic\", \"filters\": {\"customProperties_count\": \">=1\"}, \"aggregations\": []}\n"
            "- 'features with multiple dependencies' → {\"primary_entity\": \"features\", \"filters\": {\"dependencies_count\": \">1\"}, \"aggregations\": []}\n"
            "- 'count features with multiple dependencies' → {\"primary_entity\": \"features\", \"filters\": {\"dependencies_count\": \">1\"}, \"aggregations\": [\"count\"]}\n"
            "- 'show user stories with multiple labels' → {\"primary_entity\": \"userStory\", \"filters\": {\"label_count\": \">1\"}, \"aggregations\": []}\n"
            "- 'find modules with no assignees' → {\"primary_entity\": \"module\", \"filters\": {\"assignee_count\": \"0\"}, \"aggregations\": []}\n"
            "- 'pages linked to exactly 2 cycles' → {\"primary_entity\": \"page\", \"filters\": {\"linkedCycle_count\": \"2\"}, \"aggregations\": []}\n"
            "- 'epics with at least 3 custom properties' → {\"primary_entity\": \"epic\", \"filters\": {\"customProperties_count\": \">=3\"}, \"aggregations\": []}\n\n"
            "CRITICAL: When you see phrases like 'multiple', 'more than', 'at least', 'exactly', 'no', 'unassigned', 'with X', 'has X' combined with array field names (assignees, labels, dependencies, etc.), you MUST add the corresponding _count filter.\n\n"
            "## ADVANCED OPERATOR EXAMPLES (MUST FOLLOW THESE PATTERNS)\n"
            "- Query: 'work items with assignees matching role Developer'\n"
            "  → filters: {\"assignee_elemMatch\": {\"role\": \"Developer\"}}\n"
            "- Query: 'work items with assignees matching name John and role Developer'\n"
            "  → filters: {\"assignee_elemMatch\": {\"name\": \"John\", \"role\": \"Developer\"}}\n\n"
            "CRITICAL: When users mention 'matching X', 'assignees matching', etc., you MUST add the appropriate $elemMatch filter.\n\n"
            "## ADVANCED AGGREGATION EXAMPLES (MUST FOLLOW THESE PATTERNS)\n"
            "- Query: 'break down work items by priority and status'\n"
            "  → aggregations: [\"facet\"], facet_fields: [\"priority\", \"status\"]\n"
            "- Query: 'auto-group work items by estimate'\n"
            "  → aggregations: [\"bucketAuto\"], bucket_field: \"estimate\"\n"
            "- Query: 'combine work items with user stories'\n"
            "  → aggregations: [\"unionWith\"], union_collection: \"userStory\"\n"
            "- Query: 'find project dependencies'\n"
            "  → aggregations: [\"graphLookup\"], graph_from: \"project\", graph_start: \"$_id\", graph_connect_from: \"_id\", graph_connect_to: \"dependsOn\"\n\n"
            "CRITICAL: When users mention 'break down by', 'auto-group', 'combine with', 'graph traversal', etc., you MUST add the appropriate aggregation.\n"
            "Do NOT skip this - these aggregations require special handling that cannot be achieved with basic operations.\n\n"
            "## TIME-SERIES EXAMPLES\n"
            "- '7-day rolling average of work items' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"timeWindow\"], \"window_field\": \"createdTimeStamp\", \"window_size\": \"7d\", \"window_unit\": \"day\"}\n"
            "- 'trend analysis for last month' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"trend\"], \"trend_field\": \"createdTimeStamp\", \"trend_period\": \"month\", \"trend_metric\": \"count\"}\n"
            "- 'detect anomalies in work item creation' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"anomaly\"], \"anomaly_field\": \"createdTimeStamp\", \"anomaly_metric\": \"count\", \"anomaly_threshold\": 2.0}\n"
            "- 'forecast work item creation for next week' → {\"primary_entity\": \"workItem\", \"aggregations\": [\"forecast\"], \"forecast_field\": \"createdTimeStamp\", \"forecast_periods\": 7, \"forecast_metric\": \"count\"}\n\n"

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
        requested_primary = (data.get("primary_entity") or "").strip()
        primary = requested_primary if requested_primary in self.entities else "workItem"

        # Allowed relations for primary
        allowed_rels = set(self.entity_relations.get(primary, []))
        target_entities: List[str] = []
        for rel in (data.get("target_entities") or []):
            if isinstance(rel, str) and rel.split(".")[0] in allowed_rels:
                target_entities.append(rel)

        # Simplified filter processing - keep valid filters, expanded to cover all collections
        raw_filters = data.get("filters") or {}
        filters: Dict[str, Any] = {}

        # Map legacy 'status' to 'state' for workItem if present
        if primary == "workItem" and "status" in raw_filters and "state" not in raw_filters:
            raw_filters["state"] = raw_filters.pop("status")

        # For epic collection, accept 'state_name' as the canonical filter key
        # and also map legacy 'status' to 'state_name' when provided by LLMs/users
        if primary == "epic" or primary == "features" or primary == "userStory":
            if "status" in raw_filters and "state_name" not in raw_filters:
                raw_filters["state_name"] = raw_filters.pop("status")
            # Some LLMs may emit 'state' for epics; prefer 'state_name'
            if "state" in raw_filters and "state_name" not in raw_filters:
                raw_filters["state_name"] = raw_filters.pop("state")

        # Allow plain 'status' for project/cycle as their canonical status
        if primary in ("project", "cycle") and "status" in raw_filters:
            if primary == "project" and "project_status" not in raw_filters:
                raw_filters["project_status"] = raw_filters["status"]
            if primary == "cycle" and "cycle_status" not in raw_filters:
                raw_filters["cycle_status"] = raw_filters["status"]

        if primary in ("workItem","epic","features","userStory") and "label" in raw_filters:
            raw_filters["label_name"] = raw_filters["label"]
        # Normalize date filter key synonyms BEFORE validation so they are preserved
        # Examples the LLM might emit: createdAt_from, created_from, date_to, updated_since, etc.
        def _normalize_date_filter_keys(primary_entity: str, rf: Dict[str, Any]) -> Dict[str, Any]:
            normalized: Dict[str, Any] = {}
            # Determine canonical created/updated fields per entity
            if primary_entity == "page" or primary_entity == "features" or primary_entity == "userStory":
                created_field = "createdAt"
                updated_field = "updatedAt"
            elif primary_entity == "members":
                # members commonly use joiningDate
                created_field = "joiningDate"
                updated_field = None
            else:
                # workItem/project/cycle/module use createdTimeStamp/updatedTimeStamp
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
            "state", "priority", "project_status", "cycle_status", "page_visibility",
            "status", "access", "isActive", "isArchived", "isDefault", "isFavourite",
            "visibility", "locked",
            # name/title/id style queries
            "label_name", "title", "name", "displayBugNo", "projectDisplayId", "email",
            # entity name filters (secondary lookups)
            "project_name", "cycle_name", "assignee_name", "module_name", "member_role",
            # actor/name filters
            "createdBy_name", "lead_name", "leadMail", "business_name",
            # timeline specific actor/task tokens
            "actor_name", "work_item_title",
            "defaultAssignee_name", "defaultAsignee_name", "staff_name",
            # members specific
            "role", "type", "joiningDate", "joiningDate_from", "joiningDate_to",
            # Array size filters (CRITICAL - must be in known_filter_keys)
            "assignee_count", "label_count", "customProperties_count",
            "functionalRequirements_count", "nonFunctionalRequirements_count",
            "dependencies_count", "risks_count", "workItems_count", "userStories_count",
            "goals_count", "painPoints_count", "successCriteria_count",
            "linkedCycle_count", "linkedModule_count", "linkedPages_count",
            # Advanced MongoDB operator filters (CRITICAL - must be in known_filter_keys)
            "$text",  # Full-text search
            # Note: _elemMatch is handled dynamically via suffix matching
            #feature_specific

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
            elif k.endswith("_count") and isinstance(v, (str, int)):
                # Array size filters: keep as-is (values like ">1", ">=2", "0", "3", etc.)
                filters[k] = str(v).strip() if isinstance(v, str) else str(v)
            elif k == "$text" and isinstance(v, str):
                # Full-text search: keep as-is
                filters[k] = v.strip()
            elif k.endswith("_elemMatch") and isinstance(v, dict):
                # $elemMatch operator filters: keep as-is (values are objects)
                filters[k] = v
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

        # 3) Advanced feature detection from query text (heuristic fallback)
        
        
        # Graph lookup detection
        if re.search(r"\bdependenc(?:y|ies)\b.*\bgraph\b|\bgraph\b.*\bdependenc(?:y|ies)\b|\bdependency\s+chain\b|\bdepends?\s+on\b.*\bgraph\b", oq_text):
            if "graphLookup" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("graphLookup")
                data["aggregations"] = aggregations
            # Infer graph connection fields if not provided
            if not data.get("graph_connect_to"):
                if "depends" in oq_text or "dependency" in oq_text:
                    data["graph_connect_to"] = "dependsOn"
                elif primary == "project":
                    data["graph_connect_to"] = "parentProjectId"
        
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
                    data["window_field"] = "createdTimeStamp" if primary != "page" else "createdAt"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["window_field"] = "updatedTimeStamp" if primary != "page" else "updatedAt"
        
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
                    data["trend_field"] = "createdTimeStamp" if primary != "page" else "createdAt"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["trend_field"] = "updatedTimeStamp" if primary != "page" else "updatedAt"
        
        # Anomaly detection
        if re.search(r"\banomal(?:y|ies)\b|\bunusual\b|\boutlier\b|\bspike\b|\bdetect.*\banomal\b", oq_text):
            if "anomaly" not in (data.get("aggregations") or []):
                aggregations = data.get("aggregations") or []
                aggregations.append("anomaly")
                data["aggregations"] = aggregations
            # Infer anomaly field
            if not data.get("anomaly_field"):
                if "created" in oq_text or "creation" in oq_text:
                    data["anomaly_field"] = "createdTimeStamp" if primary != "page" else "createdAt"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["anomaly_field"] = "updatedTimeStamp" if primary != "page" else "updatedAt"
                elif "completion" in oq_text:
                    data["anomaly_field"] = "updatedTimeStamp" if primary != "page" else "updatedAt"
        
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
                    data["forecast_field"] = "createdTimeStamp" if primary != "page" else "createdAt"
                elif "updated" in oq_text or "modified" in oq_text:
                    data["forecast_field"] = "updatedTimeStamp" if primary != "page" else "updatedAt"

        # Aggregations - include new advanced aggregation types
        allowed_aggs = {
            "count", "group", "summary",
            "graphLookup", "timeWindow", "trend", "anomaly", "forecast",
            "facet", "bucketAuto", "unionWith"
        }
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
            if primary == "page" or primary == "features" or primary == "userStory":
                key_map = {
                    "created": "createdAt",
                    "createdAt": "createdAt",
                    "created_time": "createdAt",
                    "time": "createdAt",
                    "date": "createdAt",
                    "timestamp": "updatedAt",
                }
            elif primary == "timeline":
                key_map = {
                    "created": "timestamp",
                    "createdAt": "timestamp",
                    "created_time": "timestamp",
                    "time": "timestamp",
                    "date": "timestamp",
                    "timestamp": "timestamp",
                }
            else:
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

        # Heuristic: timeline TIME_LOGGED queries that mention per-task breakdown should group by work item
        # This enables questions like "amount of time logged by <user> per task for today"
        if primary == "timeline":
            tval = str(filters.get("type", "")).lower()
            mentions_time = any(k in oq for k in ["time logged", "amount of time", "time spent", "logged time"]) or ("time_logged" in tval)
            mentions_per_task = any(k in oq for k in ["per task", "by task", "per work item", "by work item", "per ticket", "by ticket", "breakdown"])
            if mentions_time and (mentions_per_task or ("time_logged" in tval and not group_by)):
                if "group" not in aggregations:
                    aggregations = ["group"] + [a for a in aggregations if a != "group"]
                if not group_by:
                    group_by = ["work_item_title"]
                # Grouped summaries don't need wants_details by default
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
                elif primary in ("page", "userStory", "features") and "createdTimeStamp" in inferred_sort:
                    dirv = inferred_sort.get("createdTimeStamp", -1)
                    sort_order = {"createdAt": dirv}
                else:
                    sort_order = inferred_sort

        # Fetch one heuristic
        fetch_one = bool(data.get("fetch_one", False)) or (limit == 1)

        # Extract advanced aggregation fields
        facet_fields = data.get("facet_fields")
        bucket_field = data.get("bucket_field")
        union_collection = data.get("union_collection")
        
        # Graph lookup fields
        graph_from = data.get("graph_from")
        graph_start = data.get("graph_start")
        graph_connect_from = data.get("graph_connect_from")
        graph_connect_to = data.get("graph_connect_to")
        
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
        print(f"""
            ---- QueryIntent DEBUG ----
            primary_entity: {primary}
            target_entities: {target_entities}
            filters: {filters}
            aggregations: {aggregations}
            group_by: {group_by}
            projections: {projections}
            sort_order: {sort_order}
            limit: {limit}
            skip: {skip}
            wants_details: {wants_details}
            wants_count: {wants_count}
            fetch_one: {fetch_one}
            facet_fields: {facet_fields if facet_fields else None}
            bucket_field: {bucket_field if bucket_field else None}
            union_collection: {union_collection if union_collection else None}
            graph_from: {graph_from if graph_from else None}
            graph_start: {graph_start if graph_start else None}
            graph_connect_from: {graph_connect_from if graph_connect_from else None}
            graph_connect_to: {graph_connect_to if graph_connect_to else None}
            window_field: {window_field if window_field else None}
            window_size: {window_size if window_size else None}
            window_unit: {window_unit if window_unit else None}
            trend_field: {trend_field if trend_field else None}
            trend_period: {trend_period if trend_period else None}
            trend_metric: {trend_metric if trend_metric else None}
            anomaly_field: {anomaly_field if anomaly_field else None}
            anomaly_metric: {anomaly_metric if anomaly_metric else None}
            anomaly_threshold: {float(anomaly_threshold) if anomaly_threshold is not None else None}
            forecast_field: {forecast_field if forecast_field else None}
            forecast_periods: {int(forecast_periods) if forecast_periods is not None else None}
            ---------------------------
            """)

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
            facet_fields=facet_fields if facet_fields else None,
            bucket_field=bucket_field if bucket_field else None,
            union_collection=union_collection if union_collection else None,
            graph_from=graph_from if graph_from else None,
            graph_start=graph_start if graph_start else None,
            graph_connect_from=graph_connect_from if graph_connect_from else None,
            graph_connect_to=graph_connect_to if graph_connect_to else None,
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
        )

    async def _disambiguate_name_entity(self, proposed: Dict[str, str]) -> Optional[str]:
        """Use DB counts across collections to decide which name filter is most plausible.

        Preference order on ties: assignee -> project -> cycle -> module.
        Returns the chosen filter key or None if inconclusive.
        """
        # Build candidate lookups: mapping filter key -> (collection, field)
        candidates = {
            "assignee_name": ("members", "name"),
            "project_name": ("project", "name"),
            "cycle_name": ("cycle", "name"),
            "module_name": ("module", "name"),
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
        preference = {"assignee_name": 0, "project_name": 1, "cycle_name": 2, "module_name": 3}
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
