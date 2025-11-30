"""
Lead Support Agent Tools - Focused tools for lead-related support functionality.

These tools provide:
- Lead context gathering (details, history, related data)
- Lead comparison utilities
- Content generation for messages and emails
"""

import logging
from typing import Optional, Dict, List, Any
from langchain_core.tools import tool
from datetime import datetime
import json

logger = logging.getLogger(__name__)


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
        lead_id: The unique identifier of the lead (MongoDB ObjectId or UUID)
        include_tasks: Include related tasks
        include_meetings: Include related meetings
        include_notes: Include related notes
        include_activities: Include activity history
        include_calls: Include call logs
        include_emails: Include email history
    
    Returns:
        Formatted string containing complete lead context
    """
    from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary, BUSINESS_UUID
    from bson import ObjectId
    
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()
        
        db = mongodb_tools.client[DATABASE_NAME]
        result_parts = []
        
        # Get business filter
        business_uuid = BUSINESS_UUID()
        business_filter = {}
        if business_uuid:
            try:
                business_filter["businessId"] = uuid_str_to_mongo_binary(business_uuid)
            except Exception:
                pass
        
        # Parse lead_id (could be ObjectId or UUID string)
        lead_query = {"$or": []}
        try:
            lead_query["$or"].append({"_id": ObjectId(lead_id)})
        except Exception:
            pass
        try:
            lead_query["$or"].append({"_id": uuid_str_to_mongo_binary(lead_id)})
        except Exception:
            pass
        
        if not lead_query["$or"]:
            return f"Invalid lead_id format: {lead_id}"
        
        # Add business filter to lead query
        if business_filter:
            lead_query = {"$and": [lead_query, business_filter]}
        
        # 1. Get Lead Details
        lead_coll = db["Lead"]
        lead_doc = await lead_coll.find_one(lead_query)
        
        if not lead_doc:
            return f"Lead not found with ID: {lead_id}"
        
        # Format lead information
        personal_info = lead_doc.get("personalInfo", {})
        lead_info = f"""
## Lead Profile
- **Name**: {personal_info.get('name', 'N/A')}
- **Email**: {personal_info.get('email', 'N/A')}
- **Mobile**: {personal_info.get('mobile', 'N/A')}
- **Company**: {personal_info.get('company', lead_doc.get('company', 'N/A'))}
- **Status**: {lead_doc.get('leadStatus', 'N/A')}
- **Source**: {lead_doc.get('source', 'N/A')}
- **Type**: {lead_doc.get('type', 'N/A')}
- **Lead Score**: {lead_doc.get('leadScore', 'N/A')}
- **Created**: {lead_doc.get('createdTimeStamp', 'N/A')}
- **Last Updated**: {lead_doc.get('updatedTimeStamp', 'N/A')}
"""
        
        # Add custom fields if present
        custom_fields = lead_doc.get("customFields", {})
        if custom_fields:
            lead_info += "\n### Custom Fields\n"
            for key, value in custom_fields.items():
                lead_info += f"- **{key}**: {value}\n"
        
        result_parts.append(lead_info)
        
        # Get lead reference for related queries
        lead_ref_id = lead_doc.get("_id")
        
        # Create parent ID filter for related items
        parent_filter = {"$or": [{"parentId": lead_ref_id}, {"leadId": lead_ref_id}]}
        if business_filter:
            parent_filter = {"$and": [parent_filter, business_filter]}
        
        # 2. Get Related Tasks
        if include_tasks:
            try:
                task_coll = db["task"]
                tasks = await task_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(10).to_list(length=10)
                if tasks:
                    task_info = "\n## Related Tasks\n"
                    for t in tasks:
                        task_info += f"- [{t.get('taskStatus', 'N/A')}] **{t.get('name', 'Untitled')}** - Priority: {t.get('priority', 'N/A')}, Due: {t.get('dueDate', 'N/A')}\n"
                        if t.get('description'):
                            task_info += f"  {t.get('description', '')[:100]}...\n"
                    result_parts.append(task_info)
            except Exception as e:
                logger.warning(f"Error fetching tasks: {e}")
        
        # 3. Get Related Meetings
        if include_meetings:
            try:
                meeting_coll = db["meeting"]
                meetings = await meeting_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(10).to_list(length=10)
                if meetings:
                    meeting_info = "\n## Related Meetings\n"
                    for m in meetings:
                        meeting_info += f"- [{m.get('meetingStatus', 'N/A')}] **{m.get('title', 'Untitled')}**\n"
                        meeting_info += f"  Start: {m.get('startTime', 'N/A')}, Type: {m.get('meetingType', 'N/A')}\n"
                        if m.get('description'):
                            meeting_info += f"  {m.get('description', '')[:100]}...\n"
                    result_parts.append(meeting_info)
            except Exception as e:
                logger.warning(f"Error fetching meetings: {e}")
        
        # 4. Get Related Notes
        if include_notes:
            try:
                notes_coll = db["notes"]
                notes = await notes_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(10).to_list(length=10)
                if notes:
                    notes_info = "\n## Notes\n"
                    for n in notes:
                        notes_info += f"- **{n.get('subject', 'Note')}** ({n.get('createdTimeStamp', 'N/A')})\n"
                        if n.get('description'):
                            notes_info += f"  {n.get('description', '')[:150]}...\n"
                    result_parts.append(notes_info)
            except Exception as e:
                logger.warning(f"Error fetching notes: {e}")
        
        # 5. Get Activity History
        if include_activities:
            try:
                activity_coll = db["activity"]
                activities = await activity_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(10).to_list(length=10)
                if activities:
                    activity_info = "\n## Activity History\n"
                    for a in activities:
                        activity_info += f"- [{a.get('type', 'N/A')}] {a.get('description', 'Activity')} - {a.get('createdTimeStamp', 'N/A')}\n"
                    result_parts.append(activity_info)
            except Exception as e:
                logger.warning(f"Error fetching activities: {e}")
        
        # 6. Get Call Logs
        if include_calls:
            try:
                call_coll = db["callLog"]
                calls = await call_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(5).to_list(length=5)
                if calls:
                    call_info = "\n## Call History\n"
                    for c in calls:
                        call_info += f"- **{c.get('callPurpose', 'Call')}** - {c.get('callStatus', 'N/A')}, Duration: {c.get('duration', 'N/A')}\n"
                        if c.get('callNotes'):
                            call_info += f"  Notes: {c.get('callNotes', '')[:100]}...\n"
                    result_parts.append(call_info)
            except Exception as e:
                logger.warning(f"Error fetching calls: {e}")
        
        # 7. Get Email History
        if include_emails:
            try:
                mail_coll = db["mailInfo"]
                emails = await mail_coll.find(parent_filter).sort("createdTimeStamp", -1).limit(5).to_list(length=5)
                if emails:
                    email_info = "\n## Email History\n"
                    for e in emails:
                        email_info += f"- **{e.get('subject', 'Email')}** - {e.get('status', 'N/A')}, {e.get('createdTimeStamp', 'N/A')}\n"
                    result_parts.append(email_info)
            except Exception as e:
                logger.warning(f"Error fetching emails: {e}")
        
        return "\n".join(result_parts) if result_parts else "No data found for lead."
        
    except Exception as e:
        logger.error(f"Error in get_lead_context: {e}")
        return f"Error gathering lead context: {str(e)}"


# ============================================================================
# Tool 2: Compare Leads
# ============================================================================

@tool
async def compare_leads(lead_ids: List[str]) -> str:
    """
    Compare multiple leads side-by-side across key dimensions.
    
    Args:
        lead_ids: List of lead IDs to compare (2-5 leads recommended)
    
    Returns:
        Formatted comparison table and analysis
    """
    from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary, BUSINESS_UUID
    from bson import ObjectId
    
    try:
        if not mongodb_tools.client:
            await mongodb_tools.connect()
        
        db = mongodb_tools.client[DATABASE_NAME]
        lead_coll = db["Lead"]
        task_coll = db["task"]
        meeting_coll = db["meeting"]
        activity_coll = db["activity"]
        
        business_uuid = BUSINESS_UUID()
        
        leads_data = []
        
        for lead_id in lead_ids[:5]:  # Limit to 5 leads
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
            
            if not lead_query["$or"]:
                continue
            
            lead_doc = await lead_coll.find_one(lead_query)
            if not lead_doc:
                continue
            
            lead_ref_id = lead_doc.get("_id")
            parent_filter = {"$or": [{"parentId": lead_ref_id}, {"leadId": lead_ref_id}]}
            
            # Gather metrics
            personal_info = lead_doc.get("personalInfo", {})
            task_count = await task_coll.count_documents(parent_filter)
            meeting_count = await meeting_coll.count_documents(parent_filter)
            activity_count = await activity_coll.count_documents(parent_filter)
            
            # Get open tasks count
            open_tasks = await task_coll.count_documents({
                **parent_filter,
                "taskStatus": {"$nin": ["COMPLETED", "CANCELLED"]}
            })
            
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
        
        # Summary table
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
            result += f"| {metric_name} | " + " | ".join([str(l.get(metric_key, "N/A")) for l in leads_data]) + " |\n"
        
        # Analysis section
        result += "\n## Analysis\n\n"
        
        # Find highest engagement
        max_activity = max(leads_data, key=lambda x: x["activity_count"])
        result += f"- **Highest Engagement**: {max_activity['name']} ({max_activity['activity_count']} activities)\n"
        
        # Find highest score
        max_score = max(leads_data, key=lambda x: x.get("score", 0) or 0)
        if max_score.get("score"):
            result += f"- **Highest Lead Score**: {max_score['name']} (Score: {max_score['score']})\n"
        
        # Find most meetings
        max_meetings = max(leads_data, key=lambda x: x["meeting_count"])
        result += f"- **Most Meetings**: {max_meetings['name']} ({max_meetings['meeting_count']} meetings)\n"
        
        # Find pending work
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
        query: Search query (what to look for)
        lead_id: Optional - filter to specific lead
        content_type: Optional - 'notes', 'task', 'meeting', 'activity', 'callLog', 'mailInfo'
        limit: Maximum number of results
    
    Returns:
        Relevant content chunks with context
    """
    try:
        from qdrant.initializer import RAGTool
        
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
    Get statistical summary and engagement metrics for a lead.
    
    Args:
        lead_id: The unique identifier of the lead
    
    Returns:
        Statistical summary of lead engagement and activity
    """
    from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary
    from bson import ObjectId
    from datetime import datetime, timedelta
    
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
        
        # Gather statistics
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
        
        personal_info = lead_doc.get("personalInfo", {})
        
        result = f"""
## Lead Statistics: {personal_info.get('name', 'Unknown')}

### Overall Engagement Score
- **Lead Score**: {lead_doc.get('leadScore', 'N/A')}
- **Total Activities (30 days)**: {recent_activities}
- **Total All-time Activities**: {total_activities}

### Task Metrics
| Metric | Count |
|--------|-------|
| Total Tasks | {total_tasks} |
| Completed | {completed_tasks} |
| Overdue | {overdue_tasks} |
| Completion Rate | {(completed_tasks/total_tasks*100) if total_tasks > 0 else 0:.1f}% |

### Meeting Metrics
| Metric | Count |
|--------|-------|
| Total Meetings | {total_meetings} |
| Completed | {completed_meetings} |
| Meeting Rate | {(completed_meetings/total_meetings*100) if total_meetings > 0 else 0:.1f}% |

### Communication Metrics
| Channel | Count |
|---------|-------|
| Calls | {total_calls} |
| Emails | {total_emails} |
| Notes | {total_notes} |

### Engagement Trend
- Recent activity level: {"High" if recent_activities > 10 else "Medium" if recent_activities > 3 else "Low"}
- Last 30 days: {recent_activities} activities
"""
        
        return result
        
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
