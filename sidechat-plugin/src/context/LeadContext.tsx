import { createContext, useContext, useState, useEffect, ReactNode } from "react";

export interface Lead {
  leadId: string;
  name: string;
  email: string;
  status: string;
}

interface LeadContextType {
  leads: Lead[];
  selectedLead: Lead | null;
  setSelectedLead: (lead: Lead | null) => void;
  isLoading: boolean;
  error: string | null;
}

const LeadContext = createContext<LeadContextType | undefined>(undefined);

export const LeadProvider = ({ children }: { children: ReactNode }) => {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchLeads = async () => {
      try {
        const response = await fetch("/business_leads.json");
        if (!response.ok) {
          throw new Error("Failed to fetch leads");
        }
        const data: Lead[] = await response.json();
        setLeads(data);
        // Select first lead by default if available
        if (data.length > 0) {
          setSelectedLead((prev) => prev || data[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load leads");
      } finally {
        setIsLoading(false);
      }
    };

    fetchLeads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <LeadContext.Provider
      value={{
        leads,
        selectedLead,
        setSelectedLead,
        isLoading,
        error,
      }}
    >
      {children}
    </LeadContext.Provider>
  );
};

export const useLeadContext = () => {
  const context = useContext(LeadContext);
  if (context === undefined) {
    throw new Error("useLeadContext must be used within a LeadProvider");
  }
  return context;
};
