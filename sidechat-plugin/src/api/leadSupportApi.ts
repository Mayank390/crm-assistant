import { config, getLeadSupportApiUrl } from "@/config";

// ============================================
// Response Types
// ============================================

// Current lead ID - set by the app when a lead is selected
let currentLeadId: string | null = null;

export const setCurrentLeadId = (leadId: string | null) => {
  currentLeadId = leadId;
};

export const getCurrentLeadId = () => currentLeadId;

export interface LeadSummaryResponse {
  lead_id: string;
  summary: string;
  generated_at: string;
}

export interface LeadInsightsResponse {
  lead_id: string;
  overview: string;
  key_insights: string[];
  engagement_score: string | null;
  recommended_actions: string[];
  risk_factors: string[];
  generated_at: string;
}

export interface LeadEnrichResponse {
  lead_id: string;
  enriched_data: {[key: string]: any};
  missing_fields: string[];
  recommendations: string[];
  generated_at: string;
}

export interface LeadNextStepsResponse {
  lead_id: string;
  next_steps: string;
  generated_at: string;
}

export interface LeadCompareResponse {
  lead_ids: string[];
  comparison: string;
  generated_at: string;
}

export interface DraftMessageResponse {
  lead_id: string;
  message_type: string;
  draft: string;
  generated_at: string;
}

export interface ObjectionHandlingResponse {
  lead_id: string;
  objection: string;
  response: string;
  generated_at: string;
}

export interface MeetingPrepResponse {
  lead_id: string;
  prep_document: string;
  generated_at: string;
}

// ============================================
// API Client
// ============================================

class LeadSupportApiClient {
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = getLeadSupportApiUrl(endpoint);
    
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }

    return response.json();
  }

  /**
   * Get AI-generated summary of a lead
   */
  async getSummary(leadId: string): Promise<LeadSummaryResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    return this.request<LeadSummaryResponse>("/summary", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Get AI-generated insights about a lead
   */
  async getInsights(leadId: string): Promise<LeadInsightsResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    return this.request<LeadInsightsResponse>("/insights", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Enrich a lead with inferred data from available sources
   */
  async enrichLead(leadId: string): Promise<LeadEnrichResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    return this.request<LeadEnrichResponse>("/enrich", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId,
        business_id: config.businessId,
      }),
    });
  }

  // ============================================
  // Simple GET endpoints
  // ============================================

  /**
   * Quick GET for lead summary
   */
  async getSummaryQuick(leadId: string): Promise<LeadSummaryResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadSummaryResponse>(`/${leadId}/summary${businessParam}`, {
      method: "GET",
    });
  }

  /**
   * Quick GET for lead insights
   */
  async getInsightsQuick(leadId: string): Promise<LeadInsightsResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadInsightsResponse>(`/${leadId}/insights${businessParam}`, {
      method: "GET",
    });
  }

  /**
   * Quick GET for lead enrichment
   */
  async enrichLeadQuick(leadId: string): Promise<LeadEnrichResponse> {
    if (!leadId) throw new Error("Lead ID is required");
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadEnrichResponse>(`/${leadId}/enrich${businessParam}`, {
      method: "GET",
    });
  }
}

// Export singleton instance
export const leadSupportApi = new LeadSupportApiClient();

// Export class for testing
export { LeadSupportApiClient };
