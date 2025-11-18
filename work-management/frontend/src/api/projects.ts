import { PROJECT_ENDPOINTS } from "@/api/endpoints";
import { getMemberId, getBusinessId } from "@/config";

export type Project = {
  projectId: string;
  projectName: string;
  projectDescription: string | null;
  imageUrl: string;
  icon: string;
  projectDisplayId: string;
  businessId: string;
  businessName: string | null;
  features: {
    cycles: boolean;
    modules: boolean;
    pages: boolean;
    intake: boolean;
    view: boolean;
    timeTracking: boolean;
    estimations: boolean;
    epic: boolean;
  };
  accessType: string;
  timeZone: string | null;
  lead: {
    id: string;
    name: string;
  } | null;
  defaultAssignee: {
    id: string;
    name: string;
  } | null;
  status: string;
  createdTimeStamp: string;
  guestAccess: boolean;
};

export type GetProjectsResponse = {
  data: Project[];
};

export async function getProjects(): Promise<GetProjectsResponse> {
  const businessId = getBusinessId();
  const memberId = getMemberId();
  const endpoint = PROJECT_ENDPOINTS.GET_PROJECTS(businessId, memberId);

  const res = await fetch(endpoint, {
    method: "GET",
    headers: { "accept": "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to fetch projects (${res.status})`);
  }

  return res.json();
}
