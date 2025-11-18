import { LABEL_ENDPOINTS } from "@/api/endpoints";

export type ProjectLabel = {
  id: string;
  label: string;
  color: string;
  projectId: string;
};

export type GetProjectLabelsResponse = {
  data: ProjectLabel[];
};

export async function getProjectLabels(projectId: string): Promise<GetProjectLabelsResponse> {
  const endpoint = LABEL_ENDPOINTS.GET_LABELS(projectId);

  const res = await fetch(endpoint, {
    method: "GET",
    headers: { "accept": "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to fetch project labels (${res.status})`);
  }

  return res.json();
}
