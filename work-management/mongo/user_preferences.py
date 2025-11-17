"""
User Preferences Storage and Management

Stores user preferences using Mem0 for memory management.
Also maintains MongoDB storage for backward compatibility.
Provides caching layer for efficient access.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from cachetools import TTLCache
from mongo.client import direct_mongo_client
from mongo.constants import DATABASE_NAME, uuid_str_to_mongo_binary
from agent.knowledge_graph.client import mem0_wrapper
from agent.knowledge_graph.config import create_preference_memory

logger = logging.getLogger(__name__)

# MongoDB collection for user preferences
USER_PREFERENCES_COLLECTION = "user_preferences"

# Cache for user preferences (TTL: 1 hour)
_preferences_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)


class UserPreferences:
    """Manages user preferences storage and retrieval using Mem0"""
    
    def __init__(self):
        self.mem0 = mem0_wrapper
    
    async def initialize(self):
        """Initialize MongoDB connection (for backward compatibility)"""
        await direct_mongo_client.connect()
    
    def _get_cache_key(self, user_id: str, business_id: str) -> str:
        """Generate cache key"""
        return f"{user_id}:{business_id}"
    
    async def get_preferences(self, user_id: str, business_id: str) -> Dict[str, Any]:
        """Get user preferences with caching - uses Mem0 as primary source"""
        cache_key = self._get_cache_key(user_id, business_id)
        
        # Check cache first
        cached = _preferences_cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            # Try Mem0 first
            try:
                mem0_preferences = await self.mem0.get_all_memories(
                    user_id=user_id,
                    business_id=business_id,
                    memory_types=["user_preference"]
                )
                
                # Extract preferences from Mem0 memories
                preferences_dict = {}
                for memory in mem0_preferences:
                    content = memory.get("content", "")
                    metadata = memory.get("metadata", {})
                    # Extract preference type and value from content or metadata
                    if "responseTone" in content.lower() or metadata.get("type") == "responseTone":
                        preferences_dict["responseTone"] = metadata.get("value") or content.split(":")[-1].strip()
                    elif "domainFocus" in content.lower() or metadata.get("type") == "domainFocus":
                        preferences_dict["domainFocus"] = metadata.get("value") or content.split(":")[-1].strip()
                    elif "rememberLongTermContext" in content.lower() or metadata.get("type") == "rememberLongTermContext":
                        preferences_dict["rememberLongTermContext"] = metadata.get("value", True)
                
                if preferences_dict:
                    result = {
                        "user_id": user_id,
                        "business_id": business_id,
                        "preferences": preferences_dict,
                        "updated_at": datetime.now(),
                    }
                    _preferences_cache[cache_key] = result
                    return result
            except Exception as e:
                logger.debug(f"Mem0 retrieval failed, falling back to MongoDB: {e}")
            
            # Fallback to MongoDB for backward compatibility
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_PREFERENCES_COLLECTION]
            
            # Convert UUIDs to binary for query
            user_bin = uuid_str_to_mongo_binary(user_id)
            business_bin = uuid_str_to_mongo_binary(business_id)
            
            doc = await col.find_one({
                "user_id": user_bin,
                "business_id": business_bin,
            })
            
            if doc:
                # Convert binary UUIDs back to strings
                preferences = {
                    "user_id": str(user_id),
                    "business_id": str(business_id),
                    "preferences": doc.get("preferences", {}),
                    "updated_at": doc.get("updated_at"),
                }
            else:
                # Return default preferences
                preferences = {
                    "user_id": user_id,
                    "business_id": business_id,
                    "preferences": {},
                    "updated_at": None,
                }
            
            # Cache the result
            _preferences_cache[cache_key] = preferences
            return preferences
            
        except Exception as e:
            logger.error(f"Failed to get preferences for user {user_id}: {e}")
            return {
                "user_id": user_id,
                "business_id": business_id,
                "preferences": {},
                "updated_at": None,
            }
    
    async def update_preferences(
        self,
        user_id: str,
        business_id: str,
        preferences: Dict[str, Any]
    ) -> bool:
        """Update user preferences in Mem0 and MongoDB (for backward compatibility)"""
        try:
            # Store preferences in Mem0
            try:
                messages = []
                for pref_type, pref_value in preferences.items():
                    if pref_type in ["responseTone", "domainFocus", "rememberLongTermContext", "showAgentInternals"]:
                        messages.append(create_preference_memory(pref_type, pref_value))
                
                if messages:
                    await self.mem0.add_memory(
                        user_id=user_id,
                        business_id=business_id,
                        messages=messages,
                        metadata={"source": "explicit", "type": "user_preference"}
                    )
            except Exception as e:
                logger.warning(f"Failed to update preferences in Mem0: {e}")
            
            # Also update MongoDB for backward compatibility
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_PREFERENCES_COLLECTION]
            
            # Convert UUIDs to binary for storage
            user_bin = uuid_str_to_mongo_binary(user_id)
            business_bin = uuid_str_to_mongo_binary(business_id)
            
            # Update MongoDB
            await col.update_one(
                {
                    "user_id": user_bin,
                    "business_id": business_bin,
                },
                {
                    "$set": {
                        "preferences": preferences,
                        "updated_at": datetime.now(),
                    },
                    "$setOnInsert": {
                        "user_id": user_bin,
                        "business_id": business_bin,
                        "created_at": datetime.now(),
                    },
                },
                upsert=True
            )
            
            # Invalidate cache
            cache_key = self._get_cache_key(user_id, business_id)
            _preferences_cache.pop(cache_key, None)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update preferences for user {user_id}: {e}")
            return False
    
    async def delete_preferences(self, user_id: str, business_id: str) -> bool:
        """Delete user preferences"""
        try:
            await self.initialize()
            db = direct_mongo_client.client[DATABASE_NAME]
            col = db[USER_PREFERENCES_COLLECTION]
            
            user_bin = uuid_str_to_mongo_binary(user_id)
            business_bin = uuid_str_to_mongo_binary(business_id)
            
            await col.delete_one({
                "user_id": user_bin,
                "business_id": business_bin,
            })
            
            # Invalidate cache
            cache_key = self._get_cache_key(user_id, business_id)
            _preferences_cache.pop(cache_key, None)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete preferences for user {user_id}: {e}")
            return False


# Global instance
user_preferences = UserPreferences()

