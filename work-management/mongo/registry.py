#!/usr/bin/env python3
"""
PMS Registry - Central definitions for relationships, fields, and aliases
"""

from typing import Dict, List, Any, Set

# ---- Relation Registry (single source of truth for hops)
REL: Dict[str, Dict[str, dict]] = {
    "workItem": {
        # workItem has embedded project {_id, name}; lookup only if you need more fields
        "project": {
            "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "projectDoc",
            "many": False
        },
        # workItem.assignee is an array of subdocs (with _id). Join to members by _id.
        "assignee": {
            "target": "members",
            "localField": "assignee._id",
            "foreignField": "_id",
            "as": "assignees",
            "many": True
        },
        # workItem has embedded cycle {_id, name}; join only if deeper cycle fields are needed
        "cycle": {
            "target": "cycle",
            "localField": "cycle._id",
            "foreignField": "_id",
            "as": "cycleDoc",
            "many": False
        },
        # workItem has embedded modules {_id, name} (single module reference despite plural key)
        "modules": {
            "target": "module",
            "localField": "modules._id",
            "foreignField": "_id",
            "as": "moduleDoc",
            "many": False
        },
    },

    "project": {
        # One project → many cycles/modules/members/pages/projectStates
        "cycles": {
            "target": "cycle",
            "localField": "_id",
            "foreignField": "project._id",
            "as": "cycles",
            "many": True
        },
        "modules": {
            "target": "module",
            "localField": "_id",
            "foreignField": "project._id",
            "as": "modules",
            "many": True
        },
        "members": {
            "target": "members",
            "localField": "_id",
            "foreignField": "project._id",
            "as": "members",
            "many": True
        },
        "pages": {
            "target": "page",
            "localField": "_id",
            "foreignField": "project._id",
            "as": "pages",
            "many": True
        },
        "projectStates": {
            "target": "projectState",
            "localField": "_id",
            "foreignField": "projectId",
            "as": "projectStates",
            "many": True
        },
    },

    "cycle": {
        "project": {
            "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        }
    },

    "module": {
        "project": {
            "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        },
        "assignee": {
            "target": "members",
            "localField": "assignee._id",
            "foreignField": "_id",
            "as": "assignees",
            "many": True
        }
    },

    "members": {
        "project": {
            "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        }
    },

    "page": {
        "project": {
            "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "projectDoc",
            "many": False
        },
        "linkedCycle": {
            "target": "cycle",
            "localField": "linkedCycle",
            "foreignField": "_id",
            "as": "linkedCycleDocs",
            "many": True
        },
        "linkedModule": {
            "target": "module",
            "localField": "linkedModule",
            "foreignField": "_id",
            "as": "linkedModuleDocs",
            "many": True
        },
        # Optional: pages can link to members; support lookups when present
        "linkedMembers": {
            "target": "members",
            "localField": "linkedMembers",
            "foreignField": "_id",
            "as": "linkedMembersDocs",
            "many": True
        },
    },

    "projectState": {
        "project": {
            "target": "project",
            "localField": "projectId",
            "foreignField": "_id",
            "as": "project",
            "many": False
        }
    },
    "epic":{
        "project":{
             "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        }
    },
    "features":{
        "project":{
             "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        },
        "cycles": {
            "target": "cycle",
            "localField": "cycle._id",
            "foreignField": "_id",
            "as": "linkedCyclefeatures",
            "many": True
        },
        "modules": {
            "target": "module",
            "localField": "modules._id",
            "foreignField": "_id",
            "as": "modules",
            "many": True
        },
    },
    "userStory":{
        "project":{
             "target": "project",
            "localField": "project._id",
            "foreignField": "_id",
            "as": "project",
            "many": False
        }
    }
}

# ---- Collections (one source of truth)
Collection = str  # Simplified for tool usage

# ---- Allow-listed fields (restrict what the LLM can query/sort/project)
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
    },
    "project": {
        "_id", "projectDisplayId", "name", "description",
        "imageUrl", "icon", "access", "isActive", "status",
        "favourite", "isArchived", "createdTimeStamp", "updatedTimeStamp",
        "business._id", "business.name",
        # creator/lead/assignee info
        "createdBy._id", "createdBy.name",
        "lead.name", "leadMail",
        # default assignee (note: schema uses 'defaultAsignee' spelling)
        "defaultAsignee._id", "defaultAsignee.name"
    },
    "cycle": {
        "_id", "title", "name", "description", "status",
        "startDate", "endDate",
        "project._id",
        "isDefault", "isFavourite",
        "createdTimeStamp", "updatedTimeStamp",
        "business._id",
        # normalized scalar fields from planner
        "projectName", "projectBusinessName", "projectId"
    },
    "module": {
        "_id", "title", "name", "description", "isFavourite",
        "project._id", "business._id",
        "createdTimeStamp", "assignee",
        # optional lead object commonly present in modules
        "lead.name",
        # normalized scalar fields from planner
        "projectName", "projectBusinessName", "projectId"
    },
    "members": {
        "_id", "name", "email", "role", "joiningDate",
        "type", "project._id", "project.name",
        "memberId", "staff._id", "staff.name",
        # normalized scalar fields from planner
        "projectName", "projectBusinessName", "projectId"
    },
    "page": {
        "_id", "title", "content", "visibility",
        "project._id", "project.name",
        "createdBy._id", "createdBy.name",
        "linkedCycle", "linkedModule",
        "locked", "isFavourite",
        "createdAt", "updatedAt",
        "business._id", "business.name",
        # normalized scalar fields from planner
        "projectName", "projectBusinessName", "projectId"
    },
    "projectState": {
        "_id", "projectId", "name", "icon",
        "subStates.name", "subStates.order"
    },
    "epic":{
        "_id","title", "description","stateMaster._id","stateMaster.name",
        "isMandatory", "isActive","state._id","state.name","priority","assignee",
        "label","project._id","project.name","business._id","bugNo",
        "customProperties",
        # "propertyType.value","propertyType.attributeType",
        # "propertyType.attributeValue","propertyType.attributeOptions"
        "createdBy._id", "createdBy.name",
        "createdTimeStamp", "updatedTimeStamp", "dueDate",
        "assignee", "assignee._id", "assignee.name", "label.name"
    },
    "features":{
        "basicInfo.title","basicInfo.description","basicInfo.epicId","basicInfo.moduleId","basicInfo.status",
        "problemInfo.statement","problemInfo.objective","problemInfo.successCriteria","successCriteria","displayBugNo","requirements.functionalRequirements",
        "requirements.nonFunctionalRequirements","riskAndDependencies.dependencies","riskAndDependencies.risks",
        "createdBy._id", "createdBy.name","project._id","project.name","createdTimeStamp","scope.inScope","scope.OutOfScope",
        "updatedTimeStamp","workItems","userStories","addLink","goals","painPoints","title","description",
        "endDate","startDate","releaseDate","state._id","state.name","business._id","business.name","lead._id","lead.name",
        "priority","assignee._id","assignee.name","label._id","label.name","cycle._id", "cycle.name",
        "modules._id", "modules.name","parent._id","parent.name","estimateSystem", "estimate", "estimate.hr", "estimate.min",
        "workLogs", "workLogs.user", "workLogs.user.name", "workLogs.hours", 
        "workLogs.minutes", "workLogs.description", "workLogs.loggedAt"
    },
    "userStory":{
        "_id","title", "description","stateMaster._id","stateMaster.name",
        "state._id","state.name","priority","assignee",
        "label","project._id","business._id","displayBugNo",
        "createdBy._id", "createdBy.name",
        "createdTimeStamp", "updatedTimeStamp", "dueDate","startDate",
        "assignee", "assignee._id", "assignee.name", "label.name","userGoal",
        "persona","demographics","acceptanceCriteria","epic._id","epic.name",
        "feature._id","feature.name"
    }
}

# ---- Optional field aliases (normalize synonyms / UI names)
ALIASES: Dict[str, Dict[str, str]] = {
    "project": {"id": "_id", "displayId": "projectDisplayId"},
    "workItem": {"bug": "displayBugNo", "stateName": "state.name", "last_date": "updatedTimeStamp"},
    "members": {"memberId": "_id"},
    "module": {},
    "page": {},
    "cycle": {},
    "projectState": {},
    "epic": { "bug": "bugNo", "stateName": "state.name", "last_date": "updatedTimeStamp","start_date" : "createdTimeStamp","assignee_name": "assignee.name"}
}

def resolve_field_alias(collection: str, field: str) -> str:
    """Resolve field aliases to actual field names."""
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
    """Build MongoDB $lookup stage based on relationship definition.

    Enhancements:
    - Supports field-to-field joins with $expr
    - Handles array-joins using $in when appropriate
    - Parses simple "X in Y" and "X = Y" expressions from relationship["expr"]
    - Keeps local field paths relative to current document context
    """
    def _is_array_like(path: str) -> bool:
        candidates = [
            "assignee", "linkedCycle", "linkedModule",
            "assignees", "members", "labels", "subStates._id"
        ]
        return any(c in path for c in candidates)

    # Helper to strip collection prefix from a dotted path
    def _strip_prefix(path: str, prefix: str) -> str:
        parts = path.split(".")
        if parts[0] == prefix:
            return ".".join(parts[1:])
        return path

    alias_name = relationship.get("as") or relationship.get("alias") or relationship.get("target") or from_collection
    lookup_stage: Dict[str, Any] = {
        "$lookup": {
            "from": from_collection,
            "let": {},
            "pipeline": [],
            "as": alias_name
        }
    }

    # New style: localField / foreignField
    if "localField" in relationship and "foreignField" in relationship:
        local_field_raw = relationship["localField"]
        foreign_field_raw = relationship["foreignField"]
        # Keep local path relative to current document
        local_field_path = _strip_prefix(local_field_raw, current_collection)
        if local_field_prefix:
            # When doing multi-hop, reference the field from prior lookup alias
            local_field_path = f"{local_field_prefix}.{local_field_path}"
        # Foreign path should be relative to remote collection
        foreign_field_path = _strip_prefix(foreign_field_raw, from_collection)

        var_name = f"local_{local_field_path.replace('.', '_')}"
        lookup_stage["$lookup"]["let"][var_name] = f"${local_field_path}"

        if _is_array_like(local_field_path):
            match_condition = {"$expr": {"$in": [f"${foreign_field_path}", f"$${var_name}"]}}
        else:
            match_condition = {"$expr": {"$eq": [f"$${var_name}", f"${foreign_field_path}"]}}
        lookup_stage["$lookup"]["pipeline"].append({"$match": match_condition})

    elif "join" in relationship:
        # Simple join relationship using field mappings
        join_conditions = relationship["join"]
        for foreign_field, local_field in join_conditions.items():
            foreign_parts = foreign_field.split(".")
            local_parts = local_field.split(".")
            if len(foreign_parts) > 1 and len(local_parts) > 1:
                foreign_collection = foreign_parts[0]
                foreign_field_name = ".".join(foreign_parts[1:])

                # Keep the local path relative to current document unless it's prefixed with current_collection
                if local_parts[0] == current_collection:
                    local_field_path = ".".join(local_parts[1:])
                else:
                    local_field_path = ".".join(local_parts)
                if local_field_prefix:
                    local_field_path = f"{local_field_prefix}.{local_field_path}"

                var_name = f"local_{local_field_path.replace('.', '_')}"
                lookup_stage["$lookup"]["let"][var_name] = f"${local_field_path}"

                # Choose $eq or $in depending on whether local looks like an array
                if _is_array_like(local_field_path):
                    match_condition = {
                        "$expr": {"$in": [f"${foreign_field_name}", f"$${var_name}"]}
                    }
                else:
                    match_condition = {
                        "$expr": {"$eq": [f"$${var_name}", f"${foreign_field_name}"]}
                    }
                lookup_stage["$lookup"]["pipeline"].append({"$match": match_condition})

    elif "expr" in relationship:
        # Parse simple expressions like "A.B in C.D" or "A.B = C.D"
        expr_str: str = relationship["expr"].strip()
        # Normalize operators
        normalized = expr_str.replace("==", "=")
        op = "in" if " in " in normalized else "=" if "=" in normalized else None
        if op is not None:
            left, right = [p.strip() for p in normalized.split(" in " if op == "in" else "=")]
            # left refers to one side (could be local or foreign), right the other
            # Determine which side is remote (from_collection) and which is local (current_collection)
            left_prefix = left.split(".")[0]
            right_prefix = right.split(".")[0]

            # Build paths without their collection prefixes when referencing remote
            def strip_prefix(path: str, prefix: str) -> str:
                parts = path.split(".")
                if parts[0] == prefix:
                    return ".".join(parts[1:])
                return path

            # Identify local and remote sides
            if left_prefix == from_collection:
                remote_field = strip_prefix(left, from_collection)
                # right should be from current document
                if right_prefix == current_collection:
                    local_field_path = strip_prefix(right, current_collection)
                else:
                    local_field_path = right  # already relative to current doc
                var_name = f"local_{local_field_path.replace('.', '_')}"
                lookup_stage["$lookup"]["let"][var_name] = f"${local_field_path}"

                if op == "in":
                    # remote scalar IN local array
                    match_condition = {"$expr": {"$in": [f"${remote_field}", f"$${var_name}"]}}
                else:
                    # equality
                    match_condition = {"$expr": {"$eq": [f"${remote_field}", f"$${var_name}"]}}
                lookup_stage["$lookup"]["pipeline"].append({"$match": match_condition})

            else:
                # Treat left as local, right as remote
                if left_prefix == current_collection:
                    local_field_path = strip_prefix(left, current_collection)
                else:
                    local_field_path = left
                if local_field_prefix:
                    local_field_path = f"{local_field_prefix}.{local_field_path}"
                var_name = f"local_{local_field_path.replace('.', '_')}"
                lookup_stage["$lookup"]["let"][var_name] = f"${local_field_path}"
                remote_field = strip_prefix(right, from_collection)

                if op == "in":
                    # local scalar IN remote array
                    match_condition = {"$expr": {"$in": [f"$${var_name}", f"${remote_field}"]}}
                else:
                    match_condition = {"$expr": {"$eq": [f"$${var_name}", f"${remote_field}"]}}
                lookup_stage["$lookup"]["pipeline"].append({"$match": match_condition})

        # Special-case: optional fallback noted in expr string
        if "name-eq" in expr_str.lower():
            # Heuristic: attempt to match by name fields as a fallback
            # local: try state.name, remote: try name or subStates.name
            or_conditions = []
            # local state.name
            lookup_stage["$lookup"]["let"]["local_state_name"] = "$state.name"
            or_conditions.append({"$expr": {"$eq": ["$name", "$$local_state_name"]}})
            or_conditions.append({"$expr": {"$in": ["$$local_state_name", "$subStates.name"]}})
            lookup_stage["$lookup"]["pipeline"].append({"$match": {"$or": or_conditions}})

    # Add additional filters if provided
    if additional_filters:
        lookup_stage["$lookup"]["pipeline"].append({"$match": additional_filters})

    # Add defaults if specified
    if "defaults" in relationship:
        lookup_stage["$lookup"]["pipeline"].append({"$match": relationship["defaults"]})

    return lookup_stage
