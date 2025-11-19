#!/usr/bin/env python3
"""Direct MongoDB client using PyMongo - replacing MongoDB MCP"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import Dict, Any, List
import os
import contextlib
import asyncio
import logging
import json
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
                            # Handle different business field formats across collections
                            if collection == "segmentation":
                                # Segmentation uses embedded business object
                                injected_stages.append({"$match": {"business._id": biz_bin}})
                            else:
                                # Most collections use direct businessId field
                                injected_stages.append({"$match": {"businessId": biz_bin}})
                    except ValueError as e:
                        # Invalid UUID format - log and skip business filter
                        logger.error(f"Invalid BUSINESS_UUID format '{biz_uuid}': {e}")
                    except Exception as e:
                        # Other errors - log and skip business filter
                        logger.error(f"Error applying business filter for {collection}: {e}")

                # 2) Member-level scoping (if needed in future)
                # For now, CRM doesn't have member-level filtering like work-management
                # This can be added later if needed

                # Execute aggregation - Motor uses persistent connection pool
                db = self.client[database]
                coll = db[collection]
                
                # Print MongoDB query details
                print(f"\n{'='*80}")
                print(f"MONGO QUERY EXECUTION")
                print(f"{'='*80}")
                print(f"Database: {database}")
                print(f"Collection: {collection}")
                print(f"Pipeline: {pipeline}")
                if injected_stages:
                    print(f"Injected business filter stages: {injected_stages}")
                print(f"{'='*80}\n")
                
                effective_pipeline = (injected_stages + pipeline) if injected_stages else pipeline
                cursor = coll.aggregate(effective_pipeline)
                results = await cursor.to_list(length=None)
                
                # Print MongoDB query results
                print(f"\n{'='*80}")
                print(f"MONGO QUERY RESULTS ({len(results)} document(s))")
                print(f"{'='*80}")
                print(json.dumps(results, indent=2, default=str))
                print(f"{'='*80}\n")
                
                pass
                
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
        else:
            raise ValueError(f"Tool '{tool_name}' not supported by direct client. Only 'aggregate' is implemented.")


# Global instance - drop-in replacement for mongodb_tools
direct_mongo_client = DirectMongoClient()

