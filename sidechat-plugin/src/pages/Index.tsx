import { ChatSidebar } from "@/components/ChatSidebar";
import { LeadPlugins } from "@/components/LeadPlugins";
import { config, isConfigured } from "@/config";
import { AlertCircle, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useState } from "react";

const Index = () => {
  const configured = isConfigured();
  const [showConfig, setShowConfig] = useState(!configured);

  return (
    <div className="flex h-screen bg-background">
      {/* Left Side - Lead Plugins */}
      <div className="w-[420px] border-r flex flex-col">
        <LeadPlugins />
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b flex items-center justify-between bg-muted/30">
          <div>
            <h1 className="text-xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Lead Support Agent Testing
            </h1>
            <p className="text-sm text-muted-foreground">
              Test the Lead Support Agent endpoints and WebSocket integration
            </p>
          </div>
          <Dialog open={showConfig} onOpenChange={setShowConfig}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2">
                <Settings className="h-4 w-4" />
                Configure
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Configuration</DialogTitle>
                <DialogDescription>
                  Update these values in your <code>.env</code> file or{" "}
                  <code>src/config.ts</code>
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label>API Base URL</Label>
                  <Input value={config.api.baseUrl} readOnly />
                </div>
                <div className="space-y-2">
                  <Label>WebSocket URL</Label>
                  <Input value={config.api.wsUrl} readOnly />
                </div>
                <div className="space-y-2">
                  <Label>Business ID</Label>
                  <Input
                    value={config.businessId}
                    readOnly
                    className={
                      config.businessId === "YOUR_BUSINESS_ID_HERE"
                        ? "border-destructive"
                        : ""
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Set via VITE_BUSINESS_ID env var
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Lead ID</Label>
                  <Input
                    value={config.leadId}
                    readOnly
                    className={
                      config.leadId === "YOUR_LEAD_ID_HERE"
                        ? "border-destructive"
                        : ""
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Set via VITE_LEAD_ID env var
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Member ID</Label>
                  <Input
                    value={config.memberId}
                    readOnly
                    className={
                      config.memberId === "YOUR_MEMBER_ID_HERE"
                        ? "border-destructive"
                        : ""
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Set via VITE_MEMBER_ID env var
                  </p>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {/* Configuration Warning */}
        {!configured && (
          <div className="mx-4 mt-4 p-4 bg-destructive/10 border border-destructive/20 rounded-lg flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-destructive">
                Configuration Required
              </h3>
              <p className="text-sm text-muted-foreground mt-1">
                Please configure your Business ID, Lead ID, and Member ID before
                testing. You can set these in:
              </p>
              <ul className="text-sm text-muted-foreground mt-2 list-disc list-inside">
                <li>
                  Environment variables:{" "}
                  <code className="bg-muted px-1 rounded">VITE_BUSINESS_ID</code>,{" "}
                  <code className="bg-muted px-1 rounded">VITE_LEAD_ID</code>,{" "}
                  <code className="bg-muted px-1 rounded">VITE_MEMBER_ID</code>
                </li>
                <li>
                  Or directly in{" "}
                  <code className="bg-muted px-1 rounded">src/config.ts</code>
                </li>
              </ul>
            </div>
          </div>
        )}

        {/* Instructions */}
        <div className="flex-1 p-6 overflow-auto">
          <div className="max-w-3xl mx-auto space-y-6">
            <div className="bg-muted/30 rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">How to Use</h2>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-primary font-bold">1</span>
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">REST API Plugins (Left Panel)</h3>
                    <p className="text-sm text-muted-foreground">
                      Click buttons to test individual REST API endpoints. Results
                      appear in expandable sections below each plugin.
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-primary font-bold">2</span>
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">WebSocket Chat (Right Panel)</h3>
                    <p className="text-sm text-muted-foreground">
                      Real-time streaming chat with the Lead Support Agent. Use
                      quick action buttons or type custom queries.
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-primary font-bold">3</span>
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">Quick Actions</h3>
                    <p className="text-sm text-muted-foreground">
                      Use the quick action buttons in the chat for common tasks:
                      Summarize, Next Steps, Draft Email, Meeting Prep, and Objection
                      Handling.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* API Endpoints Reference */}
            <div className="bg-muted/30 rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">API Endpoints</h2>
              <div className="space-y-2 font-mono text-sm">
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/summary</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/insights</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/next-steps</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/draft-message</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/objection</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-green-500/20 text-green-600 px-2 py-0.5 rounded text-xs">
                    POST
                  </span>
                  <span>/lead-support/meeting-prep</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="bg-blue-500/20 text-blue-600 px-2 py-0.5 rounded text-xs">
                    WS
                  </span>
                  <span>/ws/lead-support</span>
                </div>
              </div>
            </div>

            {/* Current Config Display */}
            <div className="bg-muted/30 rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">Current Configuration</h2>
              <div className="space-y-2 font-mono text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">API URL:</span>
                  <span>{config.api.baseUrl}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">WS URL:</span>
                  <span>{config.api.wsUrl}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Business ID:</span>
                  <span
                    className={
                      config.businessId === "YOUR_BUSINESS_ID_HERE"
                        ? "text-destructive"
                        : ""
                    }
                  >
                    {config.businessId.slice(0, 20)}
                    {config.businessId.length > 20 ? "..." : ""}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Lead ID:</span>
                  <span
                    className={
                      config.leadId === "YOUR_LEAD_ID_HERE"
                        ? "text-destructive"
                        : ""
                    }
                  >
                    {config.leadId.slice(0, 20)}
                    {config.leadId.length > 20 ? "..." : ""}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Member ID:</span>
                  <span
                    className={
                      config.memberId === "YOUR_MEMBER_ID_HERE"
                        ? "text-destructive"
                        : ""
                    }
                  >
                    {config.memberId.slice(0, 20)}
                    {config.memberId.length > 20 ? "..." : ""}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Side - Chat Sidebar */}
      <div className="w-[400px]">
        <ChatSidebar />
      </div>
    </div>
  );
};

export default Index;
