import { useState } from "react";
import {
  Sparkles,
  TrendingUp,
  FileText,
  Mail,
  MessageSquare,
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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  leadSupportApi,
  LeadSummaryResponse,
  LeadInsightsResponse,
  LeadNextStepsResponse,
  DraftMessageResponse,
  ObjectionHandlingResponse,
  MeetingPrepResponse,
} from "@/api/leadSupportApi";
import { useLeadContext } from "@/context/LeadContext";
import { ResponseRenderer } from "@/components/ResponseRenderer";

type PluginResult =
  | LeadSummaryResponse
  | LeadInsightsResponse
  | LeadNextStepsResponse
  | DraftMessageResponse
  | ObjectionHandlingResponse
  | MeetingPrepResponse
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
  const [summaryState, setSummaryState] = useState<PluginState>(initialPluginState);
  const [insightsState, setInsightsState] = useState<PluginState>(initialPluginState);
  const [nextStepsState, setNextStepsState] = useState<PluginState>(initialPluginState);
  const [draftState, setDraftState] = useState<PluginState>(initialPluginState);
  const [objectionState, setObjectionState] = useState<PluginState>(initialPluginState);
  const [meetingPrepState, setMeetingPrepState] = useState<PluginState>(initialPluginState);

  const [objectionInput, setObjectionInput] = useState("");
  const [draftContext, setDraftContext] = useState("");
  const [meetingContext, setMeetingContext] = useState("");
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

  const handleGetNextSteps = async () => {
    if (!leadId) return;
    setNextStepsState({ ...nextStepsState, loading: true, error: null });
    try {
      const result = await leadSupportApi.getNextSteps(leadId);
      setNextStepsState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setNextStepsState({ ...nextStepsState, loading: false, error: err.message });
    }
  };

  const handleDraftMessage = async () => {
    if (!leadId) return;
    setDraftState({ ...draftState, loading: true, error: null });
    try {
      const result = await leadSupportApi.draftMessage(leadId, "email", draftContext || undefined);
      setDraftState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setDraftState({ ...draftState, loading: false, error: err.message });
    }
  };

  const handleObjection = async () => {
    if (!leadId || !objectionInput.trim()) return;
    setObjectionState({ ...objectionState, loading: true, error: null });
    try {
      const result = await leadSupportApi.handleObjection(objectionInput, leadId);
      setObjectionState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setObjectionState({ ...objectionState, loading: false, error: err.message });
    }
  };

  const handleMeetingPrep = async () => {
    if (!leadId) return;
    setMeetingPrepState({ ...meetingPrepState, loading: true, error: null });
    try {
      const result = await leadSupportApi.prepareMeeting(leadId, meetingContext || undefined);
      setMeetingPrepState({ loading: false, error: null, result, expanded: true });
    } catch (err: any) {
      setMeetingPrepState({ ...meetingPrepState, loading: false, error: err.message });
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
    else if ("next_steps" in state.result) content = state.result.next_steps;
    else if ("draft" in state.result) content = state.result.draft;
    else if ("response" in state.result) content = state.result.response;
    else if ("prep_document" in state.result) content = state.result.prep_document;
    else if ("overview" in state.result) {
      const insights = state.result as LeadInsightsResponse;
      content = `## Overview\n${insights.overview}\n\n## Key Insights\n${insights.key_insights.map(i => `- ${i}`).join("\n")}\n\n## Engagement\n${insights.engagement_score || "N/A"}\n\n## Recommended Actions\n${insights.recommended_actions.map((a, i) => `${i + 1}. ${a}`).join("\n")}\n\n## Risk Factors\n${insights.risk_factors.length > 0 ? insights.risk_factors.map(r => `- ${r}`).join("\n") : "None identified"}`;
    }

    return (
      <Collapsible open={state.expanded} onOpenChange={(open) => {
        if (id === "summary") setSummaryState({ ...state, expanded: open });
        else if (id === "insights") setInsightsState({ ...state, expanded: open });
        else if (id === "next_steps") setNextStepsState({ ...state, expanded: open });
        else if (id === "draft") setDraftState({ ...state, expanded: open });
        else if (id === "objection") setObjectionState({ ...state, expanded: open });
        else if (id === "meeting_prep") setMeetingPrepState({ ...state, expanded: open });
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

          {/* Next Steps Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-purple-500" />
                Next Best Steps
              </CardTitle>
              <CardDescription>AI-recommended actions</CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                onClick={handleGetNextSteps}
                disabled={nextStepsState.loading || !configured}
                className="w-full"
                variant="outline"
              >
                {nextStepsState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-2" />
                )}
                Get Next Steps
              </Button>
              {renderResult(nextStepsState, "next_steps")}
            </CardContent>
          </Card>

          <Separator />

          {/* Draft Message Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Mail className="h-4 w-4 text-orange-500" />
                Draft Message
              </CardTitle>
              <CardDescription>Create personalized outreach</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input
                placeholder="Context (optional): e.g., follow up on pricing"
                value={draftContext}
                onChange={(e) => setDraftContext(e.target.value)}
              />
              <Button
                onClick={handleDraftMessage}
                disabled={draftState.loading || !configured}
                className="w-full"
                variant="outline"
              >
                {draftState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Mail className="h-4 w-4 mr-2" />
                )}
                Draft Email
              </Button>
              {renderResult(draftState, "draft")}
            </CardContent>
          </Card>

          {/* Objection Handling Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-red-500" />
                Objection Handling
              </CardTitle>
              <CardDescription>Get responses to objections</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea
                placeholder="Enter the objection: e.g., 'The price is too high'"
                value={objectionInput}
                onChange={(e) => setObjectionInput(e.target.value)}
                rows={2}
              />
              <Button
                onClick={handleObjection}
                disabled={objectionState.loading || !objectionInput.trim() || !configured}
                className="w-full"
                variant="destructive"
              >
                {objectionState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <MessageSquare className="h-4 w-4 mr-2" />
                )}
                Handle Objection
              </Button>
              {renderResult(objectionState, "objection")}
            </CardContent>
          </Card>

          {/* Meeting Prep Plugin */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Calendar className="h-4 w-4 text-cyan-500" />
                Meeting Prep
              </CardTitle>
              <CardDescription>Prepare for your meeting</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input
                placeholder="Meeting context (optional): e.g., quarterly review"
                value={meetingContext}
                onChange={(e) => setMeetingContext(e.target.value)}
              />
              <Button
                onClick={handleMeetingPrep}
                disabled={meetingPrepState.loading || !configured}
                className="w-full"
                variant="outline"
              >
                {meetingPrepState.loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Calendar className="h-4 w-4 mr-2" />
                )}
                Prepare Meeting
              </Button>
              {renderResult(meetingPrepState, "meeting_prep")}
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
