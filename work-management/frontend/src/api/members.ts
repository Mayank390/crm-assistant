import { PROJECT_ENDPOINTS } from "@/api/endpoints";

export type ProjectMember = {
  id: string;
  memberId: string;
  project: {
    id: string;
    name: string;
  };
  name: string;
  email: string;
  displayName: string | null;
  joiningDate: string;
  type: string | null;
  staff: {
    id: string;
    name: string;
  } | null;
  role: "ADMIN" | "MEMBER" | "GUEST";
  savedLayout: string;
};

export type GetProjectMembersResponse = {
  data: ProjectMember[];
};

export async function getProjectMembers(projectId: string): Promise<GetProjectMembersResponse> {
  const endpoint = PROJECT_ENDPOINTS.GET_PROJECT_MEMBERS(projectId);

  const res = await fetch(endpoint, {
    method: "GET",
    headers: { "accept": "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to fetch project members (${res.status})`);
  }

  return res.json();
}
