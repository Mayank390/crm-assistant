import os
import uuid
from bson.binary import Binary, UuidRepresentation
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database configuration
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "crm")
MONGODB_CONNECTION_STRING = os.getenv(
    "MONGODB_URI",
    "mongodb://Harshit:10_Harshith_29@4.213.88.219:27017/?authMechanism=DEFAULT&authSource=admin",
)

# Qdrant configuration
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")  # Default Qdrant URL
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "crm")  # Collection for CRM content
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")  # Sentence transformer model for embeddings
 
# Retrieval packing configuration
# Max tokens to allocate for retrieved context before sending to the LLM
# You can override via env: RAG_CONTEXT_TOKEN_BUDGET
RAG_CONTEXT_TOKEN_BUDGET: int = int(os.getenv("RAG_CONTEXT_TOKEN_BUDGET", "2200"))

# UUID conversion helpers
def uuid_str_to_mongo_binary(uuid_str: str) -> Binary:
    """Convert UUID string to MongoDB Binary format"""
    try:
        uuid_obj = uuid.UUID(uuid_str)
        return Binary.from_uuid(uuid_obj, uuid_representation=UuidRepresentation.STANDARD)
    except ValueError as e:
        raise ValueError(f"Invalid UUID format: {uuid_str}") from e

def mongo_binary_to_uuid_str(binary: Binary) -> str:
    """Convert MongoDB Binary UUID to string"""
    try:
        uuid_obj = binary.as_uuid()
        return str(uuid_obj)
    except Exception as e:
        raise ValueError(f"Invalid Binary UUID format: {binary}") from e

# Collections that have direct businessId field (for RBAC filtering)
COLLECTIONS_WITH_DIRECT_BUSINESS = {
    "Lead", "Task", "Activity", "Meeting", "Notes", "CallLog", "MailInfo", "LeadScoreRule"
}

# Runtime context helpers (can be overridden by websocket context)
def BUSINESS_UUID() -> str | None:
    """Get business UUID from runtime context or env"""
    # In production, this would come from websocket context
    return os.getenv("BUSINESS_UUID")

def MEMBER_UUID() -> str | None:
    """Get member UUID from runtime context or env"""
    # In production, this would come from websocket context
    return os.getenv("MEMBER_UUID")

class _LazyMongoDBTools:
    """Lazy wrapper to avoid circular imports"""
    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            from mongo.client import direct_mongo_client
            self._client = direct_mongo_client
        return getattr(self._client, name)

# Alias for backward compatibility with existing code
mongodb_tools = _LazyMongoDBTools()

