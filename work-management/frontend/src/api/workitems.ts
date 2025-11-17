import { WORKITEM_ENDPOINTS } from "@/api/endpoints";
import { getBusinessId, getMemberId } from "@/config";

export type CreateWorkItemRequest = {
  title: string;
  description?: string;
  projectIdentifier?: string;
  projectId?: string;
  cycleId?: string;
  subStateId?: string;
  moduleId?: string;
  assignees?: { id: string; name: string }[];
  labels?: { id: string; name: string; color: string }[];
  startDate?: string;
  endDate?: string;
  createdBy?: { id: string; name: string };
  priority?: string;
  estimate?: number;
  estimateSystem?: string;
  status?: string;
};

export type CreateWorkItemWithMembersRequest = {
  title: string;
  description?: string;
  projectIdentifier?: string;
  projectId?: string;
  cycleId?: string;
  subStateId?: string;
  moduleId?: string;
  assignees?: { id: string; name: string }[];
  labels?: { id: string; name: string; color: string }[];
  startDate?: string;
  endDate?: string;
  createdBy?: { id: string; name: string };
  priority?: string;
  estimate?: number;
  estimateSystem?: string;
  status?: string;
};

export type CreateWorkItemResponse = {
  id: string;
  title: string;
  description: string;
  projectIdentifier?: string;
  sequenceId?: string | number;
  link?: string;
};

export async function createWorkItem(payload: CreateWorkItemRequest): Promise<CreateWorkItemResponse> {
  const endpoint = WORKITEM_ENDPOINTS.CREATE_WORKITEM();

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title,
      description: payload.description || "",
      startDate: payload.startDate,
      endDate: payload.endDate,
      label: payload.labels || [],
      state: payload.subStateId ? {
        id: payload.subStateId,
        name: "" // Will be populated by backend
      } : null,
      createdBy: payload.createdBy || { id: getMemberId(), name: "" },
      priority: payload.priority || "NONE",
      estimate: payload.estimate,
      estimateSystem: payload.estimateSystem || "TIME",
      status: payload.status || "ACCEPTED",
      assignee: payload.assignees ? payload.assignees.map(a => ({
        id: a.id,
        name: a.name
      })) : [],
      modules: payload.moduleId ? {
        id: payload.moduleId,
        name: "" // Will be populated by backend
      } : null,
      cycle: payload.cycleId ? {
        id: payload.cycleId,
        name: "" // Will be populated by backend
      } : null,
      parent: null,
      project: {
        id: payload.projectId || "",
        name: "" // Will be populated by backend
      },
      business: {
        id: getBusinessId(),
        name: "" // Will be populated by backend
      }
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to create work item (${res.status})`);
  }
  return res.json();
}

export async function createWorkItemWithMembers(payload: CreateWorkItemWithMembersRequest): Promise<CreateWorkItemResponse> {
  const endpoint = WORKITEM_ENDPOINTS.CREATE_WORKITEM();

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title,
      description: payload.description || "",
      startDate: payload.startDate,
      endDate: payload.endDate,
      label: payload.labels || [],
      state: payload.subStateId ? {
        id: payload.subStateId,
        name: "" // Will be populated by backend
      } : null,
      createdBy: payload.createdBy || { id: getMemberId(), name: "" },
      priority: payload.priority || "NONE",
      estimate: payload.estimate,
      estimateSystem: payload.estimateSystem || "TIME",
      status: payload.status || "ACCEPTED",
      assignee: payload.assignees ? payload.assignees.map(a => ({
        id: a.id,
        name: a.name
      })) : [],
      modules: payload.moduleId ? {
        id: payload.moduleId,
        name: "" // Will be populated by backend
      } : null,
      cycle: payload.cycleId ? {
        id: payload.cycleId,
        name: "" // Will be populated by backend
      } : null,
      parent: null,
      project: {
        id: payload.projectId || "",
        name: "" // Will be populated by backend
      },
      business: {
        id: getBusinessId(),
        name: "" // Will be populated by backend
      }
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to create work item (${res.status})`);
  }
  return res.json();
}

export type GetWorkItemsRequest = {
  projectId: string;
  businessId: string;
  moduleId?: string;
  cycleId?: string;
  stateId?: string;
  assigneeId?: string;
  labelId?: string;
  priority?: string;
  searchText?: string;
  sortField?: string;
  sortDirection?: string;
};

export type GetWorkItemsResponse = {
  success: boolean;
  data: CreateWorkItemResponse[];
};

export async function getWorkItems(payload: GetWorkItemsRequest): Promise<GetWorkItemsResponse> {
  const endpoint = WORKITEM_ENDPOINTS.GET_WORKITEMS();

  const res = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to get work items (${res.status})`);
  }
  return res.json();
}

