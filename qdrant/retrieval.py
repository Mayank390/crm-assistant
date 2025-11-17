"""
Chunk-Aware RAG Retrieval System

Improves context quality by:
1. Retrieving multiple relevant chunks from the same document
2. Fetching adjacent chunks for better context continuity
3. Reconstructing documents from related chunks
4. Deduplicating and merging overlapping chunks intelligently
"""

from typing import List, Dict, Any, Optional, Set, Tuple
import re
import uuid
import logging
from bson import ObjectId, Binary
from mongo.constants import BUSINESS_UUID, MEMBER_UUID
from collections import defaultdict
from dataclasses import dataclass
import asyncio
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue, MatchAny, Prefetch, NearestQuery, FusionQuery, Fusion, SparseVector
)

# Configure logging
logger = logging.getLogger(__name__)

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


class ChunkAwareRetriever:
    """Enhanced RAG retrieval with chunk awareness and context reconstruction"""
    
    def __init__(self, qdrant_client, embedding_client):
        self.qdrant_client = qdrant_client
        self.embedding_client = embedding_client
        # ✅ OPTIMIZED: Cache member projects per request to avoid repeated MongoDB queries
        self._member_projects_cache: Dict[str, List[str]] = {}
        # Minimal English stopword list for lightweight keyword-overlap filtering
        self._STOPWORDS: Set[str] = {
            "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at", "by",
            "for", "with", "about", "against", "between", "into", "through", "during", "before",
            "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off",
            "over", "under", "again", "further", "here", "there", "why", "how", "all", "any",
            "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "can", "will", "just"
        }
    
    async def search_with_context(
        self,
        query: str,
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
        if vectors is None or len(vectors) == 0:
            raise RuntimeError("Embedding service returned empty vector")
        query_embedding = vectors[0]
        
        # Build filter with optional content_type and global business scoping
        must_conditions = []
        if content_type:
            must_conditions.append(FieldCondition(key="content_type", match=MatchValue(value=content_type)))

        # Business-level scoping
        # Note: business_id in Qdrant is stored as normalized UUID string from MongoDB Binary
        # We need to normalize it the same way as insertdocs.py does
        business_uuid = BUSINESS_UUID()
        if business_uuid:
            normalized_business_id = self._normalize_business_id(business_uuid)
            must_conditions.append(FieldCondition(key="business_id", match=MatchValue(value=normalized_business_id)))

        # Member-level project RBAC scoping
        # ✅ OPTIMIZED: Cache member projects at request start
        member_uuid = MEMBER_UUID()
        if member_uuid:
            try:
                # Check cache first
                cache_key = f"{member_uuid}:{business_uuid}"
                if cache_key not in self._member_projects_cache:
                    self._member_projects_cache[cache_key] = await self._get_member_projects(member_uuid, business_uuid)
                member_projects = self._member_projects_cache[cache_key]
                if member_projects:
                    # Only apply member filtering for content types that belong to projects
                    project_content_types = {"page", "work_item", "cycle", "module", "epic", "feature", "user_story"}
                    if content_type is None or content_type in project_content_types:
                        # Filter by accessible project IDs
                        must_conditions.append(FieldCondition(key="project_id", match=MatchAny(any=member_projects)))
                    elif content_type == "project":
                        # For project searches, only show projects the member has access to
                        must_conditions.append(FieldCondition(key="mongo_id", match=MatchAny(any=member_projects)))
            except Exception as e:
                # Error getting member projects - log and skip member filter
                logger.error(f"Error getting member projects for '{member_uuid}': {e}")

        search_filter = Filter(must=must_conditions) if must_conditions else None

        # Fetch more chunks initially to ensure we have multiple per document
        # ✅ OPTIMIZED: Reduced initial limit to prevent over-fetching
        initial_limit = min(max(limit * chunks_per_doc * 2, 20), 30)

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
        ✅ OPTIMIZED: Batch fetch all adjacent chunks in a single Qdrant query instead of sequential loops.
        Modifies doc_chunks in place.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
        
        # Collect all chunks to fetch across all documents
        all_chunks_to_fetch: List[Tuple[str, int]] = []  # (parent_id, chunk_index)
        
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
            
            # Collect all chunks to fetch
            for chunk_idx in to_fetch:
                all_chunks_to_fetch.append((parent_id, chunk_idx))
        
        if not all_chunks_to_fetch:
            return
        
        # ✅ OPTIMIZED: Batch fetch all chunks in a single query using $or filter
        business_uuid = BUSINESS_UUID()
        member_uuid = MEMBER_UUID()
        
        # Get member projects once (use cache if available)
        member_projects = None
        if member_uuid:
            try:
                cache_key = f"{member_uuid}:{business_uuid}"
                if cache_key not in self._member_projects_cache:
                    self._member_projects_cache[cache_key] = await self._get_member_projects(member_uuid, business_uuid)
                member_projects = self._member_projects_cache[cache_key]
            except Exception as e:
                logger.error(f"Error getting member projects for adjacent chunks '{member_uuid}': {e}")
        
        # Build batch filter conditions
        should_conditions = []
        for parent_id, chunk_idx in all_chunks_to_fetch:
            conditions = [
                FieldCondition(key="parent_id", match=MatchValue(value=parent_id)),
                FieldCondition(key="chunk_index", match=MatchValue(value=chunk_idx))
            ]
            
            if content_type:
                conditions.append(FieldCondition(key="content_type", match=MatchValue(value=content_type)))
            
            if business_uuid:
                normalized_business_id = self._normalize_business_id(business_uuid)
                conditions.append(FieldCondition(key="business_id", match=MatchValue(value=normalized_business_id)))
            
            # Add member project filter if applicable
            if member_projects:
                project_content_types = {"page", "work_item", "cycle", "module", "epic", "feature", "user_story"}
                if content_type is None or content_type in project_content_types:
                    conditions.append(FieldCondition(key="project_id", match=MatchAny(any=member_projects)))
                elif content_type == "project":
                    conditions.append(FieldCondition(key="mongo_id", match=MatchAny(any=member_projects)))
            
            should_conditions.append(Filter(must=conditions))
        
        if not should_conditions:
            return
        
        # Single batch query for all adjacent chunks
        try:
            batch_filter = Filter(should=should_conditions)
            scroll_result = self.qdrant_client.scroll(
                collection_name=collection_name,
                scroll_filter=batch_filter,
                limit=len(all_chunks_to_fetch),
                with_payload=True,
                with_vectors=False
            )
            
            if scroll_result and scroll_result[0]:
                # Group fetched chunks by parent_id
                fetched_by_parent: Dict[str, Dict[int, ChunkResult]] = defaultdict(dict)
                
                for point in scroll_result[0]:
                    payload = point.payload or {}
                    parent_id = payload.get("parent_id", payload.get("mongo_id", ""))
                    chunk_idx = payload.get("chunk_index", 0)
                    
                    adj_content_text = payload.get("content") or payload.get("full_text") or payload.get("title", "")
                    
                    adjacent_chunk = ChunkResult(
                        id=str(point.id),
                        score=0.0,  # Adjacent chunks get 0 score (context only)
                        content=adj_content_text,
                        mongo_id=payload.get("mongo_id", ""),
                        parent_id=parent_id,
                        chunk_index=chunk_idx,
                        chunk_count=payload.get("chunk_count", 1),
                        title=payload.get("title", "Untitled"),
                        content_type=payload.get("content_type", "unknown"),
                        metadata={k: v for k, v in payload.items() 
                                 if k not in ["content", "full_text", "mongo_id", "parent_id",
                                             "chunk_index", "chunk_count", "title", "content_type"]}
                    )
                    fetched_by_parent[parent_id][chunk_idx] = adjacent_chunk
                
                # Add fetched chunks to doc_chunks
                for parent_id, chunks in doc_chunks.items():
                    if parent_id in fetched_by_parent:
                        for chunk_idx, chunk in fetched_by_parent[parent_id].items():
                            chunks.append(chunk)
        
        except Exception as e:
            logger.warning(f"Batch fetch of adjacent chunks failed, falling back to sequential: {e}")
            # Fallback to sequential if batch fails
            for parent_id, chunk_idx in all_chunks_to_fetch:
                try:
                    filter_conditions = [
                        FieldCondition(key="parent_id", match=MatchValue(value=parent_id)),
                        FieldCondition(key="chunk_index", match=MatchValue(value=chunk_idx))
                    ]
                    if content_type:
                        filter_conditions.append(FieldCondition(key="content_type", match=MatchValue(value=content_type)))
                    if business_uuid:
                        normalized_business_id = self._normalize_business_id(business_uuid)
                        filter_conditions.append(FieldCondition(key="business_id", match=MatchValue(value=normalized_business_id)))
                    
                    # Add member project filter if applicable (RBAC compliance)
                    if member_projects:
                        project_content_types = {"page", "work_item", "cycle", "module", "epic", "feature", "user_story"}
                        if content_type is None or content_type in project_content_types:
                            filter_conditions.append(FieldCondition(key="project_id", match=MatchAny(any=member_projects)))
                        elif content_type == "project":
                            filter_conditions.append(FieldCondition(key="mongo_id", match=MatchAny(any=member_projects)))
                    
                    scroll_result = self.qdrant_client.scroll(
                        collection_name=collection_name,
                        scroll_filter=Filter(must=filter_conditions),
                        limit=1,
                        with_payload=True,
                        with_vectors=False
                    )
                    
                    if scroll_result and scroll_result[0]:
                        point = scroll_result[0][0]
                        payload = point.payload or {}
                        adj_content_text = payload.get("content") or payload.get("full_text") or payload.get("title", "")
                        adjacent_chunk = ChunkResult(
                            id=str(point.id),
                            score=0.0,
                            content=adj_content_text,
                            mongo_id=payload.get("mongo_id", ""),
                            parent_id=parent_id,
                            chunk_index=chunk_idx,
                            chunk_count=payload.get("chunk_count", 1),
                            title=payload.get("title", "Untitled"),
                            content_type=payload.get("content_type", "unknown"),
                            metadata={k: v for k, v in payload.items() 
                                     if k not in ["content", "full_text", "mongo_id", "parent_id",
                                                 "chunk_index", "chunk_count", "title", "content_type"]}
                        )
                        doc_chunks[parent_id].append(adjacent_chunk)
                except Exception:
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
    
    def _normalize_business_id(self, business_uuid: str) -> str:
        """Normalize business_id UUID string the same way it's stored in Qdrant.
        
        When storing in Qdrant, business_id comes from MongoDB Binary UUID which is
        normalized using normalize_mongo_id(). This function replicates that normalization
        for filtering purposes.
        
        Args:
            business_uuid: UUID string (e.g., "1eedcb26-d23a-688a-bd63-579d19dab229")
            
        Returns:
            Normalized UUID string as stored in Qdrant
        """
        try:
            from mongo.constants import uuid_str_to_mongo_binary
            business_bin = uuid_str_to_mongo_binary(business_uuid)
            return str(uuid.UUID(bytes=business_bin))
        except Exception as e:
            logger.warning(f"Failed to normalize business_id '{business_uuid}': {e}, using as-is")
            return business_uuid

    async def _get_member_projects(self, member_uuid: str, business_uuid: str) -> List[str]:
        """
        Get list of project IDs that the member has access to.

        Args:
            member_uuid: The member's UUID
            business_uuid: The business UUID for additional scoping

        Returns:
            List of project IDs the member can access (normalized like Qdrant expects)
        """
        try:
            # Import here to avoid circular imports
            from mongo.client import direct_mongo_client
            from mongo.constants import uuid_str_to_mongo_binary

            # Query MongoDB to get projects the member is associated with
            # memberId is the staff ID (staff identifier)
            member_bin = uuid_str_to_mongo_binary(member_uuid)
            pipeline = [
                {
                    "$match": {
                        "$or": [
                            {"memberId": member_bin},
                            {"staff._id": member_bin}
                        ]
                    }
                }
            ]

            # Add business scoping if available - need to join with project collection first
            if business_uuid:
                biz_bin = uuid_str_to_mongo_binary(business_uuid)
                pipeline.extend([
                    {
                        "$lookup": {
                            "from": "project",
                            "localField": "project._id",
                            "foreignField": "_id",
                            "as": "__biz_proj__"
                        }
                    },
                    {
                        "$match": {
                            "__biz_proj__.business._id": biz_bin
                        }
                    },
                    {
                        "$unset": "__biz_proj__"
                    }
                ])

            # Project the project_id
            pipeline.append({
                "$project": {
                    "project_id": "$project._id"
                }
            })

            results = await direct_mongo_client.aggregate("ProjectManagement", "members", pipeline)

            # Extract project IDs and convert back to string format using same normalization as Qdrant
            project_ids = []
            for result in results:
                if result.get("project_id"):
                    project_ids.append(self._normalize_mongo_id(result["project_id"]))

            return project_ids

        except Exception as e:
            logger.error(f"Error querying member projects: {e}")
            return []


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
