import { API_HTTP_URL, getMemberId } from "@/config";

export interface CreateMeetingRequest {
  title: string;
  description?: string;
  meetingStatus?: string;
  meetingType?: string;
  leadId?: string;
  meetingLink?: string;
  participantsList?: string[];
}

export interface Meeting {
  id: string;
  title: string;
  description: string;
  meetingStatus: string;
  leadId?: string;
}

export async function createMeeting(data: CreateMeetingRequest): Promise<Meeting> {
  const memberId = getMemberId();
  const res = await fetch(`${API_HTTP_URL}/meetings`, {
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
    const error = await res.json().catch(() => ({ detail: "Failed to create meeting" }));
    throw new Error(error.detail || "Failed to create meeting");
  }
  return res.json();
}
