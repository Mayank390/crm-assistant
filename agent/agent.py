from langchain_groq import ChatGroq
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage, SystemMessage
from langchain_core.callbacks import AsyncCallbackHandler
import asyncio
import contextlib
from typing import Dict, Any, List, AsyncGenerator, Optional
from agent.memory import conversation_memory
from typing import Optional,Tuple
from agent import tools as agent_tools
from datetime import datetime
import time
from time import perf_counter
from collections import defaultdict, deque
import os
import re
import json

# Import tools list
try:
    tools_list = agent_tools.tools
except AttributeError:
    tools_list = []

import os
from langchain_groq import ChatGroq
from mongo.constants import DATABASE_NAME, mongodb_tools
from mongo.conversations import save_assistant_message, save_action_event
from agent.callback_handler import AgentCallbackHandler
from agent.tools import get_generation_websocket
# from tracking.credit_check import check_credit_balance_for_agent
# from tracking.token_usage import record_usage
# from tracking.token_accumulator import ensure_accumulator


# from guardrails.llama_gaurd_client import llama_guard_client, get_blocked_response

# async def _run_parallel_safety_checks(
#     query: str, 
#     conversation_history: List[dict]
# ) -> tuple[bool, bool, str, str]:
#     """
#     Run Llama Guard safety check for prompt injection detection.
#     
#     Uses Llama Guard via Groq to detect attempts to:
#     - Extract system prompts or instructions
#     - Reveal internal implementation details
#     - Get raw/unprocessed responses
#     - Bypass safety guidelines (jailbreaks)
#     
#     Args:
#         query: The user input to check
#         conversation_history: Previous conversation for context
#             tuple: (toxic_check_passed, prompt_injection_safe, blocked_reason, violation_category)
#         Note: toxic_check_passed is always True (disabled), kept for API compatibility
#     """
#     # COMMENTED OUT: Toxic language check - using Llama Guard only
#     # toxic_task = asyncio.create_task(_validate_guard_async(query))
#     
#     # Run Llama Guard prompt injection check
#     try:
#         prompt_injection_result = await llama_guard_client.check_prompt_injection(
#             user_message=query,
#             conversation_history=conversation_history
#         )
#         
#         prompt_injection_safe = prompt_injection_result.is_safe
#         blocked_reason = ""
#         violation_category = ""
#         
#         if not prompt_injection_safe:
#             blocked_reason = prompt_injection_result.blocked_reason or get_blocked_response()
#             violation_category = prompt_injection_result.category or "UNKNOWN"
#             
#     except Exception as e:
#         logger.error(f"Prompt injection check failed: {e}")
#         # Fail open on error
#         prompt_injection_safe = True
#         blocked_reason = ""
#         violation_category = ""
#     
#     # Return format: (toxic_passed, prompt_injection_safe, blocked_reason, violation_category)
#     # toxic_passed is always True since we disabled that check
#     return True, prompt_injection_safe, blocked_reason, violation_category
def preprocess_lead_enrichment_query(query: str) -> Tuple[bool, Optional[str]]:
        """
        Detect if query is a lead enrichment request and extract context.
        
        Returns:
            (is_lead_enrichment_query, clarified_query)
        """
        query_lower = query.lower()
        
        # Strong indicators that this is a lead enrichment request
        lead_enrichment_patterns = [
            r'\b(find|get|search|extract|show|list|give)\s+(me\s+)?(\d+\s+)?(leads?|businesses?|companies?|shops?|stores?|restaurants?|salons?|gyms?|clinics?|hotels?)',
            r'\b(find|get|search)\s+.*\b(in|at|near)\s+\w+',  # "find X in Y"
            r'\b(business|company|shop|store)\s+(leads?|list|directory)',
        ]
        
        for pattern in lead_enrichment_patterns:
            if re.search(pattern, query_lower):
                logger.info(f"[preprocess] Detected lead enrichment query: '{query}'")
                
                # Add clarification to help LLM choose the right tool
                clarified = f"{query}\n\nIMPORTANT: Use lead_enrichment_tool to search for REAL businesses using Google Maps."
                return True, clarified
        
        return False, None

    
    
def validate_and_correct_tool_usage(tool_calls: List[Dict], original_query: str) -> Tuple[List[Dict], bool]:
        """
        Validate tool usage and auto-correct common mistakes.
        
        Returns:
            (corrected_tool_calls, was_corrected)
        """
        query_lower = original_query.lower()
        corrected_calls = []
        was_corrected = False
        
        # Detect if query is about finding/searching businesses
        is_business_search = (
            any(kw in query_lower for kw in ['find', 'get', 'search', 'extract', 'show', 'list']) and
            any(entity in query_lower for entity in ['lead', 'business', 'company', 'shop', 'store', 'restaurant', 'salon', 'gym', 'clinic'])
        )
        
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")
            
            # CORRECTION 1: Wrong tool for business search
            if is_business_search and tool_name == "generate_content":
                logger.warning(f"[validate_tool_usage] Wrong tool detected: generate_content for business search")
                logger.info(f"[validate_tool_usage] Auto-correcting to lead_enrichment_tool")
                
                # Extract parameters from generate_content call
                args = tool_call.get("args", {})
                prompt = args.get("prompt", "")
                
                # Parse business type and location from prompt
                # Example: "Generate 3 leads in Kondapur area - include local businesses"
                import re
                
                # Try to extract city (common Indian cities)
                cities = ['hyderabad', 'mumbai', 'delhi', 'bangalore', 'chennai', 'kolkata', 'pune', 'ahmedabad']
                city = 'Hyderabad'  # Default
                for c in cities:
                    if c in query_lower or c in prompt.lower():
                        city = c.title()
                        break
                
                # Try to extract area
                area_match = re.search(r'in\s+(\w+)', query_lower)
                area = area_match.group(1).title() if area_match else ''
                
                # Try to extract count
                count_match = re.search(r'(\d+)\s+leads?', query_lower)
                max_leads = int(count_match.group(1)) if count_match else 50
                
                # Try to extract business type
                business_type = 'businesses'  # Default
                for entity in ['restaurant', 'salon', 'shop', 'store', 'gym', 'clinic', 'hotel']:
                    if entity in query_lower:
                        business_type = entity + 's'
                        break
                
                # Create corrected tool call
                corrected_call = {
                    "name": "lead_enrichment_tool",
                    "args": {
                        "business_type": business_type,
                        "city": city,
                        "area": area,
                        "max_leads": max_leads,
                        "user_query": original_query
                    },
                    "id": tool_call.get("id", "")
                }
                
                corrected_calls.append(corrected_call)
                was_corrected = True
                
                logger.info(f"[validate_tool_usage] Corrected call: {corrected_call}")
                
            else:
                # Keep original call
                corrected_calls.append(tool_call)
        
        return corrected_calls, was_corrected

DEFAULT_SYSTEM_PROMPT = (
    "You are a precise, non-speculative CRM assistant.\n\n"
    "GENERAL RULES:\n"
    "- Never guess facts about the database or content. Prefer invoking a tool.\n"
    "- If a tool is appropriate, always call it before answering.\n"
    "- Keep answers concise and structured. If lists are long, summarize and offer to expand.\n"
    "- If tooling is unavailable for the task, state the limitation plainly.\n\n"
    "LEAD ENRICHMENT: Never copy tool output verbatim. Rephrase naturally using: lead count, top business names, and download link (when present).\n"
    "Example: 'Found 35 jewellers in Gachibowli including Malabar Gold, Tanishq. Download full list: [link] Ready to import?'\n"
    "Always highlight CSV download links and encourage immediate CRM import action.\n"
    "- When returning 50+ leads, emphasize the comprehensiveness: e.g., \"Comprehensive list of 87 jewellers across Gachibowli, Hyderabad\" and strongly encourage CRM import.\n\n"
    "CRM DATA MODEL — PIPELINE (AUTHORITATIVE):\n"
    "- Pipeline is a FIRST-CLASS CRM entity.\n"
    "- Pipelines are stored in the `pipeline` collection.\n"
    "- Leads reference pipelines via `Lead.pipeline._id` and `Lead.pipeline.name`.\n"
    "- Each pipeline has multiple stages stored in `Lead.pipelineStage.stageName`.\n"
    "- A pipeline can contain Leads, Prospects, and Customers (via `Lead.type`).\n\n"

    "PIPELINE QUERY RULES (STRICT):\n"
    "- Never assume a single pipeline exists.\n"
    "- Never infer pipeline names or stages.\n"
    "- Always deduplicate pipelines by `_id`.\n"
    "- Use the `pipeline` collection for listing pipelines and metadata.\n"
    "- Use the `Lead` collection for pipeline breakdowns and stage analytics.\n\n"
    "PIPELINE HARD RULES:\n"
    "- NEVER query pipelines without business scoping\n"
    "- Deduplication key = (business._id, pipeline._id)\n"
    "- Metadata queries → show_all=true\n"
    "- Analytics queries → show_all=false\n"
    "- Pipeline details of <name> MUST run sequential queries\n\n"


    "PIPELINE QUERY EXAMPLES (MANDATORY BEHAVIOR):\n"
    "- 'show all pipelines' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id returning name,show_all=true\")\n"
    "- 'list all pipelines' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id returning name,show_all=true\")\n"
    "- 'pipeline breakdown' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id returning name,show_all=true\")\n"
    "- 'pipeline details' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id with name, description, createdByName, isDefault, createdAt, updatedAt,show_all=true\")\n"
    "- 'show pipeline details' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id with name, description, createdByName, isDefault, createdAt, updatedAt,show_all=true\")\n"
    "- 'give pipeline details' → mongo_query(\"list all pipelines for this business deduplicated by business._id and _id with name, description, createdByName, isDefault, createdAt, updatedAt,show_all=true\")\n"
    "- 'pipeline details of <pipeline_name>' →\n"
    "   1) mongo_query(\"get pipeline metadata from pipeline collection where business._id is current business and name is <pipeline_name>,show_all=true\")\n"
    "   2) mongo_query(\"list all leads where pipeline.name is <pipeline_name>,show_all=false\")\n\n"

    "CRM DATA MODEL(AUTHORITATIVE):\n"
    "The CRM contains the following core entities:\n"
    "- Lead\n"
    "- Each Lead belongs to exactly ONE Pipeline\n"
    "- Stored in: Lead.pipeline\n"
    "- Fields:\n"
    "pipeline._id\n"
    "pipeline.name\n"
    "pipelineStage.stageName\n"
    "pipelineStage.statusName\n"

    "- Pipeline\n"
    "- Represents a sales workflow (e.g., Default Pipeline, Enterprise Sales)\n"
    "- Each Pipeline has multiple stages\n"
    "- Leads reference pipelines via Lead.pipeline._id\n"

    "PIPELINE TOOLING RULE (IMPORTANT):\n"
    "- Any query that LISTS pipelines or FETCHES pipeline metadata MUST call mongo_query with show_all=true.\n"

    "IMPORTANT PIPELINE RULES:\n"
    "- Pipeline data is ALWAYS accessed via Lead → pipeline or via pipeline lookup\n"
    "- Valid grouping keys include:\n"
    "pipeline.name\n"
    "pipelineStage.stageName\n"
    "pipelineStage.statusName\n"
    "- Questions mentioning:\n"
    "pipeline\n"
    "stage\n"
    "funnel\n"
    "sales flow\n"
    "MUST consider pipeline context\n\n"    
    "CRITICAL IMPORT RULES:\n"
    "- NEVER use generate_content to import leads into CRM.\n"
    "- Imports MUST use import_leads_tool followed by UI-based bulk import.\n"
    "- When user says 'import leads', 'save to CRM', 'add these to CRM' → call import_leads_tool.\n"
    "- After import_leads_tool returns '__LEADS_READY_FOR_IMPORT__', STOP immediately.\n"
    "- Do NOT continue generating or calling other tools after leads ready for import.\n\n"
    "RESPONSE FORMATTING (CRITICAL):\n"
    "- ALWAYS format your responses using **markdown** for maximum readability.\n"
    "- Use headings (##, ###) to organize sections and break up content.\n"
    "- Use **bold** for emphasis on key terms, numbers, and important concepts.\n"
    "- Use code blocks (```language) for queries, code, or technical output.\n"
    "- Use tables (| column |) when presenting structured data comparisons.\n"
    "- Use horizontal rules (---) to separate distinct sections when appropriate.\n"
    "- Use blockquotes (>) for important notes, warnings, or highlights.\n"
    "- Keep paragraphs short (2-3 sentences max) for better scanning.\n\n"
    "LIST FORMATTING (IMPORTANT):\n"
    "- Use **unordered lists (-, *)** for:\n"
    "  * Collections of items without hierarchy or priority\n"
    "  * Features, benefits, or characteristics\n"
    "  * Multiple unrelated items or options\n"
    "  * Key points or highlights that can be read in any order\n"
    "- Use **numbered lists (1., 2., 3.)** for:\n"
    "  * Sequential steps or procedures that must follow a specific order\n"
    "  * Ranked items (priorities, top results, ordered by importance)\n"
    "  * Instructions or tutorials with clear progression\n"
    "  * Chronological events or timelines\n"
    "- Use **nested lists** for hierarchical information or sub-items\n"
    "- Keep list items concise (one to two lines maximum)\n"
    "- Use **bold** for key terms within list items\n\n"
    "FORMATTING EXAMPLES:\n"
    "❌ BAD: 'There are 5 tasks and 3 meetings assigned to John.'\n"
    "✅ GOOD:\n"
    "## John's Assignments\n"
    "- **5 tasks** - High priority items requiring immediate attention\n"
    "- **3 meetings** - Scheduled appointments this week\n\n"
    "❌ BAD: 'The query returned Lead Alpha with 10 tasks, Lead Beta with 5 tasks.'\n"
    "✅ GOOD:\n"
    "## Lead Overview\n\n"
    "| Lead | Tasks | Status |\n"
    "| --- | --- | --- |\n"
    "| Alpha | 10 | Active |\n"
    "| Beta | 5 | Active |\n\n"
    "LIST USAGE EXAMPLES:\n"
    "✅ UNORDERED (for features/options):\n"
    "## Key Features\n"
    "- **Real-time sync** across all devices\n"
    "- **Advanced filtering** with custom rules\n"
    "- **Team collaboration** tools built-in\n\n"
    "✅ NUMBERED (for steps/priorities):\n"
    "## Setup Steps\n"
    "1. **Install dependencies** using npm install\n"
    "2. **Configure environment** variables in .env\n"
    "3. **Run the application** with npm start\n\n"
    "✅ NESTED (for hierarchical data):\n"
    "## Project Structure\n"
    "- **Backend**\n"
    "  - API endpoints in `/routes`\n"
    "  - Database models in `/models`\n"
    "- **Frontend**\n"
    "  - React components in `/src/components`\n"
    "  - Styles in `/src/styles`\n\n"
    "TOOL EXECUTION STRATEGY:\n"
    "- When tools are INDEPENDENT (can run without each other's results): Call them together in one batch.\n"
    "- When tools are DEPENDENT (one needs another's output): Call them separately in sequence.\n"
    "- Examples of INDEPENDENT: 'Show task counts AND meeting counts' → call both tools together\n"
    "- Examples of DEPENDENT: 'Find tasks by John, THEN search notes about those tasks' → call mongo_query first, wait for results, then call rag_search\n\n"
    "DECISION GUIDE:\n"
    "0) Lead extraction / enrichment requests (e.g., 'extract leads', 'find leads online', 'business leads in <city>') → prefer the `lead_enrichment` tool first.\n"
    "   - Default to max_leads=100 for comprehensive results unless the user specifies a smaller number or wants a quick sample.\n"
    "   - If user says \"top 10\", \"just a few\", or \"sample\", use a lower max_leads (e.g., 20–30).\n"
    "   - Always respect explicit user requests for count.\n"
    "   If it fails gracefully, explain the limitation and offer alternate approaches.\n"
    "   - Pass the FULL user query as user_query parameter for import intent detection\n\n"
    "1) Structured questions about EXISTING CRM entities/fields use 'mongo_query'\n"
    "   - Examples: counts, lists, filters, sort, group by, breakdowns by status/priority/assignee/date\n"
    "   - Collections: Lead, Task, Activity, Meeting, Notes, CallLog, MailInfo, LeadScoreRule, Segmentation, pipeline\n"
    "   - Do NOT answer from memory; run a query\n\n"
    
    "2) Content-based searches (semantic meaning) use 'rag_search'\n"
    "   - Find leads/tasks/meetings/notes by meaning, analyze content patterns, search CRM content\n"
    "   - Examples: 'find notes about follow-up', 'show meeting notes', 'content mentioning customer'\n\n"
    
    "3) CREATE new CRM entities (leads, tasks, meetings, notes) use 'generate_content'\n"
    "   - ONLY when user explicitly asks to CREATE or GENERATE a new entity\n"
    "   - Examples: 'create a new lead for TechCorp', 'generate a follow-up task', 'schedule a meeting'\n"
    "   - NOT for searching or finding existing businesses - that's lead_enrichment_tool!\n"
    "   - Content is sent DIRECTLY to frontend, tool returns only success/failure\n\n"
    
    "4) IMPORT leads to CRM  use 'import_leads_tool'\n"
    "   - ONLY when user asks to import AFTER leads have been generated\n"
    "   - Examples: 'import those leads', 'save to CRM', 'add them to my CRM'\n"
    "   - Requires leads to have been generated in the same session\n"
    "   - After calling, STOP immediately - do not continue generating\n\n"
    "5) Use 'mongo_query' for structured questions about entities/fields in collections: Lead, Task, Activity, Meeting, Notes, CallLog, MailInfo, LeadScoreRule, Segmentation, pipeline.\n"
    "   - Examples: counts, lists, filters, sort, group by, breakdowns by leadStatus/taskStatus/assignedName/priority/date.\n"
    "   - The query planner automatically determines when complex joins are beneficial and adds strategic relationships only when they improve query performance.\n"
    "   - PAGINATION: For large datasets, use natural language pagination in queries:\n"
    "     * 'page 2 of leads' → returns items 51-100\n"
    "     * 'skip 100 tasks' → skips first 100, returns next 50\n"
    "     * 'show results 21-40' → returns specific range\n"
    "     * 'group leads by status, page 2' → paginated grouped results\n"
    "     * Pagination works with all query types (list, count, grouped, aggregated)\n"
    "     * Default page size is 50. Use 'all' or 'every' for maximum results (up to 1000)\n"
    "   - Do NOT answer from memory; run a query.\n"
    "6) Use 'rag_search' for content-based searches (semantic meaning, not just keywords).\n"
    "   - Returns FULL chunk content (no truncation) for accurate synthesis and formatting.\n"
    "   - Find leads/tasks/meetings/notes by meaning, analyze content patterns, search CRM content.\n"
    "   - Examples: 'find notes about follow-up', 'show meeting notes', 'content mentioning customer', 'analyze patterns in descriptions'.\n"
    "   - INTELLIGENT CONTENT TYPE ROUTING: Choose content_type based on query context:\n"
    "     * Questions about 'leads', 'prospects', 'customers' → content_type='lead'\n"
    "     * Questions about 'tasks', 'todos', 'follow-ups' → content_type='task'\n"
    "     * Questions about 'meetings', 'calls', 'appointments' → content_type='meeting'\n"
    "     * Questions about 'notes', 'comments' → content_type='notes'\n"
    "     * Questions about 'call logs', 'call history' → content_type='callLog'\n"
    "     * Questions about 'emails', 'mail' → content_type='mailInfo'\n"
    "     * Questions about 'activities' → content_type='activity'\n"
    "     * Questions about 'segmentation', 'segments' → content_type='segmentation'\n"
    "     * Ambiguous queries → omit content_type (searches all types) OR call rag_search multiple times with different types\n"
    "7) Use 'generate_content' to CREATE new leads, tasks, meetings, or notes.\n"
    "   - CRITICAL: Content is sent DIRECTLY to frontend, tool returns only '✅ Content generated' or '❌ Error'.\n"
    "   - Do NOT expect content details in the response - they go straight to the user's screen.\n"
    "   - Just acknowledge success: 'The [type] has been generated' or similar.\n"
    "   - Examples: 'create a new lead', 'generate task for follow-up', 'schedule meeting', 'create note'.\n"
    "   - REQUIRED: content_type ('lead', 'task', 'meeting', or 'note'), prompt (user's instruction).\n"
    "   - OPTIONAL: template_title, template_content, context.\n"
    "8) Use MULTIPLE tools together when question needs different operations.\n"
    "   - Example: 'Show task counts by priority (mongo_query) and find related notes (rag_search)'.\n"
    "   - Agent decides tool combination based on query complexity and dependencies.\n\n"
    "TOOL CHEATSHEET:\n"
    "- mongo_query(query:str, show_all:bool=False): Natural-language to Mongo aggregation. Safe fields only. Advanced analytics capabilities.\n"
    "  REQUIRED: 'query' - natural language description of what MongoDB data you want.\n"
    "  CAPABILITIES: Array size filtering, complex aggregations, time-series analysis, advanced operators, trend detection.\n"
    "  PAGINATION: Supports natural language pagination ('page 2', 'skip 100', 'results 21-40') - works with all query types.\n"
    "- rag_search(query:str, content_type:str|None, group_by:str|None, limit:int=10, show_content:bool=True): Universal RAG search.\n"
    "  REQUIRED: 'query' - semantic search terms.\n"
    "  OPTIONAL: content_type ('lead'|'task'|'activity'|'meeting'|'notes'|'callLog'|'mailInfo'|'segmentation'|None for all), group_by (field name), limit, show_content.\n"
    "- generate_content(content_type:str, prompt:str, template_title:str='', template_content:str='', context:dict=None): Generate leads/tasks/meetings/notes.\n"
    "  REQUIRED: content_type ('lead'|'task'|'meeting'|'note'), prompt (what to generate).\n"
    "  OPTIONAL: template_title, template_content, context.\n"
    "  NOTE: Returns '✅ Content generated' only - full content sent directly to frontend to save tokens.\n"
    "- lead_enrichment_tool(business_type:str, city:str, area:str='', max_leads:int=100): Search and enrich local business leads using Google Maps.\n"
    "  REQUIRED: 'business_type' - type of business (e.g., 'textile businesses'), 'city' - city name (e.g., 'Hyderabad').\n"
    "  OPTIONAL: 'area' - specific locality, 'max_leads' - limit results (default 100, max 100).\n"
    "  CAPABILITIES: Google Maps search, structured data extraction (name, address, phone, email, etc.), progress streaming.\n"
    "- import_leads_tool(reason:str=''): Open CRM import UI for previously generated leads. STOP after calling this.\n"
    "  REQUIRED: None (uses leads from most recent lead_enrichment call)\n"
    "  USE FOR: Importing leads AFTER they've been found/generated\n"
    "  BEHAVIOR: Retrieves leads from cache, sends signal to frontend, returns '__LEADS_READY_FOR_IMPORT__' to stop execution\n\n"

    "CONTENT TYPE ROUTING EXAMPLES:\n"
    "- 'What leads are about?' → rag_search(query='leads', content_type='lead')\n"
    "- 'What are recent tasks about?' → rag_search(query='recent tasks', content_type='task')\n"
    "- 'What meetings are scheduled?' → rag_search(query='scheduled meetings', content_type='meeting')\n"
    "- 'Find notes about follow-up' → rag_search(query='follow-up notes', content_type='notes')\n"
    "- 'Find content about customer' → rag_search(query='customer', content_type=None)  # searches all types\n"
    "- 'How many leads have high priority tasks?' → mongo_query(query='leads with high priority tasks')\n"
    "- 'Show 7-day rolling average of lead creation' → mongo_query(query='7-day rolling average of lead creation')\n"
    "- 'Detect anomalies in task completion' → mongo_query(query='detect anomalies in task completion')\n"
    "- 'Create a new lead' → generate_content(content_type='lead', prompt='New lead: TechCorp Inc')\n"
    "- 'Generate task for follow-up' → generate_content(content_type='task', prompt='Follow-up task: Call customer tomorrow')\n"
    "- 'Schedule meeting' → generate_content(content_type='meeting', prompt='Schedule meeting with lead')\n"
    "- 'Create note' → generate_content(content_type='note', prompt='Meeting notes: Discussed pricing')\n"
    "- 'Extract textile business leads in Hyderabad' → lead_enrichment_tool(business_type='textile businesses', city='Hyderabad', max_leads=100)\n\n"
    "WHEN UNSURE WHICH TOOL:\n"
    "- If the query is ambiguous or entity/field mapping to Mongo is unclear → prefer rag_search first.\n"
    "- Question about structured data (counts, filters, group by, breakdown by leadStatus/taskStatus/assignedName/priority/date) → mongo_query.\n"
    "- Advanced analytics (time-series, trends, anomalies, complex aggregations) → mongo_query.\n"
    "- Question about content meaning/semantics (find notes, analyze patterns, content search, descriptions) → rag_search.\n"
    "- Request to CREATE/GENERATE new content → generate_content.\n"
    "- Request to EXTRACT/FIND new leads from web search → lead_enrichment_tool.\n"
    "- Question needs both structured + semantic analysis → use BOTH tools together.\n\n"
    "PATTERN ANALYSIS (EXPLICIT PATTERN QUERIES ONLY):\n"
    "- ONLY when queries EXPLICITLY ask about patterns, frequency, or causation with keywords like 'most common', 'frequent', 'patterns', 'influence', 'factors', 'why', 'what causes' → use BOTH tools:\n"
    "  1. mongo_query: For structured frequency analysis, grouping, counts by category\n"
    "  2. rag_search: For semantic pattern extraction, content analysis, text-based insights\n"
    "- Examples that trigger dual-tool pattern analysis:\n"
    "  * 'What objections are most common?' → mongo_query(group by callPurpose) + rag_search(common objections)\n"
    "  * 'What factors influence win rates?' → mongo_query(group by leadStatus) + rag_search(factors affecting deals)\n"
    "  * 'Why do deals slip?' → mongo_query(filter slipped deals) + rag_search(reasons deals delayed)\n"
    "- IMPORTANT: For pure semantic queries (e.g., 'find notes about follow-up', 'show meeting notes'), use rag_search ONLY, not pattern analysis.\n"
    "- Synthesize results: Combine structured data (frequency tables, counts) with semantic insights (themes, patterns)\n"
    "- Format pattern analysis responses with:\n"
    "  ### Structured Insights (from data)\n"
    "  [Frequency tables, counts, groupings from mongo_query]\n"
    "  ### Semantic Insights (from content)\n"
    "  [Key themes, patterns, correlations from rag_search]\n"
    "  ### Key Findings (ONLY when both tools return results)\n"
    "  [Synthesized insights combining both sources - skip this section if only one tool returned results]\n\n"
    "PAGINATION HANDLING:\n"
    "- When mongo_query returns results with pagination info (e.g., 'Found 200 total, showing 1-50'), recognize this in the response.\n"
    "- If user asks for 'next page', 'fetch more', 'page 2', 'show more' → modify the query to include skip/offset.\n"
    "- Examples: 'show next page' → add 'skip 50' or 'page 2' to the original query.\n"
    "- Always inform user about total count and offer to fetch more when pagination is available.\n\n"
    "RESPONSE FORMATTING (CRITICAL):\n"
    "- ALWAYS format your responses using **markdown** for maximum readability.\n"
    "- Use headings (##, ###) to organize sections and break up content.\n"
    "- Use **bold** for emphasis on key terms, numbers, and important concepts.\n"
    "- Use code blocks (```language) for queries, code, or technical output.\n"
    "- Use tables (| column |) when presenting structured data comparisons.\n"
    "- Use horizontal rules (---) to separate distinct sections when appropriate.\n"
    "- Use blockquotes (>) for important notes, warnings, or highlights.\n"
    "- Keep paragraphs short (2-3 sentences max) for better scanning.\n\n"
    "Respond with tool calls first, then synthesize a concise answer grounded ONLY in tool outputs."
)

# Initialize the LLM with optimized settings for tool calling
llm = ChatGroq(
    model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
    temperature=float(os.getenv("GROQ_TEMPERATURE", "0.1")),
    max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "1024")),
    streaming=True,
    verbose=False,
    top_p=0.8,
)


class TTLCache:
    """Simple TTL cache for tool results to reduce repeat latency."""

    def __init__(self, max_items: int = 256, ttl_seconds: int = 900):
        self.store: Dict[str, tuple[float, Any]] = {}
        self.max_items = max_items
        self.ttl = ttl_seconds

    def _evict_if_needed(self):
        if len(self.store) <= self.max_items:
            return
        oldest_key = min(self.store.items(), key=lambda kv: kv[1][0])[0]
        self.store.pop(oldest_key, None)

    def get(self, key: str) -> Optional[Any]:
        rec = self.store.get(key)
        if not rec:
            return None
        ts, value = rec
        if time.time() - ts > self.ttl:
            self.store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self.store[key] = (time.time(), value)
        self._evict_if_needed()


# ✅ OPTIMIZED: LLM response cache for efficient call management
_llm_response_cache = TTLCache(max_items=100, ttl_seconds=300)  # 5 min cache for LLM responses

def _hash_messages(messages: List[BaseMessage]) -> str:
    """Create a hash key from message list for caching."""
    import hashlib
    # Create a simple hash from message contents
    content_parts = []
    for msg in messages:
        content = getattr(msg, "content", "")
        msg_type = msg.__class__.__name__
        content_parts.append(f"{msg_type}:{content[:200]}")  # Limit content length for hashing
    combined = "|".join(content_parts)
    return hashlib.md5(combined.encode()).hexdigest()

# def _log_guard_violation(query: str, error_details: str, conversation_id: str) -> None:
#     """Log guard validation failures for security auditing.
#     
#     Args:
#         query: The user input that was flagged
#         error_details: Details about why it was flagged
#         conversation_id: Conversation context for audit trail
#     """
#     try:
#         query_preview = query[:100] if query else "[empty]"
#         logger.warning(
#             f"[GUARD_VIOLATION] Conversation: {conversation_id} | "
#             f"Query: {query_preview} | Details: {error_details}"
#         )
#     except Exception as e:
#         logger.error(f"Failed to log guard violation: {e}")


# Simple per-query tool router: restrict RAG unless content/context is requested
_TOOLS_BY_NAME = {getattr(t, "name", str(i)): t for i, t in enumerate(tools_list)}

def _select_tools_for_query(user_query: str):
    """Return tools exposed to the LLM for this query.

    Enhanced policy:
    - Always expose all available tools (mongo_query, rag_search, generate_content).
    - Let the LLM decide routing based on instructions; no keyword gating.
    - Add CRM-specific query analysis hints for better tool selection.
    """
    allowed_names = ["mongo_query", "rag_search", "generate_content", "lead_enrichment_tool","import_leads_tool"]
    selected_tools = [tool for name, tool in _TOOLS_BY_NAME.items() if name in allowed_names]
    if not selected_tools and "mongo_query" in _TOOLS_BY_NAME:
        selected_tools = [_TOOLS_BY_NAME["mongo_query"]]
    
    # CRM-specific query hints (for logging/debugging, not filtering)
    query_lower = user_query.lower()
    crm_entities = ['lead', 'task', 'activity', 'meeting', 'note', 'call', 'mail', 'email']
    has_crm_entity = any(entity in query_lower for entity in crm_entities)
    
    if has_crm_entity:
        # Query likely needs CRM tools - ensure they're available
        pass  # Tools already selected above
    
    return selected_tools, allowed_names

class AgentExecutor:
    """MongoDB Agent using Tool Calling with LLM-Controlled Execution
    
    Features:
    - LLM-controlled execution: The LLM decides whether tools should run in parallel
      or sequentially based on dependencies. When the LLM calls multiple tools together,
      they execute in parallel. When tools need sequential execution, the LLM will
      make separate calls.
    - Parallel execution: When the LLM calls multiple independent tools together,
      they execute concurrently using asyncio.gather() for improved performance.
    - Sequential execution: When tools have dependencies, the LLM naturally handles
      this by calling them in separate rounds.
    - Full tracing support: All tool executions (parallel or sequential) are properly traced
      with Phoenix/OpenTelemetry.
    - Conversation memory: Maintains context across multiple turns.
    
    Args:
        max_steps: Maximum number of reasoning steps (default: 8)
        system_prompt: Custom system prompt or None to use default
        enable_parallel_tools: Enable parallel tool execution (default: True)
    """

    def __init__(self, max_steps: int = 8, system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT, enable_parallel_tools: bool = True):
        # Base LLM; tools will be bound per-query via router
        self.llm_base = llm
        self.connected = False
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.tracing_enabled = False
        self.enable_parallel_tools = enable_parallel_tools
        conversation_cache_ttl = int(os.getenv("AGENT_CONVERSATION_CACHE_TTL", "300"))
        conversation_cache_size = int(os.getenv("AGENT_CONVERSATION_CACHE_SIZE", "256"))
        self._conversation_context_cache = TTLCache(
            max_items=conversation_cache_size,
            ttl_seconds=conversation_cache_ttl,
        )
        self._conversation_cache_tasks: Dict[str, asyncio.Task] = {}

    async def _get_conversation_context_cached(self, conversation_id: str) -> List[BaseMessage]:
        cached = self._conversation_context_cache.get(conversation_id)
        if cached is not None:
            return list(cached)
        context = await conversation_memory.get_recent_context(conversation_id)
        self._conversation_context_cache.set(conversation_id, list(context))
        return context

    def _append_conversation_cache(self, conversation_id: str, message: BaseMessage) -> None:
        cached = self._conversation_context_cache.get(conversation_id)
        if cached is None:
            return
        updated = list(cached)
        updated.append(message)
        self._conversation_context_cache.set(conversation_id, updated)

    def _schedule_conversation_cache_refresh(self, conversation_id: str) -> None:
        existing = self._conversation_cache_tasks.get(conversation_id)
        if existing and not existing.done():
            return

        async def _refresh():
            try:
                context = await conversation_memory.get_recent_context(conversation_id)
                self._conversation_context_cache.set(conversation_id, list(context))
            except Exception as exc:
                logger.error("Failed to refresh conversation cache for %s: %s", conversation_id, exc)
            finally:
                self._conversation_cache_tasks.pop(conversation_id, None)

        task = asyncio.create_task(_refresh())
        self._conversation_cache_tasks[conversation_id] = task

    async def _add_message_to_memory(self, conversation_id: str, message: BaseMessage) -> None:
        await conversation_memory.add_message(conversation_id, message)
        self._append_conversation_cache(conversation_id, message)
        self._schedule_conversation_cache_refresh(conversation_id)

    async def _execute_single_tool(
        self, 
        tool, 
        tool_call: Dict[str, Any], 
        selected_tools: List[Any],
        tracer=None,
        *,
        user_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> tuple[ToolMessage, bool]:
        """Execute a single tool with tracing support.
        
        Returns:
            tuple: (ToolMessage, success_flag)
        """
        tool_cm = None
        tool_start_time = perf_counter()
        with contextlib.nullcontext() as tool_span:
            # Enforce router: only allow selected tools
            actual_tool = next((t for t in selected_tools if t.name == tool_call["name"]), None)
            if not actual_tool:
                error_msg = ToolMessage(
                    content=f"Tool '{tool_call['name']}' not found.",
                    tool_call_id=tool_call["id"],
                )
                return error_msg, False

            try:
                # Validate tool arguments before execution
                args = tool_call.get("args", {})
                if args is None:
                    args = {}
                if not isinstance(args, dict):
                    raise ValueError(f"Tool arguments must be a dictionary, got {type(args)}")
                # Auto-inject context for tooling so downstream LLM usage can be tracked
                if business_id and "business_id" not in args:
                    args["business_id"] = business_id
                if user_id and "user_id" not in args:
                    args["user_id"] = user_id

                tool_name = tool_call.get("name", "unknown")
                logger.info(f"[_execute_single_tool] Executing tool: {tool_name}")
                logger.info(f"[_execute_single_tool] Tool args: {args}")
                
                result = await actual_tool.ainvoke(args)

                logger.info(f"[_execute_single_tool] Tool result type: {type(result)}")
                logger.info(f"[_execute_single_tool] Tool result preview: {str(result)[:200]}")
                
                # Validate result is not None
                if result is None:
                    result = "Tool returned no result"
                    success = False
                else:
                    success = True
                
            except ValueError as ve:
                result = f"Invalid tool arguments: {ve}"
                success = False
            except KeyError as ke:
                result = f"Missing required tool argument: {ke}"
                success = False
            except Exception as tool_exc:
                tool_name = tool_call.get("name", "unknown")
                logger.error(f"Tool execution error for {tool_name}: {tool_exc}", exc_info=True)
                result = f"Tool execution error: {str(tool_exc)}"
                success = False

            tool_message = ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
            tool_elapsed_ms = (perf_counter() - tool_start_time) * 1000
            logger.info(f"[_execute_single_tool] Tool completed in {tool_elapsed_ms:.1f}ms")
            logger.info(f"[_execute_single_tool] Success: {success}")
            return tool_message, success

    async def connect(self):
        """Connect to MongoDB MCP server"""
        # Tracing initialization removed - method does not exist
        span = None
        try:
            await mongodb_tools.connect()
            self.connected = True
            if span:
                pass
        except Exception as e:
            if span:
                pass
            raise
        finally:
            pass

    async def disconnect(self):
        """Disconnect from MongoDB MCP server"""
        await mongodb_tools.disconnect()
        self.connected = False
        # Tracing removed: nothing to clean up
        pass


    async def run_streaming(
        self,
        query: str,
        websocket=None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        business_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Run the agent with streaming support and conversation context"""
        if business_id:
            try:
                import websocket_handler
                websocket_handler.business_id_global = business_id
                if user_id:
                    websocket_handler.user_id_global = user_id
            except Exception as e:
                logger.warning(f"Failed to set websocket context: {e}")

        if not self.connected:
            await self.connect()

        try:
            tracer = None
            if tracer is not None:
                span_cm = tracer.start_as_current_span(
                    "agent_run_streaming",
                    # kind=trace.SpanKind.INTERNAL,  # Tracing removed
                    attributes={
                        "query_preview": query[:80],
                        "query_length": len(query or ""),
                        "database.name": DATABASE_NAME,
                    },
                )
            else:
                span_cm = None

            with (span_cm if span_cm is not None else contextlib.nullcontext()):
                # Use default conversation ID if none provided
                if not conversation_id:
                    conversation_id = f"conv_{int(time.time())}"

                # Get conversation history (cached per session with async refresh)
                conversation_context = await conversation_memory.get_recent_context(conversation_id)

                is_lead_enrichment, clarified_query = preprocess_lead_enrichment_query(query)
        
                if is_lead_enrichment and clarified_query:
                    logger.info(f"[run_streaming] Using clarified query for lead enrichment")
                    # Use clarified query to help LLM choose correct tool
                    query_for_llm = clarified_query
                else:
                    query_for_llm = query

                # Build messages with optional system instruction
                messages: List[BaseMessage] = []
                if self.system_prompt:
                    messages.append(SystemMessage(content=self.system_prompt))

                messages.extend(conversation_context)

                # Add current user message
                human_message = HumanMessage(content=query_for_llm)
                messages.append(human_message)

                # Skip guardrails checks - all queries are allowed now
                # The following guardrails code has been commented out:
                # ✅ PARALLEL SAFETY CHECKS: Run both toxic language + prompt injection detection
                # guardrails_context = await conversation_memory.get_messages_for_guardrails(conversation_id)
                # conversation_history_for_guard = [...]  # Convert to dict format
                # toxic_passed, prompt_injection_safe, blocked_reason, violation_category = await _run_parallel_safety_checks(...)
                # guard_passed = toxic_passed and prompt_injection_safe
                # if not guard_passed:
                #     # Handle blocked queries
                callback_handler = AgentCallbackHandler(websocket, conversation_id)

                steps = 0
                last_response: Optional[AIMessage] = None
                need_finalization: bool = False

                while steps < self.max_steps:
                    # Choose tools for this query iteration
                    selected_tools, allowed_names = _select_tools_for_query(query)
                    llm_with_tools = self.llm_base.bind_tools(selected_tools)
                    llm_cm = None

                    with (llm_cm if llm_cm is not None else contextlib.nullcontext()) as llm_span:
                        pass
                        query_lower = query.lower()
                        routing_hint = ""
                        
                        # Detect lead enrichment requests
                        if any(keyword in query_lower for keyword in ['find', 'get', 'search', 'extract']) and \
                        any(entity in query_lower for entity in ['lead', 'business', 'company', 'shop', 'store', 'restaurant']):
                            routing_hint = (
                                "\n\nROUTING HINT FOR THIS QUERY:\n"
                                "This appears to be a BUSINESS SEARCH request. You MUST use 'lead_enrichment_tool' to search for REAL businesses.\n"
                                "- DO NOT use 'generate_content' - that's for creating fictional/template entities\n"
                                "- DO NOT use 'mongo_query' - that's for querying existing CRM data\n"
                                "- DO NOT use 'rag_search' - that's for content-based searches\n"
                                "- USE 'lead_enrichment_tool' to find actual businesses using Google Maps\n"
                            )
                        
                        # Detect import requests
                        elif any(keyword in query_lower for keyword in ['import', 'save to crm', 'add to crm']):
                            routing_hint = (
                                "\n\nROUTING HINT FOR THIS QUERY:\n"
                                "This appears to be an IMPORT request. You MUST use 'import_leads_tool'.\n"
                                "- This tool retrieves previously generated leads from cache\n"
                                "- After calling this tool, STOP execution immediately\n"
                            )
                        routing_instructions = SystemMessage(content=(
                            "PLANNING & ROUTING:\n"
                            "- Break the user request into logical steps.\n"
                            "- For INDEPENDENT operations: Call multiple tools together.\n"
                            "- For DEPENDENT operations: Call tools separately (wait for results before next call).\n"
                            +routing_hint+"\n\n"
                            "RESPONSE FORMATTING (CRITICAL):\n"
                            "- ALWAYS format your responses using **markdown** for maximum readability.\n"
                            "- Use headings (##, ###) to organize sections and break up content.\n"
                            "- Use **bold** for emphasis on key terms, numbers, and important concepts.\n"
                            "- Use code blocks (```language) for queries, code, or technical output.\n"
                            "- Use tables (| column |) when presenting structured data comparisons.\n"
                            "- Use horizontal rules (---) to separate distinct sections when appropriate.\n"
                            "- Use blockquotes (>) for important notes, warnings, or highlights.\n"
                            "- Keep paragraphs short (2-3 sentences max) for better scanning.\n\n"
                            "LIST FORMATTING (IMPORTANT):\n"
                            "- Use **unordered lists (-)** for collections, features, or items without hierarchy\n"
                            "- Use **numbered lists (1., 2., 3.)** for sequential steps, priorities, or ranked items\n"
                            "- Use **nested lists** for hierarchical information\n"
                            "- Keep list items concise and use **bold** for key terms\n\n"
                            "DECISION GUIDE:\n"
                            "1) Use 'mongo_query' for structured questions about entities/fields in collections: Lead, Task, Activity, Meeting, Notes, CallLog, MailInfo, LeadScoreRule, Segmentation.\n"
                            "   - Examples: counts, lists, filters, sort, group by, breakdowns by leadStatus/taskStatus/assignedName/priority/date.\n"
                            "   - Use for: 'count leads by status', 'list tasks by assignee', 'group leads by source', 'show breakdown by taskStatus'.\n"
                            "   - The query planner automatically determines when complex joins are beneficial and adds strategic relationships only when they improve query performance.\n"
                            "   - Do NOT answer from memory; run a query.\n"
                            "2) Use 'rag_search' for content-based searches (semantic meaning, not just keywords).\n"
                            "   - Returns FULL chunk content for synthesis - analyze and format the actual content in your response.\n"
                            "   - Find leads/tasks/meetings/notes by meaning, analyze content patterns, search CRM content.\n"
                            "   - Examples: 'find notes about follow-up', 'show meeting notes', 'content mentioning customer', 'analyze patterns in descriptions'.\n"
                            "   - SMART CONTENT TYPE SELECTION: Choose appropriate content_type based on query semantics:\n"
                            "     • 'leads', 'prospects', 'customers' keywords → content_type='lead'\n"
                            "     • 'tasks', 'todos', 'follow-ups' keywords → content_type='task'\n"
                            "     • 'meetings', 'calls', 'appointments' keywords → content_type='meeting'\n"
                            "     • 'notes', 'comments' keywords → content_type='notes'\n"
                            "     • 'call logs', 'call history' keywords → content_type='callLog'\n"
                            "     • 'emails', 'mail' keywords → content_type='mailInfo'\n"
                            "     • 'activities' keywords → content_type='activity'\n"
                            "     • 'segmentation', 'segments' keywords → content_type='segmentation'\n"
                            "     • Unclear/multi-type query → content_type=None (all) OR multiple rag_search calls\n"
                            "3) Use 'generate_content' to CREATE new leads, tasks, meetings, or notes.\n"
                            "   - CRITICAL: Content sent DIRECTLY to frontend, returns only '✅ Content generated'.\n"
                            "   - Do NOT expect details - just acknowledge success to user.\n"
                            "   - Examples: 'create a new lead', 'generate task for follow-up', 'schedule meeting', 'create note'.\n"
                            "   - REQUIRED: content_type ('lead'|'task'|'meeting'|'note'), prompt.\n"
                            "   - OPTIONAL: template_title, template_content, context.\n"
                            "4) Use MULTIPLE tools together when question needs different operations.\n"
                            "   - Example: 'Show task counts by priority (mongo_query) and find related notes (rag_search)'.\n"
                            "   - Agent decides tool combination based on query complexity and dependencies.\n\n"
                            "TOOL CHEATSHEET:\n"
                            "- mongo_query(query:str, show_all:bool=False): Natural-language to Mongo aggregation. Safe fields only. Advanced analytics capabilities.\n"
                            "  REQUIRED: 'query' - natural language description of what MongoDB data you want.\n"
                            "  CAPABILITIES: Array size filtering, complex aggregations, time-series analysis, advanced operators, trend detection.\n"
                            "- rag_search(query:str, content_type:str|None, group_by:str|None, limit:int=10, show_content:bool=True): Universal RAG search.\n"
                            "  REQUIRED: 'query' - semantic search terms.\n"
                            "  OPTIONAL: content_type ('lead'|'task'|'activity'|'meeting'|'notes'|'callLog'|'mailInfo'|'segmentation'|None for all), group_by (field name), limit, show_content.\n"
                            "- generate_content(content_type:str, prompt:str, template_title:str='', template_content:str='', context:dict=None): Generate leads/tasks/meetings/notes.\n"
                            "  REQUIRED: content_type ('lead'|'task'|'meeting'|'note'), prompt (what to generate).\n"
                            "  OPTIONAL: template_title, template_content, context.\n"
                            "  NOTE: Returns '✅ Content generated' only - full content sent directly to frontend to save tokens.\n"
                            "CONTENT TYPE EXAMPLES:\n"
                            "- 'What leads are about?' → rag_search(query='leads', content_type='lead')\n"
                            "- 'Recent tasks about follow-up?' → rag_search(query='recent tasks follow-up', content_type='task')\n"
                            "- 'Scheduled meetings?' → rag_search(query='scheduled meetings', content_type='meeting')\n"
                            "- 'Find notes about customer' → rag_search(query='customer notes', content_type='notes')\n"
                            "- 'Call logs mentioning pricing' → rag_search(query='pricing call logs', content_type='callLog')\n"
                            "- 'Create a new lead' → generate_content(content_type='lead', prompt='New lead: TechCorp Inc')\n"
                            "- 'Generate task for follow-up' → generate_content(content_type='task', prompt='Follow-up task: Call customer tomorrow')\n"
                            "- 'Schedule meeting' → generate_content(content_type='meeting', prompt='Schedule meeting with lead')\n"
                            "- 'Create note' → generate_content(content_type='note', prompt='Meeting notes: Discussed pricing')\n\n"
                            "WHEN UNSURE WHICH TOOL:\n"
                            "- If the query is ambiguous or entity/field mapping to Mongo is unclear → prefer rag_search first.\n"
                            "- Question about structured data (counts, filters, group by, breakdown by leadStatus/taskStatus/assignedName/priority/date) → mongo_query.\n"
                            "- Question about content meaning/semantics (find notes, analyze patterns, content search, descriptions) → rag_search.\n"
                            "- Request to CREATE/GENERATE content → generate_content\n"
                            "- Question needs both structured + semantic analysis → use BOTH tools together\n\n"
                            "PATTERN ANALYSIS (EXPLICIT PATTERN QUERIES ONLY):\n"
                            "- ONLY when queries EXPLICITLY ask about patterns, frequency, or causation with keywords like 'most common', 'frequent', 'patterns', 'influence', 'factors', 'why', 'what causes' → use BOTH tools:\n"
                            "  1. mongo_query: For structured frequency analysis, grouping, counts by category\n"
                            "  2. rag_search: For semantic pattern extraction, content analysis, text-based insights\n"
                            "- Examples that trigger dual-tool pattern analysis:\n"
                            "  * 'What objections are most common?' → mongo_query(group by callPurpose) + rag_search(common objections)\n"
                            "  * 'What factors influence win rates?' → mongo_query(group by leadStatus) + rag_search(factors affecting deals)\n"
                            "  * 'Why do deals slip?' → mongo_query(filter slipped deals) + rag_search(reasons deals delayed)\n"
                            "- IMPORTANT: For pure semantic queries (e.g., 'find notes about follow-up', 'show meeting notes'), use rag_search ONLY, not pattern analysis.\n"
                            "- Synthesize results: Combine structured data (frequency tables, counts) with semantic insights (themes, patterns)\n"
                            "- Format pattern analysis responses with:\n"
                            "  ### Structured Insights (from data)\n"
                            "  [Frequency tables, counts, groupings from mongo_query]\n"
                            "  ### Semantic Insights (from content)\n"
                            "  [Key themes, patterns, correlations from rag_search]\n"
                            "  ### Key Findings (ONLY when both tools return results)\n"
                            "  [Synthesized insights combining both sources - skip this section if only one tool returned results]\n\n"
                            "PAGINATION HANDLING:\n"
                            "- When mongo_query returns results with pagination info (e.g., 'Found 200 total, showing 1-50'), recognize this in the response.\n"
                            "- If user asks for 'next page', 'fetch more', 'page 2', 'show more' → modify the query to include skip/offset.\n"
                            "- Examples: 'show next page' → add 'skip 50' or 'page 2' to the original query.\n"
                            "- Always inform user about total count and offer to fetch more when pagination is available.\n\n"
                            "IMPORTANT: Use valid args: mongo_query needs 'query'; rag_search needs 'query' (optional: content_type, group_by, limit, show_content); generate_content needs content_type + prompt."
                        ))
                        # Determine if this is a finalization turn BEFORE calling LLM
                        is_finalizing = need_finalization  # ✅ Save the state BEFORE modifying it

                        if need_finalization:
                            finalization_instructions = SystemMessage(content=(
                                "FINALIZATION: Write a concise answer in your own words based on the tool outputs above. "
                                "Do not paste tool outputs verbatim or include banners/emojis. "
                                "If the user asked to browse or see examples, summarize briefly and offer to expand. "
                                "For work items, present canonical fields succinctly."
                            ))
                            # Emit a natural action statement to indicate synthesis/finalization
                            try:
                                import random
                                synth_phrases = [
                                    "Putting together the findings into a clear answer",
                                    "Synthesizing the information I gathered",
                                    "Compiling the results into a comprehensive response",
                                    "Organizing the data into a coherent answer",
                                    "Bringing everything together for you"
                                ]
                                synth_action = random.choice(synth_phrases)
                                if callback_handler:
                                    # Emit synchronously for real-time delivery
                                    await callback_handler.emit_dynamic_action(synth_action)
                            except Exception:
                                pass
                            invoke_messages = messages + [routing_instructions, finalization_instructions]
                            need_finalization = False
                        else:
                            invoke_messages = messages + [routing_instructions]

                        # Only stream tokens during finalization, NOT during tool planning
                        # During tool planning, we'll emit action events instead
                        should_stream = is_finalizing  # ✅ Use the saved state
                        main_llm_start_time = perf_counter()
                        # ✅ OPTIMIZED: Check LLM response cache before making API call
                        cache_key = _hash_messages(invoke_messages)
                        cached_response = _llm_response_cache.get(cache_key)
                        
                        if cached_response and not should_stream:
                            # Use cached response for non-streaming calls (tool planning)
                            response = cached_response
                        else:
                            # Make LLM call
                            response = await llm_with_tools.ainvoke(
                                invoke_messages,
                                config={"callbacks": [callback_handler] if should_stream else []},
                            )
                            main_llm_elapsed_ms = (perf_counter() - main_llm_start_time) * 1000
                            log_msg_type = "Final Synthesis" if is_finalizing else "Tool Planning"
                            if getattr(response, "tool_calls", None):
                                original_calls = response.tool_calls
                                corrected_calls, was_corrected = validate_and_correct_tool_usage(original_calls, query)
                                
                                if was_corrected:
                                    logger.info(f"[run_streaming] Tool usage auto-corrected")
                                    # Update response with corrected calls
                                    response.tool_calls = corrected_calls
                                    
                                    # Optionally send a message to user about correction
                                    if callback_handler:
                                        try:
                                            await callback_handler.on_llm_new_token(
                                                "\n\n_[System: Correcting tool selection for better results...]_\n\n"
                                            )
                                        except Exception:
                                            pass
                            # Cache response for non-streaming calls (tool planning)
                            if not should_stream:
                                _llm_response_cache.set(cache_key, response)
                        if llm_span and getattr(response, "content", None):
                            try:
                                preview = str(response.content)[:500]
                                llm_span.set_attribute('output.value', preview)
                                llm_span.add_event("llm_response", {"preview_len": len(preview)})
                            except Exception:
                                pass
                    last_response = response

                    # Only persist assistant messages when there are NO tool calls (final response)
                    # Intermediate reasoning should not be saved as assistant messages
                    if not getattr(response, "tool_calls", None):
                        # This is a final response, save it
                        await conversation_memory.add_message(conversation_id, response)
                        try:
                            await save_assistant_message(conversation_id, getattr(response, "content", "") or "")
                        except Exception as e:
                            logger.error(f"Failed to save assistant message: {e}")
                        yield response.content
                        return
                    else:
                        # ✅ NEW: Keep intermediate response WITH reasoning in conversation history
                        # This helps LLM maintain context, but don't persist to DB (not shown to user)
                        await conversation_memory.add_message(conversation_id, response)
                        # Note: NOT calling save_assistant_message() - only actions are saved to DB

                    # Execute requested tools with streaming callbacks
                    # The LLM decides execution order by how it calls tools
                    clean_response = AIMessage(
                        content="",  # Clear content for clean message handling
                        tool_calls=response.tool_calls,  # Keep tool calls for execution
                    )
                    messages.append(clean_response)
                    did_any_tool = False
                    if len(response.tool_calls) > 1:
                        # ✅ EMIT ACTIONS FIRST - Before tool execution starts
                        for tool_call in response.tool_calls:
                            if callback_handler:
                                try:
                                    await callback_handler.on_tool_start(
                                        {"name": tool_call["name"]}, 
                                        str(tool_call.get("args", {}))
                                    )
                                except Exception:
                                    pass
                        
                        # NOW build and execute tool tasks in parallel
                        tool_tasks = [
                            self._execute_single_tool(None, tool_call, selected_tools, None, user_id=user_id, business_id=business_id)
                            for tool_call in response.tool_calls
                        ]
                        
                        tool_results = await asyncio.gather(*tool_tasks, return_exceptions=True)
                        
                        # Process results and send tool_end events
                        for i, result in enumerate(tool_results):
                            if isinstance(result, Exception):
                                # Handle exception from tool execution
                                error_msg = ToolMessage(
                                    content=f"Tool execution error: {result}",
                                    tool_call_id=response.tool_calls[i].get("id", ""),
                                )
                                if callback_handler:
                                    try:
                                        await callback_handler.on_tool_end(error_msg.content)
                                    except Exception as e:
                                        logger.error(f"Error in callback handler: {e}")
                                messages.append(error_msg)
                                try:
                                    await conversation_memory.add_message(conversation_id, error_msg)
                                except Exception as e:
                                    logger.error(f"Error saving error message to memory: {e}")
                            else:
                                tool_message, success = result
                                # Validate tool message content
                                if not tool_message.content:
                                    tool_message.content = "Tool returned empty result"
                                    success = False
                                
                                if callback_handler:
                                    try:
                                        await callback_handler.on_tool_end(tool_message.content)
                                    except Exception as e:
                                        logger.error(f"Error in callback handler: {e}")
                                
                                messages.append(tool_message)
                                try:
                                    await conversation_memory.add_message(conversation_id, tool_message)
                                except Exception as e:
                                    logger.error(f"Error saving tool message to memory: {e}")
                                
                                if success:
                                    did_any_tool = True
                    else:
                        # Single tool execution - this part is already correct
                        for tool_call in response.tool_calls:
                            if callback_handler:
                                try:
                                    await callback_handler.on_tool_start(
                                        {"name": tool_call["name"]}, 
                                        str(tool_call.get("args", {}))
                                    )
                                except Exception:
                                    pass
                            
                            tool_message, success = await self._execute_single_tool(None, tool_call, selected_tools, None, user_id=user_id, business_id=business_id)
                            logger.info(f"[run_streaming] Tool message content: '{tool_message.content}'")
                            logger.info(f"[run_streaming] Checking for import signal...")

                            if tool_message.content == "__LEADS_READY_FOR_IMPORT__":
                                logger.info("[run_streaming] ========== IMPORT SIGNAL DETECTED ==========")
                                logger.info("[run_streaming] Stopping agent execution immediately")
                                # Import UI was triggered - STOP execution immediately
                                if callback_handler:
                                    try:
                                        await callback_handler.on_tool_end("Opening import UI...")
                                    except Exception:
                                        pass
                                return

                            # Validate tool message content
                            if not tool_message.content:
                                tool_message.content = "Tool returned empty result"
                                success = False
                            
                            if callback_handler:
                                try:
                                    await callback_handler.on_tool_end(tool_message.content)
                                except Exception as e:
                                    logger.error(f"Error in callback handler: {e}")
                            
                            messages.append(tool_message)
                            try:
                                await self._add_message_to_memory(conversation_id, tool_message)
                            except Exception as e:
                                logger.error(f"Error saving tool message to memory: {e}")
                            
                            if success:
                                did_any_tool = True
                    
                    steps += 1

                    # After executing any tools, force the next LLM turn to synthesize
                    if did_any_tool:
                        need_finalization = True

                # Step cap reached; send best available response
                if last_response is not None:
                    # Register turn and update summary if needed
                    await conversation_memory.register_turn(conversation_id)
                    if await conversation_memory.should_update_summary(conversation_id, every_n_turns=3):
                        try:
                            asyncio.create_task(
                                conversation_memory.update_summary_async(conversation_id, self.llm_base)
                            )
                        except Exception as e:
                            logger.error(f"Failed to update summary: {e}")
                    yield last_response.content
                else:
                    yield "Reached maximum reasoning steps without a final answer."
                return

        except Exception as e:
            yield f"Error running streaming agent: {str(e)}"



async def main():
    """Example usage of the ProjectManagement Insights Agent"""
    agent = AgentExecutor()
    await agent.connect()
    await agent.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
