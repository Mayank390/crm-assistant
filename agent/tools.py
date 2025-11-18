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
# Rationale: CRM entities have appropriate default limits for retrieval.
CONTENT_TYPE_DEFAULT_LIMITS: Dict[str, int] = {
    "lead": 12,
    "task": 12,
    "activity": 10,
    "meeting": 10,
    "notes": 10,
    "callLog": 10,
    "mailInfo": 10,
    "segmentation": 10,
    "leadScoreRule": 10,
}

# ------------------ Enum Transformation Mappings ------------------
# Comprehensive mapping of enum values to human-readable formats
# Organized by collection and field name for efficient lookup

ENUM_TRANSFORMATIONS: Dict[str, Dict[str, Dict[str, str]]] = {
    "Lead": {
        "leadStatus": {
            "NEW": "New",
            "CONTACTED": "Contacted",
            "QUALIFIED": "Qualified",
            "ENGAGED": "Engaged",
            "PROPOSAL": "Proposal",
            "NEGOTIATION": "Negotiation",
            "WON": "Won",
            "LOST": "Lost",
            "UNQUALIFIED": "Unqualified",
            "FOLLOW_UP": "Follow Up",
            "CALL_BACK_REQUEST": "Call Back Request",
            "NOT_INTERESTED": "Not Interested",
            "INTERESTED": "Interested",
            "REGISTERED": "Registered",
            "APPLICATION_STARTED": "Application Started",
        },
        "status": {  # Alias for leadStatus
            "NEW": "New",
            "CONTACTED": "Contacted",
            "QUALIFIED": "Qualified",
            "ENGAGED": "Engaged",
            "PROPOSAL": "Proposal",
            "NEGOTIATION": "Negotiation",
            "WON": "Won",
            "LOST": "Lost",
            "UNQUALIFIED": "Unqualified",
            "FOLLOW_UP": "Follow Up",
            "CALL_BACK_REQUEST": "Call Back Request",
            "NOT_INTERESTED": "Not Interested",
            "INTERESTED": "Interested",
            "REGISTERED": "Registered",
            "APPLICATION_STARTED": "Application Started",
        },
        "type": {
            "LEAD": "Lead",
            "CUSTOMER": "Customer",
            "VENDOR": "Vendor",
        },
        "customerType": {
            "BUSINESS": "Business",
            "INDIVIDUAL": "Individual",
        },
        "source": {
            "COLD_CALL": "Cold Call",
            "REFERRAL": "Referral",
            "WEBSITE": "Website",
            "EVENT": "Event",
            "SOCIAL_MEDIA": "Social Media",
            "ADVERTISEMENT": "Advertisement",
            "INBOUND_CALLS": "Inbound Calls",
            "NETWORKING": "Networking",
            "CAMPAIGNS": "Campaigns",
            "OTHERS": "Others",
            "INVOICE": "Invoice",
        },
        "leadActiveType": {
            "ACTIVE": "Active",
            "IN_ACTIVE": "Inactive",
            "DELETED": "Deleted",
        },
        "gender": {  # For personalInfo.gender if present
            "MALE": "Male",
            "FEMALE": "Female",
            "OTHERS": "Others",
        },
    },
    "Task": {
        "taskStatus": {
            "NEW": "New",
            "NOT_STARTED": "Not Started",
            "IN_PROGRESS": "In Progress",
            "COMPLETED": "Completed",
            "WAITING_FOR_INPUT": "Waiting for Input",
            "CANCELLED": "Cancelled",
        },
        "status": {  # Alias for taskStatus
            "NEW": "New",
            "NOT_STARTED": "Not Started",
            "IN_PROGRESS": "In Progress",
            "COMPLETED": "Completed",
            "WAITING_FOR_INPUT": "Waiting for Input",
            "CANCELLED": "Cancelled",
        },
        "priority": {
            "NEW": "New",
            "HIGH": "High",
            "MEDIUM": "Medium",
            "LOW": "Low",
        },
        "notify": {
            "EMAIL": "Email",
            "POPUP": "Popup",
            "BOTH": "Both",
        },
        "repeatType": {
            "DAILY": "Daily",
            "WEEKLY": "Weekly",
            "MONTHLY": "Monthly",
            "YEARLY": "Yearly",
        },
        "endOn": {
            "NEVER": "Never",
            "AFTER_N_TIME": "After N Time",
            "ON_DATE": "On Date",
        },
    },
    "Activity": {
        "type": {
            "NOTES": "Notes",
            "EMAILS": "Emails",
            "TASKS": "Tasks",
            "CALLS": "Calls",
            "MEETING": "Meeting",
        },
        "activityStatus": {
            "OPEN": "Open",
            "CLOSE": "Close",
            "CANCELLED": "Cancelled",
        },
        "status": {  # Alias for activityStatus
            "OPEN": "Open",
            "CLOSE": "Close",
            "CANCELLED": "Cancelled",
        },
    },
    "Meeting": {
        "meetingStatus": {
            "NEW": "New",
            "SCHEDULED": "Scheduled",
            "IN_PROGRESS": "In Progress",
            "COMPLETED": "Completed",
            "CANCELLED": "Cancelled",
            "RESCHEDULED": "Rescheduled",
        },
        "status": {  # Alias for meetingStatus
            "NEW": "New",
            "SCHEDULED": "Scheduled",
            "IN_PROGRESS": "In Progress",
            "COMPLETED": "Completed",
            "CANCELLED": "Cancelled",
            "RESCHEDULED": "Rescheduled",
        },
        "meetingType": {
            "PHYSICAL": "Physical",
            "VIRTUAL": "Virtual",
        },
    },
    "CallLog": {
        "callStatus": {
            "NEW": "New",
            "ANSWERED": "Answered",
            "NO_RESPONSE": "No Response",
            "DO_NOT_CALL": "Do Not Call",
            "FAILED": "Failed",
            "MISSED_CALL": "Missed Call",
            "COMPLETED": "Completed",
            "SCHEDULED": "Scheduled",
            "NOT_ANSWERED": "Not Answered",
        },
        "status": {  # Alias for callStatus
            "NEW": "New",
            "ANSWERED": "Answered",
            "NO_RESPONSE": "No Response",
            "DO_NOT_CALL": "Do Not Call",
            "FAILED": "Failed",
            "MISSED_CALL": "Missed Call",
            "COMPLETED": "Completed",
            "SCHEDULED": "Scheduled",
            "NOT_ANSWERED": "Not Answered",
        },
        "callType": {
            "IN_BOUND": "Inbound",
            "OUT_BOUND": "Outbound",
        },
        "call_variant": {
            "SCHEDULE": "Schedule",
            "LOG": "Log",
        },
        "callPurpose": {
            "PROSPECTING": "Prospecting",
            "ADMINISTRATIVE": "Administrative",
            "NEGOTIATION": "Negotiation",
            "DEMO": "Demo",
            "PROJECT": "Project",
            "DESK": "Desk",
            "OTHERS": "Others",
        },
    },
    "MailInfo": {
        "mailType": {
            "SEND": "Send",
            "SCHEDULED": "Scheduled",
            "DRAFTS": "Drafts",
        },
    },
    "Segmentation": {
        "operator": {
            "CONTAINS": "Contains",
            "EQUALS": "Equals",
            "GREATER_THAN": "Greater Than",
            "LESS_THAN": "Less Than",
            "GREATER_THAN_OR_EQUAL": "Greater Than Or Equal",
            "LESS_THAN_OR_EQUAL": "Less Than Or Equal",
            "NOT_EQUALS": "Not Equals",
            "NOT_CONTAINS": "Not Contains",
            "STARTS_WITH": "Starts With",
            "ENDS_WITH": "Ends With",
        },
    },
    "LeadScoreRule": {
        "change": {
            "POSITIVE": "Positive",
            "NEGATIVE": "Negative",
        },
        "operator": {
            "EQUALS": "Equals",
            "GREATER_THAN": "Greater Than",
            "LESS_THAN": "Less Than",
            "GREATER_THAN_OR_EQUAL": "Greater Than Or Equal",
            "LESS_THAN_OR_EQUAL": "Less Than Or Equal",
            "NOT_EQUALS": "Not Equals",
            "CONTAINS": "Contains",
            "NOT_CONTAINS": "Not Contains",
            "STARTS_WITH": "Starts With",
            "ENDS_WITH": "Ends With",
        },
    },
    # Common enum values that might appear in multiple collections
    "_common": {
        "attachmentType": {
            "IMAGE": "Image",
            "VIDEO": "Video",
            "FILE": "File",
        },
        "socialMedia": {
            "INSTAGRAM": "Instagram",
            "FACEBOOK": "Facebook",
            "TWITTER": "Twitter",
            "LINKED_IN": "LinkedIn",
            "YOUTUBE": "YouTube",
            "PINTEREST": "Pinterest",
            "REDDIT": "Reddit",
            "TELEGRAM": "Telegram",
        },
    },
}

# Global helper function to transform enum/field values to readable format
# Moved from inside format_llm_friendly so it can be accessed by _transform_by_collection
def transform_field_value(key: str, value: Any, collection: Optional[str] = None) -> str:
    """Transform raw field values to readable format using enum mappings.

    Args:
        key: Field name (e.g., 'status', 'leadStatus', 'type')
        value: Field value (e.g., 'NEW', 'CONTACTED')
        collection: Collection name (e.g., 'Lead', 'Task') for context-aware transformation

    Returns:
        Transformed readable value
    """
    if value is None:
        return "N/A"

    if not isinstance(value, str):
        return str(value)

    # Normalize collection name (handle case variations)
    coll = (collection or "").strip()
    if coll:
        # Try exact match first
        if coll not in ENUM_TRANSFORMATIONS:
            # Try title case
            coll = coll.capitalize()

    # Try collection-specific transformation first
    if coll and coll in ENUM_TRANSFORMATIONS:
        field_mappings = ENUM_TRANSFORMATIONS[coll]
        # Check exact field name match
        if key in field_mappings:
            enum_map = field_mappings[key]
            if value.upper() in enum_map:
                return enum_map[value.upper()]

        # Check for status/state aliases
        if key.lower() in ['status', 'state'] and 'status' in field_mappings:
            enum_map = field_mappings['status']
            if value.upper() in enum_map:
                return enum_map[value.upper()]

    # Try common enum transformations
    if "_common" in ENUM_TRANSFORMATIONS:
        common_mappings = ENUM_TRANSFORMATIONS["_common"]
        for common_key, enum_map in common_mappings.items():
            if key.lower() == common_key.lower() or key.lower().endswith(common_key.lower()):
                if value.upper() in enum_map:
                    return enum_map[value.upper()]

    # Fallback: Generic transformation for UPPERCASE_SNAKE_CASE values
    if '_' in value or value.isupper():
        # Split by underscore and title case each word
        parts = value.replace('_', ' ').split()
        transformed = ' '.join(word.capitalize() for word in parts)
        return transformed

    # Already formatted, just capitalize first letter if all uppercase
    if value.isupper() and len(value) > 1:
        return value.capitalize()

    # Return as-is if already formatted
    return value

# Fallback when content_type is unknown or not provided
DEFAULT_RAG_LIMIT: int = 10

# Optional: per content_type chunk-level tuning for chunk-aware retrieval
# - chunks_per_doc controls how many high-scoring chunks are kept per reconstructed doc
# - include_adjacent controls whether to pull neighboring chunks for context
# - min_score sets a score threshold for initial vector hits
CONTENT_TYPE_CHUNKS_PER_DOC: Dict[str, int] = {
    "lead": 3,
    "task": 4,
    "activity": 2,
    "meeting": 2,
    "notes": 2,
    "callLog": 2,
    "mailInfo": 2,
    "segmentation": 2,
}

CONTENT_TYPE_INCLUDE_ADJACENT: Dict[str, bool] = {
    "lead": True,
    "task": True,
    "activity": False,
    "meeting": False,
    "notes": False,
    "callLog": False,
    "mailInfo": False,
    "segmentation": False,
}

CONTENT_TYPE_MIN_SCORE: Dict[str, float] = {
    "lead": 0.5,
    "task": 0.5,
    "activity": 0.55,
    "meeting": 0.55,
    "notes": 0.55,
    "callLog": 0.55,
    "mailInfo": 0.55,
    "segmentation": 0.55,
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
        'business', 'staff', 'createdBy', 'assignee',
        'members',
        # Date fields (but not timestamps)
        'startDate', 'endDate', 'joiningDate', 'createdAt', 'updatedAt',
        # Estimate and work tracking
        'estimate', 'estimateSystem', 'workLogs',
        # Count/aggregation results
        'total', 'count', 'group', 'items',
        # CRM fields
        'referenceNo', 'leadStatus', 'taskStatus', 'meetingStatus', 'activityStatus', 'callStatus',
        'notes', 'subject', 'mobile', 'leadName', 'assignedName', 'createdByName', 'parentName',
        'meetingType', 'meetingLink', 'meetingLocated', 'callType', 'callPurpose', 'callDuration',
        'mailType', 'toMails', 'toCcMails', 'toBccMails', 'attachments', 'score',
        'personalInfo', 'company', 'address', 'dueDate', 'startDateTime', 'endDateTime',
        'description', 'body', 'notesAttachments', 'participantsList', 'emailData',
        # Segmentation fields
        'conditions', 'tags', 'isActive', 'operator'
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
    # Normalize collection name for case-insensitive matching
    collection_lower = collection.lower()
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

    # Per collection enrichments (using normalized lowercase for matching)
    if collection_lower == "workitem":
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

    elif collection_lower == "project":
        set_name("business", "businessName")
        set_name("lead", "leadName")
        set_name("defaultAsignee", "defaultAssigneeName")
        set_name("createdBy", "createdByName")
        copy_if_present("leadMail")

    elif collection_lower == "cycle":
        # Project may only contain id; we skip if name isn't present
        set_name("project", "projectName")
        set_name("business", "businessName")

    elif collection_lower == "module":
        set_name("project", "projectName")
        set_name("lead", "leadName")
        set_name("business", "businessName")
        set_names_list("assignee", "assignees")

    elif collection_lower == "members":
        set_name("project", "projectName")
        set_name("staff", "staffName")

    elif collection_lower == "page":
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

    elif collection_lower == "projectstate":
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

    elif collection_lower == "timeline":
        # Surface friendly names and key attributes
        set_name("project", "projectName")
        # user is actor
        set_name("user", "actorName")
        # event type and field changed are useful summarizers
        if isinstance(doc.get("type"), str):
            out["timelineType"] = doc["type"]
        if isinstance(doc.get("fieldChanged"), str):
            out["fieldChanged"] = doc["fieldChanged"]


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

    # CRM collection transformations
    elif collection_lower == "lead":
        # Extract personalInfo fields
        personal_info = doc.get("personalInfo")
        if isinstance(personal_info, dict):
            if isinstance(personal_info.get("name"), str):
                out["leadName"] = personal_info["name"]
            if isinstance(personal_info.get("email"), str):
                out["leadEmail"] = personal_info["email"]
            if isinstance(personal_info.get("mobile"), str):
                out["leadMobile"] = personal_info["mobile"]
        
        # Extract company info
        company = doc.get("company")
        if isinstance(company, dict):
            company_name = company.get("name")
            if company_name:
                out["companyName"] = company_name
        
        # Extract pipeline info
        pipeline = doc.get("pipeline")
        if isinstance(pipeline, dict):
            pipeline_name = pipeline.get("name")
            if pipeline_name:
                out["pipelineName"] = pipeline_name
        
        # Copy important fields with enum transformations
        copy_if_present("referenceNo")
        # Transform enum fields
        lead_status = doc.get("leadStatus")
        if lead_status is not None:
            out["leadStatus"] = transform_field_value("leadStatus", lead_status, collection)
        status = doc.get("status")
        if status is not None:
            out["status"] = transform_field_value("status", status, collection)
        lead_type = doc.get("type")
        if lead_type is not None:
            out["type"] = transform_field_value("type", lead_type, collection)
        customer_type = doc.get("customerType")
        if customer_type is not None:
            out["customerType"] = transform_field_value("customerType", customer_type, collection)
        source = doc.get("source")
        if source is not None:
            out["source"] = transform_field_value("source", source, collection)
        lead_active_type = doc.get("leadActiveType")
        if lead_active_type is not None:
            out["leadActiveType"] = transform_field_value("leadActiveType", lead_active_type, collection)

        copy_if_present("notes")
        copy_if_present("score")
        copy_if_present("createdByName")
        copy_if_present("staffName")

    elif collection_lower == "task":
        # Copy important fields with enum transformations
        copy_if_present("name")
        # Transform enum fields
        task_status = doc.get("taskStatus")
        if task_status is not None:
            out["taskStatus"] = transform_field_value("taskStatus", task_status, collection)
        status = doc.get("status")
        if status is not None:
            out["status"] = transform_field_value("status", status, collection)
        priority = doc.get("priority")
        if priority is not None:
            out["priority"] = transform_field_value("priority", priority, collection)
        notify = doc.get("notify")
        if notify is not None:
            out["notify"] = transform_field_value("notify", notify, collection)

        copy_if_present("dueDate")
        copy_if_present("description")
        copy_if_present("assignedName")
        copy_if_present("parentName")
        copy_if_present("createdByName")
        copy_if_present("reminderDate")

    elif collection_lower == "meeting":
        # Copy important fields with enum transformations
        copy_if_present("title")
        # Transform enum fields
        meeting_status = doc.get("meetingStatus")
        if meeting_status is not None:
            out["meetingStatus"] = transform_field_value("meetingStatus", meeting_status, collection)
        status = doc.get("status")
        if status is not None:
            out["status"] = transform_field_value("status", status, collection)
        meeting_type = doc.get("meetingType")
        if meeting_type is not None:
            out["meetingType"] = transform_field_value("meetingType", meeting_type, collection)

        copy_if_present("leadName")
        copy_if_present("description")
        copy_if_present("startDateTime")
        copy_if_present("endDateTime")
        copy_if_present("assignedName")
        copy_if_present("createdByName")
        copy_if_present("meetingLink")
        copy_if_present("meetingLocated")
        
        # Handle participants
        participants = doc.get("participantsList")
        if isinstance(participants, list) and participants:
            out["participantsCount"] = len(participants)
            participant_names = []
            for p in participants[:5]:  # First 5 participants
                if isinstance(p, dict):
                    name = p.get("leadName")
                    if name:
                        participant_names.append(name)
            if participant_names:
                out["participantsNames"] = participant_names

    elif collection_lower == "notes":
        # Copy important fields
        copy_if_present("subject")
        copy_if_present("description")
        copy_if_present("leadName")
        copy_if_present("createdByName")
        
        # Handle attachments
        attachments = doc.get("notesAttachments")
        if isinstance(attachments, list) and attachments:
            out["attachmentsCount"] = len(attachments)

    elif collection_lower == "activity":
        # Extract activity type and status with transformations
        activity_type = doc.get("type")
        if activity_type is not None:
            out["type"] = transform_field_value("type", activity_type, collection)
        activity_status = doc.get("activityStatus")
        if activity_status is not None:
            out["activityStatus"] = transform_field_value("activityStatus", activity_status, collection)
        status = doc.get("status")
        if status is not None:
            out["status"] = transform_field_value("status", status, collection)

        # Extract nested data (could be task, meeting, etc.)
        data = doc.get("data")
        if isinstance(data, dict):
            data_name = data.get("name") or data.get("title")
            if data_name:
                out["activityName"] = data_name
            data_description = data.get("description")
            if data_description:
                out["activityDescription"] = truncate_str(data_description, 200)
            data_status = data.get("taskStatus") or data.get("meetingStatus")
            if data_status:
                out["activityDataStatus"] = data_status

        # Extract lead name if available
        copy_if_present("leadName")

    elif collection_lower == "calllog":
        # Copy important fields with enum transformations
        copy_if_present("title")
        # Transform enum fields
        call_status = doc.get("callStatus")
        if call_status is not None:
            out["callStatus"] = transform_field_value("callStatus", call_status, collection)
        status = doc.get("status")
        if status is not None:
            out["status"] = transform_field_value("status", status, collection)
        call_type = doc.get("callType")
        if call_type is not None:
            out["callType"] = transform_field_value("callType", call_type, collection)
        call_purpose = doc.get("callPurpose")
        if call_purpose is not None:
            out["callPurpose"] = transform_field_value("callPurpose", call_purpose, collection)
        call_variant = doc.get("call_variant")
        if call_variant is not None:
            out["call_variant"] = transform_field_value("call_variant", call_variant, collection)

        copy_if_present("callDuration")
        copy_if_present("description")
        copy_if_present("leadName")
        copy_if_present("createdByName")
        copy_if_present("startDateTime")
        copy_if_present("otherReason")

    elif collection_lower == "mailinfo":
        # Copy important fields with enum transformations
        copy_if_present("subject")
        copy_if_present("body")
        # Transform enum fields
        mail_type = doc.get("mailType")
        if mail_type is not None:
            out["mailType"] = transform_field_value("mailType", mail_type, collection)

        copy_if_present("createdByName")
        
        # Handle email recipients
        to_mails = doc.get("toMails")
        if isinstance(to_mails, list) and to_mails:
            out["toMailsCount"] = len(to_mails)
            out["toMails"] = to_mails[:5]  # First 5 recipients
        
        # Handle attachments
        attachments = doc.get("attachments")
        if isinstance(attachments, list) and attachments:
            out["attachmentsCount"] = len(attachments)

    elif collection_lower == "segmentation":
        # Copy important fields
        copy_if_present("name")
        copy_if_present("description")
        copy_if_present("isActive")
        
        # Handle business reference
        business = doc.get("business")
        if isinstance(business, dict):
            business_name = business.get("name")
            if business_name:
                out["businessName"] = business_name
        
        # Handle conditions array
        conditions = doc.get("conditions")
        if isinstance(conditions, list) and conditions:
            out["conditionsCount"] = len(conditions)
            # Transform operators in conditions
            transformed_conditions = []
            for condition in conditions[:5]:  # First 5 conditions
                if isinstance(condition, dict):
                    transformed_condition = condition.copy()
                    operator = condition.get("operator")
                    if operator:
                        transformed_condition["operator"] = transform_field_value("operator", operator, collection)
                    transformed_conditions.append(transformed_condition)
            if transformed_conditions:
                out["conditions"] = transformed_conditions
        
        # Handle tags
        tags = doc.get("tags")
        if isinstance(tags, list) and tags:
            out["tags"] = tags[:10]  # First 10 tags
            out["tagsCount"] = len(tags)
        
        copy_if_present("createdAt")
        copy_if_present("updatedAt")

    elif collection_lower == "leadscorerule":
        set_name("business", "businessName")
        copy_if_present("name")
        copy_if_present("description")
        copy_if_present("score")
        copy_if_present("change")
        copy_if_present("field")
        copy_if_present("operator")
        copy_if_present("value")
        copy_if_present("isActive")
        copy_if_present("aiAdjusted")
        copy_if_present("createdAt")
        copy_if_present("updatedAt")

    # Drop empty/None values and metadata keys
    out = {k: v for k, v in out.items() if v not in (None, "", [], {}) and k != "_class"}
    return out


def truncate_str(s: Any, limit: int = 120) -> str:
    """Truncate string to specified limit with ellipsis."""
    if not isinstance(s, str):
        return str(s)
    return s if len(s) <= limit else s[:limit] + "..."


def filter_and_transform_content(data: Any, primary_entity: Optional[str] = None) -> Any:
    """Filter and transform content with defensive checks for edge cases.
    
    Preserve meaningful fields, strip IDs/UUIDs, and flatten references per collection.

    Steps:
    1) Use existing filter to keep meaningful content fields.
    2) Strip any remaining id/uuid-like keys/values.
    3) Apply per-collection flatteners to surface human-friendly names.
    """
    # Handle None/empty input
    if data is None:
        return None
    
    if not isinstance(data, (dict, list)):
        return data
    
    # Handle empty collections
    if isinstance(data, list) and len(data) == 0:
        return []
    
    if isinstance(data, dict) and len(data) == 0:
        return {}
    
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
    MongoDB (counts, lists, filters, group-by, breakdowns, status/assignee/lead details)
    across collections: `Lead`, `Task`, `Activity`, `Meeting`, `Notes`, `CallLog`, `MailInfo`, `LeadScoreRule`, `Segmentation`.

    Do NOT use this for:
    - Free-form content questions (use `rag_search`).
    - Pure summarization or opinion without data retrieval.
    - When you already have the exact answer in prior tool results.

    Behavior:
    - Follows a planner to generate a safe aggregation pipeline; avoids
      hallucinated fields.
    - Automatically determines when complex joins are beneficial based on query requirements.
    - Intelligently adds strategic relationships only when they improve query performance:
        - Multi-hop queries: "leads by business" (Lead→business)
        - Cross-collection analysis: "members working on projects by business"
        - Complex grouping that spans multiple collections
    - Only adds joins that provide clear benefits for the specific query, avoiding unnecessary complexity.
    
    PAGINATION SUPPORT:
    - Pagination is automatically handled via natural language in queries.
    - Use phrases like "page 2", "skip 100", "show results 21-40", "next page" to paginate.
    - Pagination works with all query types: list queries, grouped queries, and aggregated queries.
    - Default page size is 50 items. Use "all" or "every" for maximum results (up to 1000).
    - For large datasets, pagination ensures manageable response sizes.
    - Examples:
      * "show me page 2 of leads" → returns items 51-100
      * "skip the first 100 tasks" → skips first 100, returns next 50
      * "show results 21-40 of meetings" → returns items 21-40
      * "group leads by status, page 2" → paginated grouped results

    Args:
    query: Natural language, structured data request about CRM entities.
    show_all: If True, output full details instead of a summary. Use sparingly.

    Returns: A compact result suitable for direct user display. Results are automatically
    formatted based on query type: lists, counts, grouped results, or trend/aggregated data.
    """
    tool_start_time = perf_counter()
    if not plan_and_execute_query:
        return "❌ Intelligent query planner not available. Please ensure query_planner.py is properly configured."

    try:
        # Validate query input
        if not query or not isinstance(query, str):
            return "❌ Invalid query: query must be a non-empty string."
        
        if len(query.strip()) == 0:
            return "❌ Invalid query: query cannot be empty."
        
        result = await plan_and_execute_query(query)
        
        # Validate result structure
        if not isinstance(result, dict):
            return f"❌ Unexpected result format from query planner: {type(result)}"
        
        if "success" not in result:
            return f"❌ Missing 'success' field in query planner result: {result}"

        if result["success"]:
            # Simplified response format - focus on data, not metadata
            response = ""
            
            # Get parsed intent
            intent = result.get("intent")
            if not intent:
                return "❌ Query planner did not return intent information."
            
            if not isinstance(intent, dict):
                return f"❌ Invalid intent format: {type(intent)}"
            
            primary_entity = intent.get('primary_entity', 'Unknown')

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

                # transform_field_value is now defined at module level above

                def render_line(entity: Dict[str, Any]) -> str:
                    e = (primary_entity or "").lower()
                    
                    # Helper to transform enum values in render_line
                    def transform_val(field_name: str, value: Any) -> str:
                        """Transform enum value for display in render_line."""
                        if value is None:
                            return None
                        return transform_field_value(field_name, value, primary_entity)
                    if e == "members":
                        name = entity.get("name")
                        email = entity.get("email")
                        role = entity.get("role")
                        type_v = entity.get("type")
                        return f"• {name or 'Member'} — role={role or 'N/A'}, email={email or 'N/A'}, type={type_v or 'N/A'}"
                    
                    # Removed work management entity rendering: epic, userStory, features
                    
                    # CRM entity rendering
                    if e == "lead":
                        ref_no = entity.get("referenceNo")
                        name = entity.get("leadName") or get_nested(entity, "personalInfo.name")
                        status = transform_val("leadStatus", entity.get("leadStatus"))
                        email = entity.get("leadEmail") or get_nested(entity, "personalInfo.email")
                        mobile = entity.get("leadMobile") or get_nested(entity, "personalInfo.mobile")
                        notes = entity.get("notes")
                        lead_type = transform_val("type", entity.get("type"))
                        score = entity.get("score")
                        company = entity.get("companyName") or get_nested(entity, "company.name")
                        pipeline = entity.get("pipelineName") or get_nested(entity, "pipeline.name")
                        source = transform_val("source", entity.get("source"))
                        customer_type = transform_val("customerType", entity.get("customerType"))
                        active_type = transform_val("leadActiveType", entity.get("leadActiveType"))
                        
                        base = f"• {ref_no or name or 'Lead'}: {name or ''}"
                        if status:
                            base += f" — status={status}"
                        if lead_type:
                            base += f", type={lead_type}"
                        if customer_type:
                            base += f", customerType={customer_type}"
                        if source:
                            base += f", source={source}"
                        if active_type:
                            base += f", activeType={active_type}"
                        if email:
                            base += f", email={email}"
                        if mobile:
                            base += f", mobile={mobile}"
                        if company:
                            base += f", company={company}"
                        if lead_type:
                            base += f", type={lead_type}"
                        if score is not None:
                            base += f", score={score}"
                        if pipeline:
                            base += f", pipeline={pipeline}"
                        if notes:
                            base += f", notes={truncate_str(notes, 100)}"
                        return base
                    
                    if e == "task":
                        name = entity.get("name")
                        status = transform_val("taskStatus", entity.get("taskStatus"))
                        priority = transform_val("priority", entity.get("priority"))
                        due_date = entity.get("dueDate")
                        description = entity.get("description")
                        assigned = entity.get("assignedName")
                        parent = entity.get("parentName")
                        created_by = entity.get("createdByName")
                        notify = transform_val("notify", entity.get("notify"))
                        
                        base = f"• {name or 'Task'}"
                        if status:
                            base += f" — status={status}"
                        if priority:
                            base += f", priority={priority}"
                        if notify:
                            base += f", notify={notify}"
                        if due_date:
                            base += f", due={due_date}"
                        if assigned:
                            base += f", assigned={assigned}"
                        if parent:
                            base += f", parent={parent}"
                        if created_by:
                            base += f", createdBy={created_by}"
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        return base
                    
                    if e == "meeting":
                        title = entity.get("title")
                        status = transform_val("meetingStatus", entity.get("meetingStatus"))
                        meeting_type = transform_val("meetingType", entity.get("meetingType"))
                        lead_name = entity.get("leadName")
                        description = entity.get("description")
                        start_dt = entity.get("startDateTime")
                        end_dt = entity.get("endDateTime")
                        assigned = entity.get("assignedName")
                        created_by = entity.get("createdByName")
                        meeting_link = entity.get("meetingLink")
                        participants = entity.get("participantsNames")
                        
                        base = f"• {title or 'Meeting'}"
                        if status:
                            base += f" — status={status}"
                        if meeting_type:
                            base += f", type={meeting_type}"
                        if lead_name:
                            base += f", lead={lead_name}"
                        if start_dt and end_dt:
                            base += f", time={start_dt} → {end_dt}"
                        elif start_dt:
                            base += f", start={start_dt}"
                        if assigned:
                            base += f", assigned={assigned}"
                        if created_by:
                            base += f", createdBy={created_by}"
                        if meeting_link:
                            base += f", link={meeting_link[:50]}..."
                        if participants:
                            base += f", participants={', '.join(participants[:3])}"
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        return base
                    
                    if e == "notes":
                        subject = entity.get("subject")
                        description = entity.get("description")
                        lead_name = entity.get("leadName")
                        created_by = entity.get("createdByName")
                        attachments_count = entity.get("attachmentsCount")
                        
                        base = f"• {subject or 'Note'}"
                        if lead_name:
                            base += f" — lead={lead_name}"
                        if created_by:
                            base += f", createdBy={created_by}"
                        if attachments_count:
                            base += f", attachments={attachments_count}"
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        return base
                    
                    if e == "activity":
                        activity_type = transform_val("type", entity.get("type"))
                        status = transform_val("activityStatus", entity.get("activityStatus"))
                        name = entity.get("activityName")
                        description = entity.get("activityDescription")
                        data_status = entity.get("activityDataStatus")
                        lead_name = entity.get("leadName")
                        
                        base = f"• {name or 'Activity'}"
                        if activity_type:
                            base += f" — type={activity_type}"
                        if status:
                            base += f", status={status}"
                        if data_status:
                            base += f", dataStatus={data_status}"
                        if lead_name:
                            base += f", lead={lead_name}"
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        return base
                    
                    if e == "calllog":
                        title = entity.get("title")
                        call_status = transform_val("callStatus", entity.get("callStatus"))
                        call_type = transform_val("callType", entity.get("callType"))
                        call_purpose = transform_val("callPurpose", entity.get("callPurpose"))
                        call_duration = entity.get("callDuration")
                        description = entity.get("description")
                        lead_name = entity.get("leadName")
                        created_by = entity.get("createdByName")
                        start_dt = entity.get("startDateTime")
                        call_variant = transform_val("call_variant", entity.get("call_variant"))
                        
                        base = f"• {title or 'Call'}"
                        if call_status:
                            base += f" — status={call_status}"
                        if call_type:
                            base += f", type={call_type}"
                        if call_purpose:
                            base += f", purpose={call_purpose}"
                        if call_variant:
                            base += f", variant={call_variant}"
                        if call_duration:
                            base += f", duration={call_duration}"
                        if lead_name:
                            base += f", lead={lead_name}"
                        if created_by:
                            base += f", createdBy={created_by}"
                        if start_dt:
                            base += f", time={start_dt}"
                        if description:
                            base += f", description={truncate_str(description, 120)}"
                        return base
                    
                    if e == "mailinfo":
                        subject = entity.get("subject")
                        mail_type = transform_val("mailType", entity.get("mailType"))
                        created_by = entity.get("createdByName")
                        to_mails = entity.get("toMails")
                        to_mails_count = entity.get("toMailsCount")
                        attachments_count = entity.get("attachmentsCount")
                        body = entity.get("body")
                        
                        base = f"• {subject or 'Email'}"
                        if mail_type:
                            base += f" — type={mail_type}"
                        if created_by:
                            base += f", from={created_by}"
                        if to_mails:
                            base += f", to={', '.join(to_mails[:3])}"
                        elif to_mails_count:
                            base += f", to={to_mails_count} recipients"
                        if attachments_count:
                            base += f", attachments={attachments_count}"
                        if body:
                            # Strip HTML tags for preview
                            body_text = re.sub(r'<[^>]+>', '', str(body))
                            base += f", body={truncate_str(body_text, 120)}"
                        return base
                    
                    if e == "segmentation":
                        name = entity.get("name")
                        description = entity.get("description")
                        is_active = entity.get("isActive")
                        business_name = entity.get("businessName")
                        conditions = entity.get("conditions")
                        conditions_count = entity.get("conditionsCount")
                        tags = entity.get("tags")
                        tags_count = entity.get("tagsCount")
                        
                        base = f"• {name or 'Segmentation'}"
                        if description:
                            base += f" — {truncate_str(description, 80)}"
                        if is_active is not None:
                            base += f", active={is_active}"
                        if business_name:
                            base += f", business={business_name}"
                        if conditions:
                            conditions_str = ", ".join([
                                f"{c.get('field', '')} {c.get('operator', '')} {c.get('value', '')}"
                                for c in conditions[:3]
                            ])
                            base += f", conditions=[{conditions_str}]"
                        elif conditions_count:
                            base += f", conditions={conditions_count} rules"
                        if tags:
                            base += f", tags={', '.join(tags[:3])}"
                        elif tags_count:
                            base += f", tags={tags_count} tags"
                        return base
                    
                    if e == "leadscorerule":
                        name = entity.get("name")
                        description = entity.get("description")
                        score = entity.get("score")
                        change = transform_val("change", entity.get("change"))
                        field = entity.get("field")
                        operator = transform_val("operator", entity.get("operator"))
                        value = entity.get("value")
                        is_active = entity.get("isActive")
                        business_name = entity.get("businessName")
                        
                        base = f"• {name or 'Lead Score Rule'}"
                        if description:
                            base += f" — {truncate_str(description, 80)}"
                        if change:
                            base += f", change={change}"
                        if score is not None:
                            base += f", score={score}"
                        if field:
                            base += f", field={field}"
                        if operator:
                            base += f", operator={operator}"
                        if value is not None:
                            base += f", value={value}"
                        if is_active is not None:
                            base += f", active={is_active}"
                        if business_name:
                            base += f", business={business_name}"
                        return base
                    
                    # Default fallback
                    title = entity.get("title") or entity.get("name") or "Item"
                    return f"• {truncate_str(title, 80)}"
                if isinstance(data, list):
                    # Handle count-only results
                    if len(data) == 1 and isinstance(data[0], dict) and "total" in data[0]:
                        return f"📊 RESULTS:\nTotal: {data[0]['total']}"

                    # Handle trend/aggregated results (with _id, count, period fields)
                    if len(data) > 0 and isinstance(data[0], dict):
                        first_item = data[0]
                        # Check for trend pattern: _id (date), count, period
                        # This pattern appears in trend analysis queries
                        if "_id" in first_item and "count" in first_item and "period" in first_item:
                            response = "📊 TREND RESULTS:\n"
                            for item in data:
                                period = item.get("period") or item.get("_id")
                                count = item.get("count", 0)
                                # Format period nicely - handle date strings
                                if isinstance(period, str):
                                    # Try to format date string nicely
                                    period_str = period
                                    # If it's a date string like "2024-11-01 00:00:00", extract just the date part
                                    if " " in period_str:
                                        period_str = period_str.split(" ")[0]
                                elif isinstance(period, dict):
                                    period_str = str(period.get("$dateTrunc", period))
                                else:
                                    period_str = str(period)
                                response += f"• {period_str}: {count} items\n"
                            return response
                        
                        # Check for trend pattern without period field (just _id and count)
                        # This handles aggregated results from $group stages
                        if "_id" in first_item and "count" in first_item and "period" not in first_item and "group" not in first_item:
                            response = "📊 AGGREGATED RESULTS:\n"
                            for item in data:
                                period_id = item.get("_id")
                                count = item.get("count", 0)
                                # Format _id nicely
                                if isinstance(period_id, dict):
                                    # Handle date trunc results
                                    date_trunc = period_id.get("$dateTrunc", {})
                                    if date_trunc:
                                        unit = date_trunc.get('unit', 'period')
                                        date_field = date_trunc.get('date', '')
                                        period_str = f"{unit} ({date_field})"
                                    else:
                                        # Handle other dict structures
                                        period_str = str(period_id)
                                elif isinstance(period_id, str):
                                    # Handle date strings - extract date part if it's a datetime string
                                    if " " in period_id:
                                        period_str = period_id.split(" ")[0]
                                    else:
                                        period_str = period_id
                                else:
                                    period_str = str(period_id)
                                response += f"• {period_str}: {count} items\n"
                            return response

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

                            # transform_field_value is now defined at format_llm_friendly level above
                            
                            # Calculate percentages for grouped results
                            def format_grouped_item(item: Dict[str, Any], total: int, has_mins: bool) -> str:
                                """Format a single grouped item with percentage."""
                                # If single group key, show just the transformed value (cleaner format)
                                if len(group_keys) == 1:
                                    key = group_keys[0]
                                    if key in item:
                                        transformed_val = transform_field_value(key, item[key], primary_entity)
                                        group_label = transformed_val
                                    else:
                                        group_label = "Unknown"
                                else:
                                    # Multiple group keys - show all with field names
                                    group_parts = []
                                    for k in group_keys:
                                        if k in item:
                                            transformed_val = transform_field_value(k, item[k], primary_entity)
                                            group_parts.append(f"{k}: {transformed_val}")
                                    group_label = ', '.join(group_parts) if group_parts else "Unknown"
                                
                                if has_mins:
                                    mins = int(item.get('totalMinutes', 0) or 0)
                                    if total_minutes and total_minutes > 0:
                                        pct = (mins / total_minutes) * 100
                                        return f"• {group_label}: {mins:,} min ({pct:.1f}%)\n"
                                    return f"• {group_label}: {mins:,} min\n"
                                else:
                                    count = item.get('count', 0)
                                    if total > 0:
                                        pct = (count / total) * 100
                                        return f"• {group_label}: {count:,} ({pct:.1f}%)\n"
                                    return f"• {group_label}: {count:,}\n"
                            
                            # Show all groups if max_items is None, otherwise limit
                            display_limit = len(sorted_data) if max_items is None else 25
                            for item in sorted_data[:display_limit]:
                                response += format_grouped_item(item, total_items, has_minutes)

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

            # Format in LLM-friendly way - this is the main content
            max_items = None if show_all else 50
            formatted_result = format_llm_friendly(filtered, max_items=max_items, primary_entity=primary_entity)
            
            # Pagination detection: Check if results exceed 50 and get total count
            total_count = None
            current_count = len(filtered) if isinstance(filtered, list) else (1 if filtered else 0)
            intent_dict = result.get("intent", {}) if isinstance(result.get("intent"), dict) else {}
            skip_value = intent_dict.get("skip", 0)
            limit_value = intent_dict.get("limit", 50)
            
            # Check if this is a grouped query - grouped queries have different pagination logic
            is_grouped_query = intent_dict.get("group_by") and len(intent_dict.get("group_by", [])) > 0
            
            # For grouped queries, check if we have many groups (>= 25 groups suggests pagination might be needed)
            # For non-grouped queries, check if we got exactly the limit (50) results
            needs_pagination_check = False
            if is_grouped_query:
                # For grouped queries, if we have 25+ groups, check total count
                needs_pagination_check = isinstance(filtered, list) and len(filtered) >= 25
            else:
                # For non-grouped queries, if we got exactly the limit (50) results, there might be more
                needs_pagination_check = isinstance(filtered, list) and len(filtered) >= 50
            
            # If we need to check pagination, get total count
            if needs_pagination_check and not intent_dict.get("wants_count"):
                try:
                    # Build a count query with the same filters
                    # For grouped queries, we need to count all items (not groups)
                    # For non-grouped queries, count all matching items
                    entity_name = intent_dict.get("primary_entity", "items")
                    query_lower = query.lower()
                    
                    # Build count query - preserve filters from original query
                    # Strategy: Use "how many [entity]" and preserve filter context
                    if "how many" not in query_lower and "count" not in query_lower:
                        # Try to preserve the original query structure but convert to count
                        # Remove grouping/breakdown keywords and convert to count
                        count_query = query
                        # Remove grouping-related phrases
                        count_query = re.sub(r'\b(breakdown|group|grouped|by)\s+[^,]+', '', count_query, flags=re.IGNORECASE)
                        count_query = re.sub(r'\b(sales\s+cycle|cycle)\b', entity_name.lower(), count_query, flags=re.IGNORECASE)
                        
                        # If entity name is in query, replace with "how many [entity]"
                        if entity_name.lower() in count_query.lower():
                            pattern = r'\b' + re.escape(entity_name.lower()) + r'\b'
                            count_query = re.sub(pattern, f"how many {entity_name.lower()}", count_query, count=1, flags=re.IGNORECASE)
                        else:
                            # Prepend "how many [entity]"
                            count_query = f"how many {entity_name.lower()}"
                            # Try to preserve filters
                            filter_keywords = ["with", "where", "that", "having", "status", "priority", "assigned", "in"]
                            for keyword in filter_keywords:
                                if keyword in query_lower:
                                    idx = query_lower.find(keyword)
                                    filter_part = query[idx:]
                                    # Remove grouping parts from filter
                                    filter_part = re.sub(r'\b(breakdown|group|grouped|by)\s+[^,]+', '', filter_part, flags=re.IGNORECASE)
                                    count_query += " " + filter_part
                                    break
                    else:
                        count_query = query
                    
                    # Execute count query
                    count_result = await plan_and_execute_query(count_query)
                    if count_result.get("success"):
                        count_data = count_result.get("result")
                        if isinstance(count_data, list) and len(count_data) > 0:
                            first_item = count_data[0]
                            if isinstance(first_item, dict) and "total" in first_item:
                                total_count = first_item["total"]
                            elif isinstance(count_data, str):
                                # Try to parse JSON string
                                try:
                                    parsed_count = json.loads(count_data)
                                    if isinstance(parsed_count, list) and len(parsed_count) > 0:
                                        if isinstance(parsed_count[0], dict) and "total" in parsed_count[0]:
                                            total_count = parsed_count[0]["total"]
                                except:
                                    pass
                    else:
                        # Log the error for debugging
                        logger.warning(f"Count query failed for pagination: {count_result.get('error', 'Unknown error')}")
                except Exception as e:
                    # If count query fails, continue without total count
                    logger.warning(f"Failed to get total count for pagination: {e}")
                    pass
            
            # Add pagination info to response if applicable
            # For grouped queries, compare total items (sum of counts) vs current groups
            # For non-grouped queries, compare total_count vs current_count
            if total_count is not None:
                if is_grouped_query:
                    # For grouped queries, calculate total items from group counts
                    total_items_in_groups = 0
                    if isinstance(filtered, list):
                        for item in filtered:
                            if isinstance(item, dict):
                                total_items_in_groups += item.get("count", 0)
                    
                    # Only show pagination if total_count > total_items_in_groups
                    if total_count > total_items_in_groups:
                        remaining = total_count - total_items_in_groups
                        # Add pagination info for grouped results
                        pagination_footer = f"\n---\n"
                        pagination_footer += f"**Note:** Found **{total_count:,} total** {primary_entity.lower()}, "
                        pagination_footer += f"showing breakdown of **{total_items_in_groups:,}** items across **{len(filtered)}** groups. "
                        pagination_footer += f"There are **{remaining:,} more** items not shown in these groups. "
                        pagination_footer += f"Would you like me to fetch more groups or see all items?\n"
                        if formatted_result:
                            formatted_result += pagination_footer
                else:
                    # For non-grouped queries, standard pagination
                    if total_count > current_count:
                        start_item = skip_value + 1
                        end_item = skip_value + current_count
                        remaining = total_count - end_item
                        
                        # Add pagination header before results
                        pagination_header = f"\n## Results Summary\n"
                        pagination_header += f"Found **{total_count:,} total** {primary_entity.lower()}\n"
                        pagination_header += f"Showing **{start_item}-{end_item}** of {total_count:,} results\n\n"
                        
                        # Insert pagination header at the start of formatted_result if it exists
                        if formatted_result:
                            # Check if formatted_result already has a header
                            if formatted_result.startswith("📊"):
                                # Insert after the first line
                                lines = formatted_result.split("\n", 1)
                                formatted_result = lines[0] + "\n" + pagination_header + (lines[1] if len(lines) > 1 else "")
                            else:
                                formatted_result = pagination_header + formatted_result
                            
                            # Add pagination footer
                            formatted_result += f"\n---\n"
                            formatted_result += f"**Note:** There are **{remaining:,} more** results available. "
                            formatted_result += f"Would you like me to fetch the next page? "
                            formatted_result += f"(You can say 'show next page', 'fetch more', or 'page 2')\n"
            
            # If members primary entity and no rows, proactively hint about filters
            try:
                if isinstance(result.get("intent"), dict) and result["intent"].get("primary_entity") == "members" and not filtered:
                    formatted_result += "\n(No members matched. Try filtering by name, role, type, or project.)"
            except Exception:
                pass
            
            # Add the formatted result - this is the actual data the LLM needs
            if formatted_result:
                response += formatted_result
            else:
                response += "No results found."
            elapsed_ms = (perf_counter() - tool_start_time) * 1000
            print(f"mongo_query (including planner) for '{query[:50]}...' took {elapsed_ms:.2f} ms")
            return response
        else:
            return f"❌ QUERY FAILED:\nQuery: '{query}'\nError: {result['error']}"

    except KeyError as ke:
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"mongo_query for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {ke}")
        return f"❌ Missing required field in query result: {ke}"
    except TypeError as te:
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"mongo_query for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {te}")
        return f"❌ Type error in query processing: {te}"
    except ValueError as ve:
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"mongo_query for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {ve}")
        return f"❌ Invalid value in query: {ve}"
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error executing mongo_query: {e}\n{error_details}")
        elapsed_ms = (perf_counter() - tool_start_time) * 1000
        print(f"mongo_query for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {e}")
        return f"❌ Error executing query: {str(e)}"


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
    - Find relevant leads, tasks, activities, meetings, notes, call logs, mail info
    - Search by semantic meaning (not just keywords)
    - Get full context for answering questions
    - Analyze content patterns and distributions
    - Group/breakdown results by any dimension
    
    **When to use:**
    - "Find/search/show me leads about X"
    - "What content discusses Y?"
    - "Which tasks mention follow-up?"
    - "Show me recent meetings about onboarding"
    - "Break down results by leadStatus/date/priority/etc."
    
    **Do NOT use for:**
    - Structured database queries (counts, filters on structured fields) → use `mongo_query`
    
    Args:
        query: Search query (semantic meaning, not just keywords)
        content_type: Filter by type - 'lead', 'task', 'activity', 'meeting', 'notes', 'callLog', 'mailInfo', 'segmentation' or None (all)
        group_by: Group results by field - 'leadStatus', 'taskStatus', 'meetingStatus', 'updatedAt', 'priority', 
                 'content_type', 'assignedName', etc. (None = no grouping)
        limit: Max results to retrieve (default 10, increase for broader searches)
        show_content: If True, shows full content; if False, shows only metadata
        use_chunk_aware: If True, uses chunk-aware retrieval for better context (default True)
    
    Returns: FULL chunk content with rich metadata - ready for LLM synthesis and formatting
    
    Examples:
        query="follow-up" → finds all content about follow-up with full text
        query="customer onboarding", content_type="lead" → finds leads with complete content
        query="meetings", content_type="meeting", group_by="meetingStatus" → meetings grouped by status
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
    """Generate leads, tasks, meetings, or notes - sends content DIRECTLY to frontend, returns minimal confirmation.
    
    **CRITICAL TOKEN OPTIMIZATION**: 
    - Full generated content is sent directly to the frontend via WebSocket
    - Agent receives only a minimal success/failure signal (no content details)
    - Prevents generated content from being sent back through the LLM
    
    Use this to create new content:
    - Leads: new customer leads, prospects
    - Tasks: follow-up tasks, reminders
    - Meetings: scheduled meetings, calls
    - Notes: meeting notes, follow-up notes
    
    Args:
        content_type: Type of content - 'lead', 'task', 'meeting', or 'note'
        prompt: User's instruction for what to generate
        template_title: Optional template title to base generation on
        template_content: Optional template content to use as structure
        context: Optional context dict with additional parameters (leadId, etc.)
    
    Returns:
        Minimal success/failure signal (NOT content details) - saves maximum tokens
    
    Examples:
        generate_content(content_type="lead", prompt="New lead: TechCorp Inc, interested in CRM")
        generate_content(content_type="task", prompt="Follow-up task: Call customer tomorrow")
        generate_content(content_type="meeting", prompt="Schedule meeting with lead")
        generate_content(content_type="note", prompt="Meeting notes: Discussed pricing")
    """
    import httpx
    
    try:
        if content_type not in ["lead", "task", "meeting", "note"]:
            return "❌ Invalid content type"
        
        # Get API base URL from environment; require explicit configuration to avoid hardcoded defaults
        api_base = os.getenv("API_BASE_URL") or os.getenv("API_HTTP_URL")
        if not api_base:
            raise RuntimeError("API_BASE_URL environment variable is not set")
        
        if content_type == "lead":
            # Call lead generation endpoint (if available)
            # For now, return a simple confirmation
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "lead",
                        "data": {"name": prompt, "leadStatus": "NEW"},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated lead as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_lead
                    await save_generated_lead(conv_id, {
                        "name": prompt,
                        "leadStatus": "NEW",
                    })
            except Exception as e:
                logger.error(f"Failed to persist generated lead to conversation: {e}")
            
            return "✅ Content generated"
            
        elif content_type == "task":
            # Call task generation endpoint (if available)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "task",
                        "data": {"name": prompt, "taskStatus": "NEW"},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated task as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_task
                    await save_generated_task(conv_id, {
                        "name": prompt,
                        "taskStatus": "NEW",
                    })
            except Exception as e:
                logger.error(f"Failed to persist generated task to conversation: {e}")
            
            return "✅ Content generated"
            
        elif content_type == "meeting":
            # Call meeting generation endpoint (if available)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "meeting",
                        "data": {"title": prompt, "meetingStatus": "NEW"},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated meeting as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_meeting
                    await save_generated_meeting(conv_id, {
                        "title": prompt,
                        "meetingStatus": "NEW",
                    })
            except Exception as e:
                logger.error(f"Failed to persist generated meeting to conversation: {e}")
            
            return "✅ Content generated"
            
        elif content_type == "leadScoreRule":
            # Call lead score rule generation endpoint (if available)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "leadScoreRule",
                        "data": {"name": prompt, "isActive": True},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")
            return "✅ Content generated"
            
        elif content_type == "segmentation":
            # Call segmentation generation endpoint (if available)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "segmentation",
                        "data": {"name": prompt, "isActive": True},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")
            return "✅ Content generated"
            
        else:  # content_type == "note"
            # Call note generation endpoint (if available)
            websocket = get_generation_websocket()
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "content_generated",
                        "content_type": "note",
                        "data": {"subject": prompt, "description": template_content or ""},
                        "success": True
                    })
                except Exception as e:
                    logger.error(f"Could not send to websocket: {e}")

            # Persist generated note as a conversation message (best-effort)
            try:
                conv_id = get_generation_conversation_id()
                if conv_id:
                    from mongo.conversations import save_generated_note
                    await save_generated_note(conv_id, {
                        "subject": prompt,
                        "description": template_content or "",
                    })
            except Exception as e:
                logger.error(f"Failed to persist generated note to conversation: {e}")
            
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
    generate_content,         # Generate leads/tasks/meetings/notes (returns summary only, not full content)
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
