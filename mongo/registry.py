#!/usr/bin/env python3
"""
CRM Registry - Central definitions for relationships, fields, and aliases
"""

from typing import Dict, List, Any, Set

# ---- Relation Registry (single source of truth for hops)
REL: Dict[str, Dict[str, dict]] = {
    "Lead": {
        # Lead has embedded references; lookups only if deeper fields needed
        "task": {
            "target": "Task",
            "localField": "_id",
            "foreignField": "parentId",
            "as": "tasks",
            "many": True
        },
        "activity": {
            "target": "Activity",
            "localField": "_id",
            "foreignField": "leadId",
            "as": "activities",
            "many": True
        },
        "meeting": {
            "target": "Meeting",
            "localField": "_id",
            "foreignField": "leadId",
            "as": "meetings",
            "many": True
        },
        "notes": {
            "target": "Notes",
            "localField": "_id",
            "foreignField": "leadId",
            "as": "notes",
            "many": True
        },
        "callLog": {
            "target": "CallLog",
            "localField": "_id",
            "foreignField": "leadId",
            "as": "callLogs",
            "many": True
        },
        "mailInfo": {
            "target": "MailInfo",
            "localField": "_id",
            "foreignField": "leadId",
            "as": "mailInfos",
            "many": True
        },
    },
    "Task": {
        # Task references Lead via parentId
        "lead": {
            "target": "Lead",
            "localField": "parentId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
    },
    "Activity": {
        # Activity references Lead and Task
        "lead": {
            "target": "Lead",
            "localField": "leadId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
        "task": {
            "target": "Task",
            "localField": "parentId",
            "foreignField": "_id",
            "as": "task",
            "many": False
        },
    },
    "Meeting": {
        # Meeting references Lead
        "lead": {
            "target": "Lead",
            "localField": "leadId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
    },
    "Notes": {
        # Notes references Lead
        "lead": {
            "target": "Lead",
            "localField": "leadId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
    },
    "CallLog": {
        # CallLog references Lead
        "lead": {
            "target": "Lead",
            "localField": "leadId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
    },
    "MailInfo": {
        # MailInfo references Lead
        "lead": {
            "target": "Lead",
            "localField": "leadId",
            "foreignField": "_id",
            "as": "lead",
            "many": False
        },
    },
}

# ---- Collections (one source of truth)
Collection = str  # Simplified for tool usage

# ---- Allow-listed fields (restrict what the LLM can query/sort/project)
ALLOWED_FIELDS: Dict[str, Set[str]] = {
    "Lead": {
        "_id", "referenceNo", "leadStatus", "personalInfo", "personalInfo.name", "personalInfo.email", 
        "personalInfo.mobile", "address", "type", "leadActiveType", "customerType", "status", "source",
        "score", "emailCount", "callCount", "emailSentStatus", "callExecutedStatus", 
        "isMasked", "isSpamOrBot", "isRemainderMailSent", "createdTimeStamp", "updatedTimeStamp",
        "businessId", "createdById", "createdByName", "staffId", "staffName", "pipeline", 
        "pipeline.name", "pipelineStage", "notes", "moreInfo", "fieldData", "company",
        "gstDetails", "shippingAddress"
    },
    "Task": {
        "_id", "name", "priority", "dueDate", "taskStatus", "reminderDays", "reminderDate",
        "notify", "description", "parentId", "parentName", "assignedTo", "assignedName",
        "assignToMailId", "createdById", "createdByName", "createdTimeStamp", "updatedTimeStamp",
        "businessId"
    },
    "Activity": {
        "_id", "type", "leadId", "parentId", "activityStatus", "data", "createdTimeStamp",
        "updatedTimeStamp", "businessId", "createdById", "createdByName"
    },
    "Meeting": {
        "_id", "title", "description", "meetingStatus", "meetingType", "leadId", "leadName",
        "createdById", "createdByName", "assignedTo", "assignedName", "participantsList",
        "meetingLink", "meetingLocated", "remainder", "participantsRemainder", "emailData",
        "startDateTime", "endDateTime", "createdTimeStamp", "updatedTimeStamp", "businessId"
    },
    "Notes": {
        "_id", "subject", "description", "leadId", "leadName", "createdById", "createdByName",
        "taskId", "createdTimeStamp", "updatedTimeStamp", "notesAttachments", "businessId"
    },
    "CallLog": {
        "_id", "title", "description", "callPurpose", "callStatus", "callType", "call_variant",
        "leadId", "leadName", "createdById", "createdByName", "startDateTime", "otherReason",
        "callDuration", "remainder", "createdTimeStamp", "updatedTimeStamp", "businessId"
    },
    "MailInfo": {
        "_id", "subject", "body", "mailType", "leadId", "toMails", "toCcMails", "toBccMails",
        "attachments", "createdById", "createdByName", "createdTimeStamp", "updatedTimeStamp",
        "businessId"
    },
    "LeadScoreRule": {
        "_id", "name", "description", "score", "change", "aiAdjusted", "isActive", "field",
        "operator", "value", "business", "business._id", "business.name", "createdAt", "updatedAt"
    },
}

# ---- Field Aliases (map common names to actual field names)
ALIASES: Dict[str, Dict[str, str]] = {
    "Lead": {
        "status": "leadStatus",
        "name": "personalInfo.name",
        "email": "personalInfo.email",
        "mobile": "personalInfo.mobile",
    },
    "Task": {
        "status": "taskStatus",
    },
    "Activity": {
        "status": "activityStatus",
    },
    "Meeting": {
        "status": "meetingStatus",
    },
    "CallLog": {
        "status": "callStatus",
    },
}

def resolve_field_alias(collection: str, field: str) -> str:
    """Resolve field alias to actual field name"""
    if collection in ALIASES and field in ALIASES[collection]:
        return ALIASES[collection][field]
    return field

def validate_fields(collection: str, fields: List[str]) -> List[str]:
    """Validate and filter fields against allowed fields for a collection."""
    if collection not in ALLOWED_FIELDS:
        return []
    allowed = ALLOWED_FIELDS[collection]
    return [field for field in fields if resolve_field_alias(collection, field) in allowed]

def build_lookup_stage(from_collection: str, relationship: Dict[str, Any], current_collection: str, additional_filters: Dict[str, Any] = None, local_field_prefix: str = None) -> Dict[str, Any]:
    """Build a MongoDB $lookup stage from a relationship definition.
    
    Args:
        from_collection: The collection to lookup from (target)
        relationship: Relationship definition dict with keys: target, localField, foreignField, as, many
        current_collection: Current collection name (for context)
        additional_filters: Optional additional filters to apply in the lookup pipeline
        local_field_prefix: Optional prefix for local field (for multi-hop lookups)
    
    Returns:
        MongoDB $lookup stage dict
    """
    target = relationship.get("target", from_collection)
    local_field = relationship.get("localField", "_id")
    foreign_field = relationship.get("foreignField", "_id")
    as_alias = relationship.get("as") or relationship.get("alias") or target
    many = relationship.get("many", False)
    
    # Apply local field prefix if provided (for multi-hop)
    if local_field_prefix:
        local_field = f"{local_field_prefix}.{local_field}" if not local_field.startswith("$") else local_field
    
    # Build lookup pipeline
    lookup_pipeline = [
        {"$match": {foreign_field: f"${local_field}"}}
    ]
    
    # Add additional filters if provided
    if additional_filters:
        lookup_pipeline.append({"$match": additional_filters})
    
    # Build lookup stage
    lookup_stage = {
        "$lookup": {
            "from": target,
            "let": {"local_id": f"${local_field}"},
            "pipeline": [
                {
                    "$match": {
                        "$expr": {
                            "$eq": [f"${foreign_field}", "$$local_id"]
                        }
                    }
                }
            ] + (lookup_pipeline[1:] if len(lookup_pipeline) > 1 else []),
            "as": as_alias
        }
    }
    
    return lookup_stage

