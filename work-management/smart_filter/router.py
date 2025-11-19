from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

# Smart Filter API Models
class SmartFilterRequest(BaseModel):
    query: str
    project_id: str
    limit: Optional[int] = 50


class WorkItemState(BaseModel):
    id: str
    name: str


class WorkItemStateMaster(BaseModel):
    id: str
    name: str


class WorkItemAssignee(BaseModel):
    id: str
    name: str


class WorkItemLabel(BaseModel):
    id: str
    name: str
    color: Optional[str] = None


class WorkItemModules(BaseModel):
    id: str
    name: str


class WorkItemCycle(BaseModel):
    id: str
    name: str
    title: Optional[str] = None


class WorkItemBusiness(BaseModel):
    id: str
    name: str


class WorkItemLead(BaseModel):
    id: str
    name: str


class WorkItemProject(BaseModel):
    id: str
    name: str


class WorkItemCreatedBy(BaseModel):
    id: str
    name: str


class WorkItemUpdatedBy(BaseModel):
    id: str
    name: str


class WorkItemParent(BaseModel):
    id: str
    name: str


class WorkItem(BaseModel):
    title: str
    description: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    releaseDate: Optional[str] = None
    stateMaster: WorkItemStateMaster
    state: WorkItemState
    business: WorkItemBusiness
    lead: Optional[WorkItemLead] = None
    priority: str
    assignee: List[WorkItemAssignee]
    label: List[WorkItemLabel]
    cycle: Optional[WorkItemCycle] = None
    modules: Optional[WorkItemModules] = None
    parent: Optional[WorkItemParent] = None
    workLogs: Optional[List[Any]] = None
    estimateSystem: Optional[str] = None
    estimate: Optional[str] = None
    id: str
    project: WorkItemProject
    view: Optional[str] = None
    displayBugNo: str
    status: str
    createdBy: WorkItemCreatedBy
    updatedBy: Optional[WorkItemUpdatedBy] = None
    attachmentUrl: Optional[str] = None
    link: Optional[str] = None
    userStory: Optional[str] = None
    feature: Optional[str] = None
    epic: Optional[str] = None
    createdTimeStamp: str
    updatedTimeStamp: str
    subWorkItems: Optional[List[Any]] = None
    timeline: Optional[List[Any]] = None


class SmartFilterResponse(BaseModel):
    data: List[WorkItem]

# Global smart filter agent instance
smart_filter_agent = None

def set_smart_filter_agent(agent):
    """Set the smart filter agent instance from the main app"""
    global smart_filter_agent
    smart_filter_agent = agent

router = APIRouter(prefix="/smart-filter", tags=["smart-filter"])

@router.post("/work-items", response_model=SmartFilterResponse)
async def smart_filter_work_items(req: SmartFilterRequest):
    """Smart filter work items using RAG + MongoDB queries based on natural language.

    This endpoint combines retrieval-augmented generation (RAG) with MongoDB aggregation
    pipelines to intelligently filter work items based on natural language queries.

    The process:
    1. Uses RAG to find relevant documents and extract work item references
    2. Parses the natural language query to extract filtering criteria
    3. Builds and executes optimized MongoDB aggregation pipeline
    4. Returns work items in the exact API response structure

    Example queries:
    - "high priority bugs assigned to John"
    - "tasks due this week in the authentication module"
    - "completed features in sprint 3"
    - "work items with 'login' in the title"
    """
    try:
        if smart_filter_agent is None:
            raise HTTPException(status_code=500, detail="Smart filter agent not initialized")

        result = await smart_filter_agent.smart_filter_work_items(
            query=req.query,
            project_id=req.project_id,
            limit=req.limit or 50
        )

        return SmartFilterResponse(
            data=result.work_items
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
