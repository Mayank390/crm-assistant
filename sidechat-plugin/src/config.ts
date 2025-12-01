/**
 * Configuration for Lead Support Agent Plugin
 * 
 * Update these values with your actual business and lead IDs for testing.
 */

export const config = {
  // API Configuration
  api: {
    // baseUrl: import.meta.env.VITE_API_BASE_URL || "https://stage-aicrm.simpo.ai",
    // wsUrl: import.meta.env.VITE_WS_BASE_URL || "wss://stage-aicrm.simpo.ai",
    baseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
    wsUrl: import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000",
  },

  // ============================================
  // PLACEHOLDER VALUES - UPDATE FOR TESTING
  // ============================================
  
  // Business ID for filtering data
  // Replace with your actual business UUID
  businessId: import.meta.env.VITE_BUSINESS_ID || "1eff7f64-09ef-670e-8c7c-2b9676f8dbb6",
  
  // Lead ID to focus on
  // Replace with your actual lead ObjectId or UUID
  leadId: import.meta.env.VITE_LEAD_ID ,
  
  // Member/User ID for authentication
  // Replace with your actual member UUID
  memberId: import.meta.env.VITE_MEMBER_ID || "1eff7f64-08ea-6fdc-99d0-3f7ae8229af5",

  // ============================================
  // Feature Flags
  // ============================================
  features: {
    enableWebSocket: true,
    enableRestApi: true,
    showDebugInfo: import.meta.env.DEV || false,
  },
};

// Type definitions for config
export type Config = typeof config;

// Helper to check if config is properly set
// Note: leadId is now dynamically selected via LeadContext
export const isConfigured = (): boolean => {
  return (
    config.businessId !== "YOUR_BUSINESS_ID_HERE" &&
    config.memberId !== "YOUR_MEMBER_ID_HERE"
  );
};

// Get WebSocket URL for lead support
export const getLeadSupportWsUrl = (): string => {
  return `${config.api.wsUrl}/ws/lead-support`;
};

// Get REST API URL for lead support
export const getLeadSupportApiUrl = (endpoint: string): string => {
  return `${config.api.baseUrl}/lead-support${endpoint}`;
};
