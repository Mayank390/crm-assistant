import { useLeadContext, Lead } from "@/context/LeadContext";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { User, Loader2 } from "lucide-react";

const getStatusColor = (status: string) => {
  switch (status) {
    case "QUALIFIED":
      return "bg-green-500/20 text-green-600 border-green-500/30";
    case "CONTACTED":
      return "bg-blue-500/20 text-blue-600 border-blue-500/30";
    case "NEW":
      return "bg-purple-500/20 text-purple-600 border-purple-500/30";
    case "FOLLOW_UP":
      return "bg-orange-500/20 text-orange-600 border-orange-500/30";
    default:
      return "bg-gray-500/20 text-gray-600 border-gray-500/30";
  }
};

export const LeadSelector = () => {
  const { leads, selectedLead, setSelectedLead, isLoading, error } = useLeadContext();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading leads...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-destructive text-sm">
        Error: {error}
      </div>
    );
  }

  const handleSelect = (leadId: string) => {
    const lead = leads.find((l) => l.leadId === leadId);
    if (lead) {
      setSelectedLead(lead);
    }
  };

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 text-muted-foreground">
        <User className="h-4 w-4" />
        <span className="text-sm font-medium">Lead:</span>
      </div>
      <Select
        value={selectedLead?.leadId || ""}
        onValueChange={handleSelect}
      >
        <SelectTrigger className="w-[280px]">
          <SelectValue placeholder="Select a lead">
            {selectedLead && (
              <div className="flex items-center gap-2">
                <span>{selectedLead.name}</span>
                <Badge
                  variant="outline"
                  className={`text-xs ${getStatusColor(selectedLead.status)}`}
                >
                  {selectedLead.status.replace("_", " ")}
                </Badge>
              </div>
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {leads.map((lead) => (
            <SelectItem key={lead.leadId} value={lead.leadId}>
              <div className="flex items-center justify-between gap-3 w-full">
                <div className="flex flex-col">
                  <span className="font-medium">{lead.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {lead.email}
                  </span>
                </div>
                <Badge
                  variant="outline"
                  className={`text-xs ${getStatusColor(lead.status)}`}
                >
                  {lead.status.replace("_", " ")}
                </Badge>
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {selectedLead && (
        <code className="text-xs bg-muted px-2 py-1 rounded">
          {selectedLead.leadId.slice(0, 8)}...
        </code>
      )}
    </div>
  );
};
