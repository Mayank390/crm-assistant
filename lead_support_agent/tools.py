"""
Lead Support Agent Tools - Focused tools for lead-related support functionality.

These tools provide:
- Lead context gathering (details, history, related data)
- Lead comparison utilities
- Content generation for messages and emails
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, Iterable, Tuple, Union

from bson import ObjectId
from bson.binary import Binary
from langchain_core.tools import tool

from mongo.constants import (
    mongodb_tools,
    DATABASE_NAME,
    uuid_str_to_mongo_binary,
    BUSINESS_UUID,
    mongo_binary_to_uuid_str,
)

logger = logging.getLogger(__name__)


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Convert deviant timestamp formats to datetime objects."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict) and "$date" in value:
        raw = value.get("$date")
        if isinstance(raw, str):
            try:
                if raw.endswith("Z"):
                    raw = raw.replace("Z", "+00:00")
                return datetime.fromisoformat(raw)
            except Exception:
                return None
    if isinstance(value, str):
        try:
            candidate = value
            if candidate.endswith("Z"):
                candidate = candidate.replace("Z", "+00:00")
            return datetime.fromisoformat(candidate)
        except Exception:
            return None
    return None


def _format_datetime(value: Any) -> str:
    dt = _coerce_datetime(value)
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _safe_text(value: Any, default: str = "N/A") -> str:
    if value in (None, "", [], {}):
        return default
    if isinstance(value, datetime):
        return _format_datetime(value)
    return str(value)


def _try_parse_object_id(value: str) -> Optional[ObjectId]:
    try:
        return ObjectId(value)
    except Exception:
        return None


def _try_parse_uuid_binary(value: str) -> Optional[Binary]:
    try:
        return uuid_str_to_mongo_binary(value)
    except Exception:
        return None


def _try_parse_hex_binary(value: str) -> Optional[Binary]:
    """Try to parse a hex string as a MongoDB Binary UUID (subtype 3)."""
    try:
        # Remove any spaces or non-hex characters
        clean_hex = ''.join(c for c in value.lower() if c in '0123456789abcdef')
        if len(clean_hex) == 32:  # 16 bytes = 32 hex chars
            binary_data = bytes.fromhex(clean_hex)
            if len(binary_data) == 16:
                return Binary(binary_data, subtype=3)
    except Exception:
        pass
    return None


def _try_parse_base64_binary(value: str) -> Optional[Binary]:
    try:
        decoded = base64.b64decode(value.strip())
        if len(decoded) == 16:
            return Binary(decoded, subtype=3)
    except Exception:
        return None
    return None


def _collect_identifier_variants(lead_doc: Dict[str, Any], lead_id: Optional[str]) -> List[Any]:
    """Collect possible identifier representations to match related items."""
    candidates: List[Any] = []
    seen: set[Tuple[str, bytes]] = set()

    if lead_doc:
        doc_id = lead_doc.get("_id")
        if doc_id is not None:
            candidates.append(doc_id)
            if isinstance(doc_id, Binary):
                try:
                    uuid_str = mongo_binary_to_uuid_str(doc_id)
                    candidates.append(uuid_str)
                except Exception:
                    pass

    if lead_id:
        candidates.append(lead_id)
        if decoded := _try_parse_base64_binary(lead_id):
            candidates.append(decoded)
        if obj_id := _try_parse_object_id(lead_id):
            candidates.append(obj_id)
        if uuid_bin := _try_parse_uuid_binary(lead_id):
            candidates.append(uuid_bin)

    normalized: List[Any] = []
    for value in candidates:
        if isinstance(value, Binary):
            key = ("bin", bytes(value))
        elif isinstance(value, ObjectId):
            key = ("obj", value.binary)
        else:
            key = ("str", str(value).encode("utf-8"))

        if key not in seen:
            seen.add(key)
            normalized.append(value)

    return normalized


def _build_related_filter(identifiers: Iterable[Any]) -> Dict[str, Any]:
    clauses: List[Dict[str, Any]] = []
    for value in identifiers:
        clauses.append({"parentId": value})
        clauses.append({"leadId": value})
    return {"$or": clauses} if clauses else {}


def _merge_filters(primary: Optional[Dict[str, Any]], business_filter: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if primary and business_filter:
        return {"$and": [primary, business_filter]}
    if business_filter:
        return business_filter
    return primary or {}


def _format_company_section(lead_doc: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    company = lead_doc.get("company") or {}
    if isinstance(company, dict):
        name = company.get("name") or company.get("companyName")
        industry = company.get("industryName")
        website = company.get("website")
        if name:
            lines.append(f"- **Company**: {name}")
        if industry:
            lines.append(f"- **Industry**: {industry}")
        if website:
            lines.append(f"- **Website**: {website}")
    address = lead_doc.get("address") or {}
    if isinstance(address, dict):
        parts = [
            address.get("street"),
            address.get("city"),
            address.get("state"),
            address.get("zipCode"),
        ]
        formatted = ", ".join(part for part in parts if part)
        if formatted:
            lines.append(f"- **Address**: {formatted}")
    return lines


def _format_field_data(field_data: Any, limit: int = 6) -> List[str]:
    if not isinstance(field_data, list):
        return []
    lines: List[str] = []
    for entry in field_data[:limit]:
        if not isinstance(entry, dict):
            continue
        key = entry.get("fieldName") or entry.get("fieldId")
        value = entry.get("fieldValue")
        if key and value:
            lines.append(f"- **{key}**: {value}")
    return lines


def _build_snapshot_section(
    tasks: List[Dict[str, Any]],
    meetings: List[Dict[str, Any]],
    notes: List[Dict[str, Any]],
    activities: List[Dict[str, Any]],
    calls: List[Dict[str, Any]],
    emails: List[Dict[str, Any]],
    latest_event: str,
) -> str:
    def _count_open(items: List[Dict[str, Any]], status_key: str, closed_values: Iterable[str]) -> int:
        closed = {value.upper() for value in closed_values}
        count = 0
        for item in items:
            status = (item.get(status_key) or "").upper()
            if status and status not in closed:
                count += 1
        return count

    open_tasks = _count_open(tasks, "taskStatus", ["COMPLETED", "CANCELLED"])
    upcoming_meetings = _count_open(meetings, "meetingStatus", ["COMPLETED", "CANCELLED"])

    lines = [
        "## Engagement Snapshot",
        f"- **Tasks**: {len(tasks)} total ({open_tasks} open)",
        f"- **Meetings**: {len(meetings)} total ({upcoming_meetings} upcoming)",
        f"- **Notes**: {len(notes)} | **Activities**: {len(activities)}",
        f"- **Calls**: {len(calls)} | **Emails**: {len(emails)}",
        f"- **Latest Touchpoint**: {latest_event}",
    ]
    return "\n".join(lines)


async def _fetch_related_documents(
    db,
    collection: str,
    related_filter: Dict[str, Any],
    business_filter: Optional[Dict[str, Any]],
    sort_field: str,
    limit: int,
) -> List[Dict[str, Any]]:
    query = _merge_filters(related_filter or {}, business_filter)
    cursor = db[collection].find(query)
    if sort_field:
        cursor = cursor.sort(sort_field, -1)
    if limit:
        cursor = cursor.limit(limit)
    return await cursor.to_list(length=limit)


# ============================================================================
# Tool 1: Get Lead Context
# ============================================================================

@tool
async def get_lead_context(
    lead_id: str,
    include_tasks: bool = True,
    include_meetings: bool = True,
    include_notes: bool = True,
    include_activities: bool = True,
    include_calls: bool = True,
    include_emails: bool = True
) -> str:
    """
    Gather comprehensive context about a specific lead including all related data.

    Args:
        lead_id: Lead identifier (UUID/ObjectId/base64 string)
        include_*: Toggles for related data

    Returns:
        Markdown formatted context block
    """
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        business_filter: Optional[Dict[str, Any]] = {}

        business_uuid = BUSINESS_UUID()
        if business_uuid:
            try:
                business_filter = {"businessId": uuid_str_to_mongo_binary(business_uuid)}
            except Exception:
                logger.warning("BUSINESS_UUID is invalid; skipping enforced business filter.")
                business_filter = {}
        else:
            business_filter = {}

        lead_coll = db["Lead"]

        lead_query_clauses: List[Dict[str, Any]] = []
        if obj_id := _try_parse_object_id(lead_id):
            lead_query_clauses.append({"_id": obj_id})
        if uuid_bin := _try_parse_uuid_binary(lead_id):
            lead_query_clauses.append({"_id": uuid_bin})
        if hex_bin := _try_parse_hex_binary(lead_id):
            lead_query_clauses.append({"_id": hex_bin})
        if base64_bin := _try_parse_base64_binary(lead_id):
            lead_query_clauses.append({"_id": base64_bin})
        lead_query_clauses.append({"_id": lead_id})

        lead_query = {"$or": lead_query_clauses}
        lead_query = _merge_filters(lead_query, business_filter)

        lead_doc = await lead_coll.find_one(lead_query)
        if not lead_doc:
            return f"Lead not found with ID: {lead_id}"

        if not business_filter and lead_doc.get("businessId"):
            business_filter = {"businessId": lead_doc["businessId"]}

        identifier_variants = _collect_identifier_variants(lead_doc, lead_id)
        related_filter = _build_related_filter(identifier_variants)

        fetchers = []
        if include_tasks:
            fetchers.append(
                _fetch_related_documents(db, "task", related_filter, business_filter, "createdTimeStamp", 8)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        if include_meetings:
            fetchers.append(
                _fetch_related_documents(db, "meeting", related_filter, business_filter, "createdTimeStamp", 8)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        if include_notes:
            fetchers.append(
                _fetch_related_documents(db, "notes", related_filter, business_filter, "createdTimeStamp", 6)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        if include_activities:
            fetchers.append(
                _fetch_related_documents(db, "activity", related_filter, business_filter, "createdTimeStamp", 10)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        if include_calls:
            fetchers.append(
                _fetch_related_documents(db, "callLog", related_filter, business_filter, "createdTimeStamp", 5)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        if include_emails:
            fetchers.append(
                _fetch_related_documents(db, "mailInfo", related_filter, business_filter, "createdTimeStamp", 5)
            )
        else:
            fetchers.append(asyncio.sleep(0, result=[]))

        tasks, meetings, notes, activities, calls, emails = await asyncio.gather(*fetchers)

        result_parts: List[str] = []
        personal_info = lead_doc.get("personalInfo", {})
        # Extract stage from pipelineStage if available
        pipeline_stage = lead_doc.get('pipelineStage', {})
        stage_name = 'N/A'
        if isinstance(pipeline_stage, dict):
            stage_name = pipeline_stage.get('stageName', 'N/A')

        # Get lead score
        lead_score = lead_doc.get('score', 'N/A')

        profile_lines = [
            "## Lead Profile",
            f"- **Name**: {personal_info.get('name', 'N/A')}",
            f"- **Email**: {personal_info.get('email', 'N/A')}",
            f"- **Mobile**: {personal_info.get('mobile', 'N/A')}",
            f"- **Lead Status**: {lead_doc.get('leadStatus', 'N/A')}",
            f"- **Pipeline Stage**: {stage_name}",
            f"- **Current Status**: {lead_doc.get('status', 'N/A')}",
            f"- **Source**: {lead_doc.get('source', 'N/A')}",
            f"- **Type**: {lead_doc.get('type', 'N/A')}",
            f"- **Lead Score**: {lead_score}",
            f"- **Created**: {_format_datetime(lead_doc.get('createdTimeStamp'))}",
            f"- **Last Updated**: {_format_datetime(lead_doc.get('updatedTimeStamp'))}",
        ]

        company_lines = _format_company_section(lead_doc)
        if company_lines:
            profile_lines.append("")
            profile_lines.append("### Organization")
            profile_lines.extend(company_lines)

        field_lines = _format_field_data(lead_doc.get("fieldData"))
        if not field_lines:
            custom_fields = lead_doc.get("customFields", {})
            if isinstance(custom_fields, dict):
                field_lines = [f"- **{k}**: {v}" for k, v in list(custom_fields.items())[:6]]

        if field_lines:
            profile_lines.append("")
            profile_lines.append("### Key Fields")
            profile_lines.extend(field_lines)

        result_parts.append("\n".join(profile_lines))

        timeline_events: List[Tuple[datetime, str, str]] = []

        def _push_event(ts_value: Any, label: str, detail: str) -> None:
            ts = _coerce_datetime(ts_value)
            if ts:
                timeline_events.append((ts, label, detail))

        for task in tasks:
            _push_event(
                task.get("createdTimeStamp"),
                "Task",
                f"{task.get('name', 'Task')} [{task.get('taskStatus', 'N/A')}] (Due: {_format_datetime(task.get('dueDate'))})",
            )

        for meeting in meetings:
            _push_event(
                meeting.get("startDateTime") or meeting.get("startTime") or meeting.get("createdTimeStamp"),
                "Meeting",
                f"{meeting.get('title', 'Meeting')} [{meeting.get('meetingStatus', 'N/A')}]",
            )

        for note in notes:
            _push_event(
                note.get("createdTimeStamp"),
                "Note",
                f"{note.get('subject', 'Note')} ({_safe_text(note.get('leadName'), 'Lead')})",
            )

        for activity in activities:
            _push_event(
                activity.get("createdTimeStamp"),
                activity.get("type", "Activity"),
                _safe_text(activity.get("description"), "Activity update"),
            )

        for call in calls:
            _push_event(
                call.get("createdTimeStamp"),
                "Call",
                f"{call.get('callPurpose', 'Call')} [{call.get('callStatus', 'N/A')}]",
            )

        for email in emails:
            _push_event(
                email.get("createdTimeStamp"),
                "Email",
                f"{email.get('subject', 'Email')} [{email.get('status', 'N/A')}]",
            )

        timeline_events.sort(key=lambda item: item[0], reverse=True)
        latest_event_str = timeline_events[0][0].strftime("%Y-%m-%d %H:%M UTC") if timeline_events else "No recent activity"

        result_parts.append(
            _build_snapshot_section(tasks, meetings, notes, activities, calls, emails, latest_event_str)
        )

        if tasks:
            task_lines = ["## Related Tasks"]
            for task in tasks:
                task_lines.append(
                    f"- [{task.get('taskStatus', 'N/A')}] **{task.get('name', 'Untitled')}** · Priority: {task.get('priority', 'N/A')} · Due: {_format_datetime(task.get('dueDate'))}"
                )
                if task.get("description"):
                    desc = task.get("description", "")
                    task_lines.append(f"  {desc[:140]}{'...' if len(desc) > 140 else ''}")
            result_parts.append("\n".join(task_lines))

        if meetings:
            meeting_lines = ["## Related Meetings"]
            for meeting in meetings:
                meeting_lines.append(
                    f"- [{meeting.get('meetingStatus', 'N/A')}] **{meeting.get('title', 'Untitled')}** ({meeting.get('meetingType', 'N/A')}) · {_format_datetime(meeting.get('startDateTime') or meeting.get('startTime'))}"
                )
                if meeting.get("description"):
                    desc = meeting.get("description", "")
                    meeting_lines.append(f"  {desc[:180]}{'...' if len(desc) > 180 else ''}")
            result_parts.append("\n".join(meeting_lines))

        if notes:
            note_lines = ["## Notes"]
            for note in notes:
                note_lines.append(
                    f"- **{note.get('subject', 'Note')}** ({_format_datetime(note.get('createdTimeStamp'))})"
                )
                if note.get("description"):
                    desc = note.get("description", "")
                    note_lines.append(f"  {desc[:200]}{'...' if len(desc) > 200 else ''}")
            result_parts.append("\n".join(note_lines))

        if activities:
            activity_lines = ["## Activity History"]
            for activity in activities:
                activity_lines.append(
                    f"- [{activity.get('type', 'N/A')}] {_safe_text(activity.get('description'), 'Activity')} · {_format_datetime(activity.get('createdTimeStamp'))}"
                )
            result_parts.append("\n".join(activity_lines))

        if calls:
            call_lines = ["## Call History"]
            for call in calls:
                call_lines.append(
                    f"- **{call.get('callPurpose', 'Call')}** — {call.get('callStatus', 'N/A')} · Duration: {_safe_text(call.get('duration', 'N/A'))}"
                )
                if call.get("callNotes"):
                    desc = call.get("callNotes", "")
                    call_lines.append(f"  Notes: {desc[:160]}{'...' if len(desc) > 160 else ''}")
            result_parts.append("\n".join(call_lines))

        if emails:
            email_lines = ["## Email History"]
            for email in emails:
                email_lines.append(
                    f"- **{email.get('subject', 'Email')}** — {email.get('status', 'N/A')} · {_format_datetime(email.get('createdTimeStamp'))}"
                )
            result_parts.append("\n".join(email_lines))

        if timeline_events:
            timeline_lines = ["## Recent Timeline"]
            for event in timeline_events[:8]:
                timeline_lines.append(
                    f"- {event[0].strftime('%Y-%m-%d %H:%M UTC')} — **{event[1]}**: {event[2]}"
                )
            result_parts.append("\n".join(timeline_lines))

        return "\n\n".join(result_parts) if result_parts else "No data found for lead."

    except Exception as e:
        logger.error(f"Error in get_lead_context: {e}", exc_info=True)
        return f"Error gathering lead context: {str(e)}"


# ============================================================================
# Tool 2: Compare Leads
# ============================================================================

@tool
async def compare_leads(lead_ids: List[str], compare_with_portfolio: bool = False) -> Union[str, List[Dict[str, Any]]]:
    """
    Compare leads - either specific leads or with business portfolio.

    Args:
        lead_ids: List of lead IDs to compare
        compare_with_portfolio: If True and only one lead_id, return business portfolio for comparison

    Returns:
        Either formatted comparison string or list of lead data for portfolio comparison
    """
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]
        lead_coll = db["Lead"]
        task_coll = db["task"]
        meeting_coll = db["meeting"]
        activity_coll = db["activity"]

        business_filter: Optional[Dict[str, Any]] = {}
        business_uuid = BUSINESS_UUID()
        if business_uuid:
            try:
                business_filter = {"businessId": uuid_str_to_mongo_binary(business_uuid)}
            except Exception:
                logger.warning("BUSINESS_UUID is invalid; skipping enforced business filter for comparisons.")
                business_filter = {}
        else:
            business_filter = {}

        # Handle portfolio comparison for single lead
        if compare_with_portfolio and len(lead_ids) == 1:
            # Return all leads in business (excluding the target lead) for portfolio comparison
            target_lead_id = lead_ids[0]
            query = business_filter.copy() if business_filter else {}

            # Exclude target lead
            exclude_clauses = []
            if obj_id := _try_parse_object_id(target_lead_id):
                exclude_clauses.append({"_id": {"$ne": obj_id}})
            if uuid_bin := _try_parse_uuid_binary(target_lead_id):
                exclude_clauses.append({"_id": {"$ne": uuid_bin}})
            if base64_bin := _try_parse_base64_binary(target_lead_id):
                exclude_clauses.append({"_id": {"$ne": base64_bin}})
            exclude_clauses.append({"_id": {"$ne": target_lead_id}})

            if exclude_clauses:
                query["$and"] = exclude_clauses

            leads_cursor = lead_coll.find(query).limit(10)  # Limit for portfolio comparison
            leads_data = []

            async for lead_doc in leads_cursor:
                lead_ref_id = lead_doc.get("_id")
                parent_core_filter = {"$or": [{"parentId": lead_ref_id}, {"leadId": lead_ref_id}]}
                parent_filter = _merge_filters(parent_core_filter, business_filter)

                personal_info = lead_doc.get("personalInfo", {})
                task_count = await task_coll.count_documents(parent_filter)
                meeting_count = await meeting_coll.count_documents(parent_filter)
                activity_count = await activity_coll.count_documents(parent_filter)

                open_task_filter = {"$and": [parent_core_filter, {"taskStatus": {"$nin": ["COMPLETED", "CANCELLED"]}}]}
                open_task_filter = _merge_filters(open_task_filter, business_filter)
                open_tasks = await task_coll.count_documents(open_task_filter)

                leads_data.append({
                    "id": str(lead_ref_id),
                    "name": personal_info.get("name", "N/A"),
                    "company": personal_info.get("company", lead_doc.get("company", "N/A")),
                    "status": lead_doc.get("leadStatus", "N/A"),
                    "source": lead_doc.get("source", "N/A"),
                    "score": lead_doc.get("leadScore", 0),
                    "created": str(lead_doc.get("createdTimeStamp", "N/A"))[:10],
                    "task_count": task_count,
                    "open_tasks": open_tasks,
                    "meeting_count": meeting_count,
                    "activity_count": activity_count,
                    "industry": lead_doc.get("company", {}).get("industryName", "N/A"),
                    "email": personal_info.get("email", "N/A"),
                    "mobile": personal_info.get("mobile", "N/A"),
                })

            return leads_data

        # Handle direct lead comparison
        leads_data = []

        for lead_id in lead_ids[:5]:  # Limit to 5 leads for direct comparison
            lead_query_clauses: List[Dict[str, Any]] = []
            if obj_id := _try_parse_object_id(lead_id):
                lead_query_clauses.append({"_id": obj_id})
            if uuid_bin := _try_parse_uuid_binary(lead_id):
                lead_query_clauses.append({"_id": uuid_bin})
            if base64_bin := _try_parse_base64_binary(lead_id):
                lead_query_clauses.append({"_id": base64_bin})
            lead_query_clauses.append({"_id": lead_id})

            lead_query = {"$or": lead_query_clauses}
            lead_query = _merge_filters(lead_query, business_filter)

            lead_doc = await lead_coll.find_one(lead_query)
            if not lead_doc:
                continue

            lead_ref_id = lead_doc.get("_id")
            parent_core_filter = {"$or": [{"parentId": lead_ref_id}, {"leadId": lead_ref_id}]}
            parent_filter = _merge_filters(parent_core_filter, business_filter)

            personal_info = lead_doc.get("personalInfo", {})
            task_count = await task_coll.count_documents(parent_filter)
            meeting_count = await meeting_coll.count_documents(parent_filter)
            activity_count = await activity_coll.count_documents(parent_filter)

            open_task_filter = {"$and": [parent_core_filter, {"taskStatus": {"$nin": ["COMPLETED", "CANCELLED"]}}]}
            open_task_filter = _merge_filters(open_task_filter, business_filter)
            open_tasks = await task_coll.count_documents(open_task_filter)

            leads_data.append({
                "id": str(lead_ref_id),
                "name": personal_info.get("name", "N/A"),
                "company": personal_info.get("company", lead_doc.get("company", "N/A")),
                "status": lead_doc.get("leadStatus", "N/A"),
                "source": lead_doc.get("source", "N/A"),
                "score": lead_doc.get("leadScore", 0),
                "created": str(lead_doc.get("createdTimeStamp", "N/A"))[:10],
                "task_count": task_count,
                "open_tasks": open_tasks,
                "meeting_count": meeting_count,
                "activity_count": activity_count,
            })

        if not leads_data:
            return "No valid leads found for comparison."

        # Build comparison output
        result = "## Lead Comparison\n\n"
        result += "| Metric | " + " | ".join([l["name"][:15] for l in leads_data]) + " |\n"
        result += "|--------|" + "|".join(["--------" for _ in leads_data]) + "|\n"

        metrics = [
            ("Company", "company"),
            ("Status", "status"),
            ("Source", "source"),
            ("Lead Score", "score"),
            ("Created", "created"),
            ("Total Tasks", "task_count"),
            ("Open Tasks", "open_tasks"),
            ("Meetings", "meeting_count"),
            ("Activities", "activity_count"),
        ]

        for metric_name, metric_key in metrics:
            result += f"| {metric_name} | " + " | ".join([str(l.get(metric_key, 'N/A')) for l in leads_data]) + " |\n"

        # Analysis section
        result += "\n## Analysis\n\n"

        max_activity = max(leads_data, key=lambda x: x["activity_count"])
        result += f"- **Highest Engagement**: {max_activity['name']} ({max_activity['activity_count']} activities)\n"

        max_score = max(leads_data, key=lambda x: x.get("score", 0) or 0)
        if max_score.get("score"):
            result += f"- **Highest Lead Score**: {max_score['name']} (Score: {max_score['score']})\n"

        max_meetings = max(leads_data, key=lambda x: x["meeting_count"])
        result += f"- **Most Meetings**: {max_meetings['name']} ({max_meetings['meeting_count']} meetings)\n"

        max_open = max(leads_data, key=lambda x: x["open_tasks"])
        if max_open["open_tasks"] > 0:
            result += f"- **Most Pending Tasks**: {max_open['name']} ({max_open['open_tasks']} open tasks)\n"

        return result

    except Exception as e:
        logger.error(f"Error in compare_leads: {e}")
        return f"Error comparing leads: {str(e)}"


# ============================================================================
# Tool 3: Search Lead Content (RAG-based)
# ============================================================================

@tool
async def search_lead_content(
    query: str,
    lead_id: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 5
) -> str:
    """
    Search for relevant content related to a lead using semantic search.

    Args:
        query (str): Search query (what to look for)
        lead_id (str, optional): Filter to specific lead ID
        content_type (str, optional): Content type filter - 'notes', 'task', 'meeting', 'activity', 'callLog', 'mailInfo'
        limit (int): Maximum number of results to return (must be integer between 1-20)

    Returns:
        str: Relevant content chunks with context and relevance scores
    """
    try:
        from qdrant.initializer import RAGTool

        # Ensure limit is an integer
        if isinstance(limit, str):
            try:
                limit = int(limit)
            except ValueError:
                limit = 5

        # Validate limit range
        limit = max(1, min(20, limit))

        rag_tool = RAGTool.get_instance()
        results = await rag_tool.search_content(
            query=query,
            content_type=content_type,
            limit=limit
        )
        
        if not results:
            return "No relevant content found."
        
        # Filter by lead_id if provided
        if lead_id:
            results = [r for r in results if str(r.get("mongo_id", "")).find(lead_id) != -1 or 
                       str(r.get("lead_id", "")) == lead_id]
        
        output = f"## Search Results for: '{query}'\n\n"
        
        for i, result in enumerate(results, 1):
            output += f"### {i}. {result.get('title', 'Untitled')} ({result.get('content_type', 'unknown')})\n"
            output += f"**Relevance Score**: {result.get('score', 0):.3f}\n\n"
            content = result.get('content', '')
            output += f"{content[:500]}{'...' if len(content) > 500 else ''}\n\n"
            output += "---\n\n"
        
        return output
        
    except Exception as e:
        logger.error(f"Error in search_lead_content: {e}")
        return f"Error searching content: {str(e)}"


# ============================================================================
# Tool 4: Get Lead Stats
# ============================================================================

@tool
async def get_lead_stats(lead_id: str) -> str:
    """
    Get AI-analyzed statistical summary and engagement insights for a lead.

    Uses LLM to analyze raw metrics and provide data-driven insights about lead engagement,
    performance patterns, and strategic recommendations.

    Args:
        lead_id: The unique identifier of the lead

    Returns:
        AI-analyzed statistical summary with insights and recommendations
    """
    from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary
    from bson import ObjectId
    from datetime import datetime, timedelta
    from langchain_groq import ChatGroq
    from langchain_core.messages import SystemMessage, HumanMessage
    from lead_support_agent.prompts import get_prompt_for_task
    import os

    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()

        db = mongodb_tools.client[DATABASE_NAME]

        # Parse lead_id
        lead_query = {"$or": []}
        try:
            lead_query["$or"].append({"_id": ObjectId(lead_id)})
        except Exception:
            pass
        try:
            lead_query["$or"].append({"_id": uuid_str_to_mongo_binary(lead_id)})
        except Exception:
            pass

        lead_doc = await db["Lead"].find_one(lead_query)
        if not lead_doc:
            return f"Lead not found: {lead_id}"

        lead_ref_id = lead_doc.get("_id")
        parent_filter = {"$or": [{"parentId": lead_ref_id}, {"leadId": lead_ref_id}]}

        # Gather raw statistics
        task_coll = db["task"]
        meeting_coll = db["meeting"]
        activity_coll = db["activity"]
        call_coll = db["callLog"]
        mail_coll = db["mailInfo"]
        notes_coll = db["notes"]

        # Task stats
        total_tasks = await task_coll.count_documents(parent_filter)
        completed_tasks = await task_coll.count_documents({**parent_filter, "taskStatus": "COMPLETED"})
        overdue_tasks = await task_coll.count_documents({
            **parent_filter,
            "taskStatus": {"$nin": ["COMPLETED", "CANCELLED"]},
            "dueDate": {"$lt": datetime.utcnow().isoformat()}
        })

        # Meeting stats
        total_meetings = await meeting_coll.count_documents(parent_filter)
        completed_meetings = await meeting_coll.count_documents({**parent_filter, "meetingStatus": "COMPLETED"})

        # Communication stats
        total_calls = await call_coll.count_documents(parent_filter)
        total_emails = await mail_coll.count_documents(parent_filter)
        total_notes = await notes_coll.count_documents(parent_filter)
        total_activities = await activity_coll.count_documents(parent_filter)

        # Recent activity (last 30 days)
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        recent_activities = await activity_coll.count_documents({
            **parent_filter,
            "createdTimeStamp": {"$gte": thirty_days_ago}
        })

        # Additional metrics for better analysis
        # Task completion rate
        task_completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        # Meeting completion rate
        meeting_completion_rate = (completed_meetings / total_meetings * 100) if total_meetings > 0 else 0

        # Activity trends (last 7 days vs 30 days)
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        recent_7day_activities = await activity_coll.count_documents({
            **parent_filter,
            "createdTimeStamp": {"$gte": seven_days_ago}
        })

        # Lead profile info
        personal_info = lead_doc.get("personalInfo", {})
        lead_name = personal_info.get('name', 'Unknown')

        # Prepare raw data for LLM analysis
        raw_data = f"""
LEAD PROFILE:
- Name: {lead_name}
- Lead Score: {lead_doc.get('leadScore', 'N/A')}
- Status: {lead_doc.get('leadStatus', 'N/A')}
- Pipeline Stage: {lead_doc.get('pipelineStage', {}).get('stageName', 'N/A') if isinstance(lead_doc.get('pipelineStage'), dict) else 'N/A'}

RAW METRICS:
- Total Tasks: {total_tasks}
- Completed Tasks: {completed_tasks}
- Overdue Tasks: {overdue_tasks}
- Task Completion Rate: {task_completion_rate:.1f}%

- Total Meetings: {total_meetings}
- Completed Meetings: {completed_meetings}
- Meeting Completion Rate: {meeting_completion_rate:.1f}%

- Total Activities (all-time): {total_activities}
- Recent Activities (30 days): {recent_activities}
- Recent Activities (7 days): {recent_7day_activities}

- Communication Channels:
  * Calls: {total_calls}
  * Emails: {total_emails}
  * Notes: {total_notes}

TIME CONTEXT:
- Analysis Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
- 30-day period: Activities from {thirty_days_ago[:10]} to present
- 7-day period: Activities from {seven_days_ago[:10]} to present
"""

        # Use LLM to analyze the statistics
        llm = ChatGroq(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.2,  # Lower temperature for more consistent analysis
            max_tokens=2048
        )

        system_prompt = get_prompt_for_task("statistics")
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Analyze the following lead statistics data and provide comprehensive insights:\n\n{raw_data}")
        ]

        response = await llm.ainvoke(messages)
        return response.content

    except Exception as e:
        logger.error(f"Error in get_lead_stats: {e}")
        return f"Error getting lead stats: {str(e)}"


# ============================================================================
# Tool 5: Generate Lead Content
# ============================================================================

@tool
async def generate_lead_content(
    content_type: str,
    lead_id: str,
    prompt: str,
    context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate content for a lead (message, email, follow-up, etc).
    
    Args:
        content_type: Type of content - 'email', 'message', 'follow_up', 'meeting_agenda', 'call_script'
        lead_id: The lead ID this content is for
        prompt: Specific instructions for the content
        context: Additional context to use
    
    Returns:
        Generated content ready to use/edit
    """
    # Note: The actual generation will be done by the LLM using the gathered context
    # This tool structures the request and provides lead context for generation
    
    result = f"""
## Content Generation Request

**Type**: {content_type}
**Lead ID**: {lead_id}
**Instructions**: {prompt}

Please generate the requested {content_type} content based on the lead context gathered.
"""
    
    if context:
        result += f"\n**Additional Context**: {json.dumps(context, indent=2)}"
    
    return result


# ============================================================================
# Export tool list
# ============================================================================

tools = [
    get_lead_context,
    compare_leads,
    search_lead_content,
    get_lead_stats,
    generate_lead_content,
]
