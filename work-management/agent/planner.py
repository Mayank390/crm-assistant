#!/usr/bin/env python3
"""
Intelligent Query Planner for PMS System
Handles natural language queries and generates optimal MongoDB aggregation pipelines
based on the relationship registry
"""

import json
import re
from time import perf_counter
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.pipeline import PipelineGenerator
    from agent.intent import LLMIntentParser
import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from mongo.constants import mongodb_tools, DATABASE_NAME
from agent.orchestrator import Orchestrator, StepSpec, as_async


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
    target_entities: List[str]  # Related entities to include
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
    # Advanced aggregation fields
    facet_fields: Optional[List[str]] = None  # Fields for $facet operation
    bucket_field: Optional[str] = None  # Field for $bucketAuto operation
    union_collection: Optional[str] = None  # Collection for $unionWith
    graph_from: Optional[str] = None  # From collection for $graphLookup
    graph_start: Optional[str] = None  # Start expression for $graphLookup
    graph_connect_from: Optional[str] = None  # Connect from field for $graphLookup
    graph_connect_to: Optional[str] = None  # Connect to field for $graphLookup
    # Time-series analysis fields
    window_field: Optional[str] = None  # Field for time window operations
    window_size: Optional[str] = None  # Size of sliding window (e.g., "7d", "30d")
    window_unit: Optional[str] = None  # Unit for window (day, week, month)
    trend_field: Optional[str] = None  # Field for trend analysis
    trend_period: Optional[str] = None  # Period for trend (week, month, quarter)
    trend_metric: Optional[str] = None  # Metric to trend (count, sum, avg)
    anomaly_field: Optional[str] = None  # Field for anomaly detection
    anomaly_metric: Optional[str] = None  # Metric for anomaly detection
    anomaly_threshold: Optional[float] = None  # Standard deviation threshold
    forecast_field: Optional[str] = None  # Field for forecasting
    forecast_periods: Optional[int] = None  # Number of periods to forecast

@dataclass
class RelationshipPath:
    """Represents a traversal path through relationships"""
    start_collection: str
    end_collection: str
    path: List[str]  # List of relationship names
    cost: int  # Computational cost of this path
    filters: Dict[str, Any]  # Filters that can be applied at each step


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

class Planner:
    """Main query planner that orchestrates the entire process"""

    def __init__(self):
        from agent.pipeline import PipelineGenerator
        from agent.intent import LLMIntentParser
        self.generator = PipelineGenerator()
        self.llm_parser = LLMIntentParser()
        self.orchestrator = Orchestrator(tracer_name=__name__, max_parallel=5)

    async def plan_and_execute(self, query: str) -> Dict[str, Any]:
        """Plan and execute a natural language query using the Orchestrator."""
        planner_start_time = perf_counter()
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
                }
                return await mongodb_tools.execute_tool("aggregate", args)

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
            elapsed_ms = (perf_counter() - planner_start_time) * 1000
            print(f"Planner.plan_and_execute for '{query[:50]}...' took {elapsed_ms:.2f} ms")
            return {
                "success": True,
                "intent": intent.__dict__,
                "pipeline": _serialize_pipeline_for_json(pipeline),
                "pipeline_js": _format_pipeline_for_display(pipeline),
                "result": result,
                "planner": "llm",
            }
        except Exception as e:
            elapsed_ms = (perf_counter() - planner_start_time) * 1000
            print(f"Planner.plan_and_execute for '{query[:50]}...' failed in {elapsed_ms:.2f} ms: {e}")
            pass
            return {
                "success": False,
                "error": str(e),
                "query": query,
            }

# Global instance
query_planner = Planner()

async def plan_and_execute_query(query: str) -> Dict[str, Any]:
    """Convenience function to plan and execute queries"""
    return await query_planner.plan_and_execute(query)
