#!/usr/bin/env python3
"""Direct MongoDB client using PyMongo - replacing MongoDB MCP"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import Dict, Any, List
import os
import contextlib
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)
from mongo.constants import (
    DATABASE_NAME,
    MONGODB_CONNECTION_STRING,
    uuid_str_to_mongo_binary,
    COLLECTIONS_WITH_DIRECT_BUSINESS,
    BUSINESS_UUID,
    MEMBER_UUID,
)


class DirectMongoClient:
    """Direct MongoDB client using Motor (async PyMongo) - replaces MongoDB MCP"""

    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.connected = False
        self._connect_lock = asyncio.Lock()

    async def connect(self):
        """Initialize direct MongoDB connection with persistent connection pool"""
        span_cm = contextlib.nullcontext()
        with span_cm as span:
            try:
                async with self._connect_lock:
                    if self.connected and self.client:
                        return

                    # Create Motor client with optimized connection pool settings
                    # Motor maintains persistent connections automatically
                    self.client = AsyncIOMotorClient(
                        MONGODB_CONNECTION_STRING,
                        maxPoolSize=50,          # Max connections in pool
                        minPoolSize=10,          # Keep minimum connections alive
                        maxIdleTimeMS=45000,     # Keep idle connections for 45s
                        waitQueueTimeoutMS=5000, # Faster timeout for queue
                        serverSelectionTimeoutMS=5000,  # Faster server selection
                        connectTimeoutMS=10000,  # Connection timeout
                        socketTimeoutMS=20000,   # Socket timeout
                    )

                    # Test connection
                    await self.client.admin.command('ping')

                    self.connected = True

            except Exception as e:
                logger.error(f"Failed to connect to MongoDB: {e}")
                raise

    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
        self.connected = False
        self.client = None

    async def aggregate(self, database: str, collection: str, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute MongoDB aggregation pipeline directly
        
        This replaces mongodb_tools.execute_tool("aggregate", {...})
        
        Args:
            database: Database name
            collection: Collection name
            pipeline: MongoDB aggregation pipeline
            
        Returns:
            List of result documents
        """
        span_cm = contextlib.nullcontext()
        with span_cm as span:
            pass
            
            # Motor maintains persistent connection pool automatically
            # No need to check connection status on every query - massive latency savings!
            if not self.client:
                raise RuntimeError("MongoDB client not initialized. Call connect() first.")
            
            try:
                # --- Resolve RBAC context at query time ---
                def _flag(name: str) -> bool:
                    return os.getenv(name, "").lower() in ("1", "true", "yes")

                # Prefer runtime websocket context; fall back to env vars (via helpers)
                biz_uuid: str | None = BUSINESS_UUID()
                member_uuid: str | None = MEMBER_UUID()
                enforce_business: bool = _flag("ENFORCE_BUSINESS_FILTER") or bool(biz_uuid)
                enforce_member: bool = _flag("ENFORCE_MEMBER_FILTER") or bool(member_uuid)

                # Prepare business and member scoping injections (prepend stages)
                injected_stages: List[Dict[str, Any]] = []

                # 1) Business scoping
                if enforce_business and biz_uuid:
                    try:
                        biz_bin = uuid_str_to_mongo_binary(biz_uuid)
                        if collection in COLLECTIONS_WITH_DIRECT_BUSINESS:
                            injected_stages.append({"$match": {"business._id": biz_bin}})
                        elif collection == "members":
                            # Join project to filter by its business
                            injected_stages.extend([
                                {"$lookup": {
                                    "from": "project",
                                    "localField": "project._id",
                                    "foreignField": "_id",
                                    "as": "__biz_proj__"
                                }},
                                {"$match": {"__biz_proj__.business._id": biz_bin}},
                                {"$unset": "__biz_proj__"},
                            ])
                        elif collection == "projectState":
                            injected_stages.extend([
                                {"$lookup": {
                                    "from": "project",
                                    "localField": "projectId",
                                    "foreignField": "_id",
                                    "as": "__biz_proj__"
                                }},
                                {"$match": {"__biz_proj__.business._id": biz_bin}},
                                {"$unset": "__biz_proj__"},
                            ])
                    except ValueError as e:
                        # Invalid UUID format - log and skip business filter
                        logger.error(f"Invalid BUSINESS_UUID format '{biz_uuid}': {e}")
                    except Exception as e:
                        # Other errors - log and skip business filter
                        logger.error(f"Error applying business filter for {collection}: {e}")

                # 2) Member-level project RBAC scoping
                if enforce_member and member_uuid:
                    try:
                        mem_bin = uuid_str_to_mongo_binary(member_uuid)

                        def _membership_join(local_field: str) -> List[Dict[str, Any]]:
                            """Build a $lookup + $match + $unset pipeline ensuring the document's project belongs to member."""
                            return [
                                {"$lookup": {
                                    "from": "members",
                                    "localField": local_field,
                                    "foreignField": "project._id",
                                    "as": "__mem__",
                                }},
                                # Ensure at least one membership document for this member
                                # memberId is the staff ID (staff identifier)
                                {"$match": {"__mem__": {"$elemMatch": {"$or": [
                                    {"memberId": mem_bin},
                                    {"staff._id": mem_bin}
                                ]}}}},
                                {"$unset": "__mem__"},
                            ]

                        if collection == "members":
                            # Only allow viewing own memberships
                            # memberId is the staff ID (staff identifier)
                            injected_stages.append({"$match": {"$or": [
                                {"memberId": mem_bin},
                                {"staff._id": mem_bin}
                            ]}})
                        elif collection == "project":
                            injected_stages.extend(_membership_join("_id"))
                        elif collection in ("workItem", "cycle", "module", "page"):
                            injected_stages.extend(_membership_join("project._id"))
                        elif collection == "projectState":
                            injected_stages.extend(_membership_join("projectId"))
                        # Other collections: no-op
                    except ValueError as e:
                        # Invalid UUID format - log and skip member filter
                        logger.error(f"Invalid MEMBER_UUID format '{member_uuid}': {e}")
                    except Exception as e:
                        # Other errors - log and skip member filter
                        logger.error(f"Error applying member filter for {collection}: {e}")

                # Execute aggregation - Motor uses persistent connection pool
                db = self.client[database]
                coll = db[collection]
                effective_pipeline = (injected_stages + pipeline) if injected_stages else pipeline
                cursor = coll.aggregate(effective_pipeline)
                results = await cursor.to_list(length=None)
                
                pass
                
                return results
                
            except Exception as e:
                pass
                raise

    async def aggregate_smart(self, database: str, collection: str, pipeline: List[Dict[str, Any]], project_id: str) -> List[Dict[str, Any]]:
        """Execute MongoDB aggregation pipeline directly
        
        This replaces mongodb_tools.execute_tool("aggregate", {...})
        
        Args:
            database: Database name
            collection: Collection name
            pipeline: MongoDB aggregation pipeline
            project_id: Project UUID for RBAC scoping
        Returns:
            List of result documents
        """
        span_cm = contextlib.nullcontext()
        with span_cm as span:
            pass
        injected_stages: List[Dict[str, Any]] = []
        try:    
            # Motor maintains persistent connection pool automatically
            # No need to check connection status on every query - massive latency savings!
            if not self.client:
                raise RuntimeError("MongoDB client not initialized. Call connect() first.")
            
            if project_id:
                try:
                    pr_id = uuid_str_to_mongo_binary(project_id)

                    injected_stages.append({"$match": {"project._id": pr_id}})
                except ValueError as e:
                        # Invalid UUID format - log and skip project filter
                        logger.error(f"Invalid PROJECT_UUID format '{project_id}': {e}")
                except Exception as e:
                    # Other errors - log and skip project filter
                    logger.error(f"Error applying project filter for {collection}: {e}")
                        
                    

            # Execute aggregation - Motor uses persistent connection pool
            db = self.client[database]
            coll = db[collection]
            effective_pipeline = (injected_stages + pipeline) if injected_stages else pipeline
            cursor = coll.aggregate(effective_pipeline)
            results = await cursor.to_list(length=None)
                
            return results
        
        except Exception as e:
                pass
                raise

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Compatibility wrapper matching MongoDB MCP interface
        
        This maintains API compatibility with existing code that calls:
        mongodb_tools.execute_tool("aggregate", args)
        """
        if tool_name == "aggregate":
            database = arguments.get("database", DATABASE_NAME)
            collection = arguments["collection"]
            pipeline = arguments["pipeline"]
            return await self.aggregate(database, collection, pipeline)
        elif tool_name == "aggregate_smart":
            database = arguments.get("database", DATABASE_NAME)
            collection = arguments["collection"]
            pipeline = arguments["pipeline"]
            project_id = arguments.get("project_id")
            return await self.aggregate_smart(database, collection, pipeline, project_id)
        else:
            raise ValueError(f"Tool '{tool_name}' not supported by direct client. Only 'aggregate' is implemented.")


# Global instance - drop-in replacement for mongodb_tools
direct_mongo_client = DirectMongoClient()
