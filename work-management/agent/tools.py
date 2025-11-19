import sys
import logging
from time import perf_counter
from langchain_core.tools import tool
from typing import Optional, Dict, List, Any, Union
import mongo.constants
import os
import json
import re
from glob import glob
from datetime import datetime
from agent.orchestrator import Orchestrator, StepSpec, as_async
from qdrant.initializer import RAGTool

# Configure logging
logger = logging.getLogger(__name__)
# Qdrant and RAG dependencies
# try:
#     from qdrant_client import QdrantClient
#     from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
#     from sentence_transformers import SentenceTransformer
#     import numpy as np
# except ImportError:
#     QdrantClient = None
#     SentenceTransformer = None
#     np = None

mongodb_tools = mongo.constants.mongodb_tools
DATABASE_NAME = mongo.constants.DATABASE_NAME
try:
    from agent.planner import plan_and_execute_query, _format_pipeline_for_display
except ImportError:
    plan_and_execute_query = None
    _format_pipeline_for_display = None


# ------------------ RAG Retrieval Defaults ------------------
# Per content_type default limits for retrieval. These are applied when the caller
# does not explicitly provide a limit (i.e., limit is None).
# Rationale: pages/work_items generally require broader recall; projects/cycles/modules
# tend to be fewer and more concise.
CONTENT_TYPE_DEFAULT_LIMITS: Dict[str, int] = {
    "page": 12,
    "work_item": 12,
    "project": 6,
    "cycle": 6,
    "module": 6,
    "epic": 6,
}

# Fallback when content_type is unknown or not provided
DEFAULT_RAG_LIMIT: int = 10

# Optional: per content_type chunk-level tuning for chunk-aware retrieval
# - chunks_per_doc controls how many high-scoring chunks are kept per reconstructed doc
# - include_adjacent controls whether to pull neighboring chunks for context
# - min_score sets a score threshold for initial vector hits
CONTENT_TYPE_CHUNKS_PER_DOC: Dict[str, int] = {
    "page": 3,          # Reduced from 4 to minimize context window usage
    "work_item": 4,     # Reduced from 3 to minimize context window usage
    "project": 2,
    "cycle": 2,
    "module": 2,
    "epic": 2,
}

CONTENT_TYPE_INCLUDE_ADJACENT: Dict[str, bool] = {
    "page": True,      # Disabled to reduce context window usage (was True)
    "work_item": True,  # Keep adjacent for work items for better context
    "project": False,
    "cycle": False,
    "module": False,
    "epic": False,
}

CONTENT_TYPE_MIN_SCORE: Dict[str, float] = {
    "page": 0.5,
    "work_item": 0.5,
    "project": 0.55,
    "cycle": 0.55,
    "module": 0.55,
    "epic": 0.55,
}


def normalize_mongodb_types(obj: Any) -> Any:
    """Convert MongoDB extended JSON types to regular Python types."""
    if obj is None:
        return None

    if isinstance(obj, dict):
        # Handle MongoDB-specific types
        if '$binary' in obj:
            # Convert binary to string representation (we'll filter it out anyway)
            return f"<binary:{obj['$binary']['base64'][:8]}...>"
        elif '$date' in obj:
            # Convert MongoDB date to string representation
            return obj['$date']
        elif '$oid' in obj:
            # Convert ObjectId to string
            return obj['$oid']
        elif '$numberLong' in obj:
            # Convert MongoDB Long to Python int
            try:
                return int(obj['$numberLong'])
            except (ValueError, TypeError):
                return obj['$numberLong']  # Return as string if conversion fails
        elif '$numberDecimal' in obj:
            # Convert MongoDB Decimal128 to Python float
            try:
                return float(obj['$numberDecimal'])
            except (ValueError, TypeError):
                return obj['$numberDecimal']  # Return as string if conversion fails
        elif '$timestamp' in obj:
            # Convert MongoDB Timestamp to dict representation
            return f"<timestamp:{obj['$timestamp']['t']},{obj['$timestamp']['i']}>"
        elif '$regex' in obj:
            # Convert MongoDB Regex to string representation
            options = obj['$regex'].get('$options', '')
            return f"<regex:{obj['$regex']['$pattern']}{'/' + options if options else ''}>"
        elif '$minKey' in obj:
            # Convert MinKey to representation
            return "<minKey>"
        elif '$maxKey' in obj:
            # Convert MaxKey to representation
            return "<maxKey>"
        else:
            # Recursively process nested objects
            return {key: normalize_mongodb_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        # Process lists recursively
        return [normalize_mongodb_types(item) for item in obj]
    else:
        # Return primitive types as-is
        return obj


def filter_meaningful_content(data: Any) -> Any:
    """Filter MongoDB documents to keep only meaningful content fields.

    Removes unnecessary fields like _id, timestamps, and other metadata
    while preserving actual content like text, names, descriptions, etc.

    Args:
        data: Raw MongoDB document(s) - can be dict, list, or other types

    Returns:
        Filtered data with only meaningful content fields
    """
    # First, normalize MongoDB extended JSON to regular Python types
    normalized_data = normalize_mongodb_types(data)

    # Handle edge cases
    if normalized_data is None:
        return None

    # Define fields that contain meaningful content (not metadata)
    CONTENT_FIELDS = {
        # Text content
        'title', 'description', 'name', 'content', 'email', 'role',
        'priority', 'status', 'state', 'displayBugNo', 'projectDisplayId',
        # Business logic fields
        'label', 'type', 'access', 'visibility', 'icon', 'imageUrl',
        'business', 'staff', 'createdBy', 'assignee', 'project', 'cycle', 'module',
        'members', 'pages', 'projectStates', 'subStates', 'linkedCycle', 'linkedModule',
        'cycles','modules',
        # Date fields (but not timestamps)
        'startDate', 'endDate', 'joiningDate', 'createdAt', 'updatedAt',
        # Estimate and work tracking
        'estimate', 'estimateSystem', 'workLogs',
        # Count/aggregation results
        'total', 'count', 'group', 'items'
    }

    # Fields to always exclude (metadata)
    EXCLUDE_FIELDS = {
        '_id', 'createdTimeStamp', 'updatedTimeStamp',
        '_priorityRank',  # Helper field added by pipeline
        '_class',  # Drop Java class metadata
    }

    def is_meaningful_field(key: str, value: Any) -> bool:
        """Check if a field contains meaningful content."""
        # Always exclude metadata fields
        if key in EXCLUDE_FIELDS:
            return False

        # Keep content fields
        if key in CONTENT_FIELDS:
            return True

        # For unknown fields, check if they have meaningful values
        if isinstance(value, str) and value.strip():
            # Non-empty strings are meaningful
            return True
        elif isinstance(value, (int, float)) and not key.endswith(('Id', '_id')):
            # Numbers that aren't IDs are meaningful
            return True
        elif isinstance(value, bool):
            # Boolean values are meaningful
            return True
        elif isinstance(value, dict):
            # Recursively check nested objects
            return any(is_meaningful_field(k, v) for k, v in value.items())
        elif isinstance(value, list) and value:
            # Check if list contains meaningful content, including dict items
            for item in value:
                if isinstance(item, (str, int, float, bool)):
                    if not isinstance(item, str) or item.strip():
                        return True
                elif isinstance(item, dict):
                    if any(is_meaningful_field(k, v) for k, v in item.items()):
                        return True
            return False

        return False

    def clean_document(doc: Any) -> Any:
        """Clean a single document or value."""
        if isinstance(doc, dict):
            # Filter dictionary
            cleaned = {}
            for key, value in doc.items():
                if is_meaningful_field(key, value):
                    if isinstance(value, (dict, list)):
                        cleaned_value = clean_document(value)
                        if cleaned_value:  # Only add if there's meaningful content
                            cleaned[key] = cleaned_value
                    else:
                        cleaned[key] = value
            return cleaned if cleaned else {}
        elif isinstance(doc, list):
            # Filter list of documents
            cleaned = []
            for item in doc:
                cleaned_item = clean_document(item)
                if cleaned_item:  # Only add if there's meaningful content
                    cleaned.append(cleaned_item)
            return cleaned
        else:
            # Return primitive values as-is
            return doc

    return clean_document(normalized_data)


def _is_hex_object_id(value: str) -> bool:
    try:
        return isinstance(value, str) and len(value) == 24 and all(c in '0123456789abcdefABCDEF' for c in value)
    except Exception:
        return False


def _is_binary_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("<binary:")


def _is_uuid_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    # Simple UUID v4-like pattern check
    if len(value) != 36:
        return False
    parts = value.split("-")
    if len(parts) != 5:
        return False
    expected_lengths = [8, 4, 4, 4, 12]
    for part, L in zip(parts, expected_lengths):
        if len(part) != L:
            return False
        if not all(c in '0123456789abcdefABCDEF' for c in part):
            return False
    return True


def _is_id_like_key(key: str) -> bool:
    # Allowlist display ids
    ALLOWLIST = {"projectDisplayId"}
    if key in ALLOWLIST:
        return False
    lowered = key.lower()
    return (
        key == "_id"
        or lowered == "id"
        or lowered.endswith("id")  # memberId, projectId, defaultAsigneeId, etc.
        or lowered.endswith("_id")
        or lowered.endswith("uuid")
    )


def _strip_ids(value: Any) -> Any:
    """Recursively remove id/uuid-like fields and raw id values from documents."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            if _is_id_like_key(k):
                # drop id-like keys entirely
                continue
            # Recurse first
            v2 = _strip_ids(v)
            # Drop values that are just IDs or binary placeholders
            if isinstance(v2, str) and (_is_hex_object_id(v2) or _is_uuid_string(v2) or _is_binary_placeholder(v2)):
                continue
            if v2 is None:
                continue
            # Drop empty containers
            if isinstance(v2, (dict, list)) and not v2:
                continue
            cleaned[k] = v2
        return cleaned
    if isinstance(value, list):
        items = [_strip_ids(x) for x in value]
        items = [x for x in items if x not in (None, {}) and not (isinstance(x, str) and (_is_hex_object_id(x) or _is_uuid_string(x) or _is_binary_placeholder(x)))]
        return items
    return value


def _ensure_list_of_names(obj: Any) -> List[str]:
    names: List[str] = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title")
                if isinstance(name, str) and name.strip():
                    names.append(name)
            elif isinstance(item, str) and item.strip() and not _is_hex_object_id(item) and not _is_binary_placeholder(item):
                names.append(item)
    elif isinstance(obj, dict):
        name = obj.get("name") or obj.get("title")
        if isinstance(name, str) and name.strip():
            names.append(name)
    elif isinstance(obj, str) and obj.strip():
        names.append(obj)
    return names


def _transform_by_collection(doc: Dict[str, Any], collection: Optional[str]) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        return doc  # type: ignore[return-value]

    collection = (collection or "").strip()
    out: Dict[str, Any] = {}

    def copy_if_present(key: str, alias: Optional[str] = None):
        val = doc.get(key)
        if val is not None:
            out[alias or key] = val

    # Common flatteners
    def set_name(source_key: str, target_key: str):
        val = doc.get(source_key)
        if isinstance(val, dict):
            name = val.get("name") or val.get("title")
            if name:
                out[target_key] = name

    def set_names_list(source_key: str, target_key: str):
        val = doc.get(source_key)
        names = _ensure_list_of_names(val)
        if names:
            out[target_key] = names

    # Always useful common keys
    for k in ["title", "name", "description", "status", "priority", "label",
              "visibility", "access", "imageUrl", "icon",
              "favourite", "isFavourite", "isActive", "isArchived",
              "content", "displayBugNo", "projectDisplayId",
              "startDate", "endDate", "createdAt", "updatedAt",
              "estimate", "estimateSystem", "workLogs"]:
        if k in doc:
            out[k] = doc[k]

    # Per collection enrichments
    if collection == "workItem":
        set_name("project", "projectName")
        set_name("state", "stateName")
        set_name("stateMaster", "stateMasterName")
        set_name("cycle", "cycleName")
        # modules in schema is a single subdoc despite plural key
        set_name("modules", "moduleName")
        set_name("business", "businessName")
        set_name("createdBy", "createdByName")
        set_names_list("assignee", "assignees")
        set_names_list("updatedBy", "updatedByNames")

        # Handle estimate object
        estimate = doc.get("estimate")
        if isinstance(estimate, dict):
            if isinstance(estimate.get("hr"), (int, float)):
                out["estimateHours"] = estimate["hr"]
            if isinstance(estimate.get("min"), (int, float)):
                out["estimateMinutes"] = estimate["min"]
            # Calculate total minutes
            total_minutes = 0
            if isinstance(estimate.get("hr"), (int, float)):
                total_minutes += estimate["hr"] * 60
            if isinstance(estimate.get("min"), (int, float)):
                total_minutes += estimate["min"]
            if total_minutes > 0:
                out["estimateTotalMinutes"] = total_minutes

        # Handle workLogs array
        work_logs = doc.get("workLogs")
        if isinstance(work_logs, list) and work_logs:
            out["workLogsCount"] = len(work_logs)
            total_logged_minutes = 0
            for log in work_logs:
                if isinstance(log, dict):
                    if isinstance(log.get("hours"), (int, float)):
                        total_logged_minutes += log["hours"] * 60
                    if isinstance(log.get("minutes"), (int, float)):
                        total_logged_minutes += log["minutes"]
            if total_logged_minutes > 0:
                out["totalLoggedMinutes"] = total_logged_minutes
                out["totalLoggedHours"] = round(total_logged_minutes / 60, 2)

    elif collection == "project":
        set_name("business", "businessName")
        set_name("lead", "leadName")
        set_name("defaultAsignee", "defaultAssigneeName")
        set_name("createdBy", "createdByName")
        copy_if_present("leadMail")

    elif collection == "cycle":
        # Project may only contain id; we skip if name isn't present
        set_name("project", "projectName")
        set_name("business", "businessName")

    elif collection == "module":
        set_name("project", "projectName")
        set_name("lead", "leadName")
        set_name("business", "businessName")
        set_names_list("assignee", "assignees")

    elif collection == "members":
        set_name("project", "projectName")
        set_name("staff", "staffName")

    elif collection == "page":
        set_name("project", "projectName")
        set_name("createdBy", "createdByName")
        set_name("business", "businessName")

        # Handle complex page content structure (Editor.js format)
        content = doc.get("content")
        if isinstance(content, dict):
            blocks = content.get("blocks")
            if isinstance(blocks, list):
                out["contentBlocksCount"] = len(blocks)
                # Extract text content from blocks
                text_blocks = []
                for block in blocks:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        block_data = block.get("data")
                        if isinstance(block_data, dict):
                            if block_type == "paragraph":
                                text = block_data.get("text", "")
                                if text.strip():
                                    text_blocks.append(truncate_str(text, 100))
                            elif block_type == "header":
                                text = block_data.get("text", "")
                                if text.strip():
                                    text_blocks.append(f"Header: {truncate_str(text, 100)}")
                if text_blocks:
                    out["contentPreview"] = text_blocks[:3]  # First 3 meaningful blocks

        # Handle linkedPages array
        if isinstance(doc.get("linkedPages"), list):
            out["linkedPagesCount"] = len(doc["linkedPages"])

        # Linked arrays could contain ids only; surface counts
        if isinstance(doc.get("linkedCycle"), list):
            out["linkedCycleCount"] = len(doc["linkedCycle"])  # type: ignore[index]
        if isinstance(doc.get("linkedModule"), list):
            out["linkedModuleCount"] = len(doc["linkedModule"])  # type: ignore[index]
        # Also surface names if available
        set_names_list("linkedCycle", "linkedCycleNames")
        set_names_list("linkedModule", "linkedModuleNames")
        set_names_list("linkedPages", "linkedPagesNames")

    elif collection == "projectState":
        # Keep core fields and slim subStates
        substates = doc.get("subStates")
        if isinstance(substates, list):
            slim: List[Dict[str, Any]] = []
            for s in substates:
                if isinstance(s, dict):
                    entry: Dict[str, Any] = {}
                    if isinstance(s.get("name"), str):
                        entry["name"] = s["name"]
                    if isinstance(s.get("order"), (int, float)):
                        entry["order"] = s["order"]
                    if entry:
                        slim.append(entry)
            if slim:
                out["subStates"] = slim

    elif collection == "timeline":
        # Surface friendly names and key attributes
        set_name("project", "projectName")
        # user is actor
        set_name("user", "actorName")
        # include work item title if present
        if isinstance(doc.get("workItemTitle"), str):
            out["workItemTitle"] = doc["workItemTitle"]
        # event type and field changed are useful summarizers
        if isinstance(doc.get("type"), str):
            out["timelineType"] = doc["type"]
        if isinstance(doc.get("fieldChanged"), str):
            out["fieldChanged"] = doc["fieldChanged"]

    elif collection == "epic":
        set_name("project", "projectName")
        set_name("business", "businessName")
        set_name("createdBy", "createdByName")
        set_names_list("assignee", "assignees")

        # Handle customProperties array with complex structures
        custom_props = doc.get("customProperties")
        if isinstance(custom_props, list) and custom_props:
            out["customPropertiesCount"] = len(custom_props)
            # Surface custom property types and values
            prop_types = []
            for prop in custom_props[:5]:  # First 5 properties
                if isinstance(prop, dict):
                    prop_type = prop.get("type") or prop.get("propertyType")
                    prop_value = prop.get("value") or prop.get("propertyValue")
                    if prop_type and prop_value:
                        prop_types.append(f"{prop_type}: {truncate_str(str(prop_value), 50)}")
                    elif prop_type:
                        prop_types.append(str(prop_type))
            if prop_types:
                out["customPropertiesSample"] = prop_types

    elif collection == "features":
        set_name("project", "projectName")
        set_name("business", "businessName")
        set_name("lead", "leadName")
        set_name("createdBy", "createdByName")
        set_name("cycle", "cycleName")
        set_name("modules", "moduleName")
        set_name("parent", "parentName")
        set_names_list("assignee", "assignees")

        # Handle nested basicInfo structure
        basic_info = doc.get("basicInfo")
        if isinstance(basic_info, dict):
            if isinstance(basic_info.get("title"), str):
                out["basicInfoTitle"] = basic_info["title"]
            if isinstance(basic_info.get("description"), str):
                out["basicInfoDescription"] = truncate_str(basic_info["description"], 200)

        # Handle nested problemInfo structure
        problem_info = doc.get("problemInfo")
        if isinstance(problem_info, dict):
            if isinstance(problem_info.get("statement"), str):
                out["problemStatement"] = truncate_str(problem_info["statement"], 200)
            if isinstance(problem_info.get("objective"), str):
                out["problemObjective"] = truncate_str(problem_info["objective"], 200)

        # Handle nested requirements structure
        requirements = doc.get("requirements")
        if isinstance(requirements, dict):
            functional_reqs = requirements.get("functionalRequirements")
            if isinstance(functional_reqs, list):
                out["functionalRequirementsCount"] = len(functional_reqs)
                # Surface first few requirements
                if functional_reqs and len(functional_reqs) > 0:
                    sample_reqs = [req for req in functional_reqs[:3] if isinstance(req, str)]
                    if sample_reqs:
                        out["functionalRequirementsSample"] = sample_reqs

            non_functional_reqs = requirements.get("nonFunctionalRequirements")
            if isinstance(non_functional_reqs, list):
                out["nonFunctionalRequirementsCount"] = len(non_functional_reqs)
                # Surface first few requirements
                if non_functional_reqs and len(non_functional_reqs) > 0:
                    sample_reqs = [req for req in non_functional_reqs[:3] if isinstance(req, str)]
                    if sample_reqs:
                        out["nonFunctionalRequirementsSample"] = sample_reqs

        # Handle nested riskAndDependencies structure
        risk_deps = doc.get("riskAndDependencies")
        if isinstance(risk_deps, dict):
            dependencies = risk_deps.get("dependencies")
            if isinstance(dependencies, list):
                out["dependenciesCount"] = len(dependencies)
                # Surface dependency titles
                dep_titles = []
                for dep in dependencies:
                    if isinstance(dep, dict) and dep.get("title"):
                        dep_titles.append(dep["title"])
                    elif isinstance(dep, str):
                        dep_titles.append(dep)
                if dep_titles:
                    out["dependencyTitles"] = dep_titles[:5]  # First 5 dependencies

            risks = risk_deps.get("risks")
            if isinstance(risks, list):
                out["risksCount"] = len(risks)
                # Surface risk summaries
                risk_summaries = []
                for risk in risks[:3]:  # First 3 risks
                    if isinstance(risk, dict):
                        summary = ""
                        if risk.get("problemLevel"):
                            summary += f"Problem: {risk['problemLevel']}"
                        if risk.get("impactLevel"):
                            summary += f", Impact: {risk['impactLevel']}"
                        if summary:
                            risk_summaries.append(summary)
                if risk_summaries:
                    out["riskSummaries"] = risk_summaries

        # Handle various array fields
        if isinstance(doc.get("workItems"), list):
            out["workItemsCount"] = len(doc["workItems"])
        if isinstance(doc.get("userStories"), list):
            out["userStoriesCount"] = len(doc["userStories"])
        if isinstance(doc.get("goals"), list):
            out["goalsCount"] = len(doc["goals"])
        if isinstance(doc.get("painPoints"), list):
            out["painPointsCount"] = len(doc["painPoints"])

        # Handle successCriteria (could be in problemInfo or top-level)
        success_criteria = doc.get("problemInfo", {}).get("successCriteria") or doc.get("successCriteria")
        if isinstance(success_criteria, list) and success_criteria:
            out["successCriteriaCount"] = len(success_criteria)
            # Surface first few criteria
            criteria_text = [str(c) for c in success_criteria[:3] if c]
            if criteria_text:
                out["successCriteriaSample"] = criteria_text

    elif collection == "userStory":
        set_name("project", "projectName")
        set_name("business", "businessName")
        set_name("createdBy", "createdByName")
        set_name("epic", "epicName")
        set_name("feature", "featureName")
        set_names_list("assignee", "assignees")

        # Handle demographics
        demographics = doc.get("demographics")
        if isinstance(demographics, dict):
            # Surface demographic information
            for key, value in demographics.items():
                if isinstance(value, str):
                    out[f"demographic{key.title()}"] = value

        # Handle acceptance criteria
        acceptance_criteria = doc.get("acceptanceCriteria")
        if isinstance(acceptance_criteria, list) and acceptance_criteria:
            out["acceptanceCriteriaCount"] = len(acceptance_criteria)
            # Surface first few criteria
            criteria_text = [str(c) for c in acceptance_criteria[:3] if c]
            if criteria_text:
                out["acceptanceCriteriaSample"] = criteria_text

        # Handle persona object with detailed structure
        persona = doc.get("persona")
        if isinstance(persona, dict):
            # Basic persona info
            if isinstance(persona.get("personaName"), str):
                out["personaName"] = persona["personaName"]
            if isinstance(persona.get("role"), str):
                out["personaRole"] = persona["role"]
            if isinstance(persona.get("techLevel"), str):
                out["personaTechLevel"] = persona["techLevel"]

            # Handle goals array
            goals = persona.get("goals")
            if isinstance(goals, list):
                out["personaGoalsCount"] = len(goals)
                # Surface first few goals
                goal_texts = [str(g) for g in goals[:3] if g]
                if goal_texts:
                    out["personaGoalsSample"] = goal_texts

            # Handle pain points array
            pain_points = persona.get("painPoints")
            if isinstance(pain_points, list):
                out["personaPainPointsCount"] = len(pain_points)
                # Surface first few pain points
                pain_texts = [str(p) for p in pain_points[:3] if p]
                if pain_texts:
                    out["personaPainPointsSample"] = pain_texts

    # Drop empty/None values and metadata keys
    out = {k: v for k, v in out.items() if v not in (None, "", [], {}) and k != "_class"}
    return out


def truncate_str(s: Any, limit: int = 120) -> str:
    """Truncate string to specified limit with ellipsis."""
    if not isinstance(s, str):
        return str(s)
    return s if len(s) <= limit else s[:limit] + "..."


def filter_and_transform_content(data: Any, primary_entity: Optional[str] = None) -> Any:
    """Preserve meaningful fields, strip IDs/UUIDs, and flatten references per collection.

    Steps:
    1) Use existing filter to keep meaningful content fields.
    2) Strip any remaining id/uuid-like keys/values.
    3) Apply per-collection flatteners to surface human-friendly names.
    """
    base = filter_meaningful_content(data)
    stripped = _strip_ids(base)

    def enrich(obj: Any) -> Any:
        if isinstance(obj, dict):
            # Merge base with collection-specific projection
            extra = _transform_by_collection(obj, primary_entity)
            # Overlay extra on top of obj (extra wins)
            merged = {**obj, **extra}
            return {k: v for k, v in merged.items() if v not in (None, "", [], {})}
        return obj

    if isinstance(stripped, list):
        return [enrich(x) for x in stripped]
    if isinstance(stripped, dict):
        return enrich(stripped)
    return stripped


@tool
async def mongo_query(query: str, show_all: bool = False) -> str:
    """Plan-first Mongo query executor for structured, factual questions.

    Use this ONLY when the user asks for authoritative data that must come from
    MongoDB (counts, lists, filters, group-by, breakdowns, state/assignee/project details)
    across collections: `project`, `workItem`, `cycle`, `module`, `epic`, `members`,
    `page`, `projectState`, `userStory`, `features`.

    Do NOT use this for:
    - Free-form content questions (use `rag_search`).
    - Pure summarization or opinion without data retrieval.
    - When you already have the exact answer in prior tool results.

    Behavior:
    - Follows a planner to generate a safe aggregation pipeline; avoids
      hallucinated fields.
    - Automatically determines when complex joins are beneficial based on query requirements.
    - Intelligently adds strategic relationships only when they improve query performance:
        - Multi-hop queries: "work items by business" (workItem→project→business)
        - Cross-collection analysis: "members working on projects by business"
        - Complex grouping that spans multiple collections
    - Only adds joins that provide clear benefits for the specific query, avoiding unnecessary complexity.

    Args:
        query: Natural language, structured data request about PM entities.
        show_all: If True, output full details instead of a summary. Use sparingly.

    Returns: A compact result suitable for direct user display.
    """
    tool_start_time = perf_counter()
    if not plan_and_execute_query:
        return "❌ Intelligent query planner not available. Please ensure query_planner.py is properly configured."

    try:
        result = await plan_and_execute_query(query)

        if result["success"]:
            response = f"🎯 INTELLIGENT QUERY RESULT:\n"
            response += f"Query: '{query}'\n\n"

            # Show parsed intent
            intent = result["intent"]
            response += f"📋 UNDERSTOOD INTENT:\n"
            if result.get("planner"):
                response += f"• Planner: {result['planner']}\n"
            response += f"• Primary Entity: {intent['primary_entity']}\n"
            if intent['target_entities']:
                response += f"• Related Entities: {', '.join(intent['target_entities'])}\n"
            if intent['filters']:
                response += f"• Filters: {intent['filters']}\n"
            if intent['aggregations']:
                response += f"• Aggregations: {', '.join(intent['aggregations'])}\n"
            response += "\n"

            # Show the generated pipeline (first few stages)
            pipeline = result.get("pipeline")
            pipeline_js = result.get("pipeline_js")
            if pipeline_js:
                response += f"🔧 GENERATED PIPELINE:\n"
                response += pipeline_js
                response += "\n"
            elif pipeline:
                response += f"🔧 GENERATED PIPELINE:\n"
                if _format_pipeline_for_display:
                    formatted_pipeline = _format_pipeline_for_display(pipeline)
                    response += formatted_pipeline
                else:
                    for i, stage in enumerate(pipeline):
                        stage_name = list(stage.keys())[0]
                        # Format the stage content nicely
                        stage_content = json.dumps(stage[stage_name], indent=2)
                        # Truncate very long content for readability but show complete structure
                        if len(stage_content) > 200:
                            stage_content = stage_content + "..."
                        response += f"• {stage_name}: {stage_content}\n"
                response += "\n"

            # Show results (compact preview)
            rows = result.get("result")
            try:
                # Attempt to parse stringified JSON results
                if isinstance(rows, str):
                    parsed = json.loads(rows)
                else:
                    parsed = rows
            except Exception:
                parsed = rows

            # Handle count results specially
            if isinstance(parsed, list) and len(parsed) > 0:
                first_item = parsed[0]
                if isinstance(first_item, dict) and "total" in first_item and len(first_item) == 1:
                    # This is a count result
                    count = first_item["total"]
                    response += f"📊 RESULT:\n"
                    response += f"Total count: {count}\n\n"
                    return response

            # Handle the specific MongoDB response format
            if isinstance(parsed, list) and len(parsed) > 0:
                # Check if first element is a string (like "Found X documents...")
                if isinstance(parsed[0], str) and parsed[0].startswith("Found"):
                    # This is the MongoDB response format: [message, doc1_json, doc2_json, ...]
                    # Parse the JSON strings and filter them
                    documents = []
                    for item in parsed[1:]:  # Skip the first message
                        if isinstance(item, str):
                            try:
                                doc = json.loads(item)
                                filtered_doc = filter_meaningful_content(doc)
                                if filtered_doc:  # Only add if there's meaningful content
                                    documents.append(filtered_doc)
                            except Exception:
                                # Skip invalid JSON
                                continue
                        else:
                            # Already parsed, filter directly
                            filtered_doc = filter_meaningful_content(item)
                            if filtered_doc:
                                documents.append(filtered_doc)

                    filtered = documents
                else:
                    # Regular list, filter as before
                    filtered = parsed
            else:
                # Not a list, filter as before
                filtered = parsed


            def format_llm_friendly(data, max_items=50, primary_entity: Optional[str] = None):
                """Format data in a more LLM-friendly way to avoid hallucinations."""
                def get_nested(d: Dict[str, Any], key: str) -> Any:
                    if key in d:
                        return d[key]
                    if "." in key:
                        cur: Any = d
                        for part in key.split("."):
                            if isinstance(cur, dict) and part in cur:
                                cur = cur[part]
                            else:
                                return None
                        return cur
                    return None

                def ensure_list_str(val: Any) -> List[str]:
                    if isinstance(val, list):
                        res: List[str] = []
                        for x in val:
                            if isinstance(x, str) and x.strip():
                                res.append(x)
                            elif isinstance(x, dict):
                                n = x.get("name") or x.get("title")
                                if isinstance(n, str) and n.strip():
                                    res.append(n)
                        return res
                    if isinstance(val, dict):
                        n = val.get("name") or val.get("title")
                        return [n] if isinstance(n, str) and n.strip() else []
                    if isinstance(val, str) and val.strip():
                        return [val]
                    return []

                def truncate_str(s: Any, limit: int = 120) -> str:
                    if not isinstance(s, str):
                        return str(s)
                    return s if len(s) <= limit else s[:limit] + "..."

                def render_line(entity: Dict[str, Any]) -> str:
                    e = (primary_entity or "").lower()
                    if e == "workitem":
                        bug = entity.get("displayBugNo") or entity.get("title") or "Item"
                        title = entity.get("title") or entity.get("name") or ""
                        state = entity.get("stateName") or get_nested(entity, "state.name")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        assignees = ensure_list_str(entity.get("assignees") or entity.get("assignee"))
                        priority = entity.get("priority")
                        label = get_nested(entity,"label.name")
                        # Build base line
                        base = f"• {bug}: {truncate_str(title, 80)} — state={state or 'N/A'}, priority={priority or 'N/A'}, assignee={(assignees[0] if assignees else 'N/A')}, project={project or 'N/A'}, label={label or 'N/A'}"
                        
                        # Add estimate if present
                        estimate = entity.get("estimate")
                        if estimate and isinstance(estimate, dict):
                            hr = estimate.get("hr", "0")
                            min_val = estimate.get("min", "0")
                            base += f", estimate={hr}h {min_val}m"
                        elif estimate:
                            base += f", estimate={estimate}"
                        
                        # Add work logs if present
                        work_logs = entity.get("workLogs")
                        if work_logs and isinstance(work_logs, list) and len(work_logs) > 0:
                            total_hours = sum(log.get("hours", 0) for log in work_logs if isinstance(log, dict))
                            total_mins = sum(log.get("minutes", 0) for log in work_logs if isinstance(log, dict))
                            total_hours += total_mins // 60
                            total_mins = total_mins % 60
                            base += f", logged={total_hours}h {total_mins}m ({len(work_logs)} logs)"
                            
                            descriptions = [
                                log.get("description", "").strip()
                                for log in work_logs
                                if isinstance(log, dict) and log.get("description")
                            ]
                            descriptions_text = "; ".join(descriptions) if descriptions else "No descriptions"

                            base += f", descriptions=[{descriptions_text}]"
                        return base
                    if e == "project":
                        pid = entity.get("projectDisplayId")
                        name = entity.get("name") or entity.get("title")
                        status_v = entity.get("status")
                        lead = entity.get("leadName") or get_nested(entity, "lead.name")
                        business = entity.get("businessName") or get_nested(entity, "business.name")
                        return f"• {pid or name}: {name or ''} — status={status_v or 'N/A'}, lead={lead or 'N/A'}, business={business or 'N/A'}"
                    if e == "cycle":
                        title = entity.get("title") or entity.get("name")
                        status_v = entity.get("status")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        sd = entity.get("startDate")
                        ed = entity.get("endDate")
                        dates = f"{sd} → {ed}" if sd or ed else "N/A"
                        return f"• {truncate_str(title or 'Cycle', 80)} — status={status_v or 'N/A'}, project={project or 'N/A'}, dates={dates}"
                    if e == "module":
                        title = entity.get("title") or entity.get("name")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        assignees = ensure_list_str(entity.get("assignees") or entity.get("assignee"))
                        business = entity.get("businessName") or get_nested(entity, "business.name")
                        return f"• {truncate_str(title or 'Module', 80)} — project={project or 'N/A'}, assignees={(len(assignees) if assignees else 0)}, business={business or 'N/A'}"
                    if e == "members":
                        name = entity.get("name")
                        email = entity.get("email")
                        role = entity.get("role")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        type_v = entity.get("type")
                        return f"• {name or 'Member'} — role={role or 'N/A'}, email={email or 'N/A'}, type={type_v or 'N/A'}, project={project or 'N/A'}"
                    if e == "page":
                        title = entity.get("title") or entity.get("name")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        visibility = entity.get("visibility")
                        fav = entity.get("isFavourite")
                        return f"• {truncate_str(title or 'Page', 80)} — visibility={visibility or 'N/A'}, favourite={fav if fav is not None else 'N/A'}, project={project or 'N/A'}"
                    if e == "projectstate":
                        name = entity.get("name")
                        icon = entity.get("icon")
                        subs = entity.get("subStates")
                        sub_count = len(subs) if isinstance(subs, list) else 0
                        return f"• {name or 'State'} — icon={icon or 'N/A'}, substates={sub_count}"
                    
                    if e == "epic":
                        title = entity.get("title") or entity.get("name")
                        description = entity.get("description")
                        state = entity.get("stateName") or get_nested(entity, "state.name")
                        priority = entity.get("priority")
                        assignee = entity.get("assigneeName") or get_nested(entity, "assignee.name")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        bug_number = entity.get("bugNo")
                        label_name = get_nested(entity, "label.name")
                        return (
                            f"• {truncate_str(title or 'Epic', 80)} — "
                            f"description={truncate_str(description, 120)}, "
                            f"state={state or 'N/A'}, priority={priority or 'N/A'}, "
                            f"project={project or 'N/A'}, assignee={assignee or 'N/A'}, "
                            f"bugNo={bug_number or 'N/A'}, label={label_name or 'N/A'}"
                        )
                    
                    if e == "userStory":
                        bug = entity.get("displayBugNo") or entity.get("title") or "Item"
                        goal = entity.get("userGoal")
                        persona = entity.get("persona")
                        demographics = entity.get("demographics")
                        feature = entity.get("feature.name")
                        Accept_criteria = entity.get("acceptanceCriteria")
                        epic = entity.get("epic.name")
                        business = entity.get("business.name")
                        title = entity.get("title") or entity.get("name") or ""
                        description = entity.get("description")
                        state = entity.get("stateName") or get_nested(entity, "state.name")
                        assignees = ensure_list_str(entity.get("assignees") or entity.get("assignee"))
                        priority = entity.get("priority")
                        label = get_nested(entity,"label.name")
                        # Build base line
                        base = f"• {bug}: {truncate_str(title, 80)} — state={state or 'N/A'}, priority={priority or 'N/A'}, assignee={([i for i in assignees] if assignees else 'N/A')}, project={project or 'N/A'}, label={label or 'N/A'}, goal={goal or 'N/A'}, feature={feature or 'N/A'}, epic={epic or 'N/A'}, business={business or 'N/A'}, acceptanceCriteria={Accept_criteria or 'N/A'}"
                        
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                            
                        # Add persona info if present
                        if persona and isinstance(persona, dict):
                            name = persona.get("personaName", "")
                            role = persona.get("role", "")
                            techLevel = persona.get("techLevel", "")
                            base += f", persona=[name: {name}, role: {role}, techLevel: {techLevel}]"
                            goals = persona.get("goals")
                            if goals and isinstance(goals, list):
                                goals_text = "; ".join([str(g) for g in goals if isinstance(g, str) and g.strip()])
                                base += f", goals=[{goals_text or 'N/A'}]"
                        elif persona:
                            base += f", persona={persona or 'N/A'}"
                            
                        # Add demographics if present
                        if demographics:
                            if isinstance(demographics, dict):
                                demo_text = ", ".join([f"{k}: {v}" for k, v in demographics.items()])
                                base += f", demographics=[{demo_text or 'N/A'}]"
                            else:
                                base += f", demographics={demographics or 'N/A'}"

                    if e == "features":
                        bug = entity.get("displayBugNo") or entity.get("title") or "Item"
                        basicInfo = entity.get("basicInfo")
                        problemInfo = entity.get("problemInfo")
                        persona = entity.get("persona")
                        requirements = entity.get("requirements")
                        risksAndDependencies = entity.get("risksAndDependencies")
                        project = entity.get("projectName") or get_nested(entity, "project.name")
                        scope = entity.get("scope")
                        workitems = entity.get("workItems")
                        userStories = entity.get("userStories")
                        links = entity.get("addLink")
                        business = entity.get("business.name")
                        title = entity.get("title") or entity.get("name") or ""
                        description = entity.get("description")
                        state = entity.get("stateName") or get_nested(entity, "state.name")
                        lead = entity.get("leadName") or get_nested(entity, "lead.name")
                        assignees = ensure_list_str(entity.get("assignees") or entity.get("assignee"))
                        cycle = entity.get("cycle")
                        module = entity.get("modules.name")
                        parent = entity.get("parent.name")
                        priority = entity.get("priority")
                        label = get_nested(entity,"label.name")
                        estimatesystem = entity.get("estimateSystem")
                        # Build base line
                        base = f"• {bug}: {truncate_str(title, 80)} — state={state or 'N/A'}, priority={priority or 'N/A'}, assignee={(assignees[0] if assignees else 'N/A')}, project={project or 'N/A'}, label={label or 'N/A'}, lead={lead or 'N/A'}, cycle={cycle or 'N/A'}, module={module or 'N/A'}, parent={parent or 'N/A'}, business={business or 'N/A'}, estimatesystem={estimatesystem or 'N/A'}, scope={scope or 'N/A'}"
                        
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        
                        # Add userStories if present
                        if userStories:
                            if isinstance(userStories, list):
                                stories_text = "; ".join([str(s.get('title') if isinstance(s, dict) else s) for s in userStories if s])
                                base += f", userStories=[{stories_text or 'N/A'}]"
                            else:
                                base += f", userStories={userStories or 'N/A'}"

                        # Add workitems if present
                        if workitems:
                            if isinstance(workitems, list):
                                items_text = "; ".join([str(w.get('title') if isinstance(w, dict) else w) for w in workitems if w])
                                base += f", workItems=[{items_text or 'N/A'}]"
                            else:
                                base += f", workItems={workitems or 'N/A'}"

                        # Add links if present
                        if links:
                            if isinstance(links, list):
                                links_text = "; ".join([str(l.get('url') if isinstance(l, dict) else l) for l in links if l])
                                base += f", links=[{links_text or 'N/A'}]"
                            else:
                                base += f", links={links or 'N/A'}"
                        
                        #Add basic info
                        if basicInfo and isinstance(basicInfo, dict):
                            title = basicInfo.get("title","")
                            status = basicInfo.get("status","")
                            description = basicInfo.get("description","")
                            base += f", basicInfo=[title: {title or 'N/A'}, status: {status or 'N/A'}, description: {description or 'N/A'}]"
                        elif basicInfo:
                            base += f", basicInfo={basicInfo or 'N/A'}"
                        
                        #Add problem info
                        if problemInfo and isinstance(problemInfo, dict):
                            statement = problemInfo.get("statement","")
                            objective = problemInfo.get("objective","")
                            successCriteria = problemInfo.get("successCriteria")
                            if successCriteria and isinstance(successCriteria, list):
                                success_text = "; ".join([str(c) for c in successCriteria if isinstance(c, str) and c.strip()])
                            base += f", problemInfo=[statement: {statement or 'N/A'}, objective: {objective or 'N/A'}, successCriteria: [{success_text or 'N/A'}]]"
                        elif problemInfo:
                            base += f", problemInfo={problemInfo or 'N/A'}"
                        
                        #Add persona
                        if persona and isinstance(persona, dict):
                            name = persona.get("personaName","")
                            role = persona.get("role","")
                            techLevel = persona.get("techLevel","")
                            base += f", persona=[name: {name or 'N/A'}, role: {role or 'N/A'}, techLevel: {techLevel or 'N/A'}]"
                            goals = persona.get("goals")
                            if goals and isinstance(goals, list):
                                goals_text = "; ".join([str(g) for g in goals if isinstance(g, str) and g.strip()])
                                base += f", goals=[{goals_text or 'N/A'}]"
                            painPoints = persona.get("painPoints")
                            if painPoints and isinstance(painPoints, list):
                                pain_text = "; ".join([str(p) for p in painPoints if isinstance(p, str) and p.strip()])
                                base += f", painPoints=[{pain_text or 'N/A'}]"
                        elif persona:
                            base += f", persona={persona or 'N/A'}"
                        
                        # Add requirements
                        if requirements and isinstance(requirements, dict):
                            functionalRequirements = requirements.get("functionalRequirements")
                            if functionalRequirements and isinstance(functionalRequirements, list):
                                func_text = "; ".join([str(r) for r in functionalRequirements if isinstance(r, str) and r.strip()])
                                base += f", functionalRequirements=[{func_text or 'N/A'}]"
                            nonFunctionalRequirements = requirements.get("nonFunctionalRequirements")
                            if nonFunctionalRequirements and isinstance(nonFunctionalRequirements, list):
                                nonfunc_text = "; ".join([str(r) for r in nonFunctionalRequirements if isinstance(r, str) and r.strip()])
                                base += f", nonFunctionalRequirements=[{nonfunc_text or 'N/A'}]"
                        elif requirements:
                            base += f", requirements={requirements or 'N/A'}"

                        # Add risks, dependencies, design links and expectations
                        if risksAndDependencies and isinstance(risksAndDependencies, dict):
                            # Risks: list of objects
                            risks = risksAndDependencies.get("risks")
                            if risks and isinstance(risks, list):
                                risk_items: List[str] = []
                                for r in risks:
                                    if isinstance(r, dict):
                                        parts: List[str] = []
                                        prob = r.get("problemLevel")
                                        if prob:
                                            parts.append(f"problem={prob}")
                                        impact = r.get("impactLevel")
                                        if impact:
                                            parts.append(f"impact={impact}")
                                        owner = r.get("riskOwner")
                                        if owner:
                                            parts.append(f"owner={owner}")
                                        desc = r.get("description")
                                        if desc:
                                            parts.append(f"description={truncate_str(desc,120)}")
                                        strat = r.get("strategy")
                                        if strat:
                                            parts.append(f"strategy={truncate_str(strat,120)}")
                                        if parts:
                                            risk_items.append("{" + ", ".join(parts) + "}")
                                    elif isinstance(r, str) and r.strip():
                                        risk_items.append(r.strip())
                                if risk_items:
                                    base += f", risks=[{'; '.join(risk_items) or 'N/A'}]"

                            # Dependencies: simple list of strings or objects
                            dependencies = risksAndDependencies.get("dependencies")
                            if dependencies and isinstance(dependencies, list):
                                dep_text = "; ".join([
                                    str(d.get("title") if isinstance(d, dict) and d.get("title") else d).strip()
                                    for d in dependencies
                                    if (isinstance(d, str) and d.strip()) or (isinstance(d, dict) and (d.get("title") or d.get("id")))
                                ])
                                if dep_text:
                                    base += f", dependencies=[{dep_text or 'N/A'}]"

                            # Design links: list of {title, url, source}
                            designLinks = risksAndDependencies.get("designLinks")
                            if designLinks and isinstance(designLinks, list):
                                links: List[str] = []
                                for dl in designLinks:
                                    if isinstance(dl, dict):
                                        t = dl.get("title") or dl.get("name")
                                        u = dl.get("url") or dl.get("link")
                                        s = dl.get("source")
                                        parts = []
                                        if t:
                                            parts.append(str(t))
                                        if u:
                                            parts.append(f"{u}")
                                        if s:
                                            parts.append(f"{s}")
                                        if parts:
                                            links.append("(" + " | ".join(parts) + ")")
                                    elif isinstance(dl, str) and dl.strip():
                                        links.append(dl.strip())
                                if links:
                                    base += f", designLinks=[{'; '.join(links) or 'N/A'}]"

                            # Expectations: list of {stakeholder: {...}, expectation: str}
                            expectations = risksAndDependencies.get("expectations")
                            if expectations and isinstance(expectations, list):
                                exp_items: List[str] = []
                                for ex in expectations:
                                    if isinstance(ex, dict):
                                        stakeholder = ex.get("stakeholder")
                                        name = None
                                        if isinstance(stakeholder, dict):
                                            name = stakeholder.get("name") or stakeholder.get("title")
                                        elif isinstance(stakeholder, str) and stakeholder.strip():
                                            name = stakeholder.strip()
                                        expect_text = ex.get("expectation") or ex.get("expectations") or ex.get("expectationText")
                                        parts: List[str] = []
                                        if name:
                                            parts.append(f"stakeholder={name}")
                                        if expect_text:
                                            parts.append(f"expectation={truncate_str(expect_text,120)}")
                                        if parts:
                                            exp_items.append("{" + ", ".join(parts) + "}")
                                        else:
                                            # fallback to string representation
                                            exp_items.append(str(ex))
                                    elif isinstance(ex, str) and ex.strip():
                                        exp_items.append(ex.strip())
                                if exp_items:
                                    base += f", expectations=[{'; '.join(exp_items)}]"

                        # Add estimate if present
                        estimate = entity.get("estimate")
                        if estimate and isinstance(estimate, dict):
                            hr = estimate.get("hr", "0")
                            min_val = estimate.get("min", "0")
                            base += f", estimate={hr}h {min_val}m"
                        elif estimate:
                            base += f", estimate={estimate}"
                        
                        # Add work logs if present
                        work_logs = entity.get("workLogs")
                        if work_logs and isinstance(work_logs, list) and len(work_logs) > 0:
                            total_hours = sum(log.get("hours", 0) for log in work_logs if isinstance(log, dict))
                            total_mins = sum(log.get("minutes", 0) for log in work_logs if isinstance(log, dict))
                            total_hours += total_mins // 60
                            total_mins = total_mins % 60
                            base += f", logged={total_hours}h {total_mins}m ({len(work_logs)} logs)"
                            
                            descriptions = [
                                log.get("description", "").strip()
                                for log in work_logs
                                if isinstance(log, dict) and log.get("description")
                            ]
                            descriptions_text = "; ".join(descriptions) if descriptions else "No descriptions"

                            base += f", descriptions=[{descriptions_text}]"
                        return base
                    # Default fallback
                    title = entity.get("title") or entity.get("name") or "Item"
                    return f"• {truncate_str(title, 80)}"
                if isinstance(data, list):
                    # Handle count-only results
                    if len(data) == 1 and isinstance(data[0], dict) and "total" in data[0]:
                        return f"📊 RESULTS:\nTotal: {data[0]['total']}"

                    # Handle grouped/aggregated results
                    if len(data) > 0 and isinstance(data[0], dict) and ("count" in data[0] or "totalMinutes" in data[0]):
                        response = "📊 RESULTS SUMMARY:\n"
                        # Prefer minutes total when available, else use count
                        has_minutes = any('totalMinutes' in item for item in data)
                        total_items = sum(item.get('count', 0) for item in data)
                        total_minutes = sum(item.get('totalMinutes', 0) for item in data) if has_minutes else None

                        # Determine what type of grouping this is
                        first_item = data[0]
                        group_keys = [k for k in first_item.keys() if k not in ['count', 'items', 'totalMinutes']]

                        if group_keys:
                            if has_minutes and total_minutes is not None:
                                response += f"Found {len(data)} groups grouped by {', '.join(group_keys)} (total {int(total_minutes)} min):\n\n"
                            else:
                                response += f"Found {total_items} items grouped by {', '.join(group_keys)}:\n\n"

                            # Sort by count (highest first) and show more groups
                            if has_minutes:
                                sorted_data = sorted(data, key=lambda x: x.get('totalMinutes', 0), reverse=True)
                            else:
                                sorted_data = sorted(data, key=lambda x: x.get('count', 0), reverse=True)

                            # Show all groups if max_items is None, otherwise limit
                            display_limit = len(sorted_data) if max_items is None else 25
                            for item in sorted_data[:display_limit]:
                                group_values = [f"{k}: {item[k]}" for k in group_keys if k in item]
                                group_label = ', '.join(group_values)
                                if has_minutes:
                                    mins = int(item.get('totalMinutes', 0) or 0)
                                    response += f"• {group_label}: {mins} min\n"
                                else:
                                    count = item.get('count', 0)
                                    response += f"• {group_label}: {count} items\n"

                            if max_items is not None and len(data) > 25:
                                if has_minutes:
                                    remaining = sum(int(item.get('totalMinutes', 0) or 0) for item in sorted_data[25:])
                                    response += f"• ... and {len(data) - 25} other categories: {remaining} min\n"
                                else:
                                    remaining = sum(item.get('count', 0) for item in sorted_data[25:])
                                    response += f"• ... and {len(data) - 25} other categories: {remaining} items\n"
                            elif max_items is None and len(data) > display_limit:
                                if has_minutes:
                                    remaining = sum(int(item.get('totalMinutes', 0) or 0) for item in sorted_data[display_limit:])
                                    response += f"• ... and {len(data) - display_limit} other categories: {remaining} min\n"
                                else:
                                    remaining = sum(item.get('count', 0) for item in sorted_data[display_limit:])
                                    response += f"• ... and {len(data) - display_limit} other categories: {remaining} items\n"
                        else:
                            if has_minutes and total_minutes is not None:
                                response += f"Found total {int(total_minutes)} min\n"
                            else:
                                response += f"Found {total_items} items\n"
                        return response

                    # Handle list of documents - show summary instead of raw JSON
                    if max_items is not None and len(data) > max_items:
                        response = f"📊 RESULTS SUMMARY:\n"
                        response += f"Found {len(data)} items. Showing key details for last {max_items}:\n\n"
                        # Show sample items in a collection-aware way
                        for i, item in enumerate(data[-max_items:], len(data) - max_items + 1):
                            if isinstance(item, dict):
                                response += render_line(item) + "\n"
                        if len(data) > max_items:
                            response += f"• ... and {len(data) - max_items} items were omitted above\n"
                        return response
                    else:
                        # Show all items or small list - show in formatted way
                        response = "📊 RESULTS:\n"
                        for item in data:
                            if isinstance(item, dict):
                                response += render_line(item) + "\n"
                        return response

                # Single document or other data
                if isinstance(data, dict):
                    # Format single document in a readable way
                    response = "📊 RESULT:\n"
                    # Prefer a single-line summary first
                    if isinstance(data, dict):
                        response += render_line(data) + "\n\n"
                    # Then show key fields compactly (truncate long strings)
                    for key, value in data.items():
                        if isinstance(value, (str, int, float, bool)):
                            response += f"• {key}: {truncate_str(value, 140)}\n"
                        elif isinstance(value, dict):
                            # Show only shallow summary for dict
                            name_val = value.get('name') or value.get('title')
                            if name_val:
                                response += f"• {key}: {truncate_str(name_val, 120)}\n"
                            else:
                                child_keys = ", ".join(list(value.keys())[:5])
                                response += f"• {key}: {{ {child_keys} }}\n"
                        elif isinstance(value, list):
                            if len(value) <= 5:
                                response += f"• {key}: {truncate_str(str(value), 160)}\n"
                            else:
                                response += f"• {key}: [{len(value)} items]\n"
                    return response
                else:
                    # Fallback to JSON for other data types
                    return f"📊 RESULTS:\n{json.dumps(data, indent=2)}"

            # Apply strong filter/transform now that we know the primary entity
            primary_entity = intent.get('primary_entity') if isinstance(intent, dict) else None
            filtered = filter_and_transform_content(filtered, primary_entity=primary_entity)

            # Format in LLM-friendly way
            max_items = None if show_all else 50
            formatted_result = format_llm_friendly(filtered, max_items=max_items, primary_entity=primary_entity)
            # If members primary entity and no rows, proactively hint about filters
            try:
                if isinstance(result.get("intent"), dict) and result["intent"].get("primary_entity") == "members" and not filtered:
                    formatted_result += "\n(No members matched. Try filtering by name, role, type, or project.)"
            except Exception:
                pass
            response += formatted_result
            elapsed_ms = (perf_counter() - tool_start_time) * 1000
            print(f"mongo_query (including planner) for '{query[:50]}...' took {elapsed_ms:.2f} ms")
            return response
        else:
            return f"❌ QUERY FAILED:\nQuery: '{query}'\nError: {result['error']}"

    except Exception as e:
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"mongo_query for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {e}")
        return f"❌ INTELLIGENT QUERY ERROR:\nQuery: '{query}'\nError: {str(e)}"


@tool
async def rag_search(
    query: str,
    content_type: Optional[str] = None,
    group_by: Optional[str] = None,
    limit: int = 10,
    show_content: bool = True,
    use_chunk_aware: bool = True
) -> str:
    """Universal RAG search tool - returns FULL chunk content for LLM synthesis.
    
    **IMPORTANT**: This tool returns complete, untruncated content chunks so you can:
    - Analyze and understand the actual content
    - Generate properly formatted responses based on real data
    - Answer questions accurately using the retrieved context
    - Synthesize information from multiple sources
    
    Use this for ANY content-based search or analysis needs:
    - Find relevant pages, work items, projects, cycles, modules, epics, userstories, features
    - Search by semantic meaning (not just keywords)
    - Get full context for answering questions
    - Analyze content patterns and distributions
    - Group/breakdown results by any dimension
    
    **When to use:**
    - "Find/search/show me pages about X"
    - "What content discusses Y?"
    - "Which work items mention authentication?"
    - "Show me recent documentation about APIs"
    - "Break down results by project/date/priority/etc."
    
    **Do NOT use for:**
    - Structured database queries (counts, filters on structured fields) → use `mongo_query`
    
    Args:
        query: Search query (semantic meaning, not just keywords)
        content_type: Filter by type - 'page', 'work_item', 'project', 'cycle', 'module', 'epic', 'userStory', 'features' or None (all)
        group_by: Group results by field - 'project_name', 'updatedAt', 'priority', 'state_name', 
                 'content_type', 'assignee_name', 'visibility', etc. (None = no grouping)
        limit: Max results to retrieve (default 10, increase for broader searches)
        show_content: If True, shows full content; if False, shows only metadata
        use_chunk_aware: If True, uses chunk-aware retrieval for better context (default True)
    
    Returns: FULL chunk content with rich metadata - ready for LLM synthesis and formatting
    
    Examples:
        query="authentication" → finds all content about authentication with full text
        query="API documentation", content_type="page" → finds API docs pages with complete content
        query="bugs", content_type="work_item", group_by="priority" → work items grouped by priority
    """
    tool_start_time = perf_counter()
    try:
        # Fix: Add project root to sys.path to resolve module imports
        # This makes 'qdrant' and 'mongo' modules importable from any script location.
        # Adjust the number of os.path.dirname if your directory structure is different.
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.append(project_root)
        from qdrant.retrieval import ChunkAwareRetriever, format_reconstructed_results
    except ImportError as e:
        return f"❌ RAG dependency error: {e}. Please ensure all modules are in the correct path."
    except Exception as e:
        return f"❌ RAG SEARCH INITIALIZATION ERROR: {str(e)}"
    
    try:
        from collections import defaultdict

        # Ensure RAGTool is initialized
        try:
            rag_tool = RAGTool.get_instance()
        except RuntimeError:
            # Try to initialize if not already done
            await RAGTool.initialize()
            rag_tool = RAGTool.get_instance()
        
        # Resolve effective limit based on content_type defaults (opt-in when caller uses default)
        effective_limit: int = limit
        if content_type:
            default_for_type = CONTENT_TYPE_DEFAULT_LIMITS.get(content_type)
            if default_for_type is not None and (limit is None or limit == DEFAULT_RAG_LIMIT):
                effective_limit = default_for_type

        # Use chunk-aware retrieval if enabled and not grouping
        if use_chunk_aware and not group_by:
            from qdrant.retrieval import ChunkAwareRetriever, format_reconstructed_results
            
            retriever = ChunkAwareRetriever(
                qdrant_client=rag_tool.qdrant_client,
                embedding_client=rag_tool.embedding_client
            )
            
            from mongo.constants import QDRANT_COLLECTION_NAME
            
            # Per content_type chunk-level tuning
            chunks_per_doc = CONTENT_TYPE_CHUNKS_PER_DOC.get(content_type or "", 3)
            include_adjacent = CONTENT_TYPE_INCLUDE_ADJACENT.get(content_type or "", True)
            min_score = CONTENT_TYPE_MIN_SCORE.get(content_type or "", 0.5)

            from mongo.constants import RAG_CONTEXT_TOKEN_BUDGET
            reconstructed_docs = await retriever.search_with_context(
                query=query,
                collection_name=QDRANT_COLLECTION_NAME,
                content_type=content_type,
                limit=effective_limit,
                chunks_per_doc=chunks_per_doc,
                include_adjacent=include_adjacent,
                min_score=min_score,
                context_token_budget=RAG_CONTEXT_TOKEN_BUDGET
            )
            
            if not reconstructed_docs:
                return f"❌ No results found for query: '{query}'"
            
            # Always pass full content chunks to the agent by default for synthesis
            # Force show_full_content=True so downstream LLM has full context
            return format_reconstructed_results(
                docs=reconstructed_docs,
                show_full_content=True,
                show_chunk_details=True
            )
        
        # Fallback to standard retrieval
        results = await rag_tool.search_content(query, content_type=content_type, limit=effective_limit)
        
        if not results:
            return f"❌ No results found for query: '{query}'"
        
        # Build response header
        response = f"🔍 RAG SEARCH: '{query}'\n"
        response += f"Found {len(results)} result(s)"
        if content_type:
            response += f" (type: {content_type})"
        response += "\n\n"
        
        # NO GROUPING - Show detailed list with metadata
        if not group_by:
            response += "📋 RESULTS:\n\n"
            for i, result in enumerate(results[:15], 1):
                response += f"[{i}] {result['content_type'].upper()}: {result['title']}\n"
                response += f"    Score: {result['score']:.3f}\n"
                
                # Show metadata compactly
                meta = []
                if result.get('project_name'):
                    meta.append(f"Project: {result['project_name']}")
                if result.get('priority'):
                    meta.append(f"Priority: {result['priority']}")
                if result.get('state_name'):
                    meta.append(f"State: {result['state_name']}")
                if result.get('assignee_name'):
                    meta.append(f"Assignee: {result['assignee_name']}")
                if result.get('displayBugNo'):
                    meta.append(f"Bug#: {result['displayBugNo']}")
                if result.get('updatedAt'):
                    date_str = str(result['updatedAt']).split('T')[0] if 'T' in str(result['updatedAt']) else str(result['updatedAt'])[:10]
                    meta.append(f"Updated: {date_str}")
                if result.get('visibility'):
                    meta.append(f"Visibility: {result['visibility']}")
                if result.get('business_name'):
                    meta.append(f"Business: {result['business_name']}")
                
                if meta:
                    response += f"    {' | '.join(meta)}\n"
                
                # Always include FULL content for LLM synthesis (no truncation)
                # This enables the LLM to generate properly formatted responses based on actual content
                if result.get('content'):
                    content_text = result['content']
                    response += f"\n    === CONTENT START ===\n{content_text}\n    === CONTENT END ===\n"
                
                response += "\n"
            
            if len(results) > 15:
                response += f"... and {len(results) - 15} more results (increase limit to see more)\n"
            
            return response
        
        # GROUPING - Aggregate and show distribution with content snippets
        groups = defaultdict(list)
        
        for result in results:
            group_val = result.get(group_by)
            
            # Handle date grouping
            if group_by in ['createdAt', 'updatedAt'] and group_val:
                if isinstance(group_val, str):
                    group_val = group_val.split('T')[0] if 'T' in group_val else group_val[:10]
            
            # Handle None/empty
            if group_val is None or group_val == "":
                group_val = "Unknown"
            
            groups[str(group_val)].append(result)
        
        # Sort groups by count
        sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
        
        response += f"📊 GROUPED BY '{group_by}':\n"
        response += f"Total groups: {len(sorted_groups)}\n\n"
        
        for group_key, items in sorted_groups[:20]:
            response += f"▸ {group_key}: {len(items)} item(s)\n"
            
            # Show sample items with content snippets for context
            for item in items[:3]:
                title = item['title'][:55] + "..." if len(item['title']) > 55 else item['title']
                response += f"  • {title} (score: {item['score']:.2f})\n"
                # Include content snippet for better LLM understanding
                if show_content and item.get('content'):
                    snippet = item['content'][:200] + "..." if len(item['content']) > 200 else item['content']
                    response += f"    Content: {snippet}\n"
            
            if len(items) > 3:
                response += f"  ... and {len(items) - 3} more\n"
            response += "\n"
        
        if len(sorted_groups) > 20:
            remaining_items = sum(len(items) for _, items in sorted_groups[20:])
            response += f"... and {len(sorted_groups) - 20} more groups ({remaining_items} items)\n"
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"rag_search for '{query[:50]}...' (type: {content_type}) took {elapsed_ms:.2f} ms")
        return response
        
    except ImportError:
        return "❌ RAG not available. Install: qdrant-client, sentence-transformers"
    except Exception as e:
        return f"❌ RAG SEARCH ERROR: {str(e)}"


# Global websocket registry for content generation
_GENERATION_WEBSOCKET = None
_GENERATION_CONVERSATION_ID = None

def set_generation_websocket(websocket):
    """Set the websocket connection for direct content streaming."""
    global _GENERATION_WEBSOCKET
    _GENERATION_WEBSOCKET = websocket

def get_generation_websocket():
    """Get the current websocket connection."""
    return _GENERATION_WEBSOCKET

def set_generation_context(websocket, conversation_id):
    """Set websocket and conversation context for generated content persistence."""
    global _GENERATION_WEBSOCKET, _GENERATION_CONVERSATION_ID
    _GENERATION_WEBSOCKET = websocket
    _GENERATION_CONVERSATION_ID = conversation_id

def get_generation_conversation_id():
    """Get the current conversation id for generated content context."""
    return _GENERATION_CONVERSATION_ID


@tool
async def generate_content(
    content_type: str,
    prompt: str,
    template_title: str = "",
    template_content: str = "",
    context: Optional[Dict[str, Any]] = None
) -> str:
    """Generate work items, pages, cycles, modules, or epics - sends content DIRECTLY to frontend, returns minimal confirmation.
    
    **CRITICAL TOKEN OPTIMIZATION**: 
    - Full generated content is sent directly to the frontend via WebSocket
    - Agent receives only a minimal success/failure signal (no content details)
    - Prevents generated content from being sent back through the LLM
    
    Use this to create new content:
    - Work items: bugs, tasks, features  
    - Pages: documentation, meeting notes, project plans
    - Cycles: sprints, iterations, development cycles
    - Modules: feature modules, components, subsystems
    - Epics: larger initiatives spanning multiple work items
    
    Args:
        content_type: Type of content - 'work_item', 'page', 'cycle', 'module', or 'epic'
        prompt: User's instruction for what to generate
        template_title: Optional template title to base generation on
        template_content: Optional template content to use as structure
        context: Optional context dict with additional parameters (pageId, projectId, etc.)
    
    Returns:
        Minimal success/failure signal (NOT content details) - saves maximum tokens
    
    Examples:
        generate_content(content_type="work_item", prompt="Bug: login fails on mobile")
        generate_content(content_type="page", prompt="Create API documentation", context={...})
        generate_content(content_type="cycle", prompt="Q4 2024 Sprint")
        generate_content(content_type="module", prompt="Authentication Module")
        generate_content(content_type="epic", prompt="Customer Onboarding Epic")
    """
    import httpx
    
    try:
        if content_type not in ["work_item", "page", "cycle", "module", "epic"]:
            return "❌ Invalid content type"
        
        # Get API base URL from environment; require explicit configuration to avoid hardcoded defaults
        api_base = os.getenv("API_BASE_URL") or os.getenv("API_HTTP_URL")
        if not api_base:
            raise RuntimeError("API_BASE_URL environment variable is not set")
        
        if content_type == "work_item":
            # Call work item generation endpoint
            url = f"{api_base}/generate/work-item"
            payload = {
                "prompt": prompt,
                "template": {
                    "title": template_title or "Work Item",
                    "content": template_content or ""
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            # Send full content directly to frontend (bypass agent)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "work_item",
                        "data": result,  # Full content to frontend
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated artifact as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_work_item
                    title = (result or {}).get("title") if isinstance(result, dict) else None
                    description = (result or {}).get("description") if isinstance(result, dict) else None
                    await save_generated_work_item(conv_id, {
                        "title": (title or "Work item").strip(),
                        "description": (description or "").strip(),
                        # Optional fields; may be filled later by explicit save to domain DB
                        "projectIdentifier": (result or {}).get("projectIdentifier") if isinstance(result, dict) else None,
                        "sequenceId": (result or {}).get("sequenceId") if isinstance(result, dict) else None,
                        "link": (result or {}).get("link") if isinstance(result, dict) else None,
                    })
            except Exception as e:
                # Non-fatal
                logger.error(f"Failed to persist generated work item to conversation: {e}")
            
            # Return MINIMAL confirmation to agent (no content details)
            return "✅ Content generated"
            
        elif content_type == "cycle":
            # Call cycle generation endpoint
            url = f"{api_base}/generate/cycle"
            payload = {
                "prompt": prompt,
                "template": {
                    "title": template_title or "Cycle",
                    "content": template_content or ""
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            # Send full content directly to frontend (bypass agent)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "cycle",
                        "data": result,  # Full content to frontend
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated artifact as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_cycle
                    title = (result or {}).get("title") if isinstance(result, dict) else None
                    description = (result or {}).get("description") if isinstance(result, dict) else None
                    await save_generated_cycle(conv_id, {
                        "title": (title or "Cycle").strip(),
                        "description": (description or "").strip(),
                    })
            except Exception as e:
                # Non-fatal
                logger.error(f"Failed to persist generated cycle to conversation: {e}")
            
            # Return MINIMAL confirmation to agent (no content details)
            return "✅ Content generated"
            
        elif content_type == "module":
            # Call module generation endpoint
            url = f"{api_base}/generate/module"
            payload = {
                "prompt": prompt,
                "template": {
                    "title": template_title or "Module",
                    "content": template_content or ""
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            # Send full content directly to frontend (bypass agent)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "module",
                        "data": result,  # Full content to frontend
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated artifact as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_module
                    title = (result or {}).get("title") if isinstance(result, dict) else None
                    description = (result or {}).get("description") if isinstance(result, dict) else None
                    await save_generated_module(conv_id, {
                        "title": (title or "Module").strip(),
                        "description": (description or "").strip(),
                    })
            except Exception as e:
                # Non-fatal
                logger.error(f"Failed to persist generated module to conversation: {e}")
            
            # Return MINIMAL confirmation to agent (no content details)
            return "✅ Content generated"

        elif content_type == "epic":
            # Call epic generation endpoint
            url = f"{api_base}/generate/epic"
            payload = {
                "prompt": prompt,
                "template": {
                    "title": template_title or "Epic",
                    "content": template_content or ""
                }
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()

            # Send full content directly to frontend (bypass agent)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "epic",
                        "data": result,  # Full content to frontend
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated epic as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_epic
                    epic_payload = {}
                    if isinstance(result, dict):
                        epic_payload = {
                            "title": result.get("title"),
                            "description": result.get("description"),
                            "priority": result.get("priority"),
                            "state": result.get("state") or result.get("stateName"),
                            "assignee": result.get("assignee"),
                            "labels": result.get("labels"),
                            "projectId": result.get("projectId"),
                            "startDate": result.get("startDate"),
                            "dueDate": result.get("dueDate"),
                            "link": result.get("link"),
                        }
                    await save_generated_epic(conv_id, epic_payload)
            except Exception as e:
                # Non-fatal
                logger.error(f"Failed to persist generated epic to conversation: {e}")

            # Return MINIMAL confirmation to agent (no content details)
            return "✅ Content generated"
            
        else:  # content_type == "page"
            # Call page generation endpoint
            url = f"{api_base}/stream-page-content"
            
            # Build request context
            page_context = context or {}
            payload = {
                "prompt": prompt,
                "template": {
                    "title": template_title or "Page",
                    "content": template_content or ""
                },
                "context": page_context.get("context", {
                    "tenantId": "",
                    "page": {"type": "DOCUMENTATION"},
                    "subject": {},
                    "timeScope": {},
                    "retrieval": {},
                    "privacy": {}
                }),
                "pageId": page_context.get("pageId", ""),
                "projectId": page_context.get("projectId", ""),
                "tenantId": page_context.get("tenantId", "")
            }
            
            # Send as query param (matching the endpoint's expectation)
            import json as json_lib
            params = {"data": json_lib.dumps(payload)}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                result = response.json()
            
            # Send full content directly to frontend (bypass agent)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "page",
                        "data": result,  # Full content to frontend
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated page as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_page
                    # Ensure blocks shape
                    blocks = result if isinstance(result, dict) else {}
                    if not isinstance(blocks.get("blocks"), list):
                        blocks = {"blocks": []}
                    title = (result or {}).get("title") if isinstance(result, dict) else None
                    await save_generated_page(conv_id, {
                        "title": (title or "Generated Page").strip(),
                        "blocks": blocks
                    })
            except Exception as e:
                logger.error(f"Failed to persist generated page to conversation: {e}")
            
            # Return MINIMAL confirmation to agent (no content details)
            return "✅ Content generated"
            
    except httpx.HTTPStatusError as e:
        error_msg = f"API error: {e.response.status_code}"
        # Send error to frontend
        websocket = get_generation_websocket()
        if websocket:
            try:
                await websocket.send_json({
                    "type": "content_generated",
                    "content_type": content_type,
                    "error": error_msg,
                    "success": False
                })
            except Exception:
                pass
        return f"❌ {error_msg}"
    except httpx.RequestError as e:
        error_msg = "Connection error"
        websocket = get_generation_websocket()
        if websocket:
            try:
                await websocket.send_json({
                    "type": "content_generated",
                    "content_type": content_type,
                    "error": error_msg,
                    "success": False
                })
            except Exception:
                pass
        return f"❌ {error_msg}"
    except Exception as e:
        error_msg = "Generation failed"
        websocket = get_generation_websocket()
        if websocket:
            try:
                await websocket.send_json({
                    "type": "content_generated",
                    "content_type": content_type,
                    "error": str(e)[:200],
                    "success": False
                })
            except Exception:
                pass
        return f"❌ {error_msg}"


# Define the tools list - streamlined and powerful
tools = [
    mongo_query,              # Structured MongoDB queries with intelligent planning
    rag_search,               # Universal RAG search with filtering, grouping, and metadata
    generate_content,         # Generate work items/pages (returns summary only, not full content)
]

# import asyncio

# if __name__ == "__main__":
#     async def main():
#         # Test the tools    
#         while True:
#             question = input("Enter your question: ")
#             if question.lower() in ['exit', 'quit']:
#                 break


#     asyncio.run(main())
