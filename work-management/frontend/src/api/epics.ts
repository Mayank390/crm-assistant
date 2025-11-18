import { API_HTTP_URL } from "@/config";

export type CreateEpicRequest = {
  title: string;
  description?: string;
  projectId?: string;
  priority?: string;
  stateName?: string;
  assigneeName?: string;
  labels?: string[];
  startDate?: string;
  dueDate?: string;
  createdBy?: string;
};

export type CreateEpicResponse = {
  id: string;
  title: string;
  description: string;
  projectId?: string | null;
  state?: string | null;
  priority?: string | null;
  link?: string | null;
};

export async function createEpic(payload: CreateEpicRequest): Promise<CreateEpicResponse> {
  const endpoint = `${API_HTTP_URL}/epics`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title,
      description: payload.description ?? "",
      project_id: payload.projectId,
      priority: payload.priority,
      state_name: payload.stateName,
      assignee: payload.assigneeName,
      labels: payload.labels,
      start_date: payload.startDate,
      due_date: payload.dueDate,
      created_by: payload.createdBy,
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to create epic (${res.status})`);
  }

  const data = await res.json();
  return {
    id: data.id,
    title: data.title,
    description: data.description,
    projectId: data.projectId ?? null,
    state: data.state ?? null,
    priority: data.priority ?? null,
    link: data.link ?? null,
  };
}

