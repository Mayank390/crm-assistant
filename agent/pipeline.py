import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

from mongo.registry import REL, ALLOWED_FIELDS, build_lookup_stage
from agent.planner import QueryIntent

class PipelineGenerator:
    """Generates MongoDB aggregation pipelines based on query intent and relationships"""

    def __init__(self):
        self.relationship_cache = {}  # Cache for computed relationship paths

    def _add_comprehensive_lookups(self, pipeline: List[Dict[str, Any]], collection: str, intent: QueryIntent, required_relations: Set[str]):
        """Add strategic lookups only for relationships that provide clear query benefits"""
        # Only add strategic relationships that are likely to improve query performance
        # without adding unnecessary complexity for simple queries

        strategic_relations = {
            'Lead': {
                # Add related entities when needed for complex queries
                'task': len(intent.group_by or []) > 1 or intent.wants_details,
                'activity': len(intent.group_by or []) > 1 or intent.wants_details,
                'meeting': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'Task': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
            'Activity': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
            'Meeting': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
            'Notes': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
            'CallLog': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
            'MailInfo': {
                # Add lead lookup when needed
                'lead': 'lead' in (intent.group_by or []) or 'leadName' in (intent.filters or {}),
            },
        }

        # Get the strategic relations for this collection
        relations_to_add = strategic_relations.get(collection, {})

        # Only add relations that are actually beneficial for this specific query
        for relation_name, should_add in relations_to_add.items():
            if should_add and relation_name in REL.get(collection, {}):
                # Only add if this relationship isn't already required but would be beneficial
                if relation_name not in required_relations:
                    required_relations.add(relation_name)

    def _needs_multi_hop_context(self, intent: QueryIntent, context_fields: List[str]) -> bool:
        """Check if the query needs multi-hop context for the given fields"""
        # Check if any context fields are referenced in group_by or filters
        for field in context_fields:
            if field in (intent.group_by or []) or f'{field}_name' in (intent.filters or {}):
                return True
        return False

    def _should_use_strategic_joins(self, intent: QueryIntent, required_relations: Set[str]) -> bool:
        """Automatically determine if strategic joins would benefit this query"""
        # Use strategic joins if:
        # 1. Query has multiple group_by fields (complex analysis)
        # 2. Query needs multi-hop context (business, cycle, module context)
        # 3. Query filters by fields that require joins
        # 4. Query requests details (indicating complex data needs)

        # Check for multi-hop context needs
        needs_multi_hop = (
            self._needs_multi_hop_context(intent, ['lead', 'task', 'activity']) or
            'lead' in (intent.group_by or []) or
            'leadName' in (intent.filters or {})
        )

        # Check for complex grouping
        has_complex_grouping = len(intent.group_by or []) > 1

        # Check for detail requests
        wants_details = intent.wants_details

        # Check if already has required relations (don't need strategic joins if relations already identified)
        has_basic_relations = len(required_relations) > 0

        # Use strategic joins if any of these conditions are met
        return needs_multi_hop or has_complex_grouping or (wants_details and has_basic_relations)

    def generate_pipeline(self, intent: QueryIntent) -> List[Dict[str, Any]]:
        """Generate MongoDB aggregation pipeline for the given intent"""
        pipeline: List[Dict[str, Any]] = []

        # Start with the primary collection
        collection = intent.primary_entity

        # Build sanitized filters once
        primary_filters = self._extract_primary_filters(intent.filters, collection) if intent.filters else {}
        secondary_filters = self._extract_secondary_filters(intent.filters, collection) if intent.filters else {}

        # COUNT-ONLY: no group_by, no details → do not add lookups
        if (("count" in intent.aggregations) or intent.wants_count) and not intent.group_by and not intent.wants_details:
            # Combine all filters for optimal count query
            all_filters = {}
            if primary_filters:
                all_filters.update(primary_filters)
            if secondary_filters:
                all_filters.update(secondary_filters)

            if all_filters:
                return [{"$match": all_filters}, {"$count": "total"}]
            else:
                return [{"$count": "total"}]

        # Add filters for the primary collection
        if primary_filters:
            pipeline.append({"$match": primary_filters})

        # Ensure lookups needed by secondary filters or grouping are included
        required_relations: Set[str] = set()

        # Determine relation tokens per primary collection
        relation_alias_by_token = {
            'Lead': {
                'task': 'task',
                'activity': 'activity',
                'meeting': 'meeting',
                'notes': 'notes',
                'callLog': 'callLog',
                'mailInfo': 'mailInfo',
            },
            'Task': {
                'lead': 'lead',
            },
            'Activity': {
                'lead': 'lead',
                'task': 'task',
            },
            'Meeting': {
                'lead': 'lead',
            },
            'Notes': {
                'lead': 'lead',
            },
            'CallLog': {
                'lead': 'lead',
            },
            'MailInfo': {
                'lead': 'lead',
            },
        }.get(collection, {})

        # Include explicit target entities requested by the intent (supports multi-hop like "project.cycles")
        for rel in (intent.target_entities or []):
            if not isinstance(rel, str) or not rel:
                continue
            first_hop = rel.split(".")[0]
            if first_hop in REL.get(collection, {}):
                required_relations.add(rel)

        # Filters → relations (map filter tokens to relation alias for this primary)
        if intent.filters:
            # CRM-specific filter to relation mappings
            if 'lead_name' in intent.filters and relation_alias_by_token.get('lead') in REL.get(collection, {}):
                required_relations.add(relation_alias_by_token['lead'])
            if 'leadId' in intent.filters and relation_alias_by_token.get('lead') in REL.get(collection, {}):
                required_relations.add(relation_alias_by_token['lead'])
            if 'assignedName' in intent.filters or 'assignedTo' in intent.filters:
                # Assigned person filters don't require joins in CRM (usually embedded)
                pass
            if 'createdByName' in intent.filters or 'createdById' in intent.filters:
                # Creator filters don't require joins in CRM (usually embedded)
                pass

        # Group-by → relations
        for token in (intent.group_by or []):
            # Map grouping token to relation alias for this primary
            rel_alias = relation_alias_by_token.get(token)
            if rel_alias and rel_alias in REL.get(collection, {}):
                required_relations.add(rel_alias)

        # Automatically add strategic lookups when they provide clear benefits for this query
        # Complex joins are now fully automatic based on query requirements
        if self._should_use_strategic_joins(intent, required_relations):
            self._add_comprehensive_lookups(pipeline, collection, intent, required_relations)

        # Add relationship lookups (supports multi-hop via dot syntax like project.states)
        for target_entity in sorted(required_relations):
            # Allow multi-hop relation names like "project.cycles"
            hops = target_entity.split(".")
            current_collection = collection
            local_prefix = None
            for hop in hops:
                if hop not in REL.get(current_collection, {}):
                    break
                relationship = REL[current_collection][hop]

                # SAFETY: avoid writing a lookup into an existing scalar field name
                # CRM collections don't have the same alias conflicts as work-management
                needs_alias_fix = False
                if needs_alias_fix:
                    # Force a safe alias to prevent clobbering embedded field
                    relationship = {**relationship, "as": f"{relationship.get('target')}Doc"}
                lookup = build_lookup_stage(relationship["target"], relationship, current_collection, local_field_prefix=local_prefix)
                if lookup:
                    pipeline.append(lookup)
                    # If array relation, unwind the alias used in $lookup
                    is_many = bool(relationship.get("isArray") or relationship.get("many", False))
                    alias_name = relationship.get("as") or relationship.get("alias") or relationship.get("target")
                    if is_many:
                        pipeline.append({
                            "$unwind": {"path": f"${alias_name}", "preserveNullAndEmptyArrays": True}
                        })
                    # Set local prefix to the alias for chaining next hop
                    local_prefix = alias_name
                current_collection = relationship["target"]

        # Add secondary filters (on joined collections) BEFORE normalizing fields
        if secondary_filters:
            pipeline.append({"$match": secondary_filters})

        # Normalize lead fields to scalars for safe filtering/printing (if needed)
        # CRM collections typically don't need this normalization, but keeping structure for future use


        # Add grouping if requested
        if intent.group_by:
            # Pre-group unwind for embedded arrays that are used as grouping keys
            # For CRM, unwind participantsList for meetings if grouping by participants
            if intent.primary_entity == 'Meeting' and 'participantsList' in intent.group_by:
                pipeline.append({
                    "$unwind": {"path": "$participantsList", "preserveNullAndEmptyArrays": True}
                })
            group_id_expr: Any
            id_fields: Dict[str, Any] = {}
            for token in intent.group_by:
                resolved = self._resolve_group_field(intent.primary_entity, token)
                if resolved:
                    # Accept either a field path (str) or a full expression (dict)
                    if isinstance(resolved, str):
                        id_fields[token] = f"${resolved}"
                    else:
                        id_fields[token] = resolved
            if not id_fields:
                # Fallback: if we can't resolve, try using the token directly as field name
                # This handles cases where the token matches a field name directly
                for token in intent.group_by:
                    # Try the token as-is (might be a direct field name)
                    if token in ALLOWED_FIELDS.get(intent.primary_entity, set()):
                        id_fields[token] = f"${token}"
                    # Also try common field name variations
                    elif intent.primary_entity == 'Lead' and token == 'status':
                        # Map generic 'status' to 'status' field for Lead
                        id_fields[token] = "$status"
                    elif intent.primary_entity == 'Lead' and token in ['leadStatus', 'lead_status']:
                        id_fields[token] = "$leadStatus"
                    elif intent.primary_entity == 'Task' and token in ['taskStatus', 'task_status']:
                        id_fields[token] = "$taskStatus"
                    elif intent.primary_entity == 'Meeting' and token in ['meetingStatus', 'meeting_status']:
                        id_fields[token] = "$meetingStatus"
                    elif intent.primary_entity == 'Activity' and token in ['activityStatus', 'activity_status']:
                        id_fields[token] = "$activityStatus"
                    elif intent.primary_entity == 'CallLog' and token in ['callStatus', 'call_status']:
                        id_fields[token] = "$callStatus"
            
            if not id_fields:
                # Still no fields resolved - log warning but continue
                logger.warning(f"Could not resolve group_by tokens {intent.group_by} for entity {intent.primary_entity}")
            else:
                group_id_expr = list(id_fields.values())[0] if len(id_fields) == 1 else id_fields

                # Special handling: for timeline TIME_LOGGED breakdowns, sum parsed minutes from newValue
                is_timeline_time_logged = (
                    intent.primary_entity == 'timeline' and (
                        isinstance(intent.filters.get('type'), str) and 'time_logged' in str(intent.filters.get('type')).lower()
                    )
                )
                if is_timeline_time_logged:
                    # Compute parsed minutes from strings like "1 hr 30 min", "45 min", "2 hr"
                    pipeline.append({
                        "$addFields": {
                            "_parsedMinutes": {
                                "$let": {
                                    "vars": {
                                        "h": {"$regexFind": {"input": "$newValue", "regex": "([0-9]+)\\s*(?:h|hr|hrs|hour|hours)"}},
                                        "m": {"$regexFind": {"input": "$newValue", "regex": "([0-9]+)\\s*(?:m|min|mins|minute|minutes)"}}
                                    },
                                    "in": {
                                        "$add": [
                                            {"$multiply": [
                                                {"$toInt": {"$ifNull": [{"$arrayElemAt": ["$$h.captures", 0]}, 0]}}, 60
                                            ]},
                                            {"$toInt": {"$ifNull": [{"$arrayElemAt": ["$$m.captures", 0]}, 0]}}
                                        ]
                                    }
                                }
                            }
                        }
                    })
                    group_stage: Dict[str, Any] = {
                        "$group": {
                            "_id": group_id_expr,
                            "totalMinutes": {"$sum": "$__parsedMinutes__"}  # placeholder to be replaced
                        }
                    }
                    # Replace placeholder key with the actual parsed minutes field name
                    group_stage["$group"]["totalMinutes"] = {"$sum": "$_parsedMinutes"}
                else:
                    group_stage: Dict[str, Any] = {
                        "$group": {
                            "_id": group_id_expr,
                            "count": {"$sum": 1},
                        }
                    }
                if intent.wants_details:
                    group_stage["$group"]["items"] = {
                        "$push": {
                            "_id": "$_id",
                            "displayBugNo": "$displayBugNo",
                            "title": "$title",
                            "priority": "$priority",
                            "estimate": "$estimate",
                            "estimateSystem": "$estimateSystem",
                            "workLogs": "$workLogs",
                        }
                    }
                pipeline.append(group_stage)
                # Sorting for grouped results: default to metric desc (count or totalMinutes), allow sorting by grouped keys
                if intent.sort_order:
                    sort_key, sort_dir = next(iter(intent.sort_order.items()))
                    if sort_key in intent.group_by:
                        # Sort by the grouped key inside _id
                        if len(id_fields) == 1:
                            pipeline.append({"$sort": {"_id": sort_dir}})
                        else:
                            pipeline.append({"$sort": {f"_id.{sort_key}": sort_dir}})
                    else:
                        # Default to the primary metric
                        if intent.primary_entity == 'timeline' and ('work_item_title' in (intent.group_by or [])) and is_timeline_time_logged:
                            pipeline.append({"$sort": {"totalMinutes": -1}})
                        else:
                            pipeline.append({"$sort": {"count": -1}})
                else:
                    if intent.primary_entity == 'timeline' and ('work_item_title' in (intent.group_by or [])) and is_timeline_time_logged:
                        pipeline.append({"$sort": {"totalMinutes": -1}})
                    else:
                        pipeline.append({"$sort": {"count": -1}})
                # Present a tidy shape
                project_shape: Dict[str, Any] = {"count": 1}
                if intent.wants_details:
                    project_shape["items"] = 1
                project_shape["group"] = "$_id"
                # Expose totalMinutes when computed
                if intent.primary_entity == 'timeline' and ('work_item_title' in (intent.group_by or [])) and is_timeline_time_logged:
                    project_shape["totalMinutes"] = 1
                pipeline.append({"$project": project_shape})
                # Note: Limit is now handled globally at the end of the pipeline

        # Add aggregations like count (skip count when details are requested)
        if intent.aggregations and not intent.wants_details and not intent.group_by:
            for agg in intent.aggregations:
                if agg == 'count':
                    pipeline.append({"$count": "total"})
                    return pipeline  # Count is terminal

        # Determine projections for details (skip when grouping since we reshape after $group)
        effective_projections: List[str] = intent.projections
        if intent.wants_details and not intent.group_by and not effective_projections:
            effective_projections = self._get_default_projections(intent.primary_entity)

        # Add sorting (handle custom priority order) — skip if already grouped
        added_priority_rank = False
        if intent.sort_order and not intent.group_by:
            if 'priority' in intent.sort_order:
                # Only compute rank if priority is part of projections to avoid surprising invisible sorts
                if (effective_projections and 'priority' in effective_projections) or (not effective_projections):
                    added_priority_rank = True
                    pipeline.append({
                        "$addFields": {
                            "_priorityRank": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq": ["$priority", "NEW"]}, "then": 4},
                                        {"case": {"$eq": ["$priority", "HIGH"]}, "then": 3},
                                        {"case": {"$eq": ["$priority", "MEDIUM"]}, "then": 2},
                                        {"case": {"$eq": ["$priority", "LOW"]}, "then": 1}
                                    ],
                                    "default": 0
                                }
                            }
                        }
                    })
                    # Use computed rank for sorting direction provided
                    direction = intent.sort_order.get('priority', -1)
                    pipeline.append({"$sort": {"_priorityRank": direction}})
                else:
                    pipeline.append({"$sort": intent.sort_order})
            elif 'state' in intent.sort_order and collection == 'workItem':
                # Sort by state via embedded state.name.
                pipeline.append({"$sort": {"state.name": intent.sort_order.get('state', 1)}})
            else:
                pipeline.append({"$sort": intent.sort_order})

        # Compute projected aliases for joined relations so projections include them when needed
        projected_aliases: Set[str] = set()
        if required_relations:
            for rel_path in sorted(required_relations):
                hops = rel_path.split(".")
                current_collection = collection
                for hop in hops:
                    if hop not in REL.get(current_collection, {}):
                        break
                    relationship = REL[current_collection][hop]
                    alias_name = relationship.get("as") or relationship.get("alias") or relationship.get("target")
                    if alias_name:
                        projected_aliases.add(alias_name)
                    current_collection = relationship["target"]

        # Add projections after sorting so computed fields can be hidden
        if effective_projections and not intent.group_by:
            projection = self._generate_projection(effective_projections, sorted(list(projected_aliases)), intent.primary_entity)
            # Ensure we exclude helper fields from output
            pipeline.append({"$project": projection})
        # Always remove priority rank helper if it was added
        if added_priority_rank:
            pipeline.append({"$unset": "_priorityRank"})

        # Add time-series analysis stages (can be combined, so use separate if statements)
        # NOTE: Pagination is added AFTER all aggregation/grouping stages (see end of function)
        if intent.aggregations:
            # Time window aggregations ($setWindowFields)
            # Support multiple aggregation name variations
            has_time_window = (
                "timeWindow" in intent.aggregations or 
                "timewindow" in [a.lower() for a in intent.aggregations] or
                "rolling" in [a.lower() for a in intent.aggregations] or
                "moving" in [a.lower() for a in intent.aggregations]
            )
            if has_time_window and intent.window_field and intent.window_size:
                # Parse window size (supports "7d", "30d", "14", etc.)
                window_size_str = str(intent.window_size).strip().lower()
                window_days = 7  # default
                try:
                    if window_size_str.endswith('d'):
                        window_days = int(window_size_str.rstrip('d'))
                    elif window_size_str.isdigit():
                        window_days = int(window_size_str)
                    else:
                        # Try to extract number
                        import re
                        match = re.search(r'(\d+)', window_size_str)
                        if match:
                            window_days = int(match.group(1))
                except (ValueError, AttributeError):
                    window_days = 7  # fallback to default
                
                # Determine what to aggregate (count for creation rates, or the field itself)
                # For date fields, we want to count occurrences per day
                is_date_field = 'date' in intent.window_field.lower() or 'timestamp' in intent.window_field.lower() or 'created' in intent.window_field.lower() or 'updated' in intent.window_field.lower()
                
                if is_date_field:
                    # For date fields, group by day first, then calculate rolling average of counts
                    pipeline.append({
                        "$group": {
                            "_id": {
                                "$dateTrunc": {
                                    "date": f"${intent.window_field}",
                                    "unit": "day"
                                }
                            },
                            "count": {"$sum": 1}
                        }
                    })
                    pipeline.append({"$sort": {"_id": 1}})
                    window_stage = {
                        "$setWindowFields": {
                            "sortBy": {"_id": 1},
                            "output": {
                                "rollingAvg": {
                                    "$avg": "$count",
                                    "window": {
                                        "range": [-window_days, "current"]
                                    }
                                },
                                "rollingSum": {
                                    "$sum": "$count",
                                    "window": {
                                        "range": [-window_days, "current"]
                                    }
                                }
                            }
                        }
                    }
                else:
                    # For numeric fields, calculate rolling average directly
                    window_stage = {
                        "$setWindowFields": {
                            "sortBy": {intent.window_field: 1},
                            "output": {
                                "rollingAvg": {
                                    "$avg": f"${intent.window_field}",
                                    "window": {
                                        "range": [-window_days, "current"]
                                    }
                                }
                            }
                        }
                    }
                pipeline.append(window_stage)

            # Trend analysis - period over period comparison
            # Support multiple aggregation name variations
            has_trend = (
                "trend" in [a.lower() for a in intent.aggregations] or
                "trends" in [a.lower() for a in intent.aggregations]
            )
            if has_trend and intent.trend_field and intent.trend_period:
                # Group by time periods and calculate metrics
                period_group = {}
                trend_period = str(intent.trend_period).lower()
                if trend_period == "week" or trend_period == "weekly":
                    period_group = {"$dateTrunc": {"date": f"${intent.trend_field}", "unit": "week"}}
                elif trend_period == "month" or trend_period == "monthly":
                    period_group = {"$dateTrunc": {"date": f"${intent.trend_field}", "unit": "month"}}
                elif trend_period == "quarter" or trend_period == "quarterly":
                    period_group = {"$dateTrunc": {"date": f"${intent.trend_field}", "unit": "quarter"}}
                elif trend_period == "day" or trend_period == "daily":
                    period_group = {"$dateTrunc": {"date": f"${intent.trend_field}", "unit": "day"}}
                else:
                    # Default to month
                    period_group = {"$dateTrunc": {"date": f"${intent.trend_field}", "unit": "month"}}

                trend_stage = {
                    "$group": {
                        "_id": period_group,
                        "count": {"$sum": 1},
                        "period": {"$first": period_group}
                    }
                }
                pipeline.append(trend_stage)
                pipeline.append({"$sort": {"_id": 1}})

            # Anomaly detection using statistical methods
            # Support multiple aggregation name variations
            has_anomaly = (
                "anomaly" in [a.lower() for a in intent.aggregations] or
                "anomalies" in [a.lower() for a in intent.aggregations] or
                "outlier" in [a.lower() for a in intent.aggregations] or
                "unusual" in [a.lower() for a in intent.aggregations]
            )
            if has_anomaly and intent.anomaly_field:
                # For date fields (like creation rates), first group by day to get counts
                anomaly_field = intent.anomaly_field
                is_date_field = 'date' in anomaly_field.lower() or 'timestamp' in anomaly_field.lower() or 'created' in anomaly_field.lower()
                
                if is_date_field:
                    # Group by day first to get daily counts
                    pipeline.append({
                        "$group": {
                            "_id": {
                                "$dateTrunc": {
                                    "date": f"${anomaly_field}",
                                    "unit": "day"
                                }
                            },
                            "count": {"$sum": 1}
                        }
                    })
                    pipeline.append({"$sort": {"_id": 1}})
                    # Then calculate stats on counts
                    stats_field = "$count"
                else:
                    # For numeric fields, use directly
                    stats_field = f"${anomaly_field}"
                
                # Use default threshold if not provided
                threshold = intent.anomaly_threshold if intent.anomaly_threshold is not None else 2.0
                
                # Calculate mean and standard deviation across all values
                # First, collect all values with their original documents
                stats_stage = {
                    "$group": {
                        "_id": None,
                        "avg": {"$avg": stats_field},
                        "std": {"$stdDevSamp": stats_field},
                        "values": {"$push": {"value": stats_field, "doc": "$$ROOT"}}
                    }
                }
                pipeline.append(stats_stage)

                # Flag anomalies based on threshold (values that deviate more than threshold * std from mean)
                anomaly_stage = {
                    "$project": {
                        "anomalies": {
                            "$filter": {
                                "input": "$values",
                                "as": "item",
                                "cond": {
                                    "$and": [
                                        # Check if std is valid (not null/zero)
                                        {"$gt": ["$std", 0]},
                                        # Check if deviation exceeds threshold
                                        {
                                            "$gt": [
                                                {"$abs": {"$subtract": ["$$item.value", "$avg"]}},
                                                {"$multiply": ["$std", threshold]}
                                            ]
                                        }
                                    ]
                                }
                            }
                        },
                        "avg": 1,
                        "std": 1,
                        "threshold": threshold,
                        "total_values": {"$size": "$values"}
                    }
                }
                pipeline.append(anomaly_stage)

            # Simple forecasting using linear trend
            # Support multiple aggregation name variations
            has_forecast = (
                "forecast" in [a.lower() for a in intent.aggregations] or
                "predict" in [a.lower() for a in intent.aggregations] or
                "projection" in [a.lower() for a in intent.aggregations]
            )
            if has_forecast and intent.forecast_field and intent.forecast_periods:
                # Calculate trend line and project forward
                forecast_periods = int(intent.forecast_periods) if intent.forecast_periods else 7
                
                # Group by day to get historical counts
                forecast_stage = {
                    "$group": {
                        "_id": {
                            "$dateTrunc": {
                                "date": f"${intent.forecast_field}",
                                "unit": "day"
                            }
                        },
                        "count": {"$sum": 1}
                    }
                }
                pipeline.append(forecast_stage)
                pipeline.append({"$sort": {"_id": 1}})

                # Calculate linear regression coefficients
                pipeline.append({
                    "$setWindowFields": {
                        "sortBy": {"_id": 1},
                        "output": {
                            "linreg": {
                                "$linreg": {
                                    "x": {"$toLong": "$_id"},
                                    "y": "$count"
                                }
                            }
                        }
                    }
                })
                
                # Get the last document with regression coefficients
                pipeline.append({
                    "$group": {
                        "_id": None,
                        "last_date": {"$last": "$_id"},
                        "last_count": {"$last": "$count"},
                        "slope": {"$last": "$linreg.slope"},
                        "intercept": {"$last": "$linreg.intercept"},
                        "historical": {"$push": {"date": "$_id", "count": "$count"}}
                    }
                })
                
                # Generate forecasted periods
                # Note: This is a simplified forecast. For production, consider using more sophisticated methods
                pipeline.append({
                    "$project": {
                        "historical": 1,
                        "forecast": {
                            "$map": {
                                "input": {"$range": [1, forecast_periods + 1]},
                                "as": "day",
                                "in": {
                                    "date": {
                                        "$add": [
                                            "$last_date",
                                            {"$multiply": ["$$day", 86400000]}  # Add days in milliseconds
                                        ]
                                    },
                                    "predicted_count": {
                                        "$add": [
                                            "$intercept",
                                            {
                                                "$multiply": [
                                                    "$slope",
                                                    {"$add": [
                                                        {"$toLong": "$last_date"},
                                                        {"$multiply": ["$$day", 86400000]}
                                                    ]}
                                                ]
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                        "slope": 1,
                        "intercept": 1
                    }
                })
        
        # Add pagination: skip then limit (apply AFTER all aggregation/grouping stages)
        # This ensures pagination works correctly for grouped/aggregated queries
        # For count queries, pagination is not needed (they return early)
        if intent.skip is not None:
            try:
                skip_value = int(intent.skip)
                if skip_value > 0:
                    pipeline.append({"$skip": skip_value})
            except (ValueError, TypeError):
                # Skip invalid skip values silently
                pass

        effective_limit = 1 if intent.fetch_one else (intent.limit or None)
        if effective_limit:
            try:
                pipeline.append({"$limit": int(effective_limit)})
            except Exception:
                pass
        
        print("The generated pipeline is:",pipeline)
        return pipeline

    def _extract_primary_filters(self, filters: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Extract filters that apply to the primary collection"""
        primary_filters = {}

        # Handle None or invalid filters
        if filters is None:
            return primary_filters
        if not isinstance(filters, dict):
            return primary_filters

        # Handle direct _id filters first using $expr with $toObjectId for safety
        def _is_hex24(s: str) -> bool:
            try:
                return isinstance(s, str) and len(s) == 24 and all(c in '0123456789abcdefABCDEF' for c in s)
            except Exception:
                return False

        if "_id" in filters:
            val = filters.get("_id")
            if isinstance(val, str) and _is_hex24(val):
                primary_filters["$expr"] = {"$eq": ["$_id", {"$toObjectId": val}]}
            elif isinstance(val, list):
                ids = [v for v in val if isinstance(v, str) and _is_hex24(v)]
                if ids:
                    primary_filters["$expr"] = {
                        "$in": [
                            "$_id",
                            {"$map": {"input": ids, "as": "id", "in": {"$toObjectId": "$$id"}}}
                        ]
                    }

        def _apply_numeric_range(target: Dict[str, Any], field: str, f: Dict[str, Any]):
            """Apply numeric range filters (e.g., score_from, score_to)."""
            from mongo.registry import resolve_field_alias
            resolved_field = resolve_field_alias(collection, field)
            
            gte_key = f"{field}_from"
            lte_key = f"{field}_to"
            range_expr: Dict[str, Any] = {}
            if gte_key in f:
                range_expr["$gte"] = float(f[gte_key])
            if lte_key in f:
                range_expr["$lte"] = float(f[lte_key])
            if range_expr:
                target[resolved_field] = range_expr

        def _apply_date_range(target: Dict[str, Any], field: str, f: Dict[str, Any]):
            # Resolve field aliases first
            from mongo.registry import resolve_field_alias
            resolved_field = resolve_field_alias(collection, field)

            # Support additional keys:
            # - {field}_within / {field}_duration: relative window like "last_7_days", "7d", {"last": {"days": 7}}
            # - allow {field}_from / {field}_to values like "now-7d" or ISO timestamps

            def _parse_relative_window(spec: Any) -> Optional[Dict[str, datetime]]:
                now = datetime.now(timezone.utc)
                start: Optional[datetime] = None
                end: datetime = now

                def _start_of_week(dt: datetime) -> datetime:
                    dow = dt.weekday()  # Monday=0
                    sod = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                    return sod - timedelta(days=dow)

                def _start_of_month(dt: datetime) -> datetime:
                    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)

                def _end_of_month(dt: datetime) -> datetime:
                    if dt.month == 12:
                        next_month = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
                    else:
                        next_month = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
                    return next_month - timedelta(microseconds=1)

                if isinstance(spec, dict) and spec.get("last"):
                    last_obj = spec.get("last") or {}
                    days = float(last_obj.get("days", 0) or 0)
                    hours = float(last_obj.get("hours", 0) or 0)
                    delta = timedelta(days=days, hours=hours)
                    if delta.total_seconds() > 0:
                        start = now - delta
                        return {"from": start, "to": end}
                    return None

                if not isinstance(spec, str):
                    return None

                s = spec.strip().lower().replace("-", "_")
                if s == "today":
                    sod = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
                    return {"from": sod, "to": end}
                if s == "yesterday":
                    sod_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
                    sod_y = sod_today - timedelta(days=1)
                    eod_y = sod_today - timedelta(microseconds=1)
                    return {"from": sod_y, "to": eod_y}
                if s == "this_week":
                    return {"from": _start_of_week(now), "to": end}
                if s == "last_week":
                    sow_this = _start_of_week(now)
                    sow_last = sow_this - timedelta(days=7)
                    eow_last = sow_this - timedelta(microseconds=1)
                    return {"from": sow_last, "to": eow_last}
                if s == "this_month":
                    return {"from": _start_of_month(now), "to": end}
                if s == "last_month":
                    som_this = _start_of_month(now)
                    if som_this.month == 1:
                        som_last = datetime(som_this.year - 1, 12, 1, tzinfo=timezone.utc)
                    else:
                        som_last = datetime(som_this.year, som_this.month - 1, 1, tzinfo=timezone.utc)
                    eom_last = _end_of_month(som_last)
                    return {"from": som_last, "to": eom_last}

                m = re.search(r"(last|past)?\s*([0-9]+)\s*(day|days|d|week|weeks|w|month|months|mo|hour|hours|h|year|years|y)", s)
                if m:
                    n = int(m.group(2))
                    unit = m.group(3)
                    if unit in {"day", "days", "d"}:
                        start = now - timedelta(days=n)
                    elif unit in {"week", "weeks", "w"}:
                        start = now - timedelta(weeks=n)
                    elif unit in {"month", "months", "mo"}:
                        start = now - timedelta(days=30 * n)
                    elif unit in {"hour", "hours", "h"}:
                        start = now - timedelta(hours=n)
                    elif unit in {"year", "years", "y"}:
                        start = now - timedelta(days=365 * n)
                    if start:
                        return {"from": start, "to": end}

                # Support "now-N{unit}" pattern directly
                m2 = re.fullmatch(r"now\s*[-+]\s*([0-9]+)\s*(d|w|m|mo|y|h)", s)
                if m2:
                    n = int(m2.group(1))
                    unit = m2.group(2)
                    if unit == "d":
                        start = now - timedelta(days=n)
                    elif unit == "w":
                        start = now - timedelta(weeks=n)
                    elif unit in {"m", "mo"}:
                        start = now - timedelta(days=30 * n)
                    elif unit == "y":
                        start = now - timedelta(days=365 * n)
                    elif unit == "h":
                        start = now - timedelta(hours=n)
                    if start:
                        return {"from": start, "to": end}
                
                # Legacy pattern support
                m3 = re.fullmatch(r"([0-9]+)\s*(d|h)", s)
                if m3:
                    n = int(m3.group(1))
                    unit = m3.group(2)
                    if unit == "d":
                        start = now - timedelta(days=n)
                    elif unit == "h":
                        start = now - timedelta(hours=n)
                    if start:
                        return {"from": start, "to": end}
                return None

            def _normalize_bound(val: Any) -> Any:
                if isinstance(val, (int, float)):
                    try:
                        if float(val) > 1e11:
                            return datetime.fromtimestamp(float(val) / 1000.0, tz=timezone.utc)
                        return datetime.fromtimestamp(float(val), tz=timezone.utc)
                    except Exception:
                        return val
                if isinstance(val, str):
                    s = val.strip().lower()
                    if s == "now":
                        return datetime.now(timezone.utc)
                    # Support all time units: d/w/m/y (days/weeks/months/years)
                    m = re.fullmatch(r"now\s*[-+]\s*([0-9]+)\s*(d|day|days|w|week|weeks|m|month|months|mo|y|year|years|h|hour|hours)", s)
                    if m:
                        n = int(m.group(1))
                        unit = m.group(2)
                        if unit in {"d", "day", "days"}:
                            return datetime.now(timezone.utc) - timedelta(days=n)
                        elif unit in {"w", "week", "weeks"}:
                            return datetime.now(timezone.utc) - timedelta(weeks=n)
                        elif unit in {"m", "month", "months", "mo"}:
                            # Approximate: 30 days per month
                            return datetime.now(timezone.utc) - timedelta(days=30 * n)
                        elif unit in {"y", "year", "years"}:
                            # Approximate: 365 days per year
                            return datetime.now(timezone.utc) - timedelta(days=365 * n)
                        elif unit in {"h", "hour", "hours"}:
                            return datetime.now(timezone.utc) - timedelta(hours=n)
                    try:
                        return datetime.fromisoformat(val)
                    except Exception:
                        return val
                return val

            # Look for date range keys using the original field name
            within = f.get(f"{field}_within") or f.get(f"{field}_duration")
            gte_key = f.get(f"{field}_from")
            lte_key = f.get(f"{field}_to")

            if within is not None:
                rng = _parse_relative_window(within)
                if rng:
                    gte_key = gte_key or rng.get("from")
                    lte_key = lte_key or rng.get("to")

            # Also interpret relative tokens provided directly in _from/_to
            # e.g. createdTimeStamp_from: "last_week" or updatedTimeStamp_to: "yesterday"
            if isinstance(gte_key, str):
                rng_from = _parse_relative_window(gte_key)
                if rng_from:
                    gte_key = rng_from.get("from")
                    # If caller did not specify an upper bound, use the window's natural end
                    if lte_key is None:
                        lte_key = rng_from.get("to")
            if isinstance(lte_key, str):
                rng_to = _parse_relative_window(lte_key)
                if rng_to:
                    lte_key = rng_to.get("to")

            if gte_key is None and lte_key is None:
                return
            range_expr: Dict[str, Any] = {}
            if gte_key is not None:
                range_expr["$gte"] = _normalize_bound(gte_key)
            if lte_key is not None:
                range_expr["$lte"] = _normalize_bound(lte_key)
            if range_expr:
                target[resolved_field] = range_expr

        # Handle negative filters (_not suffix) - convert to MongoDB $nin operator
        # If a positive filter exists for the same field, merge them together
        for key, value in filters.items():
            if key.endswith('_not'):
                # Extract base field name
                base_field = key[:-len('_not')]
                # Resolve field alias
                from mongo.registry import resolve_field_alias
                resolved_field = resolve_field_alias(collection, base_field)
                
                # Check if positive filter exists for the same field
                if base_field in filters:
                    # Merge positive and negative filters
                    filter_obj = primary_filters.get(resolved_field, {})
                    positive_value = filters[base_field]
                    
                    # Convert positive filter to $in if it's a scalar or list
                    if isinstance(positive_value, (str, int, bool)):
                        filter_obj["$in"] = [positive_value]
                    elif isinstance(positive_value, list):
                        filter_obj["$in"] = positive_value
                    else:
                        # If it's already a dict (e.g., from regex), preserve it but add $nin
                        filter_obj = positive_value.copy() if isinstance(positive_value, dict) else {}
                        if not isinstance(positive_value, dict):
                            filter_obj["$in"] = [positive_value] if not isinstance(positive_value, list) else positive_value
                    
                    # Add negative filter as $nin
                    if isinstance(value, list):
                        filter_obj["$nin"] = value
                    else:
                        filter_obj["$nin"] = [value]
                    
                    primary_filters[resolved_field] = filter_obj
                else:
                    # Only negative filter exists - use simple $nin
                    if isinstance(value, list):
                        primary_filters[resolved_field] = {"$nin": value}
                    else:
                        primary_filters[resolved_field] = {"$nin": [value]}
        
        if collection == "Lead":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'leadStatus' in filters and 'leadStatus' not in primary_filters:
                if 'leadStatus_not' not in filters:
                    primary_filters['leadStatus'] = filters['leadStatus']
            if 'status' in filters and 'status' not in primary_filters:
                if 'status_not' not in filters:
                    primary_filters['status'] = filters['status']
            if 'source' in filters:
                primary_filters['source'] = filters['source']
            if 'type' in filters:
                primary_filters['type'] = filters['type']
            if 'leadActiveType' in filters:
                primary_filters['leadActiveType'] = filters['leadActiveType']
            if 'customerType' in filters:
                primary_filters['customerType'] = filters['customerType']
            if 'personalInfo.name' in filters and isinstance(filters['personalInfo.name'], str):
                primary_filters['personalInfo.name'] = {'$regex': filters['personalInfo.name'], '$options': 'i'}
            if 'personalInfo.email' in filters and isinstance(filters['personalInfo.email'], str):
                primary_filters['personalInfo.email'] = {'$regex': filters['personalInfo.email'], '$options': 'i'}
            if 'personalInfo.mobile' in filters and isinstance(filters['personalInfo.mobile'], str):
                primary_filters['personalInfo.mobile'] = {'$regex': filters['personalInfo.mobile'], '$options': 'i'}
            if 'referenceNo' in filters and isinstance(filters['referenceNo'], str):
                primary_filters['referenceNo'] = {'$regex': f"^{filters['referenceNo']}", '$options': 'i'}
            if 'notes' in filters and isinstance(filters['notes'], str):
                primary_filters['notes'] = {'$regex': filters['notes'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            if 'staffId' in filters:
                primary_filters['staffId'] = filters['staffId']
            if 'staffName' in filters and isinstance(filters['staffName'], str):
                primary_filters['staffName'] = {'$regex': filters['staffName'], '$options': 'i'}
            if 'score' in filters:
                _apply_numeric_range(primary_filters, 'score', filters)
            if 'emailCount' in filters:
                _apply_numeric_range(primary_filters, 'emailCount', filters)
            if 'callCount' in filters:
                _apply_numeric_range(primary_filters, 'callCount', filters)
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "Task":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'taskStatus' in filters and 'taskStatus' not in primary_filters:
                if 'taskStatus_not' not in filters:
                    primary_filters['taskStatus'] = filters['taskStatus']
            if 'priority' in filters and 'priority' not in primary_filters:
                if 'priority_not' not in filters:
                    primary_filters['priority'] = filters['priority']
            if 'name' in filters and isinstance(filters['name'], str):
                primary_filters['name'] = {'$regex': filters['name'], '$options': 'i'}
            if 'description' in filters and isinstance(filters['description'], str):
                primary_filters['description'] = {'$regex': filters['description'], '$options': 'i'}
            if 'assignedName' in filters and isinstance(filters['assignedName'], str):
                primary_filters['assignedName'] = {'$regex': filters['assignedName'], '$options': 'i'}
            if 'assignedTo' in filters:
                primary_filters['assignedTo'] = filters['assignedTo']
            if 'assignToMailId' in filters and isinstance(filters['assignToMailId'], str) and filters['assignToMailId']:
                primary_filters['assignToMailId'] = {'$regex': filters['assignToMailId'], '$options': 'i'}
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            if 'notify' in filters:
                primary_filters['notify'] = filters['notify']
            if 'reminderDays' in filters:
                _apply_numeric_range(primary_filters, 'reminderDays', filters)
            if 'leadId' in filters:
                primary_filters['parentId'] = filters['leadId']  # Tasks use parentId to reference leads
            if 'parentId' in filters:
                primary_filters['parentId'] = filters['parentId']
            if 'parentName' in filters and isinstance(filters['parentName'], str):
                primary_filters['parentName'] = {'$regex': filters['parentName'], '$options': 'i'}
            _apply_date_range(primary_filters, 'dueDate', filters)
            _apply_date_range(primary_filters, 'reminderDate', filters)
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "Activity":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'activityStatus' in filters and 'activityStatus' not in primary_filters:
                if 'activityStatus_not' not in filters:
                    primary_filters['activityStatus'] = filters['activityStatus']
            if 'type' in filters:
                primary_filters['type'] = filters['type']
            if 'leadId' in filters:
                primary_filters['leadId'] = filters['leadId']
            if 'parentId' in filters:
                primary_filters['parentId'] = filters['parentId']
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'reminderDate', filters)

        elif collection == "Meeting":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'meetingStatus' in filters and 'meetingStatus' not in primary_filters:
                if 'meetingStatus_not' not in filters:
                    primary_filters['meetingStatus'] = filters['meetingStatus']
            if 'meetingType' in filters and 'meetingType' not in primary_filters:
                if 'meetingType_not' not in filters:
                    primary_filters['meetingType'] = filters['meetingType']
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'description' in filters and isinstance(filters['description'], str):
                primary_filters['description'] = {'$regex': filters['description'], '$options': 'i'}
            if 'leadName' in filters and isinstance(filters['leadName'], str):
                primary_filters['leadName'] = {'$regex': filters['leadName'], '$options': 'i'}
            if 'leadId' in filters:
                primary_filters['leadId'] = filters['leadId']
            if 'assignedName' in filters and isinstance(filters['assignedName'], str):
                primary_filters['assignedName'] = {'$regex': filters['assignedName'], '$options': 'i'}
            if 'assignedTo' in filters:
                primary_filters['assignedTo'] = filters['assignedTo']
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            if 'meetingLink' in filters and isinstance(filters['meetingLink'], str) and filters['meetingLink'].strip():
                primary_filters['meetingLink'] = {'$regex': filters['meetingLink'], '$options': 'i'}
            if 'meetingLocated' in filters and isinstance(filters['meetingLocated'], str) and filters['meetingLocated'].strip():
                primary_filters['meetingLocated'] = {'$regex': filters['meetingLocated'], '$options': 'i'}
            if 'remainder' in filters:
                _apply_numeric_range(primary_filters, 'remainder', filters)
            if 'participantsRemainder' in filters:
                _apply_numeric_range(primary_filters, 'participantsRemainder', filters)
            _apply_date_range(primary_filters, 'startDateTime', filters)
            _apply_date_range(primary_filters, 'endDateTime', filters)
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "Notes":
            if 'subject' in filters and isinstance(filters['subject'], str):
                primary_filters['subject'] = {'$regex': filters['subject'], '$options': 'i'}
            if 'description' in filters and isinstance(filters['description'], str):
                primary_filters['description'] = {'$regex': filters['description'], '$options': 'i'}
            if 'leadName' in filters and isinstance(filters['leadName'], str):
                primary_filters['leadName'] = {'$regex': filters['leadName'], '$options': 'i'}
            if 'leadId' in filters:
                primary_filters['leadId'] = filters['leadId']
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            if 'taskId' in filters:
                primary_filters['taskId'] = filters['taskId']
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)

        elif collection == "CallLog":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'callStatus' in filters and 'callStatus' not in primary_filters:
                if 'callStatus_not' not in filters:
                    primary_filters['callStatus'] = filters['callStatus']
            if 'callType' in filters and 'callType' not in primary_filters:
                if 'callType_not' not in filters:
                    primary_filters['callType'] = filters['callType']
            if 'call_variant' in filters:
                primary_filters['call_variant'] = filters['call_variant']
            if 'callPurpose' in filters:
                primary_filters['callPurpose'] = filters['callPurpose']
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'description' in filters and isinstance(filters['description'], str):
                primary_filters['description'] = {'$regex': filters['description'], '$options': 'i'}
            if 'leadName' in filters and isinstance(filters['leadName'], str):
                primary_filters['leadName'] = {'$regex': filters['leadName'], '$options': 'i'}
            if 'leadId' in filters:
                primary_filters['leadId'] = filters['leadId']
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            if 'callDuration' in filters:
                # callDuration can be empty string or number string
                if isinstance(filters['callDuration'], str) and filters['callDuration'].strip():
                    try:
                        # Try to parse as number for range filters
                        float(filters['callDuration'])
                        _apply_numeric_range(primary_filters, 'callDuration', filters)
                    except (ValueError, TypeError):
                        # If not a number, treat as string filter
                        primary_filters['callDuration'] = {'$regex': filters['callDuration'], '$options': 'i'}
            if 'otherReason' in filters and isinstance(filters['otherReason'], str):
                # otherReason can be empty string, handle it gracefully
                if filters['otherReason'].strip():
                    primary_filters['otherReason'] = {'$regex': filters['otherReason'], '$options': 'i'}
            if 'remainder' in filters:
                _apply_numeric_range(primary_filters, 'remainder', filters)
            _apply_date_range(primary_filters, 'startDateTime', filters)
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "MailInfo":
            # Only add positive filter if it wasn't already merged with negative filter
            if 'mailType' in filters and 'mailType' not in primary_filters:
                if 'mailType_not' not in filters:
                    primary_filters['mailType'] = filters['mailType']
            if 'subject' in filters and isinstance(filters['subject'], str):
                primary_filters['subject'] = {'$regex': filters['subject'], '$options': 'i'}
            if 'body' in filters and isinstance(filters['body'], str):
                primary_filters['body'] = {'$regex': filters['body'], '$options': 'i'}
            if 'leadId' in filters:
                primary_filters['leadId'] = filters['leadId']
            if 'createdByName' in filters and isinstance(filters['createdByName'], str):
                primary_filters['createdByName'] = {'$regex': filters['createdByName'], '$options': 'i'}
            if 'createdById' in filters:
                primary_filters['createdById'] = filters['createdById']
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        # Handle array size filters (e.g., participantsList_count: ">1")
        array_size_filters = {}
        array_field_map = {
            'participantsList_count': 'participantsList',  # For Meeting
            'notesAttachments_count': 'notesAttachments',  # For Notes
            'attachments_count': 'attachments',  # For MailInfo
            'toMails_count': 'toMails',  # For MailInfo
            'toCcMails_count': 'toCcMails',  # For MailInfo
            'toBccMails_count': 'toBccMails',  # For MailInfo
            'fieldData_count': 'fieldData',  # For Lead
        }

        for count_key, array_field in array_field_map.items():
            if count_key in filters:
                condition = filters[count_key]
                if isinstance(condition, str):
                    # Parse conditions like ">1", ">=2", "0", "=3", etc.
                    if condition.startswith('>'):
                        if condition.startswith('>='):
                            min_size = int(condition[2:])
                            array_size_filters[array_field] = {'$gte': min_size}
                        else:
                            min_size = int(condition[1:])
                            array_size_filters[array_field] = {'$gt': min_size}
                    elif condition.startswith('='):
                        exact_size = int(condition[1:])
                        array_size_filters[array_field] = {'$size': exact_size}
                    elif condition.isdigit():
                        exact_size = int(condition)
                        array_size_filters[array_field] = {'$size': exact_size}
                    else:
                        # Handle other conditions like "<2", "<=3"
                        if condition.startswith('<='):
                            max_size = int(condition[2:])
                            array_size_filters[array_field] = {'$lte': max_size}
                        elif condition.startswith('<'):
                            max_size = int(condition[1:])
                            array_size_filters[array_field] = {'$lt': max_size}

        # Convert array size filters to $expr for MongoDB
        # First, ensure $expr exists and wrap any existing content in $and if needed
        if array_size_filters:
            if '$expr' not in primary_filters:
                primary_filters['$expr'] = {}
            
            existing_expr = primary_filters['$expr']
            # If $expr already has content but not wrapped in $and, we need to wrap it
            if '$and' not in existing_expr and existing_expr:
                # Wrap existing $expr content in $and array
                wrapped_expr = existing_expr.copy()
                primary_filters['$expr'] = {'$and': [wrapped_expr]}
            elif '$and' not in primary_filters['$expr']:
                primary_filters['$expr']['$and'] = []
        
        # Now add all array size conditions
        for array_field, size_condition in array_size_filters.items():
            if '$size' in size_condition:
                # Exact size match
                size_val = size_condition['$size']
                primary_filters['$expr']['$and'].append({
                    '$eq': [{'$size': f'${array_field}'}, size_val]
                })
            elif '$gt' in size_condition:
                # Greater than
                size_val = size_condition['$gt']
                primary_filters['$expr']['$and'].append({
                    '$gt': [{'$size': f'${array_field}'}, size_val]
                })
            elif '$gte' in size_condition:
                # Greater than or equal
                size_val = size_condition['$gte']
                primary_filters['$expr']['$and'].append({
                    '$gte': [{'$size': f'${array_field}'}, size_val]
                })
            elif '$lt' in size_condition:
                # Less than
                size_val = size_condition['$lt']
                primary_filters['$expr']['$and'].append({
                    '$lt': [{'$size': f'${array_field}'}, size_val]
                })
            elif '$lte' in size_condition:
                # Less than or equal
                size_val = size_condition['$lte']
                primary_filters['$expr']['$and'].append({
                    '$lte': [{'$size': f'${array_field}'}, size_val]
                })

        # Handle advanced MongoDB operators
        advanced_operators = {}

        # $elemMatch for complex array element matching
        for key, value in filters.items():
            if key.endswith('_elemMatch') and isinstance(value, dict):
                array_field = key.replace('_elemMatch', '')
                advanced_operators[array_field] = {'$elemMatch': value}

        # $text for full-text search
        if '$text' in filters:
            primary_filters['$text'] = {'$search': filters['$text']}

        # Add advanced operators to primary filters
        for field, operator in advanced_operators.items():
            primary_filters[field] = operator

        return primary_filters

    def _extract_secondary_filters(self, filters: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Extract filters that apply to joined collections, guarded by available relations."""
        s: Dict[str, Any] = {}

        # Project name: allow both embedded project.name and joined alias projectDoc.name
        if 'project_name' in filters and collection == 'project':
            s['$or'] = [
                {'name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectDoc.name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectName': {'$regex': filters['project_name'], '$options': 'i'}},
            ]
        elif 'project_name' in filters:
            # For non-project collections, match on the joined project document
            s['$or'] = [
                {'project.name': {'$regex': filters['project_name'], '$options': 'i'}},
                {'projectDoc.name': {'$regex': filters['project_name'], '$options': 'i'}},
            ]

        # Assignee name via joined alias 'assignees' (only if relation exists)
        if 'assignee_name' in filters and 'assignee' in REL.get(collection, {}):
            # Prefer embedded assignee names when present; joined alias may be 'assignees'
            s['$or'] = s.get('$or', []) + [
                {'assignee.name': {'$regex': filters['assignee_name'], '$options': 'i'}},
                {'assignees.name': {'$regex': filters['assignee_name'], '$options': 'i'}},
            ]
        # Member role filter when relation exists
        if 'member_role' in filters:
            # For workItem: embedded assignee or joined members
            if collection == 'workItem' and 'assignee' in REL.get(collection, {}):
                s['$or'] = s.get('$or', []) + [
                    {'assignee.role': {'$regex': f"^{filters['member_role']}$", '$options': 'i'}},
                    {'assignees.role': {'$regex': f"^{filters['member_role']}$", '$options': 'i'}},
                ]
            # For project: through members join
            if collection == 'project' and 'members' in REL.get('project', {}):
                s['members.role'] = {'$regex': f"^{filters['member_role']}$", '$options': 'i'}
            # For module: embedded assignee or joined members
            if collection == 'module' and 'assignee' in REL.get('module', {}):
                s['$or'] = s.get('$or', []) + [
                    {'assignee.role': {'$regex': f"^{filters['member_role']}$", '$options': 'i'}},
                    {'assignees.role': {'$regex': f"^{filters['member_role']}$", '$options': 'i'}},
                ]

        # Cycle name filter: prefer embedded cycle.name; support joined aliases
        if 'cycle_name' in filters:
            if collection == 'workItem':
                s['cycle.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}
            elif 'cycle' in REL.get(collection, {}):
                s['cycle.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}
            elif 'cycles' in REL.get(collection, {}):
                s['cycles.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}
            elif collection == 'page' and 'linkedCycle' in REL.get('page', {}):
                s['linkedCycleDocs.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}

        # Module name filter: prefer embedded modules.name; support joined aliases
        if 'module_name' in filters:
            if collection == 'workItem':
                s['modules.name'] = {'$regex': filters['module_name'], '$options': 'i'}
            elif 'module' in REL.get(collection, {}):
                s['module.name'] = {'$regex': filters['module_name'], '$options': 'i'}
            elif 'modules' in REL.get(collection, {}):
                s['modules.name'] = {'$regex': filters['module_name'], '$options': 'i'}
            elif collection == 'page' and 'linkedModule' in REL.get('page', {}):
                s['linkedModuleDocs.name'] = {'$regex': filters['module_name'], '$options': 'i'}

        # Business name via embedded or joined path
        if 'business_name' in filters:
            # Directly embedded business on these collections
            if collection in ('project', 'page'):
                s['$or'] = s.get('$or', []) + [
                    {'business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectDoc.business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectBusinessName': {'$regex': filters['business_name'], '$options': 'i'}},
                ]
            # For cycle/module: prefer project join to reach project.business.name
            if collection in ('cycle', 'module'):
                s['$or'] = s.get('$or', []) + [
                    {'project.business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectDoc.business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectBusinessName': {'$regex': filters['business_name'], '$options': 'i'}},
                ]
            # For members: through joined project
            if collection == 'members' and 'project' in REL.get('members', {}):
                s['$or'] = s.get('$or', []) + [
                    {'project.business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectDoc.business.name': {'$regex': filters['business_name'], '$options': 'i'}},
                    {'projectBusinessName': {'$regex': filters['business_name'], '$options': 'i'}},
                ]

        # Page linked members: support name filter via joined alias when available
        if collection == 'page' and 'LinkedMembers_0_name' in filters:
            # Interpret as any linked member name regex
            s['linkedMembersDocs.name'] = {'$regex': filters['LinkedMembers_0_name'], '$options': 'i'}

        return s

    def _generate_lookup_stage(self, from_collection: str, target_entity: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        # Deprecated in favor of build_lookup_stage imported from registry
        if from_collection not in REL or target_entity not in REL[from_collection]:
            return {}
        relationship = REL[from_collection][target_entity]
        return build_lookup_stage(relationship["target"], relationship, from_collection)

    def _generate_projection(self, projections: List[str], target_entities: List[str], primary_entity: str) -> Dict[str, Any]:
        """Generate projection object"""
        projection = {"_id": 1}  # Always include ID

        # Add requested projections
        for field in projections:
            if field in ALLOWED_FIELDS.get(primary_entity, {}):
                projection[field] = 1

        # Add target entity fields
        for entity in target_entities:
            if entity in REL.get(primary_entity, {}):
                projection[entity] = 1

        return projection

    def _get_default_projections(self, primary_entity: str) -> List[str]:
        """Return sensible default fields for detail queries per collection.
        Only returns fields that are allow-listed for the given collection.
        """
        defaults_map: Dict[str, List[str]] = {
            "Lead": [
                "referenceNo", "leadStatus", "personalInfo.name", "personalInfo.email", "personalInfo.mobile",
                "status", "score", "emailCount", "callCount", "createdTimeStamp", "updatedTimeStamp"
            ],
            "Task": [
                "name", "taskStatus", "priority", "dueDate", "assignedName", "createdByName",
                "description", "createdTimeStamp", "updatedTimeStamp"
            ],
            "Activity": [
                "type", "activityStatus", "createdTimeStamp"
            ],
            "Meeting": [
                "title", "meetingStatus", "meetingType", "leadName", "assignedName", "createdByName",
                "startDateTime", "endDateTime", "description", "createdTimeStamp", "updatedTimeStamp"
            ],
            "Notes": [
                "subject", "description", "leadName", "createdByName", "createdTimeStamp"
            ],
            "CallLog": [
                "title", "callStatus", "callType", "leadName", "createdByName",
                "startDateTime", "description", "createdTimeStamp", "updatedTimeStamp"
            ],
            "MailInfo": [
                "subject", "mailType", "createdByName", "toMails", "createdTimeStamp", "updatedTimeStamp"
            ],
        }

        candidates = defaults_map.get(primary_entity, ["_id"])  # fallback _id

        # Validate against allow-listed fields for safety
        allowed = ALLOWED_FIELDS.get(primary_entity, set())
        validated: List[str] = []
        for field in candidates:
            # Keep only fields that are explicitly allow-listed for primary entity
            if field in allowed:
                validated.append(field)

        # After computing validated, if it's empty, fall back to a minimal safe set
        if not validated:
            minimal = ["title", "priority", "createdTimeStamp"]
            validated = [f for f in minimal if f in allowed]
        return validated

    def _resolve_group_field(self, primary_entity: str, token: str) -> Optional[str]:
        """Map a grouping token to a concrete field path or Mongo expression.

        Returns either a string field path (relative to current doc) or a dict representing
        a MongoDB aggregation expression (e.g., for date bucketing).
        """
        # Date bucket helper
        def date_field_for(entity: str, which: str) -> Optional[str]:
            # which: 'created' | 'updated'
            # CRM entities use createdTimeStamp/updatedTimeStamp consistently
            # Meeting and CallLog use startDateTime for created grouping (more meaningful)
            if entity == 'Meeting' and which == 'created':
                return 'startDateTime'  # Use startDateTime for meeting creation grouping
            if entity == 'CallLog' and which == 'created':
                return 'startDateTime'  # Use startDateTime for call log creation grouping
            # Default to *TimeStamp for other CRM entities
            # Activity and Notes don't have updatedTimeStamp in all records, so only use createdTimeStamp
            if entity in ('Activity', 'Notes') and which == 'updated':
                return None  # These collections don't consistently have updatedTimeStamp
            return 'createdTimeStamp' if which == 'created' else 'updatedTimeStamp'

        def bucket_expr(entity: str, which: str, unit: str):
            field = date_field_for(entity, which)
            if not field:
                return None
            # Prefer $dateTrunc for week/month; for day we can also truncate
            if unit in {'week', 'month', 'day'}:
                return {"$dateTrunc": {"date": f"${field}", "unit": unit}}
            return None

        # Base mappings
        mapping: Dict[str, Dict[str, Any]] = {
            'Lead': {
                'leadStatus': 'leadStatus',
                'status': 'status',
                'assignedName': 'assignedName',
                'createdByName': 'createdByName',
                'priority': 'priority',  # If lead has priority
                'created_day': bucket_expr('Lead', 'created', 'day'),
                'created_week': bucket_expr('Lead', 'created', 'week'),
                'created_month': bucket_expr('Lead', 'created', 'month'),
                'updated_day': bucket_expr('Lead', 'updated', 'day'),
                'updated_week': bucket_expr('Lead', 'updated', 'week'),
                'updated_month': bucket_expr('Lead', 'updated', 'month'),
            },
            'Task': {
                'taskStatus': 'taskStatus',
                'priority': 'priority',
                'assignedName': 'assignedName',
                'createdByName': 'createdByName',
                'lead': 'lead.name',  # If joined
                'created_day': bucket_expr('Task', 'created', 'day'),
                'created_week': bucket_expr('Task', 'created', 'week'),
                'created_month': bucket_expr('Task', 'created', 'month'),
                'updated_day': bucket_expr('Task', 'updated', 'day'),
                'updated_week': bucket_expr('Task', 'updated', 'week'),
                'updated_month': bucket_expr('Task', 'updated', 'month'),
            },
            'Activity': {
                'activityStatus': 'activityStatus',
                'type': 'type',
                'createdByName': 'createdByName',
                'created_day': bucket_expr('Activity', 'created', 'day'),
                'created_week': bucket_expr('Activity', 'created', 'week'),
                'created_month': bucket_expr('Activity', 'created', 'month'),
            },
            'Meeting': {
                'meetingStatus': 'meetingStatus',
                'meetingType': 'meetingType',
                'assignedName': 'assignedName',
                'createdByName': 'createdByName',
                'lead': 'lead.name',  # If joined
                'created_day': bucket_expr('Meeting', 'created', 'day'),
                'created_week': bucket_expr('Meeting', 'created', 'week'),
                'created_month': bucket_expr('Meeting', 'created', 'month'),
            },
            'Notes': {
                'subject': 'subject',
                'createdByName': 'createdByName',
                'lead': 'lead.name',  # If joined
                'created_day': bucket_expr('Notes', 'created', 'day'),
                'created_week': bucket_expr('Notes', 'created', 'week'),
                'created_month': bucket_expr('Notes', 'created', 'month'),
            },
            'CallLog': {
                'callStatus': 'callStatus',
                'callType': 'callType',
                'call_variant': 'call_variant',
                'callPurpose': 'callPurpose',
                'createdByName': 'createdByName',
                'lead': 'lead.name',  # If joined
                'created_day': bucket_expr('CallLog', 'created', 'day'),
                'created_week': bucket_expr('CallLog', 'created', 'week'),
                'created_month': bucket_expr('CallLog', 'created', 'month'),
                'updated_day': bucket_expr('CallLog', 'updated', 'day'),
                'updated_week': bucket_expr('CallLog', 'updated', 'week'),
                'updated_month': bucket_expr('CallLog', 'updated', 'month'),
            },
            'MailInfo': {
                'mailType': 'mailType',
                'createdByName': 'createdByName',
                'lead': 'lead.name',  # If joined
                'created_day': bucket_expr('MailInfo', 'created', 'day'),
                'created_week': bucket_expr('MailInfo', 'created', 'week'),
                'created_month': bucket_expr('MailInfo', 'created', 'month'),
                'updated_day': bucket_expr('MailInfo', 'updated', 'day'),
                'updated_week': bucket_expr('MailInfo', 'updated', 'week'),
                'updated_month': bucket_expr('MailInfo', 'updated', 'month'),
            },
        }
        entity_map = mapping.get(primary_entity, {})
        val = entity_map.get(token)
        # Some bucket_expr entries may be None if field not applicable
        return val if val is not None else None
