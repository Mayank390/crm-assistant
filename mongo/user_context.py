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

logger = logging.getLogger(__name__)

# MongoDB collection for user context documents
USER_CONTEXT_COLLECTION = "user_context"


class UserContext:
    """Manages long-term context documents for users"""
    
    def __init__(self):
        # Note: Mem0 integration can be added later if needed
        pass
    
    async def initialize(self):
        """Initialize MongoDB connection"""
        await direct_mongo_client.connect()
    
    async def create_context_document(
        self,
        user_id: str,
        business_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "explicit"
    ) -> Optional[str]:
        """Create a new context document - stores in MongoDB"""
        try:
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
                "source": source,
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
        """Get all context documents for a user"""
        try:
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

