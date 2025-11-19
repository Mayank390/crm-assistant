import json
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Dict, Any, List, Optional
from bson import ObjectId
from mongo.conversations import conversation_mongo_client, CONVERSATIONS_DB_NAME, TEMPLATES_COLLECTION_NAME

# Load system default templates from JSON file
def load_system_defaults() -> Dict[str, List[Dict[str, Any]]]:
    """Load system default templates from JSON file."""
    json_path = os.path.join(os.path.dirname(__file__), "system_defaults.json")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="System defaults file not found")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid system defaults JSON")

SYSTEM_DEFAULT_TEMPLATES = load_system_defaults()

def get_system_defaults(template_type: Optional[str] = None, skip: int = 0, limit: int = 50) -> tuple[List[Dict[str, Any]], int]:
    """Get system default templates with optional filtering and pagination."""
    if template_type and template_type in SYSTEM_DEFAULT_TEMPLATES:
        templates = SYSTEM_DEFAULT_TEMPLATES[template_type][skip:skip + limit]
        total_count = len(SYSTEM_DEFAULT_TEMPLATES[template_type])
    elif template_type:
        # No templates for this type
        templates = []
        total_count = 0
    else:
        # Return all templates across all types
        all_templates = []
        for category_templates in SYSTEM_DEFAULT_TEMPLATES.values():
            all_templates.extend(category_templates)

        templates = all_templates[skip:skip + limit]
        total_count = len(all_templates)

    return templates, total_count

# Pydantic models for API requests/responses
class CreateTemplateRequest(BaseModel):
    user_input: str
    project_id: str
    business_id: str
    template_type: str = "work_item"  # Default to work_item
    is_default: bool = False

class GenerateTemplateResponse(BaseModel):
    template: Dict[str, Any]

class TemplateDocument(BaseModel):
    id: str
    project_id: str
    business_id: str
    template: Dict[str, Any]
    is_default: bool = False
    created_at: Optional[str] = None

class CreateTemplateDirectRequest(BaseModel):
    """Request model for directly creating a template."""
    name: str
    description: str
    title: str
    content: str
    priority: str = "Medium"  # Default priority
    template_type: str = "work_item"  # Default template type
    project_id: str
    business_id: str
    is_default: bool = False

    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v):
        allowed_priorities = ['High', 'Medium', 'Low']
        if v not in allowed_priorities:
            raise ValueError(f'Priority must be one of: {", ".join(allowed_priorities)}')
        return v

    @field_validator('template_type')
    @classmethod
    def validate_template_type(cls, v):
        allowed_types = ['work_item', 'page', 'cycle', 'module', 'epic']
        if v not in allowed_types:
            raise ValueError(f'Template type must be one of: {", ".join(allowed_types)}')
        return v

class UpdateTemplateRequest(BaseModel):
    """Request model for updating a template."""
    name: Optional[str] = None
    description: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    priority: Optional[str] = None
    template_type: Optional[str] = None
    is_default: Optional[bool] = None

    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v):
        if v is None:
            return v
        allowed_priorities = ['High', 'Medium', 'Low']
        if v not in allowed_priorities:
            raise ValueError(f'Priority must be one of: {", ".join(allowed_priorities)}')
        return v

    @field_validator('template_type')
    @classmethod
    def validate_template_type(cls, v):
        if v is None:
            return v
        allowed_types = ['work_item', 'page', 'cycle', 'module', 'epic']
        if v not in allowed_types:
            raise ValueError(f'Template type must be one of: {", ".join(allowed_types)}')
        return v

class GetTemplatesResponse(BaseModel):
    templates: List[TemplateDocument]
    total_count: int

class CreateTemplateDirectResponse(BaseModel):
    """Response model for direct template creation."""
    template_id: str
    template: Dict[str, Any]
    created_at: str

# Global template generator instance
template_generator = None

def set_template_generator(generator):
    """Set the template generator instance from the main app"""
    global template_generator
    template_generator = generator

router = APIRouter(prefix="/templates", tags=["templates"])

@router.post("/create", response_model=GenerateTemplateResponse)
async def create_template(req: CreateTemplateRequest):
    """
    Generate a structured template in JSON format based on a user's input and template type.

    The function uses specialized prompts for different template types (work_item, page, cycle, module, epic)
    to generate contextually appropriate templates. Each template type has its own expert prompt
    designed for that specific domain.

    Supported template types:
      - work_item: Individual tasks and activities
      - page: Documentation pages, meeting notes, feature specs
      - cycle: Iterative processes like sprints, releases, reviews
      - module: Software modules, components, integrations
      - epic: Strategic initiatives, product roadmaps, large projects

    The returned template always includes:
      - id (str): Lowercase, hyphen-separated unique identifier.
      - name (str): Human-readable name of the template.
      - description (str): Short summary of the template's purpose.
      - title (str): Formatted title with an emoji and placeholder.
      - content (str): Markdown-formatted sections with relevant headings.
      - priority (str): One of "High", "Medium", or "Low" based on context.

    If insufficient context is provided, an error JSON is returned:
        {"error": "Insufficient context. Please describe your [type] requirements."}

    Example Usage:
        Input:
        {
            "user_input": "I'm a data scientist running model experiments.",
            "template_type": "work_item",
            "project_id": "proj123",
            "business_id": "biz456",
            "is_default": false
        }

        Expected Output:
        {
          "id": "model-experiment",
          "name": "Model Experiment",
          "description": "Template for running and documenting machine learning experiments",
          "title": "🤖 Model Experiment: [Model Name]",
          "content": "## Objective\\n\\n## Hypothesis\\n\\n## Dataset and Features\\n\\n## Model Configuration\\n\\n## Evaluation Metrics\\n\\n## Results and Insights\\n",
          "priority": "High"
        }

    Returns:
        dict: A structured JSON-like dictionary representing the generated template.
    """
    try:
        if template_generator is None:
            raise HTTPException(status_code=500, detail="Template generator not initialized")

        result = await template_generator.generate_template(
            user_input=req.user_input,
            prompt_type=req.template_type
        )
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, TEMPLATES_COLLECTION_NAME)
        if result:
            await coll.insert_one(
                {
                    "project_id": req.project_id,
                    "business_id": req.business_id,
                    "template": result,
                    "is_default": req.is_default
                }
            )
        return GenerateTemplateResponse(
            template = result
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=CreateTemplateDirectResponse)
async def create_template_direct(req: CreateTemplateDirectRequest):
    """
    Create a new template directly without AI generation.

    This endpoint allows direct creation of templates with user-provided content.
    The template will be stored in the database and can be retrieved later.

    Parameters:
      - name: Human-readable name of the template
      - description: Short summary of the template's purpose
      - title: Formatted title with emoji and placeholder
      - content: Markdown-formatted content sections
      - priority: Priority level (High, Medium, Low)
      - template_type: Type of template (work_item, page, cycle, module, epic)
      - project_id: Associated project ID
      - business_id: Associated business ID
      - is_default: Whether this is a default template

    Returns:
        CreateTemplateDirectResponse: Object containing the created template ID and data

    Example:
        POST /templates
        {
            "name": "Custom Bug Report",
            "description": "Template for reporting bugs",
            "title": "🐛 Bug Report: [Issue Title]",
            "content": "## Description\\n\\n## Steps to Reproduce\\n\\n## Expected Behavior\\n",
            "priority": "High",
            "template_type": "work_item",
            "project_id": "proj123",
            "business_id": "biz456",
            "is_default": false
        }
    """
    try:
        # Generate a unique ID for the template
        template_id = str(uuid.uuid4())

        # Create the template structure
        template_data = {
            "id": f"{req.template_type}-{template_id[:8]}",  # Create a readable ID
            "name": req.name,
            "description": req.description,
            "title": req.title,
            "content": req.content,
            "priority": req.priority,
            "template_type": req.template_type
        }

        # Prepare the document for MongoDB
        document = {
            "project_id": req.project_id,
            "business_id": req.business_id,
            "template": template_data,
            "is_default": req.is_default,
            "created_at": datetime.utcnow().isoformat()
        }

        # Insert into database
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, TEMPLATES_COLLECTION_NAME)
        result = await coll.insert_one(document)

        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to create template")

        return CreateTemplateDirectResponse(
            template_id=str(result.inserted_id),
            template=template_data,
            created_at=document["created_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=GetTemplatesResponse)
async def get_templates(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    business_id: Optional[str] = Query(None, description="Filter by business ID"),
    template_type: Optional[str] = Query(None, description="Filter by template type (work_item, page, cycle, module, epic)"),
    limit: int = Query(50, description="Maximum number of templates to return", ge=1, le=100),
    skip: int = Query(0, description="Number of templates to skip", ge=0),
    include_defaults: bool = Query(True, description="Include system default templates if no user templates exist")
):
    """
    Retrieve templates using intelligent priority logic with embedded system defaults.

    Template Priority System:
    1. If user has templates marked as is_default=true → Return user default templates
    2. If user has templates but none marked as default → Return user's templates
    3. If user has no templates → Return system default templates (from code)

    System defaults are embedded in the application code (40 templates total: 8 per category).
    This ensures users always have templates available without requiring database seeding.

    Query Parameters:
      - project_id (optional): Filter templates by project ID
      - business_id (optional): Filter templates by business ID
      - template_type (optional): Filter by template type (work_item, page, cycle, module, epic)
      - limit (optional): Maximum number of templates to return (1-100, default: 50)
      - skip (optional): Number of templates to skip for pagination (default: 0)
      - include_defaults (optional): Include system default templates if no user templates found (default: true)

    Returns:
        GetTemplatesResponse: Object containing:
          - templates: List of template documents with metadata
          - total_count: Total number of templates matching the filters

    Example Usage:
        GET /templates?project_id=proj123&template_type=work_item&limit=10

    Each template document includes:
      - id: MongoDB document ID
      - project_id: Associated project ID
      - business_id: Associated business ID
      - template: The template data (id, name, description, title, content, priority)
      - is_default: Whether this is a system default template
      - created_at: Timestamp when the template was created
    """
    try:
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, TEMPLATES_COLLECTION_NAME)

        # Build base filter for user templates (exclude system defaults)
        user_base_filter = {}
        if project_id:
            user_base_filter["project_id"] = project_id
        if business_id:
            user_base_filter["business_id"] = business_id
        if template_type:
            user_base_filter["template.id"] = {"$regex": f"^{template_type}", "$options": "i"}

        # Exclude system default templates from user query
        user_base_filter["is_default"] = {"$ne": True}

        # First check if user has any templates at all
        user_total_count = await coll.count_documents(user_base_filter)

        templates_docs = []
        total_count = 0

        if user_total_count > 0:
            # User has templates, check if any are marked as default
            user_default_filter = user_base_filter.copy()
            user_default_filter["is_default"] = True

            user_default_count = await coll.count_documents(user_default_filter)

            if user_default_count > 0:
                # User has templates marked as default, return those
                cursor = coll.find(user_default_filter).sort("_id", -1).skip(skip).limit(limit)
                templates_docs = await cursor.to_list(length=None)
                total_count = user_default_count
            else:
                # User has templates but none marked as default, return user's templates
                cursor = coll.find(user_base_filter).sort("_id", -1).skip(skip).limit(limit)
                templates_docs = await cursor.to_list(length=None)
                total_count = user_total_count
        else:
            # User has no templates at all, return system defaults
            if include_defaults:
                system_templates, total_count = get_system_defaults(template_type, skip, limit)
                # Convert system templates to the same format as database documents
                templates_docs = [{
                    "_id": f"system_{i}",
                    "template": template,
                    "is_default": True,
                    "project_id": "system",
                    "business_id": "system"
                } for i, template in enumerate(system_templates)]

        # Convert ObjectId to string and format response
        templates = []
        for doc in templates_docs:
            # Handle both database documents (with ObjectId) and system templates (with string ID)
            if isinstance(doc.get("_id"), str) and doc["_id"].startswith("system_"):
                # System template
                template_doc = {
                    "id": doc["_id"],
                    "project_id": doc["project_id"],
                    "business_id": doc["business_id"],
                    "template": doc["template"],
                    "is_default": doc.get("is_default", False),
                    "created_at": None
                }
            else:
                # Database document
                template_doc = {
                    "id": str(doc["_id"]),
                    "project_id": doc["project_id"],
                    "business_id": doc["business_id"],
                    "template": doc["template"],
                    "is_default": doc.get("is_default", False),
                    "created_at": doc.get("_id").generation_time.isoformat() if doc.get("_id") else None
                }
            templates.append(TemplateDocument(**template_doc))

        return GetTemplatesResponse(
            templates=templates,
            total_count=total_count
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{template_id}", response_model=CreateTemplateDirectResponse)
async def update_template(template_id: str, req: UpdateTemplateRequest):
    """
    Update an existing template.

    This endpoint allows updating template properties. Only provided fields will be updated.

    Parameters:
      - template_id: The MongoDB ObjectId of the template to update
      - name: Human-readable name of the template (optional)
      - description: Short summary of the template's purpose (optional)
      - title: Formatted title with emoji and placeholder (optional)
      - content: Markdown-formatted content sections (optional)
      - priority: Priority level (High, Medium, Low) (optional)
      - template_type: Type of template (work_item, page, cycle, module, epic) (optional)
      - is_default: Whether this is a default template (optional)

    Returns:
        CreateTemplateDirectResponse: Object containing the updated template ID and data

    Example:
        PUT /templates/507f1f77bcf86cd799439011
        {
            "name": "Updated Bug Report",
            "priority": "Low"
        }
    """
    try:
        # Validate that template_id is a valid ObjectId
        try:
            object_id = ObjectId(template_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid template ID format")

        # Get the collection
        coll = await conversation_mongo_client.get_collection(CONVERSATIONS_DB_NAME, TEMPLATES_COLLECTION_NAME)

        # Find the existing template
        existing_doc = await coll.find_one({"_id": object_id})
        if not existing_doc:
            raise HTTPException(status_code=404, detail="Template not found")

        # Prepare update document
        update_data = {}
        template_update = {}

        # Only update fields that are provided
        if req.name is not None:
            template_update["name"] = req.name
        if req.description is not None:
            template_update["description"] = req.description
        if req.title is not None:
            template_update["title"] = req.title
        if req.content is not None:
            template_update["content"] = req.content
        if req.priority is not None:
            template_update["priority"] = req.priority
        if req.template_type is not None:
            # Update the template ID prefix if template_type changed
            template_update["id"] = f"{req.template_type}-{str(uuid.uuid4())[:8]}"
            template_update["template_type"] = req.template_type
        if req.is_default is not None:
            update_data["is_default"] = req.is_default

        # Add updated_at timestamp
        update_data["updated_at"] = datetime.utcnow().isoformat()

        # Build the full update document
        if template_update:
            update_data["template"] = {**existing_doc["template"], **template_update}
        else:
            update_data["template"] = existing_doc["template"]

        # Update the document
        result = await coll.update_one(
            {"_id": object_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update template")

        # Return the updated template
        updated_doc = await coll.find_one({"_id": object_id})
        if not updated_doc:
            raise HTTPException(status_code=500, detail="Failed to retrieve updated template")

        return CreateTemplateDirectResponse(
            template_id=str(updated_doc["_id"]),
            template=updated_doc["template"],
            created_at=updated_doc.get("created_at", updated_doc.get("updated_at"))
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

