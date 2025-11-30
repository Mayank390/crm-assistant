import { config, getLeadSupportApiUrl } from "@/config";

// ============================================
// Response Types
// ============================================

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
  async getSummary(leadId?: string): Promise<LeadSummaryResponse> {
    return this.request<LeadSummaryResponse>("/summary", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Get AI-generated insights about a lead
   */
  async getInsights(leadId?: string): Promise<LeadInsightsResponse> {
    return this.request<LeadInsightsResponse>("/insights", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Get AI-recommended next best steps for a lead
   */
  async getNextSteps(leadId?: string): Promise<LeadNextStepsResponse> {
    return this.request<LeadNextStepsResponse>("/next-steps", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Compare multiple leads side-by-side
   */
  async compareLeads(leadIds: string[]): Promise<LeadCompareResponse> {
    return this.request<LeadCompareResponse>("/compare", {
      method: "POST",
      body: JSON.stringify({
        lead_ids: leadIds,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Draft a personalized message for a lead
   */
  async draftMessage(
    leadId?: string,
    messageType: string = "email",
    context?: string
  ): Promise<DraftMessageResponse> {
    return this.request<DraftMessageResponse>("/draft-message", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        message_type: messageType,
        context,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Get AI-powered response to a sales objection
   */
  async handleObjection(
    objection: string,
    leadId?: string
  ): Promise<ObjectionHandlingResponse> {
    return this.request<ObjectionHandlingResponse>("/objection", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        objection,
        business_id: config.businessId,
      }),
    });
  }

  /**
   * Get AI-generated meeting preparation document
   */
  async prepareMeeting(
    leadId?: string,
    meetingContext?: string
  ): Promise<MeetingPrepResponse> {
    return this.request<MeetingPrepResponse>("/meeting-prep", {
      method: "POST",
      body: JSON.stringify({
        lead_id: leadId || config.leadId,
        meeting_context: meetingContext,
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
  async getSummaryQuick(leadId?: string): Promise<LeadSummaryResponse> {
    const id = leadId || config.leadId;
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadSummaryResponse>(`/${id}/summary${businessParam}`, {
      method: "GET",
    });
  }

  /**
   * Quick GET for lead insights
   */
  async getInsightsQuick(leadId?: string): Promise<LeadInsightsResponse> {
    const id = leadId || config.leadId;
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadInsightsResponse>(`/${id}/insights${businessParam}`, {
      method: "GET",
    });
  }

  /**
   * Quick GET for lead next steps
   */
  async getNextStepsQuick(leadId?: string): Promise<LeadNextStepsResponse> {
    const id = leadId || config.leadId;
    const businessParam = config.businessId ? `?business_id=${config.businessId}` : "";
    return this.request<LeadNextStepsResponse>(`/${id}/next-steps${businessParam}`, {
      method: "GET",
    });
  }
}

// Export singleton instance
export const leadSupportApi = new LeadSupportApiClient();

// Export class for testing
export { LeadSupportApiClient };
