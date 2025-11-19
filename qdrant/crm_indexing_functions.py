# CRM Indexing Functions - Template for insertdocs.py

def index_leads_to_qdrant():
    """Index Lead collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index: {e}")

        documents = lead_collection.find({}, {
            "_id": 1, "referenceNo": 1, "leadStatus": 1, "personalInfo": 1, 
            "notes": 1, "moreInfo": 1, "fieldData": 1, "company": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1,
            "createdById": 1, "createdByName": 1, "staffId": 1, "staffName": 1,
            "pipeline": 1, "source": 1, "type": 1, "customerType": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content from various fields
            text_parts = []
            
            # Personal info
            if doc.get("personalInfo"):
                pi = doc["personalInfo"]
                if isinstance(pi, dict):
                    if pi.get("name"):
                        text_parts.append(f"Name: {pi['name']}")
                    if pi.get("email"):
                        text_parts.append(f"Email: {pi['email']}")
                    if pi.get("mobile"):
                        text_parts.append(f"Mobile: {pi['mobile']}")
            
            # Notes
            if doc.get("notes"):
                text_parts.append(f"Notes: {doc['notes']}")
            
            # More info
            if doc.get("moreInfo") and isinstance(doc["moreInfo"], dict):
                for key, value in doc["moreInfo"].items():
                    if isinstance(value, str) and value.strip():
                        text_parts.append(f"{key}: {value}")
            
            # Company info
            if doc.get("company") and isinstance(doc["company"], dict):
                if doc["company"].get("name"):
                    text_parts.append(f"Company: {doc['company']['name']}")
            
            # Field data
            if doc.get("fieldData") and isinstance(doc["fieldData"], list):
                for field in doc["fieldData"]:
                    if isinstance(field, dict) and field.get("fieldValue"):
                        field_name = field.get("fieldName", "")
                        field_value = str(field.get("fieldValue", ""))
                        if field_value.strip():
                            text_parts.append(f"{field_name}: {field_value}")
            
            combined_text = " ".join(text_parts).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "referenceNo": doc.get("referenceNo"),
                "leadStatus": doc.get("leadStatus"),
                "type": doc.get("type"),
                "customerType": doc.get("customerType"),
                "source": doc.get("source"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            # Business ID
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Pipeline
            if doc.get("pipeline") and isinstance(doc["pipeline"], dict):
                metadata["pipeline_name"] = doc["pipeline"].get("name")
            
            # Created by
            if doc.get("createdByName"):
                metadata["created_by_name"] = doc["createdByName"]
            
            if doc.get("staffName"):
                metadata["staff_name"] = doc["staffName"]
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "lead")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("lead", mongo_id, doc.get("referenceNo", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("referenceNo", f"Lead {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "lead"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/lead/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid leads to index.")
            return {"status": "warning", "message": "No valid leads found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} lead chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during lead indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_tasks_to_qdrant():
    """Index Task collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception as e:
            if "already exists" not in str(e):
                logger.error(f"Failed to ensure index: {e}")

        documents = task_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "priority": 1, "taskStatus": 1,
            "dueDate": 1, "parentId": 1, "parentName": 1, "assignedTo": 1, "assignedName": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("name"):
                text_parts.append(doc["name"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("parentName"):
                text_parts.append(f"Parent: {doc['parentName']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "priority": doc.get("priority"),
                "taskStatus": doc.get("taskStatus"),
                "dueDate": doc.get("dueDate"),
                "parentName": doc.get("parentName"),
                "assignedName": doc.get("assignedName"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "task")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("task", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Task {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "task"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/task/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid tasks to index.")
            return {"status": "warning", "message": "No valid tasks found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} task chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during task indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_activities_to_qdrant():
    """Index Activity collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = activity_collection.find({}, {
            "_id": 1, "type": 1, "activityStatus": 1, "data": 1,
            "leadId": 1, "parentId": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1, "createdById": 1, "createdByName": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content from data field (often JSON string)
            text_parts = []
            if doc.get("type"):
                text_parts.append(f"Type: {doc['type']}")
            if doc.get("data"):
                data = doc["data"]
                if isinstance(data, str):
                    text_parts.append(data)
                elif isinstance(data, dict):
                    # Serialize dict to text
                    for key, value in data.items():
                        if isinstance(value, str) and value.strip():
                            text_parts.append(f"{key}: {value}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "type": doc.get("type"),
                "activityStatus": doc.get("activityStatus"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "activity")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("activity", mongo_id, doc.get("type", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("type", f"Activity {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "activity"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/activity/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid activities to index.")
            return {"status": "warning", "message": "No valid activities found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} activity chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during activity indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_meetings_to_qdrant():
    """Index Meeting collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = meeting_collection.find({}, {
            "_id": 1, "title": 1, "description": 1, "meetingStatus": 1, "meetingType": 1,
            "leadId": 1, "leadName": 1, "startDateTime": 1, "endDateTime": 1,
            "assignedTo": 1, "assignedName": 1, "participantsList": 1, "meetingLink": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1, "updatedTimeStamp": 1,
            "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("title"):
                text_parts.append(doc["title"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("leadName"):
                text_parts.append(f"Lead: {doc['leadName']}")
            if doc.get("participantsList") and isinstance(doc["participantsList"], list):
                participants = []
                for p in doc["participantsList"]:
                    if isinstance(p, dict):
                        if p.get("leadName"):
                            participants.append(p["leadName"])
                if participants:
                    text_parts.append(f"Participants: {', '.join(participants)}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "meetingStatus": doc.get("meetingStatus"),
                "meetingType": doc.get("meetingType"),
                "leadName": doc.get("leadName"),
                "assignedName": doc.get("assignedName"),
                "createdByName": doc.get("createdByName"),
                "startDateTime": doc.get("startDateTime"),
                "endDateTime": doc.get("endDateTime"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "meeting")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("meeting", mongo_id, doc.get("title", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("title", f"Meeting {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "meeting"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/meeting/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid meetings to index.")
            return {"status": "warning", "message": "No valid meetings found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} meeting chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during meeting indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_notes_to_qdrant():
    """Index Notes collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = notes_collection.find({}, {
            "_id": 1, "subject": 1, "description": 1, "leadId": 1, "leadName": 1,
            "taskId": 1, "createdById": 1, "createdByName": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("subject"):
                text_parts.append(doc["subject"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("leadName"):
                text_parts.append(f"Lead: {doc['leadName']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "leadName": doc.get("leadName"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "notes")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("notes", mongo_id, doc.get("subject", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("subject", f"Note {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "notes"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/notes/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid notes to index.")
            return {"status": "warning", "message": "No valid notes found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} notes chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during notes indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_callLogs_to_qdrant():
    """Index CallLog collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = callLog_collection.find({}, {
            "_id": 1, "title": 1, "description": 1, "callPurpose": 1, "callStatus": 1,
            "callType": 1, "leadId": 1, "leadName": 1, "startDateTime": 1, "callDuration": 1,
            "otherReason": 1, "createdById": 1, "createdByName": 1,
            "createdTimeStamp": 1, "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("title"):
                text_parts.append(doc["title"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("callPurpose"):
                text_parts.append(f"Purpose: {doc['callPurpose']}")
            if doc.get("otherReason"):
                text_parts.append(f"Reason: {doc['otherReason']}")
            if doc.get("leadName"):
                text_parts.append(f"Lead: {doc['leadName']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "callStatus": doc.get("callStatus"),
                "callType": doc.get("callType"),
                "callPurpose": doc.get("callPurpose"),
                "leadName": doc.get("leadName"),
                "createdByName": doc.get("createdByName"),
                "startDateTime": doc.get("startDateTime"),
                "callDuration": doc.get("callDuration"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "callLog")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("callLog", mongo_id, doc.get("title", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("title", f"Call Log {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "callLog"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/callLog/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid call logs to index.")
            return {"status": "warning", "message": "No valid call logs found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} call log chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during call log indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_mailInfos_to_qdrant():
    """Index MailInfo collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = mailInfo_collection.find({}, {
            "_id": 1, "subject": 1, "body": 1, "mailType": 1, "leadId": 1,
            "toMails": 1, "toCcMails": 1, "toBccMails": 1, "attachments": 1,
            "createdById": 1, "createdByName": 1, "createdTimeStamp": 1,
            "updatedTimeStamp": 1, "businessId": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("subject"):
                text_parts.append(doc["subject"])
            if doc.get("body"):
                body_clean = html_to_text(doc["body"])
                if body_clean:
                    text_parts.append(body_clean)
            if doc.get("toMails"):
                if isinstance(doc["toMails"], list):
                    text_parts.append(f"To: {', '.join(doc['toMails'])}")
                elif isinstance(doc["toMails"], str):
                    text_parts.append(f"To: {doc['toMails']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "mailType": doc.get("mailType"),
                "createdByName": doc.get("createdByName"),
                "createdTimeStamp": doc.get("createdTimeStamp"),
                "updatedTimeStamp": doc.get("updatedTimeStamp"),
            }
            
            if doc.get("businessId"):
                try:
                    metadata["business_id"] = normalize_mongo_id(doc["businessId"])
                except Exception:
                    pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "mailInfo")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("mailInfo", mongo_id, doc.get("subject", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("subject", f"Mail {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "mailInfo"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/mailInfo/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid mail infos to index.")
            return {"status": "warning", "message": "No valid mail infos found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} mail info chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during mail info indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_leadScoreRules_to_qdrant():
    """Index LeadScoreRule collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = leadScoreRule_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "score": 1, "change": 1,
            "isActive": 1, "field": 1, "operator": 1, "value": 1,
            "business": 1, "createdAt": 1, "updatedAt": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("name"):
                text_parts.append(doc["name"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("field"):
                text_parts.append(f"Field: {doc['field']}")
            if doc.get("operator"):
                text_parts.append(f"Operator: {doc['operator']}")
            if doc.get("value"):
                text_parts.append(f"Value: {doc['value']}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "score": doc.get("score"),
                "change": doc.get("change"),
                "isActive": doc.get("isActive"),
                "field": doc.get("field"),
                "operator": doc.get("operator"),
                "value": doc.get("value"),
                "createdAt": doc.get("createdAt"),
                "updatedAt": doc.get("updatedAt"),
            }
            
            if doc.get("business") and isinstance(doc["business"], dict):
                if doc["business"].get("_id"):
                    try:
                        metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
                    except Exception:
                        pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "leadScoreRule")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("leadScoreRule", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Lead Score Rule {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "leadScoreRule"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/leadScoreRule/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid lead score rules to index.")
            return {"status": "warning", "message": "No valid lead score rules found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} lead score rule chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during lead score rule indexing: {e}")
        return {"status": "error", "message": str(e)}


def index_segmentations_to_qdrant():
    """Index Segmentation collection to Qdrant"""
    try:
        ensure_collection_with_hybrid(QDRANT_COLLECTION, vector_size=EMBEDDING_DIMENSION)
        
        documents = segmentation_collection.find({}, {
            "_id": 1, "name": 1, "description": 1, "conditions": 1, "tags": 1,
            "isActive": 1, "business": 1, "createdAt": 1, "updatedAt": 1
        })
        points = []
        splade = get_splade_encoder()
        
        for doc in documents:
            mongo_id = normalize_mongo_id(doc["_id"])
            
            # Build text content
            text_parts = []
            if doc.get("name"):
                text_parts.append(doc["name"])
            if doc.get("description"):
                text_parts.append(doc["description"])
            if doc.get("conditions"):
                if isinstance(doc["conditions"], dict):
                    # Serialize conditions dict
                    conditions_text = json.dumps(doc["conditions"], indent=2)
                    text_parts.append(f"Conditions: {conditions_text}")
                elif isinstance(doc["conditions"], str):
                    text_parts.append(f"Conditions: {doc['conditions']}")
            if doc.get("tags") and isinstance(doc["tags"], list):
                text_parts.append(f"Tags: {', '.join(doc['tags'])}")
            
            combined_text = " ".join(filter(None, text_parts)).strip()
            if not combined_text:
                continue
            
            # Extract metadata
            metadata = {
                "isActive": doc.get("isActive"),
                "createdAt": doc.get("createdAt"),
                "updatedAt": doc.get("updatedAt"),
            }
            
            if doc.get("tags") and isinstance(doc["tags"], list):
                metadata["tags"] = doc["tags"]
            
            if doc.get("business") and isinstance(doc["business"], dict):
                if doc["business"].get("_id"):
                    try:
                        metadata["business_id"] = normalize_mongo_id(doc["business"]["_id"])
                    except Exception:
                        pass
            
            # Chunk text
            chunks = get_chunks_for_content(combined_text, "segmentation")
            if not chunks:
                chunks = [combined_text]
            
            word_count = len(combined_text.split())
            _stats.record("segmentation", mongo_id, doc.get("name", ""), len(chunks), word_count)
            
            vectors = embedder.encode(chunks)
            if len(vectors) != len(chunks):
                raise EmbeddingServiceError("Embedding service returned unexpected vector count")
            
            for idx, chunk in enumerate(chunks):
                vector = vectors[idx]
                title = doc.get("name", f"Segmentation {mongo_id[:8]}")
                full_text = f"{title} {chunk}".strip()
                splade_vec = splade.encode_text(full_text)
                
                payload = {
                    "mongo_id": mongo_id,
                    "parent_id": mongo_id,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "title": title,
                    "content": chunk,
                    "full_text": full_text,
                    "content_type": "segmentation"
                }
                payload.update({k: v for k, v in metadata.items() if v is not None})
                
                point_kwargs = {
                    "id": point_id_from_seed(f"{mongo_id}/segmentation/{idx}"),
                    "vector": {"dense": vector},
                    "payload": payload,
                }
                if splade_vec.get("indices"):
                    point_kwargs["vector"]["sparse"] = SparseVector(
                        indices=splade_vec["indices"], values=splade_vec["values"]
                    )
                points.append(PointStruct(**point_kwargs))
        
        if not points:
            logger.warning("No valid segmentations to index.")
            return {"status": "warning", "message": "No valid segmentations found to index."}
        
        total_indexed = upload_in_batches(points, QDRANT_COLLECTION)
        logger.info(f"✅ Indexed {total_indexed} segmentation chunks to Qdrant.")
        return {"status": "success", "indexed_documents": total_indexed}
    
    except Exception as e:
        logger.error(f"Error during segmentation indexing: {e}")
        return {"status": "error", "message": str(e)}

