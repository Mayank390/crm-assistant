"""
Smart Filter Tools - Integration tools for the smart-filter agent

This module provides tool wrappers that integrate with the existing tools
in tools.py to enable the smart-filter agent to use mongo-query and RAG
functionality while maintaining its orchestration pattern.
"""

import json
import os
import sys
import re
import json
import traceback
import uuid
import asyncio
import logging
from mongo.constants import uuid_str_to_mongo_binary, BUSINESS_UUID, MEMBER_UUID, COLLECTIONS_WITH_DIRECT_BUSINESS
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from collections import defaultdict
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue, MatchAny, Prefetch, NearestQuery, FusionQuery, Fusion, SparseVector
)
from utils.mongo_to_uuid import mongo_uuid_converter
from langchain_core.tools import tool
from .planner import plan_and_execute_query

# Configure logging
logger = logging.getLogger(__name__)
# Import the existing tools
try:
    from tools import  rag_search
except ImportError:
    # Fallback for testing
    rag_search = None
from bson import ObjectId, Binary
# Import necessary modules for RAG and MongoDB operations
try:
    from qdrant.retrieval import ChunkAwareRetriever
    from qdrant.initializer import RAGTool
    from mongo.constants import mongodb_tools, DATABASE_NAME, QDRANT_COLLECTION_NAME
except ImportError:
    ChunkAwareRetriever = None
    RAGTool = None
    mongodb_tools = None
    DATABASE_NAME = os.getenv("MONGODB_DATABASE", "ProjectManagement")
    QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "ProjectManagement")
    build_lookup_stage = None
    REL = None


@dataclass
class MongoQueryResult:
    """Result from mongo-query tool execution"""
    work_items: List[Dict[str, Any]]
    total_count: int
    query: str
    raw_result: Any


@dataclass
class RAGSearchResult:
    """Result from RAG search tool execution"""
    work_items: List[Dict[str, Any]]
    total_count: int
    query: str
    reconstructed_docs: List[Any] = None  # Optional reconstructed docs from RAG search
    work_item_ids: Set[str] = None  # Optional set of work item IDs found
    rag_context: str = ""  # Optional RAG context string

@dataclass
class ChunkResult:
    """Represents a single chunk with metadata"""
    id: str
    score: float
    content: str
    mongo_id: str
    parent_id: str
    chunk_index: int
    chunk_count: int
    title: str
    content_type: str
    metadata: Dict[str, Any]

@dataclass
class ReconstructedDocument:
    """Represents a document reconstructed from multiple chunks"""
    mongo_id: str
    title: str
    content_type: str
    chunks: List[ChunkResult]
    max_score: float
    avg_score: float
    full_content: str
    metadata: Dict[str, Any]
    chunk_coverage: str  # e.g., "chunks 1,2,5 of 10"

CONTENT_TYPE_DEFAULT_LIMITS: Dict[str, int] = {
    "page": 12,
    "work_item": 12,
    "project": 6,
    "cycle": 6,
    "module": 6,
    "epic": 6,
}

# Fallback when content_type is unknown or not provided
DEFAULT_RAG_LIMIT: int = 10

# Optional: per content_type chunk-level tuning for chunk-aware retrieval
# - chunks_per_doc controls how many high-scoring chunks are kept per reconstructed doc
# - include_adjacent controls whether to pull neighboring chunks for context
# - min_score sets a score threshold for initial vector hits
CONTENT_TYPE_CHUNKS_PER_DOC: Dict[str, int] = {
    "page": 3,          # Reduced from 4 to minimize context window usage
    "work_item": 4,     # Reduced from 3 to minimize context window usage
    "project": 2,
    "cycle": 2,
    "module": 2,
    "epic": 2,
}

CONTENT_TYPE_INCLUDE_ADJACENT: Dict[str, bool] = {
    "page": True,      # Disabled to reduce context window usage (was True)
    "work_item": True,  # Keep adjacent for work items for better context
    "project": False,
    "cycle": False,
    "module": False,
    "epic": False,
}

CONTENT_TYPE_MIN_SCORE: Dict[str, float] = {
    "page": 0.5,
    "work_item": 0.5,
    "project": 0.55,
    "cycle": 0.55,
    "module": 0.55,
    "epic": 0.55,
}


class SmartFilterTools:
    """Tools for smart-filter agent to call mongo-query and RAG functionality"""

    _instance = None  # Class variable to hold the single instance

    def __new__(cls,*args,**kwargs):
        """Ensure only one instance exists"""
        if cls._instance is None:
            cls._instance = super(SmartFilterTools, cls).__new__(cls)
            # Initialize instance variables
            cls._instance.rag_tool = None
            cls._instance.retriever = None
            cls._instance.rag_available = False
        return cls._instance

    def __init__(self, qdrant_client=None, embedding_client=None):
        self.qdrant_client = qdrant_client
        self.embedding_client = embedding_client
        # Minimal English stopword list for lightweight keyword-overlap filtering
        self._STOPWORDS: Set[str] = {
            "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "by",
            "for", "with", "about", "against", "between", "into", "through", "during", "before",
            "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off",
            "over", "under", "again", "further", "here", "there", "why", "how", "all", "any",
            "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "can", "will", "just"
        }
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        # Lazy initialization - RAG will be initialized when first used
        # This avoids sync/async issues in __init__
        pass

    async def ensure_mongodb_connection(self) -> bool:
        """Ensure MongoDB connection is established"""
        if not mongodb_tools:
            return False

        try:
            await mongodb_tools.connect()
            return True
        except Exception:
            return False

    @classmethod
    async def initialize(cls):
        """
        Pre-initialize RAG components at server startup.
        This should be called once at server startup, similar to RAGTool.initialize()
        """
        instance = cls()
        if instance.rag_available and instance.retriever:
            return  # Already initialized

        await instance.ensure_rag_initialized()

    async def ensure_rag_initialized(self) -> bool:
        """Ensure RAG components are initialized"""
        if self.rag_available and self.retriever:
            return True

        if not RAGTool:
            logger.error("RAGTool not available (import failed)")
            return False

        try:
            # Set environment variable to avoid OpenMP threading issues
            import os
            os.environ['OMP_NUM_THREADS'] = '1'
            os.environ['TOKENIZERS_PARALLELISM'] = 'false'

            # Check if RAGTool is already initialized
            try:
                existing_instance = RAGTool.get_instance()
                if existing_instance and existing_instance.connected:
                    self.rag_tool = existing_instance
                    # Only log on first initialization
                    if not self.rag_available:
                        pass
                else:
                    await RAGTool.initialize()
                    self.rag_tool = RAGTool.get_instance()
            except RuntimeError:
                # Not initialized yet, initialize it
                await RAGTool.initialize()
                self.rag_tool = RAGTool.get_instance()

            if self.rag_tool and self.rag_tool.connected:
                self.retriever = ChunkAwareRetriever(
                    qdrant_client=self.rag_tool.qdrant_client,
                    embedding_client=self.rag_tool.embedding_client
                )
                self.rag_available = True
                # Only log on first initialization
                if not hasattr(self, '_logged_init'):
                    self._logged_init = True
                return True
            else:
                logger.error("RAGTool initialized but not connected")
                return False
        except Exception as e:
            logger.error(f"RAG initialization failed: {e}")
            # Don't set rag_available to False here, let it retry
            return False

    async def fetch_work_items_by_ids(self, work_item_ids: Set[str]) -> List[Dict[str, Any]]:
        """
        Fetch complete work item documents by their IDs from MongoDB

        Args:
            work_item_ids: Set of work item IDs (can be displayBugNo or _id)

        Returns:
            List of complete work item documents
        """
        if not work_item_ids:
            return []

        # Ensure MongoDB connection
        if not await self.ensure_mongodb_connection():
            raise RuntimeError("MongoDB connection failed")

        try:
            # Convert IDs to list for MongoDB query
            id_list = list(work_item_ids)

            # Build aggregation pipeline to fetch work items by IDs
            # We need to handle both displayBugNo and _id lookups
            pipeline = [
                {
                    "$match": {
                        "$or": [
                            {"displayBugNo": {"$in": id_list}},
                            {"_id": {"$in": id_list}}
                        ]
                    }
                }
            ]

            # Execute the query
            results = await mongodb_tools.aggregate(
                database=DATABASE_NAME,
                collection="workItem",
                pipeline=pipeline
            )

            return results if results else []

        except Exception as e:
            logger.error(f"Failed to fetch work items by IDs: {e}")
            return []
    
    # async def execute_mongo_query(
    #     self,
    #     query: str,
    #     project_id: str = None,
    #     show_all: bool = False,
    #     limit: Optional[int] = None,
    # ) -> MongoQueryResult:
    #     """
    #     Execute mongo-query with the given parameters

    #     Args:
    #         query: Natural language query for MongoDB
    #         show_all: Whether to show all results or limit for performance

    #     Returns:
    #         MongoQueryResult with formatted work items
    #     """
    #     # Note: mongo_query is no longer used - we use plan_and_execute_query from planner

    #     try:
    #         result_payload = await plan_and_execute_query(query , project_id=project_id)

    #         if not isinstance(result_payload, dict):
    #             raise RuntimeError("Planner returned unexpected response type")

    #         if not result_payload.get("success"):
    #             raise RuntimeError(result_payload.get("error", "Unknown planner error"))

    #         raw_rows = result_payload.get("result") or []

    #         work_items: List[Dict[str, Any]] = []
    #         total_count: int = 0

    #         if isinstance(raw_rows, list):
    #             for item in raw_rows:
    #                 if isinstance(item, dict):
    #                     work_items.append(item)
    #                 elif isinstance(item, str):
    #                     try:
    #                         parsed_item = json.loads(item)
    #                         if isinstance(parsed_item, dict):
    #                             work_items.append(parsed_item)
    #                     except Exception:
    #                         continue

    #             # Attempt to extract total/count metadata when present
    #             if raw_rows and isinstance(raw_rows[0], dict) and "total" in raw_rows[0]:
    #                 try:
    #                     total_count = int(raw_rows[0]["total"])
    #                 except Exception:
    #                     total_count = len(work_items)
    #             else:
    #                 total_count = len(work_items)

    #         elif isinstance(raw_rows, dict):
    #             # Count-only shape
    #             if "total" in raw_rows:
    #                 try:
    #                     total_count = int(raw_rows["total"])
    #                 except Exception:
    #                     total_count = 0
    #             # When single document returned
    #             if raw_rows:
    #                 work_items.append(raw_rows)

    #         # Honor explicit limit when provided (unless show_all requested)
    #         if not show_all and limit is not None and limit > 0:
    #             work_items = work_items[:limit]

    #         if total_count == 0:
    #             total_count = len(work_items)

    #         return MongoQueryResult(
    #             work_items=work_items,
    #             total_count=total_count,
    #             query=query,
    #             raw_result=result_payload,
    #         )

    #     except Exception as e:
    #         raise RuntimeError(f"Mongo query execution failed: {str(e)}")
    
    
    from typing import Any, Dict, List, Optional

    async def execute_mongo_query(
        self,
        query: str,
        project_id: Optional[str] = None,
        show_all: bool = False,
        limit: Optional[int] = None,
    ) -> MongoQueryResult:
        """
        Execute a natural-language MongoDB query via the planner.

        Args:
            query: Natural language query for MongoDB
            project_id: Optional project UUID for scoping
            show_all: If True, ignore limit
            limit: Optional max number of items to return

        Returns:
            MongoQueryResult containing work items, total count, and raw planner result
        """
        try:
            # 🪵 Debug log: show initial call context

            # Execute via planner
            result_payload = await plan_and_execute_query(query, project_id=project_id)

            if not isinstance(result_payload, dict):
                raise RuntimeError("Planner returned unexpected non-dict response")

            if not result_payload.get("success"):
                raise RuntimeError(result_payload.get("error", "Unknown planner error"))

            raw_rows = result_payload.get("result") or []

            work_items: List[Dict[str, Any]] = []
            total_count: int = 0

            # 🪵 Debug: show result shape

            # Handle list results
            if isinstance(raw_rows, list):
                for item in raw_rows:
                    if isinstance(item, dict):
                        work_items.append(item)
                    elif isinstance(item, str):
                        try:
                            parsed_item = json.loads(item)
                            if isinstance(parsed_item, dict):
                                work_items.append(parsed_item)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse string row: {item}")
                            continue

                # Try to extract total count metadata
                if raw_rows and isinstance(raw_rows[0], dict) and "total" in raw_rows[0]:
                    try:
                        total_count = int(raw_rows[0]["total"])
                    except Exception:
                        total_count = len(work_items)
                else:
                    total_count = len(work_items)

            # Handle dict results (single doc or count)
            elif isinstance(raw_rows, dict):
                if "total" in raw_rows:
                    try:
                        total_count = int(raw_rows["total"])
                    except Exception:
                        total_count = 0
                if raw_rows:
                    work_items.append(raw_rows)
                if total_count == 0:
                    total_count = len(work_items)

            # Apply limit (if not showing all)
            if not show_all and limit is not None and limit > 0:
                work_items = work_items[:limit]

            if total_count == 0:
                total_count = len(work_items)

            # 🪵 Debug summary

            return MongoQueryResult(
                work_items=work_items,
                total_count=total_count,
                query=query,
                raw_result=result_payload,
            )

        except Exception as e:
            # Detailed error logging
            logger.error(f"Query execution failed: {e}")
            logger.error(f"Query: {query}, Project ID: {project_id}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Mongo query execution failed: {str(e)}")

    
    async def search_with_context(
        self,
        query: str,
        project_id: str,
        collection_name: str,
        content_type: Optional[str] = None,
        limit: int = 10,
        chunks_per_doc: int = 3,
        include_adjacent: bool = True,
        min_score: float = 0.5,
        text_query: Optional[str] = None,
        *,
        # Quality filters (token cost control)
        min_content_chars: int = 30,
        min_keyword_overlap: float = 0.05,
        # Retrieval behavior flags
        enable_keyword_fallback: bool = False,
        # Sparse tuning (to ensure SPLADE signal isn't over-filtered)
        sparse_score_threshold: Optional[float] = None,
        sparse_limit_multiplier: float = 2.0,
        # Packing budget (approx token budget for merged content)
        context_token_budget: Optional[int] = None,
    ) -> List[ReconstructedDocument]:
        """
        Perform chunk-aware search with context reconstruction.
        
        Args:
            query: Search query
            collection_name: Qdrant collection name
            content_type: Filter by content type
            limit: Max number of DOCUMENTS to return (not chunks)
            chunks_per_doc: Max chunks to retrieve per document
            include_adjacent: Whether to fetch adjacent chunks for context
            min_score: Minimum relevance score threshold
            text_query: Optional custom keyword query for fallback full_text
            min_content_chars: Drop chunks with content shorter than this (after strip)
            min_keyword_overlap: Minimum query-token overlap ratio required
            enable_keyword_fallback: If True, allow full_text prefetch fallback
            
        Returns:
            List of reconstructed documents with full context
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Step 1: Initial vector search (retrieve more chunks to cover more docs)
        vectors = self.embedding_client.encode([query])
        if not vectors:
            raise RuntimeError("Embedding service returned empty vector")
        query_embedding = vectors[0]
        
        # Build filter with optional content_type and global business scoping
        must_conditions = []
        if content_type:
            must_conditions.append(FieldCondition(key="content_type", match=MatchValue(value=content_type)))

        if project_id:
            must_conditions.append(FieldCondition(key="project_id", match=MatchValue(value=uuid_str_to_mongo_binary(project_id))))

        search_filter = Filter(must=must_conditions) if must_conditions else None

        # Fetch more chunks initially to ensure we have multiple per document
        # Increase pool size for smaller chunks to maintain document recall
        initial_limit = max(limit * max(chunks_per_doc * 3, 10), 50)

        # search_results = self.qdrant_client.search(
        #     collection_name=collection_name,
        #     query_vector=query_embedding,
        #     query_filter=search_filter,
        #     limit=initial_limit,
        #     with_payload=True,
        #     score_threshold=min_score
        # )
        
        # --- Hybrid Search Logic ---
        # Prefer dense + SPLADE-sparse fusion; fall back to full_text keyword if SPLADE unavailable

        dense_prefetch = Prefetch(
            query=NearestQuery(nearest=query_embedding),
            using="dense",
            limit=initial_limit,
            score_threshold=min_score,
            filter=search_filter
        )

        prefetch_list = [dense_prefetch]

        # Try SPLADE for sparse query
        sparse_added = False
        try:
            from qdrant.encoder import get_splade_encoder
            splade = get_splade_encoder()
            splade_vec = splade.encode_text(query)
            if splade_vec.get("indices"):
                sparse_prefetch = Prefetch(
                    query=NearestQuery(
                        nearest=SparseVector(indices=splade_vec["indices"], values=splade_vec["values"]),
                    ),
                    using="sparse",
                    limit=max(initial_limit, int(initial_limit * max(1.0, float(sparse_limit_multiplier)))),
                    # Use dedicated threshold for sparse; default None to avoid over-filtering
                    score_threshold=sparse_score_threshold,
                    filter=search_filter,
                )
                prefetch_list.append(sparse_prefetch)
                sparse_added = True
        except Exception as e:
            # SPLADE optional; fall back to keyword search
            pass

        if enable_keyword_fallback and not sparse_added:
            # Fallback to text index keyword search; use provided text_query or original query
            keyword_query = text_query or query
            keyword_prefetch = Prefetch(
                query=NearestQuery(nearest=keyword_query),
                using="full_text",
                limit=initial_limit,
                filter=search_filter,
            )
            prefetch_list.append(keyword_prefetch)

        hybrid_query = FusionQuery(fusion=Fusion.RRF)

        try:
            search_results = self.qdrant_client.query_points(
                collection_name=collection_name,
                prefetch=prefetch_list,
                query=hybrid_query,
                limit=initial_limit,
            ).points
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []
        

        if not search_results:
            return []
        
        # Step 2: Group chunks by parent document
        doc_chunks: Dict[str, List[ChunkResult]] = defaultdict(list)
        
        # Pre-tokenize query for lightweight overlap checks
        query_terms = self._tokenize(query)

        for result in search_results:
            payload = result.payload or {}
            
            # Prefer 'content'; fallback to 'full_text' or title if missing
            content_text = payload.get("content") or payload.get("full_text") or payload.get("title", "")

            # Quality gates to prune irrelevant/low-signal chunks early
            if not self._should_keep_chunk(
                content_text=content_text,
                query_terms=query_terms,
                min_content_chars=min_content_chars,
                min_keyword_overlap=min_keyword_overlap,
            ):
                continue

            chunk = ChunkResult(
                id=str(result.id),
                score=result.score,
                content=content_text,
                mongo_id=payload.get("mongo_id", ""),
                parent_id=payload.get("parent_id", payload.get("mongo_id", "")),
                chunk_index=payload.get("chunk_index", 0),
                chunk_count=payload.get("chunk_count", 1),
                title=payload.get("title", "Untitled"),
                content_type=payload.get("content_type", "unknown"),
                metadata={k: v for k, v in payload.items() 
                         if k not in ["content", "full_text", "mongo_id", "parent_id", 
                                     "chunk_index", "chunk_count", "title", "content_type"]}
            )
            
            parent_id = chunk.parent_id or chunk.mongo_id
            doc_chunks[parent_id].append(chunk)
        
        # Step 3: Fetch adjacent chunks for better context (if enabled)
        if include_adjacent:
            await self._fetch_adjacent_chunks(doc_chunks, collection_name, content_type)
        
        # Step 4: Reconstruct documents from chunks
        reconstructed_docs = self._reconstruct_documents(
            doc_chunks, 
            max_docs=limit,
            chunks_per_doc=chunks_per_doc
        )

        # Optionally pack to a token budget by pruning extra context chunks
        if context_token_budget is not None and context_token_budget > 0:
            reconstructed_docs = self._pack_docs_to_budget(reconstructed_docs, context_token_budget)

        return reconstructed_docs

    # --- Lightweight quality filters ---
    def _tokenize(self, text: str) -> Set[str]:
        if not text:
            return set()
        # Alphanumeric tokens, lowercased; remove trivial stopwords
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return {t for t in tokens if t and t not in self._STOPWORDS}

    def _keyword_overlap(self, query_terms: Set[str], text: str) -> float:
        if not query_terms:
            return 0.0
        doc_terms = self._tokenize(text)
        if not doc_terms:
            return 0.0
        intersection = query_terms & doc_terms
        return len(intersection) / max(1, len(query_terms))

    def _should_keep_chunk(
        self,
        *,
        content_text: str,
        query_terms: Set[str],
        min_content_chars: int,
        min_keyword_overlap: float,
    ) -> bool:
        if not content_text:
            return False
        text = content_text.strip()
        if len(text) < min_content_chars:
            # Short snippets (e.g., "Hi") must have stronger lexical signal
            return self._keyword_overlap(query_terms, text) >= max(min_keyword_overlap, 0.2)
        # For longer content, apply configured overlap threshold if set (>0)
        if min_keyword_overlap > 0:
            return self._keyword_overlap(query_terms, text) >= min_keyword_overlap
        return True
    
    async def _fetch_adjacent_chunks(
        self,
        doc_chunks: Dict[str, List[ChunkResult]],
        collection_name: str,
        content_type: Optional[str]
    ):
        """
        Fetch adjacent chunks to fill gaps and provide better context.
        Modifies doc_chunks in place.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        for parent_id, chunks in doc_chunks.items():
            if not chunks:
                continue
            
            # Find the chunk with highest score
            best_chunk = max(chunks, key=lambda c: c.score)
            chunk_count = best_chunk.chunk_count
            
            # Determine which chunks we have
            existing_indices = {c.chunk_index for c in chunks}
            
            # Identify adjacent chunks to fetch (±1 from each existing chunk)
            adjacent_indices: Set[int] = set()
            for idx in existing_indices:
                if idx > 0:
                    adjacent_indices.add(idx - 1)
                if idx < chunk_count - 1:
                    adjacent_indices.add(idx + 1)
            
            # Remove indices we already have
            to_fetch = adjacent_indices - existing_indices
            
            if not to_fetch:
                continue
            
            # Fetch missing adjacent chunks using scroll/search by parent_id and chunk_index
            # Note: This requires a compound filter which Qdrant supports
            for chunk_idx in to_fetch:
                try:
                    filter_conditions = [
                        FieldCondition(key="parent_id", match=MatchValue(value=parent_id)),
                        FieldCondition(key="chunk_index", match=MatchValue(value=chunk_idx))
                    ]
                    
                    if content_type:
                        filter_conditions.append(
                            FieldCondition(key="content_type", match=MatchValue(value=content_type))
                            # FieldCondition(key="project_id", match=MatchValue(value=project_id))
                        )

                    
                    # Use scroll to find specific chunk (more efficient than search for exact match)
                    scroll_result = self.qdrant_client.scroll(
                        collection_name=collection_name,
                        scroll_filter=Filter(must=filter_conditions),
                        limit=1,
                        with_payload=True,
                        with_vectors=False
                    )
                    
                    if scroll_result and scroll_result[0]:
                        for point in scroll_result[0]:
                            payload = point.payload or {}
                            # Prefer 'content'; fallback to 'full_text' or title if missing
                            adj_content_text = payload.get("content") or payload.get("full_text") or payload.get("title", "")

                            adjacent_chunk = ChunkResult(
                                id=str(point.id),
                                score=0.0,  # Adjacent chunks get 0 score (context only)
                                content=adj_content_text,
                                mongo_id=payload.get("mongo_id", ""),
                                parent_id=payload.get("parent_id", payload.get("mongo_id", "")),
                                chunk_index=payload.get("chunk_index", 0),
                                chunk_count=payload.get("chunk_count", 1),
                                title=payload.get("title", "Untitled"),
                                content_type=payload.get("content_type", "unknown"),
                                metadata={k: v for k, v in payload.items() 
                                         if k not in ["content", "full_text", "mongo_id", "parent_id",
                                                     "chunk_index", "chunk_count", "title", "content_type"]}
                            )
                            chunks.append(adjacent_chunk)
                
                except Exception as e:
                    logger.error(f"Could not fetch adjacent chunk {chunk_idx} for {parent_id}: {e}")
                    continue
    
    def _reconstruct_documents(
        self,
        doc_chunks: Dict[str, List[ChunkResult]],
        max_docs: int,
        chunks_per_doc: int
    ) -> List[ReconstructedDocument]:
        """
        Reconstruct full documents from chunks with smart ordering and deduplication.
        """
        reconstructed = []
        
        # Sort documents by best chunk score
        sorted_docs = sorted(
            doc_chunks.items(),
            key=lambda x: max(c.score for c in x[1]),
            reverse=True
        )
        
        for parent_id, chunks in sorted_docs[:max_docs]:
            if not chunks:
                continue
            
            # Sort chunks by index for proper document reconstruction
            chunks.sort(key=lambda c: c.chunk_index)
            
            # Limit chunks per document (keep highest scoring + adjacent for context)
            scored_chunks = [c for c in chunks if c.score > 0]
            context_chunks = [c for c in chunks if c.score == 0]
            
            # Keep top scoring chunks plus their adjacent context
            top_scored = sorted(scored_chunks, key=lambda c: c.score, reverse=True)[:chunks_per_doc]
            top_indices = {c.chunk_index for c in top_scored}
            
            # Include adjacent context chunks
            relevant_context = [
                c for c in context_chunks 
                if any(abs(c.chunk_index - idx) <= 1 for idx in top_indices)
            ]
            
            selected_chunks = sorted(top_scored + relevant_context, key=lambda c: c.chunk_index)
            
            # Calculate statistics
            scored = [c for c in selected_chunks if c.score > 0]
            max_score = max(c.score for c in scored) if scored else 0.0
            avg_score = sum(c.score for c in scored) / len(scored) if scored else 0.0
            
            # Reconstruct full content with smart merging
            full_content = self._merge_chunks(selected_chunks)
            
            # Build chunk coverage info
            # Convert to 1-based indices for display
            chunk_indices = sorted([c.chunk_index + 1 for c in selected_chunks])
            total_chunks = chunks[0].chunk_count if chunks else 1
            coverage = self._format_coverage(chunk_indices, total_chunks)
            
            # Use metadata from best scoring chunk
            best_chunk = max(chunks, key=lambda c: c.score)
            
            doc = ReconstructedDocument(
                mongo_id=parent_id,
                title=best_chunk.title,
                content_type=best_chunk.content_type,
                chunks=selected_chunks,
                max_score=max_score,
                avg_score=avg_score,
                full_content=full_content,
                metadata=best_chunk.metadata,
                chunk_coverage=coverage
            )
            
            reconstructed.append(doc)
        
        return reconstructed
    
    def _merge_chunks(self, chunks: List[ChunkResult]) -> str:
        """
        Intelligently merge chunks, handling overlaps and maintaining readability.
        """
        if not chunks:
            return ""
        
        if len(chunks) == 1:
            return chunks[0].content
        
        # For now, use simple concatenation with markers
        # TODO: Implement overlap detection and smart merging
        merged_parts = []
        
        for i, chunk in enumerate(chunks):
            if i > 0:
                prev_chunk = chunks[i - 1]
                # Check if chunks are adjacent
                if chunk.chunk_index == prev_chunk.chunk_index + 1:
                    # Adjacent chunks - they overlap, try to merge smoothly
                    # For now, just add separator
                    merged_parts.append("\n")
                else:
                    # Gap in chunks - add clear separator
                    merged_parts.append(f"\n\n[... chunk {prev_chunk.chunk_index + 1} to {chunk.chunk_index - 1} omitted ...]\n\n")
            
            merged_parts.append(chunk.content)
        
        return "".join(merged_parts)
    
    def _format_coverage(self, indices: List[int], total: int) -> str:
        """
        Format chunk coverage info (e.g., 'chunks 1-3,5,7-9 of 12')
        """
        if not indices:
            return "no chunks"
        
        # Group consecutive indices into ranges
        ranges = []
        start = indices[0]
        end = indices[0]
        
        for idx in indices[1:]:
            if idx == end + 1:
                end = idx
            else:
                ranges.append(f"{start}-{end}" if start != end else f"{start}")
                start = end = idx
        
        ranges.append(f"{start}-{end}" if start != end else f"{start}")
        
        return f"chunks {','.join(ranges)} of {total}"

    # --- Budget packing utilities ---
    def _rough_token_count(self, text: str) -> int:
        # Very rough token estimator: ~0.75 tokens/word, but use 1.0 for safety with punctuation
        # Using words count as upper-bound to be conservative
        if not text:
            return 0
        return max(1, len(text.split()))

    def _pack_docs_to_budget(self, docs: List[ReconstructedDocument], budget_tokens: int) -> List[ReconstructedDocument]:
        """
        Trim merged content across documents to fit within an approximate token budget.
        Strategy:
        - Keep documents sorted by score (already is)
        - For each document, if over budget, drop lowest-utility context chunks first
          while preserving at least one high-scoring chunk.
        - Recompute merged content after pruning.
        """
        packed: List[ReconstructedDocument] = []
        remaining = max(1, budget_tokens)

        for doc in docs:
            # Quick accept if content already small
            content_tokens = self._rough_token_count(doc.full_content)
            if content_tokens <= remaining:
                packed.append(doc)
                remaining -= content_tokens
                continue

            # Otherwise, prune chunks: keep scored first then adjacent context around them
            scored = [c for c in doc.chunks if c.score > 0]
            if not scored:
                # If no scored chunks (edge case), keep first chunk only
                kept = doc.chunks[:1]
            else:
                # Start with top scored chunk, then add neighbors until we hit remaining
                top = sorted(scored, key=lambda c: c.score, reverse=True)
                kept_indices: Set[int] = set()
                kept: List[ChunkResult] = []
                for s in top:
                    if s.chunk_index in kept_indices:
                        continue
                    # Add s
                    kept.append(s)
                    kept_indices.add(s.chunk_index)
                    # Try to add immediate neighbors if present
                    for delta in (-1, 1):
                        neighbor_idx = s.chunk_index + delta
                        for c in doc.chunks:
                            if c.chunk_index == neighbor_idx and neighbor_idx not in kept_indices:
                                kept.append(c)
                                kept_indices.add(neighbor_idx)
                    # Merge and check size; stop early if we exceed remaining
                    merged = self._merge_chunks(sorted(kept, key=lambda c: c.chunk_index))
                    if self._rough_token_count(merged) > remaining:
                        # Remove last added neighbor(s) if they pushed over budget
                        # Keep at least the top scored chunk
                        kept = [s]
                        break

            # Rebuild document with kept chunks
            kept_sorted = sorted(kept, key=lambda c: c.chunk_index)
            merged_content = self._merge_chunks(kept_sorted)
            merged_tokens = self._rough_token_count(merged_content)

            if merged_tokens <= remaining:
                remaining -= merged_tokens
            else:
                # If still too big, truncate content text conservatively by words
                words = merged_content.split()
                if remaining > 10:  # avoid micro snippets
                    merged_content = " ".join(words[:remaining])
                    remaining = 0
                else:
                    merged_content = " ".join(words[:10])
                    remaining = 0

            packed.append(ReconstructedDocument(
                mongo_id=doc.mongo_id,
                title=doc.title,
                content_type=doc.content_type,
                chunks=kept_sorted,
                max_score=doc.max_score,
                avg_score=doc.avg_score,
                full_content=merged_content,
                metadata=doc.metadata,
                chunk_coverage=doc.chunk_coverage,
            ))

            if remaining <= 0:
                break

        return packed

    def _normalize_mongo_id(self, mongo_id) -> str:
        """Convert Mongo _id (ObjectId or Binary UUID) into a safe string like Qdrant expects."""
        if isinstance(mongo_id, ObjectId):
            return str(mongo_id)
        elif isinstance(mongo_id, Binary) and mongo_id.subtype == 3:
            return str(uuid.UUID(bytes=mongo_id))
        return str(mongo_id)


    def format_reconstructed_results(
        docs: List[ReconstructedDocument],
        show_full_content: bool = True,
        show_chunk_details: bool = True
    ) -> str:
        """
        Format reconstructed documents for display to LLM.
        
        Args:
            docs: List of reconstructed documents
            show_full_content: Whether to show full merged content
            show_chunk_details: Whether to show individual chunk scores
            
        Returns:
            Formatted string representation
        """
        if not docs:
            return "No results found."
        
        response_parts = []
        response_parts.append(f"🔍 CHUNK-AWARE RETRIEVAL: {len(docs)} document(s) reconstructed\n")
        
        for i, doc in enumerate(docs, 1):
            response_parts.append(f"\n[{i}] {doc.content_type.upper()}: {doc.title}")
            response_parts.append(f"    Relevance: {doc.max_score:.3f} (avg: {doc.avg_score:.3f})")
            response_parts.append(f"    Coverage: {doc.chunk_coverage}")
            
            # Show metadata compactly
            meta = []
            if doc.metadata.get('project_name'):
                meta.append(f"Project: {doc.metadata['project_name']}")
            if doc.metadata.get('priority'):
                meta.append(f"Priority: {doc.metadata['priority']}")
            if doc.metadata.get('state_name'):
                meta.append(f"State: {doc.metadata['state_name']}")
            if doc.metadata.get('assignee_name'):
                meta.append(f"Assignee: {doc.metadata['assignee_name']}")
            if doc.metadata.get('visibility'):
                meta.append(f"Visibility: {doc.metadata['visibility']}")
            
            if meta:
                response_parts.append(f"    {' | '.join(meta)}")
            
            # Show chunk details if requested
            if show_chunk_details and len(doc.chunks) > 1:
                scored_chunks = [c for c in doc.chunks if c.score > 0]
                if scored_chunks:
                    chunk_info = ", ".join([f"#{c.chunk_index}({c.score:.2f})" for c in scored_chunks])
                    response_parts.append(f"    Matched chunks: {chunk_info}")
            
            # Show full content without truncation so the LLM has complete context for synthesis
            # This enables the LLM to generate properly formatted, accurate responses based on actual content
            if show_full_content:
                content = doc.full_content
                response_parts.append(f"\n    === CONTENT START ===")
                response_parts.append(content)
                response_parts.append(f"    === CONTENT END ===")
            
            response_parts.append("")  # Empty line between docs
        
        return "\n".join(response_parts)


    def extract_keywords(text: str, max_terms: int = 12) -> str:
        """
        Lightweight keyword extractor used for fallback full_text queries.
        Removes trivial stopwords and non-alphanumerics; returns space-joined terms.
        """
        if not text:
            return ""
        stop = {
            "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "by",
            "for", "with", "about", "against", "between", "into", "through", "during", "before",
            "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off",
            "over", "under", "again", "further", "here", "there", "why", "how", "all", "any",
            "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "can", "will", "just"
        }
        terms = re.findall(r"[a-z0-9]+", text.lower())
        terms = [t for t in terms if t and t not in stop]
        # Deduplicate while keeping order
        seen = set()
        unique_terms = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                unique_terms.append(t)
            if len(unique_terms) >= max_terms:
                break
        return " ".join(unique_terms)

    async def rag_search(
        self,
        query: str,
        project_id: str,
        content_type: Optional[str] = None,
        group_by: Optional[str] = None,
        limit: int = 10,
        show_content: bool = True,
        use_chunk_aware: bool = True
    ) -> str:
        """Universal RAG search tool - returns FULL chunk content for LLM synthesis.
        
        **IMPORTANT**: This tool returns complete, untruncated content chunks so you can:
        - Analyze and understand the actual content
        - Generate properly formatted responses based on real data
        - Answer questions accurately using the retrieved context
        - Synthesize information from multiple sources
        
        Use this for ANY content-based search or analysis needs:
        - Find relevant pages, work items, projects, cycles, modules, epics
        - Search by semantic meaning (not just keywords)
        - Get full context for answering questions
        - Analyze content patterns and distributions
        - Group/breakdown results by any dimension
        
        **When to use:**
        - "Find/search/show me pages about X"
        - "What content discusses Y?"
        - "Which work items mention authentication?"
        - "Show me recent documentation about APIs"
        - "Break down results by project/date/priority/etc."
        
        **Do NOT use for:**
        - Structured database queries (counts, filters on structured fields) → use `mongo_query`
        
        Args:
            query: Search query (semantic meaning, not just keywords)
            content_type: Filter by type - 'page', 'work_item', 'project', 'cycle', 'module', 'epic', or None (all)
            group_by: Group results by field - 'project_name', 'updatedAt', 'priority', 'state_name', 
                    'content_type', 'assignee_name', 'visibility', etc. (None = no grouping)
            limit: Max results to retrieve (default 10, increase for broader searches)
            show_content: If True, shows full content; if False, shows only metadata
            use_chunk_aware: If True, uses chunk-aware retrieval for better context (default True)
        
        Returns: FULL chunk content with rich metadata - ready for LLM synthesis and formatting
        
        Examples:
            query="authentication" → finds all content about authentication with full text
            query="API documentation", content_type="page" → finds API docs pages with complete content
            query="bugs", content_type="work_item", group_by="priority" → work items grouped by priority
        """
        try:
            # Fix: Add project root to sys.path to resolve module imports
            # This makes 'qdrant' and 'mongo' modules importable from any script location.
            # Adjust the number of os.path.dirname if your directory structure is different.
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.append(project_root)
            from qdrant.retrieval import ChunkAwareRetriever, format_reconstructed_results
        except ImportError as e:
            return f"❌ RAG dependency error: {e}. Please ensure all modules are in the correct path."
        except Exception as e:
            return f"❌ RAG SEARCH INITIALIZATION ERROR: {str(e)}"
        
        try:
            from collections import defaultdict

            # Ensure RAGTool is initialized
            try:
                rag_tool = RAGTool.get_instance()
            except RuntimeError:
                # Try to initialize if not already done
                await RAGTool.initialize()
                rag_tool = RAGTool.get_instance()
            
            # Resolve effective limit based on content_type defaults (opt-in when caller uses default)
            effective_limit: int = limit
            if content_type:
                default_for_type = CONTENT_TYPE_DEFAULT_LIMITS.get(content_type)
                if default_for_type is not None and (limit is None or limit == DEFAULT_RAG_LIMIT):
                    effective_limit = default_for_type

            # Use chunk-aware retrieval if enabled and not grouping
            if use_chunk_aware and not group_by:
                # from qdrant.retrieval import ChunkAwareRetriever, format_reconstructed_results
                
                # retriever = ChunkAwareRetriever(
                #     qdrant_client=rag_tool.qdrant_client,
                #     embedding_model=rag_tool.embedding_model
                # )
                
                from mongo.constants import QDRANT_COLLECTION_NAME
                
                # Per content_type chunk-level tuning
                chunks_per_doc = CONTENT_TYPE_CHUNKS_PER_DOC.get(content_type or "", 3)
                include_adjacent = CONTENT_TYPE_INCLUDE_ADJACENT.get(content_type or "", True)
                min_score = CONTENT_TYPE_MIN_SCORE.get(content_type or "", 0.5)

                from mongo.constants import RAG_CONTEXT_TOKEN_BUDGET
                reconstructed_docs = await self.search_with_context(
                    query=query,
                    project_id=project_id,
                    collection_name=QDRANT_COLLECTION_NAME,
                    content_type=content_type,
                    limit=effective_limit,
                    chunks_per_doc=chunks_per_doc,
                    include_adjacent=include_adjacent,
                    min_score=min_score,
                    context_token_budget=RAG_CONTEXT_TOKEN_BUDGET
                )
                
                if not reconstructed_docs:
                    return f"❌ No results found for query: '{query}'"
                
                # Always pass full content chunks to the agent by default for synthesis
                # Force show_full_content=True so downstream LLM has full context
                return format_reconstructed_results(
                    docs=reconstructed_docs,
                    show_full_content=True,
                    show_chunk_details=True
                ) 
        except:
            logger.error("RAG Search Failed.")

    async def execute_rag_search(
            self,
            query: str,
            project_id: str = None,
            content_type: str = "work_item",  # Keep focused on work items for smart filtering
            limit: int = 20,
            use_chunk_aware: bool = True
        ) -> RAGSearchResult:
            """
            Execute RAG search to find work items by directly using retriever, then fetch complete documents.
            Optimized to avoid returning chunk content to save tokens.

            Args:
                query: Search query
                content_type: Content type to search (default: work_item)
                limit: Maximum results to retrieve
                use_chunk_aware: Whether to use chunk-aware retrieval

            Returns:
                RAGSearchResult with complete work item documents
            """
            try:
                work_item_ids = set()
                reconstructed_docs = None

                # Try optimized path first: use ChunkAwareRetriever directly
                rag_initialized = await self.ensure_rag_initialized()
                if rag_initialized and self.retriever and use_chunk_aware:
                    try:
                        # Get reconstructed docs directly without formatting content for agent
                        reconstructed_docs = await self.search_with_context(
                            query=query,
                            project_id=project_id,
                            collection_name=QDRANT_COLLECTION_NAME,
                            content_type=content_type,
                            limit=limit,
                            chunks_per_doc=3,
                            include_adjacent=True,
                            min_score=0.1,  # Lower threshold for better recall
                            min_keyword_overlap=0.0,  # Remove keyword overlap requirement
                            context_token_budget=4000
                        )

                        # Extract work item IDs directly from reconstructed docs
                        for doc in reconstructed_docs:
                            if doc.mongo_id:
                                work_item_ids.add(str(doc.mongo_id))

                            # Collect metadata-sourced identifiers
                            if doc.metadata:
                                for key in ["mongo_id", "work_item_id", "workItemId", "displayBugNo", "display_bug_no"]:
                                    value = doc.metadata.get(key)
                                    if isinstance(value, str) and value.strip():
                                        work_item_ids.add(value.strip())
                                    elif isinstance(value, list):
                                        for item in value:
                                            if isinstance(item, str) and item.strip():
                                                work_item_ids.add(item.strip())

                            # Regex-based fallback from reconstructed content
                            try:
                                import re
                                content_lower = doc.full_content.lower()
                                patterns = [
                                    r'([A-Z]+-\d+)',  # BUG-123 style identifiers
                                    r'displaybugno[:\s]+([\w-]+)',
                                    r'bug[:\s]+([\w-]+)',
                                ]
                                for pattern in patterns:
                                    for match in re.findall(pattern, content_lower, re.IGNORECASE):
                                        if isinstance(match, tuple):
                                            match = match[0]
                                        cleaned = re.sub(r'[^\w-]', '', match)
                                        if cleaned:
                                            work_item_ids.add(cleaned)
                            except Exception:
                                pass
    
                    except Exception as e:
                        logger.error(f"Direct RAG search failed: {e}")

                # Fallback: use rag_search tool if optimized path failed or no IDs found
                if not work_item_ids and rag_search:
                    try:
                        result = await rag_search.ainvoke({
                            "query": query,
                            "content_type": content_type,
                            "limit": limit,
                            "show_content": False,  # Don't return content to save tokens
                            "use_chunk_aware": use_chunk_aware
                        })

                        # Parse minimal result to extract work item IDs
                        lines = result.split('\n')
                        for line in lines:
                            line = line.strip()

                            # Look for work item patterns in the minimal content
                            if content_type == "work_item" and 'displayBugNo:' in line:
                                try:
                                    bug_match = line.split('displayBugNo: ')[1]
                                    if bug_match:
                                        bug_number = bug_match.split()[0].rstrip(',')
                                        if bug_number and len(bug_number) > 2:
                                            work_item_ids.add(bug_number)
                                except Exception:
                                    pass

                            # Look for ID patterns
                            if 'mongo_id:' in line or 'id:' in line:
                                try:
                                    id_part = line.split(':')[1].strip()
                                    if id_part and len(id_part) > 2:
                                        work_item_ids.add(id_part)
                                except Exception:
                                    pass

                    except Exception as e:
                        logger.error(f"Fallback RAG search failed: {e}")

                # Fetch complete work item documents by IDs
                work_items = []
                if work_item_ids:
                    work_items = await self.fetch_work_items_by_ids(work_item_ids)
                    # Limit results to the requested limit
                    work_items = work_items[:limit]

                return RAGSearchResult(
                    work_items=work_items,
                    total_count=len(work_items),
                    query=query,
                    reconstructed_docs=reconstructed_docs,
                    work_item_ids=work_item_ids,
                    rag_context=""
                )

            except Exception as e:
                raise RuntimeError(f"RAG search execution failed: {str(e)}")



# Global instance
# smart_filter_tools = SmartFilterTools()
