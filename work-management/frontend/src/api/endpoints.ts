import { STAGE_API_BASE_URL } from "@/config";

/**
 * Centralized API endpoints configuration
 * All API URLs are defined here for easy management and updates
 */

export const PROJECT_ENDPOINTS = {
  // Get projects for a member
  GET_PROJECTS: (businessId: string, memberId: string) =>
    `${STAGE_API_BASE_URL}/project/memberId?businessId=${businessId}&memberId=${memberId}`,

  // Get project members
  GET_PROJECT_MEMBERS: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/${projectId}/member`,

  // Create project (if needed in future)
  CREATE_PROJECT: () =>
    `${STAGE_API_BASE_URL}/project`,

  // Update project (if needed in future)
  UPDATE_PROJECT: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/${projectId}`,

  // Delete project (if needed in future)
  DELETE_PROJECT: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/${projectId}`,
};

export const CYCLE_ENDPOINTS = {
  // Get all cycles
  GET_ALL_CYCLES: (businessId: string, projectId?: string) => {
    const url = new URL(`${STAGE_API_BASE_URL}/project/cycle/get-all`);
    url.searchParams.set('businessId', businessId);
    if (projectId) {
      url.searchParams.set('projectId', projectId);
    }
    return url.toString();
  },

  // Create cycle
  CREATE_CYCLE: () =>
    `${STAGE_API_BASE_URL}/project/cycle`,

  // Update cycle
  UPDATE_CYCLE: (cycleId: string) =>
    `${STAGE_API_BASE_URL}/project/cycle/${cycleId}`,

  // Delete cycle
  DELETE_CYCLE: (cycleId: string) =>
    `${STAGE_API_BASE_URL}/project/cycle?id=${cycleId}`,

  // Mark cycle as favourite
  MARK_FAVOURITE: (cycleId: string) =>
    `${STAGE_API_BASE_URL}/project/cycle/${cycleId}/favourite`,

  // Get cycle analytics
  GET_ANALYTICS: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/cycle/${projectId}/active-analytics`,

  // Get work items by cycle
  GET_WORKITEMS: (cycleId: string) =>
    `${STAGE_API_BASE_URL}/project/cycle/id?id=${cycleId}`,
};

export const WORKITEM_ENDPOINTS = {
  // Create work item
  CREATE_WORKITEM: () =>
    `${STAGE_API_BASE_URL}/project/work-item`,

  // Get work items
  GET_WORKITEMS: () =>
    `${STAGE_API_BASE_URL}/project/workItem`,

  // Update work item
  UPDATE_WORKITEM: (workItemId: string) =>
    `${STAGE_API_BASE_URL}/project/work-item/${workItemId}`,

  // Delete work item
  DELETE_WORKITEM: (workItemId: string) =>
    `${STAGE_API_BASE_URL}/project/workItem?id=${workItemId}`,

  // Update work item state
  UPDATE_SUBSTATE: () =>
    `${STAGE_API_BASE_URL}/project/work-item/update-sub-state`,

  // Add comment to work item
  ADD_COMMENT: () =>
    `${STAGE_API_BASE_URL}/project/work-items/comment`,

  // Log work on work item
  WORK_LOG: (workItemId: string) =>
    `${STAGE_API_BASE_URL}/project/work-item/${workItemId}/work-log`,

  // Update work item fields
  UPDATE_FIELDS: (workItemId: string) =>
    `${STAGE_API_BASE_URL}/project/work-item/${workItemId}/update/function`,

  // Add attachment
  ADD_ATTACHMENT: (workItemId: string) =>
    `${STAGE_API_BASE_URL}/project/work-item/${workItemId}/add-attachment`,

  // Remove attachment
  REMOVE_ATTACHMENT: (workItemId: string, attachmentId: string) =>
    `${STAGE_API_BASE_URL}/project/work-item/${workItemId}/remove-attachment/${attachmentId}`,
};

export const MODULE_ENDPOINTS = {
  // Get modules
  GET_MODULES: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/${projectId}/modules`,

  // Create module
  CREATE_MODULE: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/module`,

  // Update module
  UPDATE_MODULE: (moduleId: string) =>
    `${STAGE_API_BASE_URL}/project/module/${moduleId}`,

  // Delete module
  DELETE_MODULE: (moduleId: string) =>
    `${STAGE_API_BASE_URL}/project/module?id=${moduleId}`,

  // Get all modules with PUT method (based on user requirements)
  GET_ALL_MODULES: () =>
    `${STAGE_API_BASE_URL}/project/module`,

  // Mark module as favourite
  MARK_FAVOURITE: (moduleId: string) =>
    `${STAGE_API_BASE_URL}/project/module/${moduleId}/favourite`,

  // Get work items by module
  GET_WORKITEMS: (moduleId: string) =>
    `${STAGE_API_BASE_URL}/project/module/id?moduleId=${moduleId}`,
};

export const PAGE_ENDPOINTS = {
  // Get pages
  GET_PAGES: (projectId: string) =>
    `${STAGE_API_BASE_URL}/page/${projectId}`,

  // Create page
  CREATE_PAGE: (projectId?: string) =>
    `${STAGE_API_BASE_URL}/page`,

  // Update page
  UPDATE_PAGE: (pageId: string) =>
    `${STAGE_API_BASE_URL}/page/${pageId}`,

  // Delete page
  DELETE_PAGE: (pageId: string) =>
    `${STAGE_API_BASE_URL}/page/${pageId}`,

  // Get page details
  GET_PAGE_DETAIL: (pageId: string) =>
    `${STAGE_API_BASE_URL}/page/detail/${pageId}`,

  // Mark page as favourite
  MARK_FAVOURITE: (pageId: string) =>
    `${STAGE_API_BASE_URL}/page/${pageId}/favourite`,

  // Lock/unlock page
  LOCK_UNLOCK: (pageId: string) =>
    `${STAGE_API_BASE_URL}/page/${pageId}/lock-unlock`,
};

export const SUBSTATE_ENDPOINTS = {
  // Get sub-states for a project
  GET_SUBSTATES: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/states/${projectId}/sub-states`,
};

export const LABEL_ENDPOINTS = {
  // Get labels for a project
  GET_LABELS: (projectId: string) =>
    `${STAGE_API_BASE_URL}/project/${projectId}/label`,
};
