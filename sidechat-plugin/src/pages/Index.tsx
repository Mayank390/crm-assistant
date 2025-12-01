import { ChatSidebar } from "@/components/ChatSidebar";
import { LeadPlugins } from "@/components/LeadPlugins";
import { LeadSelector } from "@/components/LeadSelector";
import { LeadProvider, useLeadContext } from "@/context/LeadContext";
import { config } from "@/config";
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

const IndexContent = () => {
  const { selectedLead } = useLeadContext();
  const configured = selectedLead !== null;
  const [showConfig, setShowConfig] = useState(false);

  return (
    <div className="flex h-screen bg-background flex-col">
      {/* Compact Header */}
      <div className="p-3 border-b bg-muted/30 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            Lead Support Agent
          </h1>
          {!configured && (
            <div className="flex items-center gap-2 text-destructive text-sm">
              <AlertCircle className="h-4 w-4" />
              <span>No Lead Selected</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <LeadSelector />
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
                  API settings. Lead is selected from the dropdown above.
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
                  <Input value={config.businessId} readOnly />
                </div>
                <div className="space-y-2">
                  <Label>Selected Lead</Label>
                  <Input
                    value={selectedLead ? `${selectedLead.name} (${selectedLead.leadId})` : "No lead selected"}
                    readOnly
                    className={!selectedLead ? "border-destructive" : ""}
                  />
                  <p className="text-xs text-muted-foreground">
                    Select a lead from the dropdown in the header
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
      </div>

      {/* Main Content - Left and Right Panels */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Side - Lead Plugins */}
        <div className="flex-1 border-r flex flex-col overflow-hidden">
          <LeadPlugins />
        </div>

        {/* Right Side - Chat Sidebar */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <ChatSidebar />
        </div>
      </div>
    </div>
  );
};

const Index = () => {
  return (
    <LeadProvider>
      <IndexContent />
    </LeadProvider>
  );
};

export default Index;
