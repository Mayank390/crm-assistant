"""
User Preferences Storage and Management

Stores user preferences in MongoDB.
Provides caching layer for efficient access.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from cachetools import TTLCache
from mongo.client import direct_mongo_client
from mongo.constants import DATABASE_NAME, uuid_str_to_mongo_binary

logger = logging.getLogger(__name__)

# MongoDB collection for user preferences
USER_PREFERENCES_COLLECTION = "user_preferences"

# Cache for user preferences (TTL: 1 hour)
_preferences_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)


class UserPreferences:
    """Manages user preferences storage and retrieval"""
    
    def _get_cache_key(self, user_id: str, business_id: str) -> str:
        """Generate cache key"""
        return f"{user_id}:{business_id}"
    
    async def get_preferences(self, user_id: str, business_id: str) -> Dict[str, Any]:
        """Get user preferences with caching"""
        cache_key = self._get_cache_key(user_id, business_id)
        
        # Check cache first
        cached = _preferences_cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            await direct_mongo_client.connect()
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
        """Update user preferences in MongoDB"""
        try:
            await direct_mongo_client.connect()
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
            await direct_mongo_client.connect()
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

