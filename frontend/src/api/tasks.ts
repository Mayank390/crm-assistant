import { API_HTTP_URL, getMemberId } from "@/config";

export interface CreateTaskRequest {
  name: string;
  description?: string;
  priority?: string;
  taskStatus?: string;
  dueDate?: string;
  leadId?: string;
}

export interface Task {
  id: string;
  name: string;
  description: string;
  priority: string;
  taskStatus: string;
  leadId?: string;
}

export async function createTask(data: CreateTaskRequest): Promise<Task> {
  const memberId = getMemberId();
  const res = await fetch(`${API_HTTP_URL}/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...data,
      created_by: memberId,
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to create task" }));
    throw new Error(error.detail || "Failed to create task");
  }
  return res.json();
}
