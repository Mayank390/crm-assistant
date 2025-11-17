import { API_HTTP_URL, getMemberId } from "@/config";

export interface CreateLeadRequest {
  name: string;
  email?: string;
  mobile?: string;
  leadStatus?: string;
  referenceNo?: string;
}

export interface Lead {
  id: string;
  name: string;
  email?: string;
  mobile?: string;
  leadStatus: string;
  referenceNo?: string;
}

export async function createLead(data: CreateLeadRequest): Promise<Lead> {
  const memberId = getMemberId();
  const res = await fetch(`${API_HTTP_URL}/leads`, {
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
    const error = await res.json().catch(() => ({ detail: "Failed to create lead" }));
    throw new Error(error.detail || "Failed to create lead");
  }
  return res.json();
}
