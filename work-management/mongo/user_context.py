"""
User Context Storage for Long-term Context

Stores detailed long-term context documents using Mem0 for semantic retrieval.
Also maintains MongoDB storage for backward compatibility.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from mongo.client import direct_mongo_client
from mongo.constants import DATABASE_NAME, uuid_str_to_mongo_binary
from agent.knowledge_graph.client import mem0_wrapper
from agent.knowledge_graph.config import create_context_memory

logger = logging.getLogger(__name__)

# MongoDB collection for user context documents
USER_CONTEXT_COLLECTION = "user_context"


class UserContext:
    """Manages long-term context documents for users using Mem0"""
    
    def __init__(self):
        self.mem0 = mem0_wrapper
    
    async def initialize(self):
        """Initialize MongoDB connection (for backward compatibility)"""
        await direct_mongo_client.connect()
    
    async def create_context_document(
        self,
        user_id: str,
        business_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "explicit"
    ) -> Optional[str]:
        """Create a new context document - stores in Mem0 and MongoDB"""
        try:
            # Store in Mem0 for semantic retrieval
            try:
                # Create context memory with proper formatting
                context_mem = create_context_memory(content, document_id=None, source=source)
                # Merge additional metadata if provided
                if metadata:
                    context_mem["metadata"].update(metadata)
                messages = [context_mem]
                
                result = await self.mem0.add_memory(
                    user_id=user_id,
                    business_id=business_id,
                    messages=messages,
                    metadata={"source": source, "type": "user_context"}
                )
                
                # Extract memory ID if available
                memory_id = None
                if isinstance(result, dict):
                    memory_id = result.get("id") or result.get("memory_id")
            except Exception as e:
                logger.warning(f"Failed to store context in Mem0: {e}")
                memory_id = None
            
            # Also store in MongoDB for backward compatibility
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_CONTEXT_COLLECTION]
            
            user_bin = uuid_str_to_mongo_binary(user_id)
            business_bin = uuid_str_to_mongo_binary(business_id)
            
            doc = {
                "user_id": user_bin,
                "business_id": business_bin,
                "content": content,
                "metadata": metadata or {},
                "source": source,  # "explicit" or "learned"
                "mem0_id": memory_id,  # Store Mem0 ID for reference
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
            
            result = await col.insert_one(doc)
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Failed to create context document for user {user_id}: {e}")
            return None
    
    async def update_context_document(
        self,
        document_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update an existing context document"""
        try:
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_CONTEXT_COLLECTION]
            
            from bson import ObjectId
            update_doc = {"updated_at": datetime.now()}
            if content is not None:
                update_doc["content"] = content
            if metadata is not None:
                update_doc["metadata"] = metadata
            
            result = await col.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": update_doc}
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Failed to update context document {document_id}: {e}")
            return False
    
    async def get_user_context_documents(
        self,
        user_id: str,
        business_id: str,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all context documents for a user - uses Mem0 as primary source"""
        try:
            # Try Mem0 first
            try:
                mem0_memories = await self.mem0.get_all_memories(
                    user_id=user_id,
                    business_id=business_id,
                    memory_types=["user_context"]
                )
                
                documents = []
                for memory in mem0_memories[:limit]:
                    metadata = memory.get("metadata", {})
                    mem_source = metadata.get("source", "explicit")
                    
                    # Filter by source if specified
                    if source and mem_source != source:
                        continue
                    
                    documents.append({
                        "id": memory.get("id", ""),
                        "content": memory.get("content", ""),
                        "metadata": metadata,
                        "source": mem_source,
                        "created_at": memory.get("created_at"),
                        "updated_at": memory.get("updated_at"),
                    })
                
                if documents:
                    return documents
            except Exception as e:
                logger.debug(f"Mem0 retrieval failed, falling back to MongoDB: {e}")
            
            # Fallback to MongoDB for backward compatibility
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_CONTEXT_COLLECTION]
            
            user_bin = uuid_str_to_mongo_binary(user_id)
            business_bin = uuid_str_to_mongo_binary(business_id)
            
            query = {
                "user_id": user_bin,
                "business_id": business_bin,
            }
            if source:
                query["source"] = source
            
            documents = []
            cursor = col.find(query).sort("updated_at", -1).limit(limit)
            async for doc in cursor:
                documents.append({
                    "id": str(doc["_id"]),
                    "content": doc.get("content", ""),
                    "metadata": doc.get("metadata", {}),
                    "source": doc.get("source", "explicit"),
                    "created_at": doc.get("created_at"),
                    "updated_at": doc.get("updated_at"),
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to get context documents for user {user_id}: {e}")
            return []
    
    async def delete_context_document(self, document_id: str) -> bool:
        """Delete a context document"""
        try:
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_CONTEXT_COLLECTION]
            
            from bson import ObjectId
            result = await col.delete_one({"_id": ObjectId(document_id)})
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Failed to delete context document {document_id}: {e}")
            return False


# Global instance
user_context = UserContext()

