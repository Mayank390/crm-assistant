import { SUBSTATE_ENDPOINTS } from "@/api/endpoints";

export type SubState = {
  id: string;
  name: string;
  description?: string;
  color?: string;
  order: number;
  default: boolean;
  // Make properties optional to handle different API response formats
  [key: string]: any;
};

export type ProjectState = {
  id: string;
  projectId: string;
  name: string;
  icon: string;
  subStates: SubState[];
  // Make properties optional to handle different API response formats
  [key: string]: any;
};

export type GetSubStatesResponse = {
  data: ProjectState[];
};

export async function getSubStates(projectId: string): Promise<GetSubStatesResponse> {
  const endpoint = SUBSTATE_ENDPOINTS.GET_SUBSTATES(projectId);

  const res = await fetch(endpoint, {
    method: "GET",
    headers: { "accept": "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to fetch sub-states (${res.status})`);
  }

  const response = await res.json();

  // Handle the response format from the API
  if (response.data && Array.isArray(response.data)) {
    return { data: response.data };
  }

  // Fallback for different response formats
  return { data: [] };
}

// Helper function to get all sub-states as a flat array grouped by state
export function getSubStatesByState(statesResponse: GetSubStatesResponse): Record<string, SubState[]> {
  const result: Record<string, SubState[]> = {};

  statesResponse.data.forEach(state => {
    if (state.subStates && Array.isArray(state.subStates)) {
      result[state.name] = state.subStates.sort((a, b) => a.order - b.order);
    }
  });

  return result;
}

// Helper function to get all sub-states as a flat array
export function getAllSubStatesAsArray(statesResponse: GetSubStatesResponse): SubState[] {
  const subStates: SubState[] = [];

  statesResponse.data.forEach(state => {
    if (state.subStates && Array.isArray(state.subStates)) {
      subStates.push(...state.subStates);
    }
  });

  return subStates.sort((a, b) => a.order - b.order);
}

// Helper function to find the default sub-state for a given state name
export function getDefaultSubState(statesResponse: GetSubStatesResponse, stateName: string): SubState | null {
  const state = statesResponse.data.find(s => s.name === stateName);
  if (!state) return null;

  return state.subStates?.find(subState => subState.default) || state.subStates?.[0] || null;
}
