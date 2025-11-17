import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, CalendarClock, Search, Check, Calendar } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getAllCycles, getAllCyclesAsArray, type Cycle, type CyclesByStatus } from "@/api/cycles";
import { getCachedCycles } from "@/api/projectData";

/**
 * CycleSelector component for selecting cycles from the API
 * Handles different API response formats gracefully
 * Includes safety checks for cycle object properties
 */

export type CycleSelectorProps = {
  projectId?: string;
  selectedCycle?: Cycle | null;
  onCycleSelect: (cycle: Cycle | null) => void;
  trigger?: React.ReactNode;
  className?: string;
};

export const CycleSelector: React.FC<CycleSelectorProps> = ({
  projectId,
  selectedCycle,
  onCycleSelect,
  trigger,
  className
}) => {
  const [open, setOpen] = useState(false);
  const [cyclesByStatus, setCyclesByStatus] = useState<CyclesByStatus>({
    UPCOMING: [],
    ACTIVE: [],
    COMPLETED: []
  });
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open) {
      loadCycles();
    }
  }, [open, projectId]);

  const loadCycles = async () => {
    setLoading(true);
    try {
      // First check if data is cached
      const cachedCycles = getCachedCycles(projectId);
      if (cachedCycles) {
        setCyclesByStatus(cachedCycles.data);
        setLoading(false);
        return;
      }

      // If not cached, fetch from API
      const response = await getAllCycles(projectId);
      setCyclesByStatus(response.data);
    } catch (error) {
      // Failed to load cycles
      setCyclesByStatus({
        UPCOMING: [],
        ACTIVE: [],
        COMPLETED: []
      });
    } finally {
      setLoading(false);
    }
  };

  // Get all cycles as a flat array for filtering
  const allCycles = getAllCyclesAsArray({ data: cyclesByStatus });

  const filteredCycles = allCycles.filter(cycle =>
    cycle?.title?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    cycle?.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Group filtered cycles back by status
  const filteredCyclesByStatus: CyclesByStatus = {
    UPCOMING: filteredCycles.filter(cycle => cycle.status === 'UPCOMING'),
    ACTIVE: filteredCycles.filter(cycle => cycle.status === 'ACTIVE'),
    COMPLETED: filteredCycles.filter(cycle => cycle.status === 'COMPLETED')
  };

  const handleCycleSelect = (cycle: Cycle) => {
    onCycleSelect(cycle);
    setOpen(false);
  };

  const handleClearSelection = () => {
    onCycleSelect(null);
    setOpen(false);
  };

  const formatDateRange = (cycle: Cycle) => {
    if (!cycle?.startDate && !cycle?.endDate) return null;

    try {
      const startDate = cycle.startDate ? new Date(cycle.startDate).toLocaleDateString() : null;
      const endDate = cycle.endDate ? new Date(cycle.endDate).toLocaleDateString() : null;

      if (startDate && endDate) {
        return `${startDate} → ${endDate}`;
      } else if (startDate) {
        return `From ${startDate}`;
      } else if (endDate) {
        return `Until ${endDate}`;
      }
    } catch (error) {
      // Error formatting date range - return null
    }
    return null;
  };

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return 'default';
      case 'UPCOMING':
        return 'secondary';
      case 'COMPLETED':
        return 'outline';
      default:
        return 'secondary';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'UPCOMING':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'COMPLETED':
        return 'bg-green-100 text-green-800 border-green-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const renderCyclesByStatus = (status: keyof CyclesByStatus, title: string) => {
    const cycles = filteredCyclesByStatus[status];
    if (cycles.length === 0) return null;

    return (
      <div key={status} className="space-y-2">
        <div className="flex items-center gap-2 px-1">
          <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
          <Badge variant={getStatusBadgeVariant(status)} className="text-xs">
            {cycles.length}
          </Badge>
        </div>
        <div className="space-y-2">
          {cycles.map((cycle) => (
            cycle && cycle.id && cycle.title ? (
              <Card
                key={cycle.id}
                className={cn(
                  "cursor-pointer transition-colors hover:bg-muted/50",
                  selectedCycle?.id === cycle.id && "ring-2 ring-primary"
                )}
                onClick={() => handleCycleSelect(cycle)}
              >
                <CardContent className="p-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {selectedCycle?.id === cycle.id && (
                        <Check className="h-4 w-4 text-primary" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium truncate flex-1">{cycle.title}</h4>
                        <Badge
                          variant={getStatusBadgeVariant(cycle.status)}
                          className="text-xs shrink-0"
                        >
                          {cycle.status}
                        </Badge>
                        {selectedCycle?.id === cycle.id && (
                          <Check className="h-4 w-4 text-primary flex-shrink-0" />
                        )}
                      </div>

                      {formatDateRange(cycle) && (
                        <div className="flex items-center gap-1 mb-2">
                          <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="text-xs text-muted-foreground">
                            {formatDateRange(cycle)}
                          </span>
                        </div>
                      )}

                      {cycle.description && (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {cycle.description}
                        </p>
                      )}

                      {cycle.completionPercentage !== undefined && (
                        <div className="mt-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">
                              {cycle.completionPercentage}% complete
                            </span>
                            <div className="flex-1 bg-muted rounded-full h-1.5">
                              <div
                                className="bg-primary h-1.5 rounded-full transition-all"
                                style={{ width: `${cycle.completionPercentage}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ) : null
          ))}
        </div>
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className={cn("gap-2", className)}>
            <CalendarClock className="h-4 w-4" />
            {selectedCycle ? selectedCycle.title : "Select Cycle"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5" />
            Select Cycle
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search cycles..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedCycle && (
            <Button variant="outline" size="sm" onClick={handleClearSelection}>
              Clear
            </Button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : allCycles.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No cycles found matching your search." : "No cycles available."}
            </div>
          ) : (
            <div className="space-y-4">
              {renderCyclesByStatus('ACTIVE', 'Active Cycles')}
              {renderCyclesByStatus('UPCOMING', 'Upcoming Cycles')}
              {renderCyclesByStatus('COMPLETED', 'Completed Cycles')}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default CycleSelector;
