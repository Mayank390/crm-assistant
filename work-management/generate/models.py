from typing import Dict, Any, Optional
from pydantic import BaseModel


class TemplateInput(BaseModel):
    title: str
    content: str


class ContextEnvelope(BaseModel):
    tenantId: str
    page: Dict[str, Any]
    subject: Dict[str, Any]
    timeScope: Dict[str, Any]
    retrieval: Dict[str, Any]
    privacy: Dict[str, Any]


class GenerateRequest(BaseModel):
    prompt: str
    template: TemplateInput


class GenerateResponse(BaseModel):
    title: str
    description: str


class PageGenerateRequest(BaseModel):
    context: ContextEnvelope
    template: TemplateInput
    prompt: str
    pageId: str
    projectId: str
    tenantId: str


class WorkItemSurpriseMeRequest(BaseModel):
    title: str
    description: Optional[str] = None


class CycleSurpriseMeRequest(BaseModel):
    title: str
    description: Optional[str] = None


class ModuleSurpriseMeRequest(BaseModel):
    title: str
    description: Optional[str] = None


class EpicSurpriseMeRequest(BaseModel):
    title: str
    description: Optional[str] = None

