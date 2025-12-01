import { useState } from "react";
import {
  Sparkles,
  TrendingUp,
  FileText,
  Calendar,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  leadSupportApi,
  LeadSummaryResponse,
  LeadInsightsResponse,
  LeadEnrichResponse,
  LeadNextStepsResponse,
  DraftMessageResponse,
  ObjectionHandlingResponse,
  MeetingPrepResponse,
  LeadCompareResponse,
} from "@/api/leadSupportApi";
import { useLeadContext } from "@/context/LeadContext";
import { useLeadSupportSocket } from "@/hooks/useLeadSupportSocket";
import { ResponseRenderer } from "@/components/ResponseRenderer";

type PluginResult =
  | LeadSummaryResponse
  | LeadInsightsResponse
  | LeadEnrichResponse
  | LeadNextStepsResponse
  | DraftMessageResponse
  | ObjectionHandlingResponse
  | MeetingPrepResponse
  | LeadCompareResponse
  | null;

interface PluginState {
  loading: boolean;
  error: string | null;
  result: PluginResult;
  expanded: boolean;
}

const initialPluginState: PluginState = {
  loading: false,
  error: null,
  result: null,
  expanded: false,
};

export const LeadPlugins = () => {
  const { selectedLead } = useLeadContext();
  const {
    summarizeLead,
    getInsights,
    enrichLead,
    getNextSteps,
    draftMessage: sendDraftMessage,
    handleObjection: sendHandleObjection,
    prepareForMeeting,
    messages,
    isLoading: socketLoading,
    error: socketError,
  } = useLeadSupportSocket({ leadId: selectedLead?.leadId });

  const [summaryState, setSummaryState] = useState<PluginState>(initialPluginState);
  const [insightsState, setInsightsState] = useState<PluginState>(initialPluginState);
  const [enrichState, setEnrichState] = useState<PluginState>(initialPluginState);

  const [copiedId, setCopiedId] = useState<string | null>(null);

  const configured = selectedLead !== null;
  const leadId = selectedLead?.leadId;

  const copyToClipboard = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // ============================================
  // Plugin Handlers
  // ============================================

  const handleGetSummary = async () => {
    if (!leadId) return;
    setSummaryState({ ...summaryState, loading: true, error: null });
    try {
      const result = await leadSupportApi.getSummary(leadId);
      setSummaryState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setSummaryState({ ...summaryState, loading: false, error: err.message });
    }
  };

  const handleGetInsights = async () => {
    if (!leadId) return;
    setInsightsState({ ...insightsState, loading: true, error: null });
    try {
      const result = await leadSupportApi.getInsights(leadId);
      setInsightsState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setInsightsState({ ...insightsState, loading: false, error: err.message });
    }
  };

  const handleEnrichLead = async () => {
    if (!leadId) return;
    setEnrichState({ ...enrichState, loading: true, error: null });
    try {
      const result = await leadSupportApi.enrichLead(leadId);
      setEnrichState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setEnrichState({ ...enrichState, loading: false, error: err.message });
    }
  };


  // ============================================
  // Render Helpers
  // ============================================

  const renderResult = (state: PluginState, id: string) => {
    if (state.error) {
      return (
        <div className="mt-3 p-3 bg-destructive/10 rounded-lg text-destructive text-sm">
          <AlertCircle className="h-4 w-4 inline mr-2" />
          {state.error}
        </div>
      );
    }

    if (!state.result) return null;

    // Generate content for clipboard copy
    let content = "";
    if ("summary" in state.result) content = state.result.summary;
    else if ("enriched_data" in state.result) {
      const enrich = state.result as LeadEnrichResponse;
      content = `## Enriched Data\n${enrich.enriched_data?.enriched_text || "No enriched data available."}\n\n## Missing Fields\n${enrich.missing_fields.map(f => `- ${f}`).join("\n")}\n\n## Recommendations\n${enrich.recommendations.map((r, i) => `${i + 1}. ${r}`).join("\n")}`;
    }
    else if ("overview" in state.result) {
      const insights = state.result as LeadInsightsResponse;
      content = `## Overview\n${insights.overview}\n\n## Key Insights\n${insights.key_insights.map(i => `- ${i}`).join("\n")}\n\n## Engagement\n${insights.engagement_score || "N/A"}\n\n## Recommended Actions\n${insights.recommended_actions.map((a, i) => `${i + 1}. ${a}`).join("\n")}\n\n## Risk Factors\n${insights.risk_factors.length > 0 ? insights.risk_factors.map(r => `- ${r}`).join("\n") : "None identified"}`;
    }

    return (
      <Collapsible open={state.expanded} onOpenChange={(open) => {
        if (id === "summary") setSummaryState({ ...state, expanded: open });
        else if (id === "insights") setInsightsState({ ...state, expanded: open });
        else if (id === "enrich") setEnrichState({ ...state, expanded: open });
      }}>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="w-full mt-3 justify-between">
            <span className="text-xs text-muted-foreground">
              {state.expanded ? "Hide Result" : "Show Result"}
            </span>
            {state.expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-2 relative">
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-2 right-2 h-8 w-8 z-10"
              onClick={() => copyToClipboard(content, id)}
            >
              {copiedId === id ? (
                <Check className="h-4 w-4 text-green-500" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
            <ResponseRenderer result={state.result} type={id} />
            <p className="text-xs text-muted-foreground mt-2 px-1">
              Generated: {new Date(state.result.generated_at).toLocaleString()}
            </p>
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  };

  // ============================================
  // Main Render
  // ============================================

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          Lead Support Plugins
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          AI-powered tools for lead management
        </p>
        
        {/* Config Status */}
        <div className="mt-3 flex items-center gap-2">
          <Badge variant={configured ? "default" : "destructive"}>
            {configured ? "Lead Selected" : "No Lead Selected"}
          </Badge>
          {selectedLead && (
            <span className="text-xs text-muted-foreground">
              {selectedLead.name}
            </span>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* Summary Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-4 w-4 text-blue-500" />
                Lead Summary
              </CardTitle>
              <CardDescription>Get a comprehensive AI summary</CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                onClick={handleGetSummary}
                disabled={summaryState.loading || !configured}
                className="w-full"
              >
                {summaryState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Sparkles className="h-4 w-4 mr-2" />
                )}
                Generate Summary
              </Button>
              {renderResult(summaryState, "summary")}
            </CardContent>
          </Card>

          {/* Insights Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-green-500" />
                AI Insights
              </CardTitle>
              <CardDescription>Overview, insights, and risk factors</CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                onClick={handleGetInsights}
                disabled={insightsState.loading || !configured}
                className="w-full"
                variant="outline"
              >
                {insightsState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <TrendingUp className="h-4 w-4 mr-2" />
                )}
                Get Insights
              </Button>
              {renderResult(insightsState, "insights")}
            </CardContent>
          </Card>

          {/* Enrich Lead Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-purple-500" />
                Enrich Lead
              </CardTitle>
              <CardDescription>Analyze and enrich lead data</CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                onClick={handleEnrichLead}
                disabled={enrichState.loading || !configured}
                className="w-full"
                variant="outline"
              >
                {enrichState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-2" />
                )}
                Enrich Lead
              </Button>
              {renderResult(enrichState, "enrich")}
            </CardContent>
          </Card>

        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="p-3 border-t bg-muted/30">
        <p className="text-xs text-muted-foreground text-center">
          {selectedLead ? (
            <>
              Using: <span className="font-medium">{selectedLead.name}</span> (
              <code className="bg-muted px-1 rounded">{selectedLead.leadId.slice(0, 12)}...</code>)
            </>
          ) : (
            "No lead selected"
          )}
        </p>
      </div>
    </div>
  );
};
