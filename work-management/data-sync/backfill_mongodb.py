#!/usr/bin/env python3
"""
Backfill script to import existing MongoDB data into the Kafka pipeline.

This script reads documents from MongoDB collections and sends them as change events
to Kafka topics, mimicking the MongoDB Kafka connector's behavior for existing data.
"""

import json
import os
import sys
import time
import logging
from typing import Dict, Any, List, Optional

import pymongo
from confluent_kafka import Producer
from confluent_kafka import KafkaError, KafkaException

# Import document normalization and point ID generation from consumer
from qdrant.indexing_shared import normalize_document_ids, point_id_from_seed, normalize_mongo_id

# Import Qdrant client to check for existing data
try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Configuration - match the connector setup
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://WebsiteBuilderAdmin:JfOCiOKMVgSIMPOBUILDERGkli8@13.90.63.91:27017,172.171.192.172:27017/ProjectManagement?authSource=admin&replicaSet=rs0"
)
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "ProjectManagement")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC_PREFIX = os.getenv("KAFKA_TOPIC_PREFIX", "ProjectManagement.")

# Collections to backfill - configurable via environment
BACKFILL_COLLECTIONS_STR = os.getenv("BACKFILL_COLLECTIONS", "epic,features,cycle,module,project,workItem,userStory,page")
COLLECTIONS_TO_BACKFILL = [col.strip() for col in BACKFILL_COLLECTIONS_STR.split(",") if col.strip()]

# Batch size for processing
BATCH_SIZE = int(os.getenv("BACKFILL_BATCH_SIZE", "1000"))
SLEEP_BETWEEN_BATCHES = float(os.getenv("BACKFILL_SLEEP", "1.0"))

# Default to production mode (not dry run)
DEFAULT_DRY_RUN = os.getenv("BACKFILL_DRY_RUN", "false").lower() == "true"

# Qdrant configuration for duplicate checking
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "ProjectManagement")

# Enable smart incremental backfill (only index missing documents)
INCREMENTAL_BACKFILL = os.getenv("INCREMENTAL_BACKFILL", "true").lower() == "true"

# Batch size for checking existing points in Qdrant
QDRANT_CHECK_BATCH_SIZE = int(os.getenv("QDRANT_CHECK_BATCH_SIZE", "1000"))


class MongoDBBackfill:
    """Handles backfilling MongoDB data to Kafka."""

    def __init__(self):
        self.mongo_client = None
        self.kafka_producer = None
        self.database = None
        self.qdrant_client = None

    def connect_mongodb(self) -> bool:
        """Connect to MongoDB."""
        try:
            self.mongo_client = pymongo.MongoClient(MONGODB_URI)
            self.database = self.mongo_client[DATABASE_NAME]

            # Test connection
            self.mongo_client.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False

    def connect_kafka(self) -> bool:
        """Connect to Kafka."""
        try:
            conf = {
                'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
                'acks': 'all',
                'retries': 3,
                'max.in.flight.requests.per.connection': 1,
                'delivery.timeout.ms': 30000,
                'request.timeout.ms': 10000
            }
            self.kafka_producer = Producer(conf)
            return True
        except Exception as e:
            logger.error(f"Kafka connection failed: {e}")
            return False

    def connect_qdrant(self) -> bool:
        """Connect to Qdrant to check for existing data."""
        if not QDRANT_AVAILABLE:
            logger.warning("Qdrant client not available, skipping duplicate check")
            return False
        try:
            self.qdrant_client = QdrantClient(url=QDRANT_URL)
            # Test connection
            self.qdrant_client.get_collections()
            return True
        except Exception as e:
            logger.warning(f"Qdrant connection failed: {e}, proceeding with backfill")
            return False

    def get_qdrant_point_count(self) -> int:
        """Get the current point count in Qdrant collection."""
        if not self.qdrant_client:
            return 0
        
        try:
            collections = self.qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            
            if QDRANT_COLLECTION not in collection_names:
                return 0
            
            collection_info = self.qdrant_client.get_collection(QDRANT_COLLECTION)
            return collection_info.points_count if hasattr(collection_info, 'points_count') else 0
        except Exception as e:
            logger.warning(f"Failed to get Qdrant point count: {e}")
            return 0

    def check_points_exist(self, point_ids: List[str]) -> set:
        """Check which point IDs already exist in Qdrant.
        
        Args:
            point_ids: List of point IDs to check
            
        Returns:
            Set of point IDs that exist in Qdrant
        """
        if not self.qdrant_client or not point_ids:
            return set()
        
        try:
            # Retrieve points by ID (only returns existing ones)
            result = self.qdrant_client.retrieve(
                collection_name=QDRANT_COLLECTION,
                ids=point_ids,
                with_payload=False,
                with_vectors=False
            )
            # Return set of IDs that exist
            return {str(point.id) for point in result}
        except Exception as e:
            logger.warning(f"Failed to check existing points: {e}, assuming none exist")
            return set()

    def check_documents_exist(self, mongo_ids: List[str]) -> set:
        """Check which documents already exist in Qdrant by mongo_id.

        Args:
            mongo_ids: List of MongoDB document IDs to check

        Returns:
            Set of mongo_ids that have at least one point in Qdrant
        """
        if not self.qdrant_client or not mongo_ids:
            return set()

        try:
            # Check if any points exist with these mongo_ids
            # We use a filter query to find points with matching mongo_id
            existing_mongo_ids = set()

            # Process in batches to avoid overwhelming Qdrant filter queries
            batch_size = 100
            for i in range(0, len(mongo_ids), batch_size):
                batch_mongo_ids = mongo_ids[i:i + batch_size]
                batch_found = set()  # Track found mongo_ids for this batch

                # Build filter for this batch
                should_conditions = []
                for mongo_id in batch_mongo_ids:
                    should_conditions.append(
                        qmodels.FieldCondition(
                            key="mongo_id",
                            match=qmodels.MatchValue(value=mongo_id),
                        )
                    )

                filter_query = qmodels.Filter(should=should_conditions)

                # Scroll with pagination to handle documents with multiple chunks
                # Limit per page: assume max 5 chunks per document
                scroll_limit = len(batch_mongo_ids) * 5
                next_page_offset = None
                max_pages = 100  # Safety limit to prevent infinite loops
                page_count = 0

                try:
                    while page_count < max_pages:
                        page_count += 1
                        
                        # Scroll with current offset
                        scroll_kwargs = {
                            "collection_name": QDRANT_COLLECTION,
                            "scroll_filter": filter_query,
                            "limit": scroll_limit,
                            "with_payload": True,  # Get full payload to access mongo_id
                            "with_vectors": False
                        }
                        if next_page_offset is not None:
                            scroll_kwargs["offset"] = next_page_offset

                        result = self.qdrant_client.scroll(**scroll_kwargs)

                        # Check if result exists and has points
                        if not result or not result[0]:
                            break

                        # Extract unique mongo_ids from results
                        for point in result[0]:
                            if hasattr(point, 'payload') and point.payload:
                                mongo_id = point.payload.get('mongo_id')
                                if mongo_id:
                                    batch_found.add(mongo_id)
                                    existing_mongo_ids.add(mongo_id)

                        # Early exit: if we've found all mongo_ids in this batch, stop paginating
                        if len(batch_found) >= len(batch_mongo_ids):
                            break

                        # Check for next page
                        # Scroll always returns a tuple: (points, next_page_offset)
                        if len(result) > 1:
                            next_offset = result[1]
                            # If next_offset is None, we've reached the end
                            if next_offset is None:
                                break
                            # Safety check: if offset hasn't changed, break to avoid infinite loop
                            if next_offset == next_page_offset:
                                logger.warning(f"Offset unchanged at {next_offset}, stopping pagination")
                                break
                            next_page_offset = next_offset
                        else:
                            # No more pages (shouldn't happen with proper Qdrant client, but safe check)
                            break

                except Exception as e:
                    logger.warning(f"Failed to check batch {i//batch_size + 1}: {e}")
                    continue

            return existing_mongo_ids

        except Exception as e:
            logger.warning(f"Failed to check existing documents: {e}, assuming none exist")
            return set()

    def generate_point_id_for_document(self, collection_name: str, document: Dict[str, Any]) -> Optional[str]:
        """Generate the deterministic point ID that would be used for this document in Qdrant.
        
        This matches the logic in the consumer/indexing pipeline.
        """
        try:
            # Normalize the document ID
            mongo_id = normalize_mongo_id(document.get("_id"))
            if not mongo_id:
                return None
            
            # Map collection names to content types (matching indexing_shared.py logic)
            content_type_map = {
                "page": "page",
                "workItem": "work_item",
                "project": "project",
                "cycle": "cycle",
                "module": "module",
                "epic": "epic",
                "feature": "feature",
                "features": "feature",
                "userStory": "user_story",
                "userStories": "user_story",
            }
            
            content_type = content_type_map.get(collection_name)
            if not content_type:
                logger.warning(f"Unknown collection type: {collection_name}")
                return None
            
            # Generate base point ID for chunk 0 (same as indexing pipeline)
            # Point IDs are generated as: "{mongo_id}/{content_type}/{chunk_index}"
            point_id = point_id_from_seed(f"{mongo_id}/{content_type}/0")
            return point_id
            
        except Exception as e:
            logger.error(f"Failed to generate point ID for document: {e}")
            return None

    def create_change_event(self, collection_name: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Create a change event message in the format expected by the consumer."""
        # Normalize document IDs to handle Binary objects and other MongoDB types
        normalized_document = normalize_document_ids(document)
        return {
            "operationType": "insert",
            "ns": {
                "db": DATABASE_NAME,
                "coll": collection_name
            },
            "fullDocument": normalized_document,
            "documentKey": {"_id": normalized_document["_id"]}
        }

    def get_collection_count(self, collection_name: str) -> int:
        """Get the total count of documents in a collection."""
        try:
            collection = self.database[collection_name]
            return collection.count_documents({})
        except Exception as e:
            logger.error(f"Error getting count for {collection_name}: {e}")
            return 0

    def backfill_collection(self, collection_name: str, dry_run: bool = False, incremental: bool = True) -> Dict[str, int]:
        """Backfill a single collection with smart incremental support.
        
        Args:
            collection_name: Name of the MongoDB collection
            dry_run: If True, don't actually send to Kafka
            incremental: If True, check Qdrant and only send missing documents
            
        Returns:
            Dictionary with statistics: processed, skipped, errors
        """
        collection = self.database[collection_name]
        topic_name = f"{KAFKA_TOPIC_PREFIX}{collection_name}"

        total_count = self.get_collection_count(collection_name)

        if total_count == 0:
            logger.info(f"No documents to process for collection {collection_name}")
            return {"processed": 0, "skipped": 0, "errors": 0}

        logger.info(f"📊 Collection '{collection_name}' has {total_count} documents in MongoDB")

        processed = 0
        skipped = 0
        errors = 0

        try:
            # If incremental mode is enabled and Qdrant is available, check for existing documents
            if incremental and self.qdrant_client:
                logger.info(f"🔍 Checking Qdrant for existing documents from '{collection_name}'...")

                # Fetch all documents and their mongo_ids
                cursor = collection.find({}, batch_size=BATCH_SIZE)
                documents_to_process = []

                for document in cursor:
                    mongo_id = normalize_mongo_id(document.get("_id"))
                    if mongo_id:
                        documents_to_process.append({
                            "document": document,
                            "mongo_id": mongo_id
                        })

                logger.info(f"📝 Found {len(documents_to_process)} documents to check")

                # Check existing documents in batches by mongo_id
                all_mongo_ids = [item["mongo_id"] for item in documents_to_process]
                existing_mongo_ids = self.check_documents_exist(all_mongo_ids)

                logger.info(f"✅ Found {len(existing_mongo_ids)} existing documents in Qdrant")
                logger.info(f"📤 Will backfill {len(documents_to_process) - len(existing_mongo_ids)} missing documents")

                # Process only documents that don't exist in Qdrant
                for i, item in enumerate(documents_to_process):
                    document = item["document"]
                    mongo_id = item["mongo_id"]

                    try:
                        # Skip if already exists in Qdrant
                        if mongo_id in existing_mongo_ids:
                            skipped += 1
                            continue
                        
                        # Create change event for missing document
                        change_event = self.create_change_event(collection_name, document)

                        if not dry_run:
                            # Send to Kafka
                            try:
                                self.kafka_producer.produce(
                                    topic=topic_name,
                                    value=json.dumps(change_event),
                                    key=str(document["_id"])
                                )
                                self.kafka_producer.poll(0)
                            except KafkaException as e:
                                logger.error(f"Kafka error sending to {topic_name}: {e}")
                                errors += 1
                                continue
                        
                        processed += 1

                        # Progress reporting
                        if (i + 1) % BATCH_SIZE == 0:
                            logger.info(f"  Progress: {processed} sent, {skipped} skipped, {errors} errors")
                            time.sleep(SLEEP_BETWEEN_BATCHES)

                    except Exception as e:
                        errors += 1
                        logger.error(f"Error processing document {document.get('_id', 'unknown')}: {e}")
                        if errors > 10:
                            logger.error("Too many errors, stopping collection processing")
                            break
            else:
                # Non-incremental mode: process all documents
                logger.info(f"⚠️  Incremental mode disabled, processing all documents")
                cursor = collection.find({}, batch_size=BATCH_SIZE)

                for i, document in enumerate(cursor):
                    try:
                        change_event = self.create_change_event(collection_name, document)

                        if not dry_run:
                            try:
                                self.kafka_producer.produce(
                                    topic=topic_name,
                                    value=json.dumps(change_event),
                                    key=str(document["_id"])
                                )
                                self.kafka_producer.poll(0)
                            except KafkaException as e:
                                logger.error(f"Kafka error sending to {topic_name}: {e}")
                                errors += 1
                                continue
                        processed += 1

                        if (i + 1) % BATCH_SIZE == 0:
                            logger.info(f"  Progress: {processed} processed, {errors} errors")
                            time.sleep(SLEEP_BETWEEN_BATCHES)

                    except Exception as e:
                        errors += 1
                        logger.error(f"Error processing document {document.get('_id', 'unknown')}: {e}")
                        if errors > 10:
                            logger.error("Too many errors, stopping collection processing")
                            break

        except Exception as e:
            logger.error(f"Error processing collection {collection_name}: {e}")

        return {"processed": processed, "skipped": skipped, "errors": errors}

    def backfill_all_collections(self, collections: Optional[List[str]] = None, dry_run: bool = False, incremental: bool = True) -> Dict[str, Dict[str, int]]:
        """Backfill all specified collections with incremental support.
        
        Args:
            collections: List of collection names to backfill
            dry_run: If True, don't actually send to Kafka
            incremental: If True, only backfill missing documents
            
        Returns:
            Dictionary mapping collection names to statistics
        """
        if collections is None:
            collections = COLLECTIONS_TO_BACKFILL

        results = {}
        
        # Get initial Qdrant point count
        initial_count = self.get_qdrant_point_count()
        if incremental and initial_count > 0:
            logger.info(f"📊 Qdrant currently has {initial_count} points")
            logger.info(f"🔄 Running incremental backfill (will only add missing documents)")
        elif incremental:
            logger.info(f"📊 Qdrant is empty, running full backfill")
        else:
            logger.info(f"⚠️  Running full backfill (incremental mode disabled)")

        total_processed = 0
        total_skipped = 0
        total_errors = 0

        for collection_name in collections:
            try:
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing collection: {collection_name}")
                logger.info(f"{'='*60}")
                
                stats = self.backfill_collection(collection_name, dry_run=dry_run, incremental=incremental)
                results[collection_name] = stats
                
                total_processed += stats["processed"]
                total_skipped += stats["skipped"]
                total_errors += stats["errors"]
                
                logger.info(f"✅ Collection '{collection_name}' complete:")
                logger.info(f"   - Processed: {stats['processed']}")
                logger.info(f"   - Skipped: {stats['skipped']}")
                logger.info(f"   - Errors: {stats['errors']}")
                
            except Exception as e:
                logger.error(f"Failed to process collection {collection_name}: {e}")
                results[collection_name] = {"processed": 0, "skipped": 0, "errors": 1}
                total_errors += 1

        # Flush producer to ensure all messages are sent
        if not dry_run and self.kafka_producer:
            logger.info(f"\n🔄 Flushing Kafka producer...")
            remaining = self.kafka_producer.flush(30)
            if remaining > 0:
                logger.error(f"❌ {remaining} messages may not have been delivered")
            else:
                logger.info(f"✅ All messages delivered successfully")

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"BACKFILL SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"📊 Total documents processed: {total_processed}")
        logger.info(f"⏭️  Total documents skipped: {total_skipped}")
        logger.info(f"❌ Total errors: {total_errors}")
        
        # Get final Qdrant point count
        if incremental:
            final_count = self.get_qdrant_point_count()
            added = final_count - initial_count
            logger.info(f"📈 Qdrant points: {initial_count} → {final_count} (+{added})")

        return results

    def close(self):
        """Close connections."""
        # Note: confluent-kafka Producer doesn't have a close() method
        # Messages are flushed in backfill_all_collections()
        if self.mongo_client:
            self.mongo_client.close()


def main():
    """Main function."""
    import argparse

    global BATCH_SIZE, SLEEP_BETWEEN_BATCHES  # Declare globals first

    parser = argparse.ArgumentParser(description="Backfill MongoDB data to Kafka with smart incremental support")
    parser.add_argument("--dry-run", action="store_true", help="Run without actually sending to Kafka")
    parser.add_argument("--collections", nargs="*", help="Specific collections to backfill")
    parser.add_argument("--batch-size", type=int, help="Batch size for processing")
    parser.add_argument("--sleep", type=float, help="Sleep between batches")
    parser.add_argument("--no-incremental", action="store_true", help="Disable incremental mode (backfill all documents)")

    args = parser.parse_args()

    # Override globals with args (for manual runs) or use environment defaults
    if args.batch_size is not None:
        BATCH_SIZE = args.batch_size
    if args.sleep is not None:
        SLEEP_BETWEEN_BATCHES = args.sleep

    # Determine dry run mode
    dry_run = args.dry_run or DEFAULT_DRY_RUN

    # Determine collections to process
    collections = args.collections if args.collections else COLLECTIONS_TO_BACKFILL
    
    # Determine incremental mode
    incremental = INCREMENTAL_BACKFILL and not args.no_incremental

    backfill = MongoDBBackfill()

    try:
        logger.info(f"\n{'='*60}")
        logger.info(f"MONGODB TO QDRANT BACKFILL")
        logger.info(f"{'='*60}")
        logger.info(f"Mode: {'Incremental (smart)' if incremental else 'Full (all documents)'}")
        logger.info(f"Collections: {', '.join(collections)}")
        logger.info(f"Dry run: {'Yes' if dry_run else 'No'}")
        logger.info(f"{'='*60}\n")

        # Connect to services
        if not backfill.connect_mongodb():
            logger.error("❌ Failed to connect to MongoDB")
            sys.exit(1)
        logger.info("✅ Connected to MongoDB")

        # Connect to Qdrant for incremental check (if enabled)
        if incremental:
            if backfill.connect_qdrant():
                logger.info("✅ Connected to Qdrant for incremental sync")
            else:
                logger.warning("⚠️  Could not connect to Qdrant, falling back to full backfill")
                incremental = False

        if not dry_run and not backfill.connect_kafka():
            logger.error("❌ Failed to connect to Kafka")
            sys.exit(1)
        if not dry_run:
            logger.info("✅ Connected to Kafka")

        # Perform backfill
        results = backfill.backfill_all_collections(collections, dry_run=dry_run, incremental=incremental)

        # Exit status
        total_processed = sum(r.get("processed", 0) for r in results.values())
        total_skipped = sum(r.get("skipped", 0) for r in results.values())
        
        if total_processed > 0 or total_skipped > 0:
            sys.exit(0)
        else:
            logger.warning("⚠️  No documents were processed or skipped.")
            sys.exit(0)

    except KeyboardInterrupt:
        logger.error("\n❌ Backfill interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        backfill.close()


if __name__ == "__main__":
    main()