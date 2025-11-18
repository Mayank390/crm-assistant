import { API_HTTP_URL, getMemberId, getBusinessId } from "@/config";

export async function getConversations(): Promise<Array<{ id: string; title: string; updatedAt?: string }>> {
  try {
    const userId = getMemberId();
    const businessId = getBusinessId();
    
    if (!userId || !businessId) {
      console.warn("Missing user_id or business_id for conversations API");
      return [];
    }
    
    const url = new URL(`${API_HTTP_URL}/conversations`);
    url.searchParams.set('user_id', userId);
    url.searchParams.set('business_id', businessId);
    
    const res = await fetch(url.toString(), {
      headers: {
        'accept': 'application/json',
      },
    });
    
    if (!res.ok) throw new Error("failed");
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export async function getConversationMessages(conversationId: string): Promise<Array<{
  id: string;
  type: string;
  content: string;
  liked?: boolean;
  feedback?: string;
  lead?: { name: string; email?: string; mobile?: string; leadStatus?: string; referenceNo?: string };
  task?: { name: string; description?: string; priority?: string; taskStatus?: string; dueDate?: string; leadId?: string };
  meeting?: { title: string; description?: string; meetingStatus?: string; meetingType?: string; leadId?: string; meetingLink?: string };
  note?: { subject: string; description: string; leadId?: string };
}>> {
  try {
    const res = await fetch(`${API_HTTP_URL}/conversations/${encodeURIComponent(conversationId)}`);
    if (!res.ok) throw new Error("failed");
    const data = await res.json();
    if (data && Array.isArray(data.messages)) return data.messages;
    return [];
  } catch {
    return [];
  }
}

export async function reactToMessage(args: { conversationId: string; messageId: string; liked?: boolean; feedback?: string }): Promise<boolean> {
  try {
    const res = await fetch(`${API_HTTP_URL}/conversations/reaction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: args.conversationId,
        message_id: args.messageId,
        liked: args.liked,
        feedback: args.feedback ?? undefined,
      }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return !!data?.ok;
  } catch {
    return false;
  }
}
