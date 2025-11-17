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
            'workItem': {
                # Only add project if we're doing multi-hop queries or need business context
                'project': self._needs_multi_hop_context(intent, ['business', 'cycle', 'module']),
            },
            'project': {
                # Only add business if we're grouping by or filtering by business
                'business': 'business' in (intent.group_by or []) or 'business_name' in (intent.filters or {}),
            },
            'cycle': {
                # Only add project if we're doing complex analysis
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'module': {
                # Only add project if we're doing complex analysis
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'members': {
                # Only add project if we're doing complex analysis
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'page': {
                # Only add project if we're doing complex analysis
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'epic': {
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
            },
            'features': {
                'project': len(intent.group_by or []) > 1 or intent.wants_details,
                'cycles': self._needs_multi_hop_context(intent, ['cycle']),
                'modules': self._needs_multi_hop_context(intent, ['module']),
            }
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
            self._needs_multi_hop_context(intent, ['business', 'cycle', 'module']) or
            'business' in (intent.group_by or []) or
            'business_name' in (intent.filters or {})
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
            'workItem': {
                # All are embedded on workItem; no lookup needed for filters/grouping
                'project': None,
                'assignee': None,
                'module': None,
                'cycle': None,
                # For business grouping we may need a project join to ensure business name
                'business': 'project',
            },
            'project': {
                'cycle': 'cycles',
                'module': 'modules',
                'assignee': 'members',
                'page': 'pages',
                'project': None,
            },
            'cycle': {
                'project': 'project',
                'business': 'project',
            },
            'module': {
                'project': 'project',
                'assignee': 'assignee',
                'business': 'project',
            },
            'page': {
                'project': 'project',  # key in REL is 'project', alias is 'projectDoc'
                'cycle': 'linkedCycle',
                'module': 'linkedModule',
                'business': 'project',
                'linkedMembers': 'linkedMembers',
            },
            'members': {
                'project': 'project',
                'business': 'project',
            },
            'projectState': {
                'project': 'project',
                'business': 'project',
            },
            'epic': {
                'project': 'project',
                'business': 'project',
            },
            'features': {
                'project': 'project',
                'business': 'project',
                'cycle': 'cycles',
                'module': 'modules',
            },
            'userStory': {
                'project': 'project',
                'business': 'project',
            }

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
            # For workItem, project/assignee/cycle/modules are embedded; no lookups needed for name filters
            if collection != 'workItem':
                if 'project_name' in intent.filters and relation_alias_by_token.get('project') in REL.get(collection, {}):
                    required_relations.add(relation_alias_by_token['project'])
                if 'cycle_name' in intent.filters and relation_alias_by_token.get('cycle') in REL.get(collection, {}):
                    required_relations.add(relation_alias_by_token['cycle'])
                if 'assignee_name' in intent.filters and relation_alias_by_token.get('assignee') in REL.get(collection, {}):
                    required_relations.add(relation_alias_by_token['assignee'])
                if 'module_name' in intent.filters and relation_alias_by_token.get('module') in REL.get(collection, {}):
                    required_relations.add(relation_alias_by_token['module'])
                # Business name may require project hop for collections without embedded business
                if 'business_name' in intent.filters:
                    # If primary lacks direct business relation, but has project relation, join project
                    if relation_alias_by_token.get('project') in REL.get(collection, {}):
                        required_relations.add(relation_alias_by_token['project'])
                # Page linked members filter requires linkedMembers join
                if collection == 'page' and 'LinkedMembers_0_name' in intent.filters and relation_alias_by_token.get('linkedMembers') in REL.get(collection, {}):
                    required_relations.add(relation_alias_by_token['linkedMembers'])
            if 'member_role' in intent.filters:
                # Require member join depending on collection
                if collection == 'workItem' and 'assignee' in REL.get(collection, {}):
                    required_relations.add('assignee')
                if collection == 'project' and 'members' in REL.get('project', {}):
                    required_relations.add('members')
                if collection == 'module' and 'assignee' in REL.get('module', {}):
                    required_relations.add('assignee')

            # Multi-hop fallbacks for cycle/module via project when direct relations are absent
            if 'cycle_name' in intent.filters and ('cycle' not in REL.get(collection, {}) and 'cycles' not in REL.get(collection, {}) and 'linkedCycle' not in REL.get(collection, {})):
                if 'project' in REL.get(collection, {}) and 'cycles' in REL.get('project', {}):
                    required_relations.add('project')
                    required_relations.add('project.cycles')
            if 'module_name' in intent.filters and ('module' not in REL.get(collection, {}) and 'modules' not in REL.get(collection, {}) and 'linkedModule' not in REL.get(collection, {})):
                if 'project' in REL.get(collection, {}) and 'modules' in REL.get('project', {}):
                    required_relations.add('project')
                    required_relations.add('project.modules')

        # Group-by → relations
        for token in (intent.group_by or []):
            # Map grouping token to relation alias for this primary
            rel_alias = relation_alias_by_token.get(token)
            if rel_alias and rel_alias in REL.get(collection, {}):
                required_relations.add(rel_alias)
            # Multi-hop fallback for grouping keys that require project hop (e.g., cycle/module on workItem)
            if token == 'cycle' and ('cycle' not in REL.get(collection, {}) and 'cycles' not in REL.get(collection, {})):
                if 'project' in REL.get(collection, {}) and 'cycles' in REL.get('project', {}):
                    required_relations.add('project')
                    required_relations.add('project.cycles')
            if token == 'module' and ('module' not in REL.get(collection, {}) and 'modules' not in REL.get(collection, {})):
                if 'project' in REL.get(collection, {}) and 'modules' in REL.get('project', {}):
                    required_relations.add('project')
                    required_relations.add('project.modules')

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
                needs_alias_fix = (
                    relationship.get("target") == "project"
                    and current_collection in {"cycle", "module", "page", "members", "projectState"}
                )
                if needs_alias_fix:
                    # Force a safe alias to prevent clobbering embedded project field
                    relationship = {**relationship, "as": "projectDoc"}
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

        # Normalize project fields to scalars for safe filtering/printing
        if intent.primary_entity in {"cycle", "module", "page", "members", "projectState"}:
            pipeline.append({
                "$addFields": {
                    "projectId": {"$ifNull": ["$project._id", {"$first": "$projectDoc._id"}]},
                    "projectName": {"$ifNull": ["$project.name", {"$first": "$projectDoc.name"}]},
                    "projectBusinessName": {"$ifNull": ["$project.business.name", {"$first": "$projectDoc.business.name"}]}
                }
            })

        # $unionWith - combine with another collection (MUST come BEFORE grouping)
        # This allows grouping the combined results from multiple collections
        if intent.union_collection:
            union_with_stage = {
                "$unionWith": {
                    "coll": intent.union_collection,
                    "pipeline": [{"$match": {}}]  # Add filters if needed
                }
            }
            pipeline.append(union_with_stage)

        # Add grouping if requested
        if intent.group_by:
            # Pre-group unwind for embedded arrays that are used as grouping keys
            # For workItem, assignee is an array subdocument; unwind to get per-assignee buckets
            if intent.primary_entity == 'workItem' and 'assignee' in intent.group_by:
                pipeline.append({
                    "$unwind": {"path": "$assignee", "preserveNullAndEmptyArrays": True}
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
                # Fallback: do nothing if we can't resolve
                pass
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
                # Respect limit on grouped results
                if intent.limit:
                    pipeline.append({"$limit": intent.limit})

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
                                        {"case": {"$eq": ["$priority", "URGENT"]}, "then": 5},
                                        {"case": {"$eq": ["$priority", "HIGH"]}, "then": 4},
                                        {"case": {"$eq": ["$priority", "MEDIUM"]}, "then": 3},
                                        {"case": {"$eq": ["$priority", "LOW"]}, "then": 2},
                                        {"case": {"$eq": ["$priority", "NONE"]}, "then": 1}
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

        # Add pagination: skip then limit (only for non-grouped queries; grouped handled above)
        if not intent.group_by:
            # Apply skip before limit
            try:
                if intent.skip and int(intent.skip) > 0:
                    pipeline.append({"$skip": int(intent.skip)})
            except Exception:
                pass
            effective_limit = 1 if intent.fetch_one else (intent.limit or None)
            if effective_limit:
                pipeline.append({"$limit": int(effective_limit)})

        # Add advanced aggregation stages (check these BEFORE regular group aggregation)
        if intent.aggregations:
            # $bucketAuto - automatic range grouping
            if "bucketAuto" in intent.aggregations and intent.bucket_field:
                bucket_auto_stage = {
                    "$bucketAuto": {
                        "groupBy": f"${intent.bucket_field}",
                        "buckets": 5,
                        "output": {"count": {"$sum": 1}}
                    }
                }
                pipeline.append(bucket_auto_stage)
                # Skip regular group_by handling when using $bucketAuto
                intent.group_by = []

            # $facet - multiple aggregations
            elif "facet" in intent.aggregations and intent.facet_fields:
                facet_stage = {"$facet": {}}
                for field in intent.facet_fields:
                    facet_stage["$facet"][f"{field}_breakdown"] = [
                        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 10}
                    ]
                pipeline.append(facet_stage)
                # Skip regular group_by handling when using $facet
                intent.group_by = []

        # $graphLookup - graph traversal
        # Check if graph lookup is requested (either explicitly or inferred from query)
        # Improved detection: check aggregations, explicit graph fields, or query context
        has_graph_aggregation = "graphLookup" in intent.aggregations
        has_explicit_graph_fields = (
            intent.graph_from and intent.graph_start and 
            intent.graph_connect_from and intent.graph_connect_to
        )
        # Check filters for dependency-related terms
        filters_str = str(intent.filters).lower() if intent.filters else ""
        has_dependency_context = (
            "dependency" in filters_str or 
            "depends" in filters_str or
            "graph" in filters_str or
            "chain" in filters_str or
            "relationship" in filters_str
        )
        
        needs_graph_lookup = has_graph_aggregation or has_explicit_graph_fields or has_dependency_context
        
        if needs_graph_lookup:
            # Set defaults based on primary entity
            graph_from = intent.graph_from or intent.primary_entity
            graph_start = intent.graph_start or "$_id"
            
            # Try to infer connection fields based on common patterns
            if not intent.graph_connect_from or not intent.graph_connect_to:
                # Common dependency patterns
                if "dependency" in str(intent.filters).lower() or "depends" in str(intent.filters).lower():
                    graph_connect_from = intent.graph_connect_from or "_id"
                    graph_connect_to = intent.graph_connect_to or "dependsOn"
                elif intent.primary_entity == "project":
                    graph_connect_from = intent.graph_connect_from or "_id"
                    graph_connect_to = intent.graph_connect_to or "parentProjectId"
                elif intent.primary_entity == "workItem":
                    graph_connect_from = intent.graph_connect_from or "_id"
                    graph_connect_to = intent.graph_connect_to or "dependsOn"
                else:
                    graph_connect_from = intent.graph_connect_from or "_id"
                    graph_connect_to = intent.graph_connect_to or "relatedId"
            else:
                graph_connect_from = intent.graph_connect_from
                graph_connect_to = intent.graph_connect_to
            
            graph_lookup_stage = {
                "$graphLookup": {
                    "from": graph_from,
                    "startWith": graph_start,
                    "connectFromField": graph_connect_from,
                    "connectToField": graph_connect_to,
                    "as": "graph_path",
                    "maxDepth": 5,
                    "depthField": "depth"
                }
            }
            pipeline.append(graph_lookup_stage)

        # Add time-series analysis stages (can be combined, so use separate if statements)
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
        print("The generated pipeline is:",pipeline)
        return pipeline

    def _extract_primary_filters(self, filters: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Extract filters that apply to the primary collection"""
        primary_filters = {}

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

                m2 = re.fullmatch(r"([0-9]+)\s*(d|h)", s)
                if m2:
                    n = int(m2.group(1))
                    unit = m2.group(2)
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
                    m = re.fullmatch(r"now\s*[-+]\s*([0-9]+)\s*(d|day|days|h|hour|hours)", s)
                    if m:
                        n = int(m.group(1))
                        unit = m.group(2)
                        if unit in {"d", "day", "days"}:
                            return datetime.now(timezone.utc) - timedelta(days=n)
                        if unit in {"h", "hour", "hours"}:
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

        if collection == "workItem":
            if 'status' in filters:
                primary_filters['status'] = filters['status']
            if 'priority' in filters:
                primary_filters['priority'] = filters['priority']
            if 'state' in filters:
                # Map logical state filter to embedded field
                primary_filters['state.name'] = filters['state']
            # Exclude states (array) support, mapped to state.name not-in
            if 'state_not' in filters and isinstance(filters['state_not'], list) and filters['state_not']:
                primary_filters['state.name'] = primary_filters.get('state.name') or {}
                # If previously set to a scalar via 'state', turn into $nin with preservation
                if isinstance(primary_filters['state.name'], str):
                    primary_filters['state.name'] = {"$in": [primary_filters['state.name']]}
                # Merge not-in
                primary_filters['state.name']["$nin"] = filters['state_not']
            if 'label_name' in filters and isinstance(filters['label_name'], str):
                primary_filters['label.name'] = {'$regex': filters['label_name'], '$options': 'i'}
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'displayBugNo' in filters and isinstance(filters['displayBugNo'], str):
                primary_filters['displayBugNo'] = {'$regex': f"^{filters['displayBugNo']}", '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)
            # Support dueDate ranges uniformly
            _apply_date_range(primary_filters, 'dueDate', filters)

        elif collection == "project":
            if 'project_status' in filters:
                primary_filters['status'] = filters['project_status']
            if 'status' in filters and 'status' not in primary_filters:
                primary_filters['status'] = filters['status']
            if 'isActive' in filters:
                primary_filters['isActive'] = bool(filters['isActive'])
            if 'isArchived' in filters:
                primary_filters['isArchived'] = bool(filters['isArchived'])
            if 'access' in filters:
                primary_filters['access'] = filters['access']
            if 'isFavourite' in filters:
                # Some schemas use 'favourite' on projects
                primary_filters['favourite'] = bool(filters['isFavourite'])
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'lead_name' in filters and isinstance(filters['lead_name'], str):
                primary_filters['lead.name'] = {'$regex': filters['lead_name'], '$options': 'i'}
            if 'leadMail' in filters and isinstance(filters['leadMail'], str):
                primary_filters['leadMail'] = {'$regex': f"^{filters['leadMail']}", '$options': 'i'}
            if 'projectDisplayId' in filters and isinstance(filters['projectDisplayId'], str):
                primary_filters['projectDisplayId'] = {'$regex': f"^{filters['projectDisplayId']}", '$options': 'i'}
            if 'name' in filters and isinstance(filters['name'], str):
                primary_filters['name'] = {'$regex': filters['name'], '$options': 'i'}
            if 'business_name' in filters and isinstance(filters['business_name'], str):
                primary_filters['business.name'] = {'$regex': filters['business_name'], '$options': 'i'}
            # default assignee (object): allow name filtering
            if 'defaultAssignee_name' in filters and isinstance(filters['defaultAssignee_name'], str):
                primary_filters['defaultAsignee.name'] = {'$regex': filters['defaultAssignee_name'], '$options': 'i'}
            if 'defaultAsignee_name' in filters and isinstance(filters['defaultAsignee_name'], str):
                primary_filters['defaultAsignee.name'] = {'$regex': filters['defaultAsignee_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "cycle":
            if 'cycle_status' in filters:
                primary_filters['status'] = filters['cycle_status']
            if 'status' in filters and 'status' not in primary_filters:
                primary_filters['status'] = filters['status']
            if 'isDefault' in filters:
                primary_filters['isDefault'] = bool(filters['isDefault'])
            if 'isFavourite' in filters:
                primary_filters['isFavourite'] = bool(filters['isFavourite'])
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            _apply_date_range(primary_filters, 'startDate', filters)
            _apply_date_range(primary_filters, 'endDate', filters)
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

            # Optional duration-based filtering in days: duration_days_from/to
            dur_from = filters.get('duration_days_from')
            dur_to = filters.get('duration_days_to')
            if dur_from is not None or dur_to is not None:
                dur_bounds: List[Dict[str, Any]] = []
                dur_expr = {
                    "$divide": [
                        {"$subtract": [
                            {"$ifNull": ["$endDate", "$$NOW"]},
                            "$startDate"
                        ]},
                        86400000
                    ]
                }
                try:
                    if dur_from is not None:
                        dur_from_val = float(dur_from)
                        dur_bounds.append({"$gte": [dur_expr, dur_from_val]})
                except Exception:
                    pass
                try:
                    if dur_to is not None:
                        dur_to_val = float(dur_to)
                        dur_bounds.append({"$lte": [dur_expr, dur_to_val]})
                except Exception:
                    pass
                if dur_bounds:
                    expr = {"$and": dur_bounds} if len(dur_bounds) > 1 else dur_bounds[0]
                    if "$expr" in primary_filters:
                        existing = primary_filters["$expr"]
                        primary_filters["$expr"] = {"$and": [existing, expr]}
                    else:
                        primary_filters["$expr"] = expr

        elif collection == "page":
            if 'page_visibility' in filters:
                primary_filters['visibility'] = filters['page_visibility']
            if 'visibility' in filters:
                primary_filters['visibility'] = filters['visibility']
            if 'isFavourite' in filters:
                primary_filters['isFavourite'] = bool(filters['isFavourite'])
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'locked' in filters:
                primary_filters['locked'] = bool(filters['locked'])
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdAt', filters)
            _apply_date_range(primary_filters, 'updatedAt', filters)

        elif collection == "module":
            if 'isFavourite' in filters:
                primary_filters['isFavourite'] = bool(filters['isFavourite'])
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'name' in filters and isinstance(filters['name'], str):
                primary_filters['name'] = {'$regex': filters['name'], '$options': 'i'}
            if 'business_name' in filters and isinstance(filters['business_name'], str):
                primary_filters['business.name'] = {'$regex': filters['business_name'], '$options': 'i'}
            if 'lead_name' in filters and isinstance(filters['lead_name'], str):
                primary_filters['lead.name'] = {'$regex': filters['lead_name'], '$options': 'i'}
            if 'assignee_name' in filters and isinstance(filters['assignee_name'], str):
                # module.assignee can be array of member subdocs
                primary_filters['assignee.name'] = {'$regex': filters['assignee_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)

        elif collection == "members":
            if 'role' in filters and isinstance(filters['role'], str):
                primary_filters['role'] = {'$regex': f"^{filters['role']}$", '$options': 'i'}
            if 'type' in filters and isinstance(filters['type'], str):
                primary_filters['type'] = {'$regex': f"^{filters['type']}$", '$options': 'i'}
            if 'name' in filters and isinstance(filters['name'], str):
                primary_filters['name'] = {'$regex': filters['name'], '$options': 'i'}
            if 'email' in filters and isinstance(filters['email'], str):
                primary_filters['email'] = {'$regex': f"^{filters['email']}", '$options': 'i'}
            if 'project_name' in filters and isinstance(filters['project_name'], str):
                primary_filters['project.name'] = {'$regex': filters['project_name'], '$options': 'i'}
            if 'staff_name' in filters and isinstance(filters['staff_name'], str):
                primary_filters['staff.name'] = {'$regex': filters['staff_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'joiningDate', filters)

        elif collection == "projectState":
            if 'name' in filters and isinstance(filters['name'], str):
                primary_filters['name'] = {'$regex': filters['name'], '$options': 'i'}
            if 'sub_state_name' in filters and isinstance(filters['sub_state_name'], str):
                primary_filters['subStates.name'] = {'$regex': filters['sub_state_name'], '$options': 'i'}

        elif collection == "epic":
            if 'priority' in filters:
                primary_filters['priority'] = filters['priority']
            if 'state' in filters:
                # Map logical state filter to embedded field
                primary_filters['state.name'] = filters['state']
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'label_name' in filters and isinstance(filters['label_name'], str):
                primary_filters['label.name'] = {'$regex': filters['label_name'], '$options': 'i'}
            if 'project_name' in filters and isinstance(filters['project_name'], str):
                primary_filters['project.name'] = {'$regex': filters['project_name'], '$options': 'i'}
            if 'assignee_name' in filters and isinstance(filters['assignee_name'], str):
                # epic.assignee can be array of member subdocs
                primary_filters['assignee.name'] = {'$regex': filters['assignee_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)

        elif collection == "features":
            if 'priority' in filters:
                primary_filters['priority'] = filters['priority']
            if 'state' in filters:
                # Map logical state filter to embedded field
                primary_filters['state.name'] = filters['state']
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'label_name' in filters and isinstance(filters['label_name'], str):
                primary_filters['label.name'] = {'$regex': filters['label_name'], '$options': 'i'}
            if 'project_name' in filters and isinstance(filters['project_name'], str):
                primary_filters['project.name'] = {'$regex': filters['project_name'], '$options': 'i'}
            if 'assignee_name' in filters and isinstance(filters['assignee_name'], str):
                # features.assignee can be array of member subdocs
                primary_filters['assignee.name'] = {'$regex': filters['assignee_name'], '$options': 'i'}
            if 'lead_name' in filters and isinstance(filters['lead_name'], str):
                primary_filters['lead.name'] = {'$regex': filters['lead_name'], '$options': 'i'}
            if 'cycle_name' in filters and isinstance(filters['cycle_name'], str):
                primary_filters['cycle.name'] = {'$regex': filters['cycle_name'], '$options': 'i'}
            if 'module_name' in filters and isinstance(filters['module_name'], str):
                primary_filters['modules.name'] = {'$regex': filters['module_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)
            _apply_date_range(primary_filters, 'startDate', filters)
            _apply_date_range(primary_filters, 'endDate', filters)

        elif collection == "userStory":
            if 'priority' in filters:
                primary_filters['priority'] = filters['priority']
            if 'state' in filters:
                # Map logical state filter to embedded field
                primary_filters['state.name'] = filters['state']
            if 'createdBy_name' in filters and isinstance(filters['createdBy_name'], str):
                primary_filters['createdBy.name'] = {'$regex': filters['createdBy_name'], '$options': 'i'}
            if 'title' in filters and isinstance(filters['title'], str):
                primary_filters['title'] = {'$regex': filters['title'], '$options': 'i'}
            if 'label_name' in filters and isinstance(filters['label_name'], str):
                primary_filters['label.name'] = {'$regex': filters['label_name'], '$options': 'i'}
            if 'project_name' in filters and isinstance(filters['project_name'], str):
                primary_filters['project.name'] = {'$regex': filters['project_name'], '$options': 'i'}
            if 'assignee_name' in filters and isinstance(filters['assignee_name'], str):
                # userStory.assignee can be array of member subdocs
                primary_filters['assignee.name'] = {'$regex': filters['assignee_name'], '$options': 'i'}
            if 'epic_name' in filters and isinstance(filters['epic_name'], str):
                primary_filters['epic.name'] = {'$regex': filters['epic_name'], '$options': 'i'}
            if 'feature_name' in filters and isinstance(filters['feature_name'], str):
                primary_filters['feature.name'] = {'$regex': filters['feature_name'], '$options': 'i'}
            _apply_date_range(primary_filters, 'createdTimeStamp', filters)
            _apply_date_range(primary_filters, 'updatedTimeStamp', filters)
            _apply_date_range(primary_filters, 'startDate', filters)
            _apply_date_range(primary_filters, 'dueDate', filters)

        # Handle array size filters (e.g., assignee_count: ">1")
        array_size_filters = {}
        array_field_map = {
            'assignee_count': 'assignee',
            'label_count': 'label',
            'customProperties_count': 'customProperties',
            'functionalRequirements_count': 'requirements.functionalRequirements',
            'nonFunctionalRequirements_count': 'requirements.nonFunctionalRequirements',
            'dependencies_count': 'riskAndDependencies.dependencies',
            'risks_count': 'riskAndDependencies.risks',
            'workItems_count': 'workItems',
            'userStories_count': 'userStories',
            'goals_count': 'goals',
            'painPoints_count': 'painPoints',
            'successCriteria_count': 'problemInfo.successCriteria',
            'linkedCycle_count': 'linkedCycle',
            'linkedModule_count': 'linkedModule',
            'linkedPages_count': 'linkedPages'
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
            "workItem": [
                "displayBugNo", "title", "priority",
                "state.name", "assignee","label.name",
                "project.name", "cycle.name", "modules.name",
                "createdTimeStamp", "estimateSystem", "estimate", "workLogs"
            ],
            "project": [
                "projectDisplayId", "name", "status", "isActive", "isArchived", "createdTimeStamp",
                "createdBy.name", "lead.name", "leadMail", "defaultAsignee.name"
            ],
            "cycle": [
                "title", "status", "startDate", "endDate", "projectName", "projectId"
            ],
            "members": [
                "name", "email", "role", "joiningDate", "projectName", "projectId"
            ],
            "page": [
                "title", "visibility", "createdAt", "projectName", "projectId"
            ],
            "module": [
                "title", "description", "isFavourite", "createdTimeStamp", "projectName", "projectId"
            ],
            "projectState": [
                "name", "subStates.name", "subStates.order"
            ],
            "epic": [
                "title", "priority", "state.name", "createdTimeStamp", "project.name","description","assignee.name","bugNo","label.name"
            ],
            "features": [
                "basicInfo","problemInfo","persona","displayBugNo","requirements","riskAndDependencies","createdBy.name","project.name","createdAt","scope",
                "workItems","userStories","addLink","goals","painPoints","title","description","startDate","endDate","releaseDate","state.name",
                "business.name","lead.name","priority","assignee","label","cycle","modules.name","parent.name","workLogs","estimatesystem","estimate"
            ],
            "userStory":[
                "displayBugNo","userGoal","persona","demographics","feature.name","acceptanceCriteria","epic.name","createdBy.name","createdAt","title","description",
                "state.name","business.name","priority","assignee","label"
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
            if entity == 'page':
                return 'createdAt' if which == 'created' else 'updatedAt'
            if entity == 'timeline':
                # timeline stores a single 'timestamp' field for event time
                return 'timestamp'
            # Default to *TimeStamp for other entities
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
            'workItem': {
                'project': 'project.name',
                'assignee': 'assignee.name',
                'cycle': 'cycle.name',
                'module': 'modules.name',
                'state': 'state.name',
                'label': 'label.name',
                'status': 'state.name',  # accept 'status' as synonym for state
                'priority': 'priority',
                'business': 'projectDoc.business.name',  # ensure join if needed
                'created_day': bucket_expr('workItem', 'created', 'day'),
                'created_week': bucket_expr('workItem', 'created', 'week'),
                'created_month': bucket_expr('workItem', 'created', 'month'),
                'updated_day': bucket_expr('workItem', 'updated', 'day'),
                'updated_week': bucket_expr('workItem', 'updated', 'week'),
                'updated_month': bucket_expr('workItem', 'updated', 'month'),
            },
            'project': {
                'status': 'status',
                'business': 'business.name',
                'created_day': bucket_expr('project', 'created', 'day'),
                'created_week': bucket_expr('project', 'created', 'week'),
                'created_month': bucket_expr('project', 'created', 'month'),
                'updated_day': bucket_expr('project', 'updated', 'day'),
                'updated_week': bucket_expr('project', 'updated', 'week'),
                'updated_month': bucket_expr('project', 'updated', 'month'),
            },
            'cycle': {
                'project': 'project.name',
                'status': 'status',
                'created_day': bucket_expr('cycle', 'created', 'day'),
                'created_week': bucket_expr('cycle', 'created', 'week'),
                'created_month': bucket_expr('cycle', 'created', 'month'),
                'updated_day': bucket_expr('cycle', 'updated', 'day'),
                'updated_week': bucket_expr('cycle', 'updated', 'week'),
                'updated_month': bucket_expr('cycle', 'updated', 'month'),
            },
            'page': {
                'project': 'projectDoc.name',
                'cycle': 'linkedCycleDocs.name',
                'module': 'linkedModuleDocs.name',
                'visibility': 'visibility',
                'business': 'projectDoc.business.name',
                'created_day': bucket_expr('page', 'created', 'day'),
                'created_week': bucket_expr('page', 'created', 'week'),
                'created_month': bucket_expr('page', 'created', 'month'),
                'updated_day': bucket_expr('page', 'updated', 'day'),
                'updated_week': bucket_expr('page', 'updated', 'week'),
                'updated_month': bucket_expr('page', 'updated', 'month'),
            },
            'module': {
                'project': 'project.name',
                'business': 'project.business.name',
                'created_day': bucket_expr('module', 'created', 'day'),
                'created_week': bucket_expr('module', 'created', 'week'),
                'created_month': bucket_expr('module', 'created', 'month'),
            },
            'members': {
                'project': 'project.name',
                'business': 'project.business.name',
                'created_day': bucket_expr('members', 'created', 'day'),
                'created_week': bucket_expr('members', 'created', 'week'),
                'created_month': bucket_expr('members', 'created', 'month'),
            },
            'projectState': {
                'project': 'project.name',
                'business': 'project.business.name',
            },
            'timeline': {
                'project': 'project.name',
                'status': 'type',
                'assignee': 'user.name',
                'created_day': bucket_expr('timeline', 'created', 'day'),
                'created_week': bucket_expr('timeline', 'created', 'week'),
                'created_month': bucket_expr('timeline', 'created', 'month'),
                'updated_day': bucket_expr('timeline', 'updated', 'day'),
                'updated_week': bucket_expr('timeline', 'updated', 'week'),
                'updated_month': bucket_expr('timeline', 'updated', 'month'),
            },
        }
        entity_map = mapping.get(primary_entity, {})
        val = entity_map.get(token)
        # Some bucket_expr entries may be None if field not applicable
        return val if val is not None else None
