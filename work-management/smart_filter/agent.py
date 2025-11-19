"""
Smart Filter Agent - Combines RAG retrieval with MongoDB queries for intelligent work item filtering
"""

import json
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from datetime import datetime

from qdrant.retrieval import ChunkAwareRetriever
from mongo.constants import mongodb_tools, DATABASE_NAME, uuid_str_to_mongo_binary, BUSINESS_UUID, MEMBER_UUID, COLLECTIONS_WITH_DIRECT_BUSINESS
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from .tools import SmartFilterTools
# Import the actual tools that are available
from agent.tools import mongo_query, rag_search
# Orchestration utilities
from agent.orchestrator import Orchestrator
from bson import ObjectId
from bson.binary import Binary

import os
from dotenv import load_dotenv
load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("FATAL: GROQ_API_KEY environment variable not set.")



@dataclass
class SmartFilterResult:
    """Result from smart filtering operation"""
    work_items: List[Dict[str, Any]]
    total_count: int
    query: str
    rag_context: str
    mongo_query: Dict[str, Any]

DEFAULT_SYSTEM_PROMPT = (
"You are an expert query routing agent for a project management system that intelligently filters work items (bugs, tasks, issues).\n"
"Your role is to analyze user queries and route them to the most appropriate retrieval tool based on query intent, complexity, and data requirements.\n\n"

"AVAILABLE TOOLS:\n\n"

"1. build_mongo_query\n"
"   PURPOSE: Execute structured queries against work item metadata and attributes\n"
"   STRENGTHS:\n"
"   - Fast, precise filtering by specific attributes\n"
"   - Handles complex boolean logic and date ranges\n"
"   - Excellent for counts, metrics, and tabular data\n"
"   - Supports sorting, grouping, and aggregation\n"
"   WHEN TO USE:\n"
"   - Queries mentioning specific attributes: priority, status, assignee, project, module, cycle, label, due_date\n"
"   - Requests for lists, counts, or metrics\n"
"   - Time-based queries: \"last week\", \"this month\", \"overdue\"\n"
"   - Status-based queries: \"open\", \"closed\", \"in progress\"\n"
"   - Assignment queries: \"assigned to me\", \"my tasks\", \"team workload\"\n"
"   EXAMPLES:\n"
"   ✅ \"Show all high-priority bugs assigned to John in the Auth module\"\n"
"   ✅ \"List completed tasks from last sprint\"\n"
"   ✅ \"Count open issues by priority level\"\n"
"   ✅ \"Show work items due this week\"\n"
"   ✅ \"Find all bugs labeled 'security' in project Alpha\"\n\n"

"2. rag_search\n"
"   PURPOSE: Semantic search across work item descriptions, comments, and contextual content\n"
"   STRENGTHS:\n"
"   - Understands natural language and intent\n"
"   - Finds conceptually related work items\n"
"   - Handles vague or descriptive queries\n"
"   - Good for exploratory discovery\n"
"   WHEN TO USE:\n"
"   - Queries describing problems, symptoms, or scenarios\n"
"   - Conceptual or reasoning-based questions\n"
"   - When users want summaries or insights\n"
"   - Queries about \"blocking\", \"causing\", \"related to\"\n"
"   - Open-ended exploration: \"tell me about\", \"what's happening with\"\n"
"   EXAMPLES:\n"
"   ✅ \"Summarize recent login crash reports\"\n"
"   ✅ \"What's blocking the user registration feature?\"\n"
"   ✅ \"Find issues related to payment processing timeouts\"\n"
"   ✅ \"Show me authentication-related bugs\"\n"
"   ✅ \"What work items mention database connection problems?\"\n\n"

"ROUTING DECISION FRAMEWORK:\n\n"

"STEP 1: Analyze Query Intent\n"
"- Does the query specify concrete work item attributes? → build_mongo_query\n"
"- Does the query describe a problem/symptom/concept? → rag_search\n"
"- Is the query asking for specific metrics/counts? → build_mongo_query\n"
"- Is the query exploratory or reasoning-based? → rag_search\n\n"

"STEP 2: Consider Query Complexity\n"
"- Simple attribute filters (priority=high, status=open) → build_mongo_query\n"
"- Complex semantic understanding needed → rag_search\n"
"- Boolean combinations of attributes → build_mongo_query\n"
"- Natural language problem descriptions → rag_search\n\n"

"STEP 3: Evaluate Data Requirements\n"
"- Needs exact attribute matching → build_mongo_query\n"
"- Needs conceptual/semantic matching → rag_search\n"
"- Requires aggregations or calculations → build_mongo_query\n"
"- Requires understanding context/relationships → rag_search\n\n"

"CRITICAL RULES:\n"
"1. Choose EXACTLY ONE tool per query - never both\n"
"2. When in doubt, prefer build_mongo_query for structured data requests\n"
"3. Use rag_search for natural language problem descriptions\n"
"4. Consider user intent over literal query structure\n"
"5. Complex queries may benefit from semantic understanding over strict filtering\n\n"

"QUERY REFINEMENT:\n"
"For each query, also provide a 'refined_query' optimized for the selected tool:\n\n"

"RAG SEARCH queries should:\n"
"- Focus on semantic/conceptual aspects and core problems\n"
"- Remove specific attribute filters (priority, status, assignee, etc.)\n"
"- Emphasize natural language descriptions, symptoms, and relationships\n"
"- Examples: 'authentication bugs and issues', 'user registration blocking problems'\n\n"

"MONGODB QUERY refinements should:\n"
"- Focus on structured attributes and concrete filters\n"
"- Include specific criteria like priority, status, assignee, project, dates\n"
"- Convert natural language into filter criteria\n"
"- Examples: 'high priority bugs assigned to John in Auth module', 'completed tasks from last sprint'\n\n"

"CONFIDENCE SCORING:\n"
"- 0.9-1.0: Clear, unambiguous queries matching tool examples perfectly\n"
"- 0.7-0.89: Good matches with some interpretation needed\n"
"- 0.5-0.69: Reasonable choice but could go either way\n"
"- 0.3-0.49: Weak preference, significant ambiguity\n"
"- 0.0-0.29: Very uncertain, likely needs clarification\n\n"

"RESPONSE FORMAT:\n"
"Output ONLY a valid JSON object with this exact structure:\n"
"{\n"
"  \"tool\": \"build_mongo_query\" | \"rag_search\",\n"
"  \"refined_query\": \"optimized query for the selected tool\",\n"
"  \"confidence\": 0.0-1.0,\n"
"  \"reason\": \"brief explanation of routing decision and query refinement\"\n"
"}\n\n"
"No additional text, markdown, or commentary allowed.")

class SmartFilterAgent:
    """Agent that combines RAG retrieval with MongoDB queries for intelligent work item filtering"""

    def __init__(self, max_steps: int = 2, system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT):
        self.llm = ChatGroq(
            model="openai/gpt-oss-120b",
            temperature=0.1,  # Slightly creative for query understanding
            max_tokens=1024,
            top_p=0.8,
        )
        self.connected = False
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        from qdrant.initializer import RAGTool
        from mongo.constants import QDRANT_COLLECTION_NAME
        self.rag_tool = RAGTool.get_instance()
        self.collection_name = QDRANT_COLLECTION_NAME
        self.retriever = SmartFilterTools(
            qdrant_client=self.rag_tool.qdrant_client,
            embedding_client=self.rag_tool.embedding_client
        )
        # Initialize RAG components
        self.orchestrator = Orchestrator(tracer_name="smart_filter_agent", max_parallel=3)
    
    async def smart_filter_work_items(self, query: str, project_id: str ,limit: int = 50) -> SmartFilterResult:
        """Route query to the appropriate retrieval path and normalize results."""

        normalized_query = (query or "").strip()
        if not normalized_query:
            raise ValueError("Query must be a non-empty string")

        await self.retriever.ensure_mongodb_connection()

        tool_choice, tool_query = await self._determine_tool(normalized_query)

        if tool_choice == "rag_search":
            rag_result = await self._handle_rag_flow(tool_query, project_id, limit)
            if rag_result.work_items:
                return rag_result

        return await self._handle_mongo_flow(tool_query, project_id, limit)

    async def _determine_tool(self, query: str) -> tuple[str, str]:
        """Use router model (with heuristics fallback) to choose execution path and get refined query."""

        try:
            messages = [
                SystemMessage(content=self.system_prompt or DEFAULT_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]
            ai_response = await self.llm.ainvoke(messages)
            content = self._clean_model_output(ai_response.content)
            if content:
                try:
                    data = json.loads(content)
                    tool = data.get("tool")
                    refined_query = data.get("refined_query", query)  # fallback to original query
                    if tool in ("build_mongo_query", "rag_search"):
                        return tool, refined_query
                except Exception:
                    pass
        except Exception:
            pass

    async def _handle_mongo_flow(self, query: str, project_id: str, limit: int) -> SmartFilterResult:
        mongo_result = await self.retriever.execute_mongo_query(query, project_id=project_id, limit=limit)
        formatted_items = self._format_work_items(mongo_result.work_items)

        metadata: Dict[str, Any] = {}
        if isinstance(mongo_result.raw_result, dict):
            metadata = {
                "pipeline": mongo_result.raw_result.get("pipeline"),
                "intent": mongo_result.raw_result.get("intent"),
                "planner": mongo_result.raw_result.get("planner"),
            }

        total = mongo_result.total_count or len(formatted_items)

        return SmartFilterResult(
            work_items=formatted_items,
            total_count=total,
            query=query,
            rag_context="",
            mongo_query=metadata,
        )

    async def _handle_rag_flow(self, query: str, project_id: str, limit: int) -> SmartFilterResult:
        rag_result = await self.retriever.execute_rag_search(query, project_id=project_id, limit=limit)

        priority = self._build_rag_identifier_priority(rag_result)
        object_id_pairs, display_ids = self._separate_identifiers(priority)

        if not object_id_pairs and not display_ids:
            return SmartFilterResult(
                work_items=[],
                total_count=0,
                query=query,
                rag_context=rag_result.rag_context,
                mongo_query={},
            )

        object_ids = [obj for _, obj in object_id_pairs]
        docs = await self._fetch_work_items_by_identifiers(object_ids, display_ids, limit)
        ordered_docs = self._order_documents_by_priority(docs, priority)
        formatted_items = self._format_work_items(ordered_docs)

        conditions: List[Dict[str, Any]] = []
        if object_ids:
            conditions.append({"_id": {"$in": object_ids}})
        if display_ids:
            conditions.append({"displayBugNo": {"$in": display_ids}})

        if len(conditions) == 1:
            mongo_filter = conditions[0]
        else:
            mongo_filter = {"$or": conditions}

        return SmartFilterResult(
            work_items=formatted_items,
            total_count=len(formatted_items),
            query=query,
            rag_context=rag_result.rag_context,
            mongo_query={
                "match": mongo_filter,
                "identifiers": priority,
            },
        )

    async def _fetch_work_items_by_identifiers(
        self,
        object_ids: List[ObjectId],
        display_bug_numbers: List[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        conditions: List[Dict[str, Any]] = []
        if object_ids:
            conditions.append({"_id": {"$in": object_ids}})
        if display_bug_numbers:
            conditions.append({"displayBugNo": {"$in": display_bug_numbers}})

        if not conditions:
            return []

        if len(conditions) == 1:
            match_stage = conditions[0]
        else:
            match_stage = {"$or": conditions}

        pipeline: List[Dict[str, Any]] = [{"$match": match_stage}, {"$sort": {"updatedTimeStamp": -1}}]
        if limit and limit > 0:
            pipeline.append({"$limit": int(limit)})

        results = await mongodb_tools.execute_tool(
            "aggregate",
            {
                "database": DATABASE_NAME,
                "collection": "workItem",
                "pipeline": pipeline,
            },
        )

        return results if isinstance(results, list) else []

    def _build_rag_identifier_priority(self, rag_result) -> List[str]:
        ordered: List[str] = []
        seen: Set[str] = set()

        for doc in rag_result.reconstructed_docs or []:
            candidates: List[str] = []
            if getattr(doc, "mongo_id", None):
                candidates.append(str(doc.mongo_id))
            if doc.metadata:
                for key in ["mongo_id", "work_item_id", "workItemId", "displayBugNo", "display_bug_no"]:
                    value = doc.metadata.get(key)
                    if isinstance(value, str):
                        candidates.append(value)
                    elif isinstance(value, list):
                        candidates.extend(v for v in value if isinstance(v, str))

            for candidate in candidates:
                cleaned = (candidate or "").strip()
                if cleaned and cleaned not in seen:
                    ordered.append(cleaned)
                    seen.add(cleaned)

        for identifier in rag_result.work_item_ids:
            cleaned = (identifier or "").strip()
            if cleaned and cleaned not in seen:
                ordered.append(cleaned)
                seen.add(cleaned)

        return ordered

    def _separate_identifiers(
        self,
        identifiers: List[str],
    ) -> Tuple[List[Tuple[str, ObjectId]], List[str]]:
        object_id_pairs: List[Tuple[str, ObjectId]] = []
        display_ids: List[str] = []
        seen: Set[str] = set()

        for identifier in identifiers:
            cleaned = (identifier or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)

            if self._is_object_id(cleaned):
                try:
                    object_id_pairs.append((cleaned, ObjectId(cleaned)))
                    continue
                except Exception:
                    pass

            display_ids.append(cleaned)

        return object_id_pairs, display_ids

    def _order_documents_by_priority(
        self,
        docs: List[Dict[str, Any]],
        priority_identifiers: List[str],
    ) -> List[Dict[str, Any]]:
        if not docs or not priority_identifiers:
            return docs

        index: Dict[str, int] = {identifier: idx for idx, identifier in enumerate(priority_identifiers)}

        def sort_key(doc: Dict[str, Any]) -> Tuple[int, str]:
            candidates = self._doc_identifier_candidates(doc)
            for candidate in candidates:
                if candidate in index:
                    return (index[candidate], candidate)
            return (len(priority_identifiers), candidates[0] if candidates else "")

        return sorted(docs, key=sort_key)

    def _doc_identifier_candidates(self, doc: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        raw_id = doc.get("_id") or doc.get("id")
        if raw_id is not None:
            id_str = self._stringify_id(raw_id)
            if id_str:
                candidates.append(id_str)

        display_bug = doc.get("displayBugNo") or doc.get("bugNo")
        if isinstance(display_bug, str) and display_bug.strip():
            candidates.append(display_bug.strip())

        return candidates

    def _format_work_items(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for item in raw_items or []:
            if isinstance(item, dict):
                formatted.append(self._format_single_work_item(item))
        return formatted

    def _format_single_work_item(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        state_doc = doc.get("state") or {}
        state = {
            "id": self._stringify_id(state_doc.get("id") or state_doc.get("_id")) or "",
            "name": state_doc.get("name")
                or doc.get("stateName")
                or doc.get("status")
                or "",
        }

        state_master_doc = doc.get("stateMaster") or {}
        state_master = {
            "id": self._stringify_id(state_master_doc.get("id") or state_master_doc.get("_id")) or "",
            "name": state_master_doc.get("name") or "",
        }

        formatted = {
            "title": doc.get("title") or doc.get("name") or "",
            "description": doc.get("description"),
            "startDate": self._serialize_datetime(doc.get("startDate")),
            "endDate": self._serialize_datetime(doc.get("endDate")),
            "releaseDate": self._serialize_datetime(doc.get("releaseDate")),
            "stateMaster": state_master,
            "state": state,
            "business": self._format_reference(doc.get("business")),
            "lead": self._format_reference(doc.get("lead")),
            "priority": doc.get("priority") or "",
            "assignee": self._format_assignees(doc.get("assignee")),
            "label": self._format_labels(doc.get("label")),
            "cycle": self._format_reference(doc.get("cycle"), include_title=True),
            "modules": self._format_reference(doc.get("modules")),
            "parent": self._format_reference(doc.get("parent")),
            "workLogs": doc.get("workLogs") if isinstance(doc.get("workLogs"), list) else None,
            "estimateSystem": doc.get("estimateSystem"),
            "estimate": doc.get("estimate"),
            "id": self._stringify_id(doc.get("_id") or doc.get("id")) or "",
            "project": self._format_reference(doc.get("project")),
            "view": doc.get("view"),
            "displayBugNo": doc.get("displayBugNo") or doc.get("bugNo") or "",
            "status": doc.get("status") or "ACCEPTED",  # Default to ACCEPTED if not provided
            "createdBy": self._format_reference(doc.get("createdBy")),
            "updatedBy": self._format_reference(doc.get("updatedBy")),
            "attachmentUrl": doc.get("attachmentUrl"),
            "link": doc.get("link"),
            "userStory": doc.get("userStory"),
            "feature": doc.get("feature"),
            "epic": doc.get("epic"),
            "createdTimeStamp": self._serialize_datetime(doc.get("createdTimeStamp")) or self._serialize_datetime(doc.get("createdOn")),
            "updatedTimeStamp": self._serialize_datetime(doc.get("updatedTimeStamp")) or self._serialize_datetime(doc.get("updatedOn")),
            "subWorkItems": doc.get("subWorkItems") if isinstance(doc.get("subWorkItems"), list) else None,
            "timeline": doc.get("timeline") if isinstance(doc.get("timeline"), list) else None,
        }

        return formatted

    def _format_assignees(self, value: Any) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        data = value
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return result

        for entry in data:
            if isinstance(entry, dict):
                assignee_id = self._stringify_id(entry.get("id") or entry.get("_id")) or ""
                name = entry.get("name") or entry.get("title") or ""
                if name:
                    result.append({"id": assignee_id, "name": name})
            elif isinstance(entry, str) and entry.strip():
                result.append({"id": "", "name": entry.strip()})

        return result

    def _format_labels(self, value: Any) -> List[Dict[str, Optional[str]]]:
        result: List[Dict[str, Optional[str]]] = []
        data = value
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return result

        for entry in data:
            if isinstance(entry, dict):
                label_id = self._stringify_id(entry.get("id") or entry.get("_id")) or ""
                name = entry.get("name") or entry.get("title") or ""
                color = entry.get("color")
                if name:
                    result.append({"id": label_id, "name": name, "color": color})

        return result

    def _format_reference(self, value: Any, include_title: bool = False) -> Optional[Dict[str, Any]]:
        ref = value
        if isinstance(ref, list):
            ref = ref[0] if ref else None
        if not isinstance(ref, dict):
            return None

        ref_id = self._stringify_id(ref.get("id") or ref.get("_id")) or ""
        ref_name = ref.get("name") or ref.get("title") or ""

        if not ref_id and not ref_name:
            return None

        payload: Dict[str, Any] = {"id": ref_id, "name": ref_name}
        if include_title:
            title_val = ref.get("title")
            if title_val:
                payload["title"] = title_val

        return payload

    def _serialize_datetime(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            try:
                return value.isoformat()
            except Exception:
                return value.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(value, (int, float)):
            try:
                numeric = value / 1000.0 if value > 1e12 else value
                return datetime.fromtimestamp(numeric).isoformat()
            except Exception:
                return str(value)
        if isinstance(value, dict) and "$date" in value:
            return str(value["$date"])
        if isinstance(value, str):
            return value
        return str(value)

    def _stringify_id(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, Binary):
            try:
                return str(value.as_uuid())
            except Exception:
                try:
                    return value.hex()
                except Exception:
                    return str(value)
        return str(value)

    def _clean_model_output(self, content: Optional[str]) -> str:
        if not content:
            return ""
        text = content.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
        if text.startswith("```"):
            stripped = text.strip("`\n")
            if stripped.startswith("json\n"):
                stripped = stripped[5:]
            text = stripped
        return text.strip()

    def _is_object_id(self, candidate: str) -> bool:
        if not candidate or len(candidate) != 24:
            return False
        try:
            int(candidate, 16)
            return True
        except Exception:
            return False

# Global instance - initialized lazily during startup
smart_filter_agent = None
