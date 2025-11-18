import { PAGE_ENDPOINTS } from "@/api/endpoints";
import { getBusinessId, getMemberId } from "@/config";

export type CreatePageRequest = {
  title: string;
  content: { blocks: any[] };
  projectId?: string;
  createdBy?: { id: string; name: string };
  linkedCycle?: Array<{ id: string; name: string }>;
  linkedModule?: Array<{ id: string; name: string }>;
  linkedMembers?: Array<{ id: string; name: string }>;
  linkedPages?: Array<{ id: string; name: string }>;
};

export type CreatePageResponse = {
  id: string;
  title: string;
  content: string; // stringified Editor.js JSON
  link?: string;
  business?: {
    id: string;
    name: string;
  };
  project?: {
    id: string;
    name: string;
  };
  createdBy?: {
    id: string;
    name: string;
  };
  visibility?: string;
  locked?: boolean;
  favourite?: boolean;
  readTime?: string;
  wordCount?: number;
  linkedCycle?: Array<{
    id: string;
    name: string;
  }>;
  linkedModule?: Array<{
    id: string;
    name: string;
  }>;
  linkedMembers?: Array<{
    id: string;
    name: string;
  }>;
  linkedPages?: Array<{
    id: string;
    name: string;
  }>;
};

export async function createPage(payload: CreatePageRequest): Promise<CreatePageResponse> {
  const endpoint = PAGE_ENDPOINTS.CREATE_PAGE(payload.projectId);

  // Calculate word count and read time
  const contentText = JSON.stringify(payload.content);
  const wordCount = contentText.split(/\s+/).filter(word => word.length > 0).length;
  const readTime = `${Math.ceil(wordCount / 200)}`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title,
      content: JSON.stringify(payload.content), // Stringify the Editor.js content
      business: {
        id: getBusinessId(),
        name: "" // Will be populated by backend
      },
      project: {
        id: payload.projectId || "",
        name: "" // Will be populated by backend
      },
      createdBy: payload.createdBy || {
        id: getMemberId(),
        name: "" // Will be populated by backend
      },
      visibility: "PUBLIC",
      locked: false,
      favourite: false,
      readTime,
      wordCount,
      linkedCycle: payload.linkedCycle || [],
      linkedModule: payload.linkedModule || [],
      linkedMembers: payload.linkedMembers || [],
      linkedPages: payload.linkedPages || [],
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to create page (${res.status})`);
  }
  return res.json();
}

export type GetPagesRequest = {
  moduleId?: string;
  cycleId?: string;
  pageId?: string;
  createdBy?: { id: string; name: string };
  memberIds?: string[];
};

export type GetPagesResponse = {
  success: boolean;
  data: CreatePageResponse[];
};

export async function getPages(projectId: string, filters?: GetPagesRequest): Promise<GetPagesResponse> {
  const endpoint = PAGE_ENDPOINTS.GET_PAGES(projectId);

  const res = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters || {}),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to get pages (${res.status})`);
  }
  return res.json();
}

export async function getPageDetail(pageId: string): Promise<CreatePageResponse> {
  const endpoint = PAGE_ENDPOINTS.GET_PAGE_DETAIL(pageId);

  const res = await fetch(endpoint, {
    method: "GET",
    headers: { "accept": "application/json" },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to get page detail (${res.status})`);
  }
  return res.json();
}

