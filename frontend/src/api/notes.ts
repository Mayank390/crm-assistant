import { API_HTTP_URL, getMemberId } from "@/config";

export interface CreateNoteRequest {
  subject: string;
  description: string;
  leadId?: string;
}

export interface Note {
  id: string;
  subject: string;
  description: string;
  leadId?: string;
}

export async function createNote(data: CreateNoteRequest): Promise<Note> {
  const memberId = getMemberId();
  const res = await fetch(`${API_HTTP_URL}/notes`, {
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
    const error = await res.json().catch(() => ({ detail: "Failed to create note" }));
    throw new Error(error.detail || "Failed to create note");
  }
  return res.json();
}
