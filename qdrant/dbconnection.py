import os
import logging
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, OptimizersConfigDiff, SparseVectorParams
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# --- Connect to MongoDB ---
mongo_uri = os.getenv("MONGODB_URI", "mongodb://WebsiteBuilderAdmin:JfOCiOKMVgSIMPOBUILDERGkli8@13.90.63.91:27017,172.171.192.172:27017/ProjectManagement?authSource=admin&replicaSet=rs0")
mongo_database = os.getenv("MONGODB_DATABASE", "ProjectManagement")

mongo_client = None
db = None
page_collection = None
workitem_collection = None
cycle_collection = None
module_collection = None
project_collection = None
epic_collection = None
userStory_collection = None
features_collection = None

try:
    mongo_client = MongoClient(
        mongo_uri,
        directConnection=True,
        serverSelectionTimeoutMS=5000
    )

    # Try listing databases to confirm connection

    # Access your specific collections
    db = mongo_client[mongo_database]
    page_collection = db.get_collection("page")
    workitem_collection = db.get_collection("workItem")
    cycle_collection = db.get_collection("cycle")
    module_collection = db.get_collection("module")
    project_collection = db.get_collection("project")
    epic_collection = db.get_collection("epic")
    userStory_collection = db.get_collection("userStory")
    features_collection = db.get_collection("features")

except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")

# --- Connect to Qdrant ---
qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
qdrant_collection = os.getenv("QDRANT_COLLECTION", "ProjectManagement")

try:
    qdrant_client = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key or None,
        timeout=60 
    )

    # Check if collection exists, if not, create with named vectors + sparse for hybrid search
    existing_collections = qdrant_client.get_collections()
    existing_names = [col.name for col in getattr(existing_collections, "collections", [])]
    if qdrant_collection not in existing_names:
        qdrant_client.create_collection(
            collection_name=qdrant_collection,
            vectors_config={
                "dense": VectorParams(size=768, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(),
            },
        )
    
    # Force immediate indexing on this collection
    try:
        qdrant_client.update_collection(
            collection_name=qdrant_collection,
            optimizer_config=OptimizersConfigDiff(indexing_threshold=1)
        )
    except Exception as e:
        logger.warning(f"Failed to set optimizer config: {e}")

    # Try listing collections to confirm connection

except Exception as e:
    logger.error(f"Qdrant connection failed: {e}")

import asyncio

if __name__ == "__main__":
    # Test basic connection
    try:
        collections = qdrant_client.get_collections()
    except Exception as e:
        logger.error(f"Qdrant connection failed: {e}")

