import { getProjectMembers, type GetProjectMembersResponse } from "@/api/members";
import { getProjectLabels, type GetProjectLabelsResponse } from "@/api/labels";
import { getAllCycles, type GetAllCyclesResponse } from "@/api/cycles";
import { getAllModules, type GetAllModulesResponse } from "@/api/modules";
import { getSubStates, type GetSubStatesResponse } from "@/api/substates";

// Global cache system for all project-related data
// This cache is used by all selectors to avoid repeated API calls

interface ProjectDataCache {
  data: ProjectData;
  timestamp: number;
  expiresAt: number;
}

interface GlobalProjectCache {
  members: Map<string, ProjectDataCache>;
  labels: Map<string, ProjectDataCache>;
  cycles: Map<string, ProjectDataCache>;
  modules: Map<string, ProjectDataCache>;
  substates: Map<string, ProjectDataCache>;
}

const globalProjectCache: GlobalProjectCache = {
  members: new Map(),
  labels: new Map(),
  cycles: new Map(),
  modules: new Map(),
  substates: new Map(),
};

const CACHE_TTL = 5 * 60 * 1000; // 5 minutes in milliseconds

// Helper function to check if cache is expired
function isCacheExpired(cacheEntry: ProjectDataCache): boolean {
  return Date.now() >= cacheEntry.expiresAt;
}

// Helper function to get from cache
function getFromCache(cacheMap: Map<string, ProjectDataCache>, key: string): ProjectData | null {
  const cached = cacheMap.get(key);
  if (cached && !isCacheExpired(cached)) {
    return cached.data;
  }
  // Remove expired cache entry
  if (cached) {
    cacheMap.delete(key);
  }
  return null;
}

// Helper function to set in cache
function setInCache(cacheMap: Map<string, ProjectDataCache>, key: string, data: ProjectData): void {
  cacheMap.set(key, {
    data,
    timestamp: Date.now(),
    expiresAt: Date.now() + CACHE_TTL
  });
}

export type ProjectData = {
  members: GetProjectMembersResponse;
  labels: GetProjectLabelsResponse;
  cycles: GetAllCyclesResponse;
  modules: GetAllModulesResponse;
  substates: GetSubStatesResponse;
};

export type ProjectDataError = {
  members?: string;
  labels?: string;
  cycles?: string;
  modules?: string;
  substates?: string;
};

/**
 * Fetch all project-related data (members, labels, cycles, modules, substates) in parallel
 * This is used to pre-fetch all project data when a project is selected to avoid
 * individual API calls for each selector component
 */
export async function getAllProjectData(projectId: string): Promise<ProjectData> {
  const cacheKey = `project-${projectId}`;

  // Check if all data is already cached
  const membersCached = getFromCache(globalProjectCache.members, projectId);
  const labelsCached = getFromCache(globalProjectCache.labels, projectId);
  const cyclesCached = getFromCache(globalProjectCache.cycles, projectId);
  const modulesCached = getFromCache(globalProjectCache.modules, projectId);
  const substatesCached = getFromCache(globalProjectCache.substates, projectId);

  if (membersCached && labelsCached && cyclesCached && modulesCached && substatesCached) {
    return {
      members: membersCached.members,
      labels: labelsCached.labels,
      cycles: cyclesCached.cycles,
      modules: modulesCached.modules,
      substates: substatesCached.substates,
    };
  }

  try {
    const [membersResponse, labelsResponse, cyclesResponse, modulesResponse, substatesResponse] = await Promise.allSettled([
      getProjectMembers(projectId),
      getProjectLabels(projectId),
      getAllCycles(projectId),
      getAllModules(projectId),
      getSubStates(projectId),
    ]);

    const result: ProjectData = {
      members: { data: [] },
      labels: { data: [] },
      cycles: { data: { UPCOMING: [], ACTIVE: [], COMPLETED: [] } },
      modules: { data: [] },
      substates: { data: [] },
    };

    const errors: ProjectDataError = {};

    // Handle members
    if (membersResponse.status === 'fulfilled') {
      result.members = membersResponse.value;
      setInCache(globalProjectCache.members, projectId, result);
    } else {
      // Failed to fetch project members
      errors.members = membersResponse.reason?.message || 'Failed to fetch members';
    }

    // Handle labels
    if (labelsResponse.status === 'fulfilled') {
      result.labels = labelsResponse.value;
      setInCache(globalProjectCache.labels, projectId, result);
    } else {
      // Failed to fetch project labels
      errors.labels = labelsResponse.reason?.message || 'Failed to fetch labels';
    }

    // Handle cycles
    if (cyclesResponse.status === 'fulfilled') {
      result.cycles = cyclesResponse.value;
      setInCache(globalProjectCache.cycles, projectId, result);
    } else {
      // Failed to fetch project cycles
      errors.cycles = cyclesResponse.reason?.message || 'Failed to fetch cycles';
    }

    // Handle modules
    if (modulesResponse.status === 'fulfilled') {
      result.modules = modulesResponse.value;
      setInCache(globalProjectCache.modules, projectId, result);
    } else {
      // Failed to fetch project modules
      errors.modules = modulesResponse.reason?.message || 'Failed to fetch modules';
    }

    // Handle substates
    if (substatesResponse.status === 'fulfilled') {
      result.substates = substatesResponse.value;
      setInCache(globalProjectCache.substates, projectId, result);
    } else {
      // Failed to fetch project substates
      errors.substates = substatesResponse.reason?.message || 'Failed to fetch substates';
    }

    // If there are any errors, we might want to handle them, but for now just log them
    if (Object.keys(errors).length > 0) {
      // Some project data failed to load
    }

    return result;
  } catch (error) {
    // Failed to fetch project data
    throw error;
  }
}

// Individual cache getter functions for selectors
export function getCachedMembers(projectId: string): GetProjectMembersResponse | null {
  const cached = getFromCache(globalProjectCache.members, projectId);
  return cached ? cached.members : null;
}

export function getCachedLabels(projectId: string): GetProjectLabelsResponse | null {
  const cached = getFromCache(globalProjectCache.labels, projectId);
  return cached ? cached.labels : null;
}

export function getCachedCycles(projectId: string): GetAllCyclesResponse | null {
  const cached = getFromCache(globalProjectCache.cycles, projectId);
  return cached ? cached.cycles : null;
}

export function getCachedModules(projectId: string): GetAllModulesResponse | null {
  const cached = getFromCache(globalProjectCache.modules, projectId);
  return cached ? cached.modules : null;
}

export function getCachedSubStates(projectId: string): GetSubStatesResponse | null {
  const cached = getFromCache(globalProjectCache.substates, projectId);
  return cached ? cached.substates : null;
}

/**
 * Send project data to the conversation via WebSocket
 * This function sends the project data as a message to the conversation area
 */
export async function sendProjectDataToConversation(
  projectData: ProjectData,
  projectName: string,
  projectDisplayId: string,
  conversationId?: string
): Promise<string> {
  // Return a confirmation message that can be displayed in the conversation
  const message = `✅ Project data loaded for "${projectName} (${projectDisplayId})" - Ready to create work items, cycles, modules, epics, and pages.`;

  // Try to send via the existing chat socket system
  if (typeof window !== 'undefined') {
    try {
      // Try to access the WebSocket through the useChatSocket hook
      // This is a bit of a hack, but it should work for now
      const socket = (window as any).__projectLensSocket;
      if (socket && socket.send) {
        socket.send({
          message: message,
          conversation_id: conversationId,
        });
      }
    } catch (error) {
      // Failed to send project data via WebSocket - silently fail as this is not critical functionality
    }
  }

  return message;
}

/**
 * Clear project data cache for a specific project
 */
export function clearProjectDataCache(projectId?: string): void {
  if (projectId) {
    globalProjectCache.members.delete(projectId);
    globalProjectCache.labels.delete(projectId);
    globalProjectCache.cycles.delete(projectId);
    globalProjectCache.modules.delete(projectId);
    globalProjectCache.substates.delete(projectId);
  } else {
    // Clear all cache
    globalProjectCache.members.clear();
    globalProjectCache.labels.clear();
    globalProjectCache.cycles.clear();
    globalProjectCache.modules.clear();
    globalProjectCache.substates.clear();
  }
}

/**
 * Get cache statistics for debugging
 */
export function getProjectDataCacheStats(): {
  members: { size: number; keys: string[] };
  labels: { size: number; keys: string[] };
  cycles: { size: number; keys: string[] };
  modules: { size: number; keys: string[] };
  substates: { size: number; keys: string[] };
} {
  return {
    members: {
      size: globalProjectCache.members.size,
      keys: Array.from(globalProjectCache.members.keys())
    },
    labels: {
      size: globalProjectCache.labels.size,
      keys: Array.from(globalProjectCache.labels.keys())
    },
    cycles: {
      size: globalProjectCache.cycles.size,
      keys: Array.from(globalProjectCache.cycles.keys())
    },
    modules: {
      size: globalProjectCache.modules.size,
      keys: Array.from(globalProjectCache.modules.keys())
    },
    substates: {
      size: globalProjectCache.substates.size,
      keys: Array.from(globalProjectCache.substates.keys())
    }
  };
}

/**
 * Invalidate cache for a specific project when data might have changed
 * This should be called when:
 * - A new work item/cycle/module is created
 * - Data is modified through the UI
 * - User performs actions that might change project data
 */
export function invalidateProjectCache(projectId: string): void {
  globalProjectCache.members.delete(projectId);
  globalProjectCache.labels.delete(projectId);
  globalProjectCache.cycles.delete(projectId);
  globalProjectCache.modules.delete(projectId);
  globalProjectCache.substates.delete(projectId);
}

/**
 * Pre-load project data for multiple projects (useful for bulk operations)
 */
export async function preloadProjectsData(projectIds: string[]): Promise<void> {
  const preloadPromises = projectIds.map(async (projectId) => {
    try {
      await getAllProjectData(projectId);
    } catch (error) {
      // Failed to preload data for project - continue with other projects
    }
  });

  await Promise.allSettled(preloadPromises);
}
