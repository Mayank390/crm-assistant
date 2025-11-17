/**
 * API functions for syncing user preferences to backend
 */

import { API_BASE_URL, getMemberId, getBusinessId } from "./endpoints";

export interface UserPreferences {
  responseTone?: "professional" | "friendly" | "concise" | "detailed";
  domainFocus?: "product" | "engineering" | "design" | "marketing" | "general";
  showAgentInternals?: boolean;
  rememberLongTermContext?: boolean;
  longTermContext?: string;
}

export interface UserContextRequest {
  user_id: string;
  business_id: string;
  content: string;
  metadata?: Record<string, any>;
}

/**
 * Sync user preferences to backend MongoDB
 */
export async function syncPreferencesToBackend(
  preferences: Partial<UserPreferences>
): Promise<boolean> {
  try {
    const userId = getMemberId();
    const businessId = getBusinessId();

    if (!userId || !businessId) {
      console.warn("Missing user_id or business_id for preferences sync");
      return false;
    }

    // TODO: Create API endpoint for preferences sync
    // For now, preferences are sent via WebSocket handshake
    // This function is a placeholder for future REST API implementation
    
    return true;
  } catch (error) {
    console.error("Failed to sync preferences:", error);
    return false;
  }
}

/**
 * Save long-term context to backend
 */
export async function saveLongTermContext(
  content: string,
  metadata?: Record<string, any>
): Promise<{ success: boolean; id?: string; error?: string }> {
  try {
    const userId = getMemberId();
    const businessId = getBusinessId();

    if (!userId || !businessId) {
      return {
        success: false,
        error: "Missing user_id or business_id",
      };
    }

    const response = await fetch(`${API_BASE_URL}/api/user-context`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: userId,
        business_id: businessId,
        content,
        metadata,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      return {
        success: false,
        error: error || "Failed to save context",
      };
    }

    const data = await response.json();
    return {
      success: true,
      id: data.id,
    };
  } catch (error) {
    console.error("Failed to save long-term context:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

