import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Tag, Search, Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getSubStates, getSubStatesByState, getAllSubStatesAsArray, type SubState, type GetSubStatesResponse } from "@/api/substates";
import { getCachedSubStates } from "@/api/projectData";

/**
 * SubStateSelector component for selecting sub-states from the API
 * Handles different API response formats gracefully
 * Includes safety checks for sub-state object properties
 */

export type SubStateSelectorProps = {
  projectId: string;
  selectedSubState?: SubState | null;
  onSubStateSelect: (subState: SubState | null) => void;
  trigger?: React.ReactNode;
  className?: string;
  stateName?: string; // Optional filter to show only sub-states from a specific state
};

export const SubStateSelector: React.FC<SubStateSelectorProps> = ({
  projectId,
  selectedSubState,
  onSubStateSelect,
  trigger,
  className,
  stateName
}) => {
  const [open, setOpen] = useState(false);
  const [subStatesResponse, setSubStatesResponse] = useState<GetSubStatesResponse>({ data: [] });
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open && projectId) {
      loadSubStates();
    }
  }, [open, projectId]);

  const loadSubStates = async () => {
    setLoading(true);
    try {
      // First check if data is cached
      const cachedSubStates = getCachedSubStates(projectId);
      if (cachedSubStates) {
        setSubStatesResponse(cachedSubStates);
        setLoading(false);
        return;
      }

      // If not cached, fetch from API
      const response = await getSubStates(projectId);
      setSubStatesResponse(response);
    } catch (error) {
      // Failed to load sub-states
      setSubStatesResponse({ data: [] });
    } finally {
      setLoading(false);
    }
  };

  // Get all sub-states as a flat array for filtering
  const allSubStates = getAllSubStatesAsArray(subStatesResponse);

  // Filter sub-states by state name if provided
  const filteredSubStates = stateName
    ? allSubStates.filter(subState => {
        const state = subStatesResponse.data.find(s =>
          s.subStates?.some(ss => ss.id === subState.id)
        );
        return state?.name === stateName;
      })
    : allSubStates;

  // Apply search filter
  const searchFilteredSubStates = filteredSubStates.filter(subState =>
    subState?.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    subState?.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Group filtered sub-states back by state
  const subStatesByState = getSubStatesByState({
    data: subStatesResponse.data.map(state => ({
      ...state,
      subStates: stateName
        ? state.subStates?.filter(ss => searchFilteredSubStates.some(fss => fss.id === ss.id))
        : state.subStates?.filter(ss => searchFilteredSubStates.some(fss => fss.id === ss.id))
    }))
  });

  const handleSubStateSelect = (subState: SubState) => {
    onSubStateSelect(subState);
    setOpen(false);
  };

  const handleClearSelection = () => {
    onSubStateSelect(null);
    setOpen(false);
  };

  const getStateColor = (color?: string) => {
    if (!color) return 'bg-gray-100 text-gray-800 border-gray-200';

    // Handle common color formats
    if (color.startsWith('#')) {
      return `border-gray-200`;
    }

    // Handle named colors
    switch (color.toLowerCase()) {
      case 'red':
        return 'bg-red-100 text-red-800 border-red-200';
      case 'blue':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'green':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'yellow':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'purple':
        return 'bg-purple-100 text-purple-800 border-purple-200';
      case 'pink':
        return 'bg-pink-100 text-pink-800 border-pink-200';
      case 'indigo':
        return 'bg-indigo-100 text-indigo-800 border-indigo-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const renderSubStatesByState = (stateName: string, title: string) => {
    const subStates = subStatesByState[stateName];
    if (!subStates || subStates.length === 0) return null;

    return (
      <div key={stateName} className="space-y-2">
        <div className="flex items-center gap-2 px-1">
          <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
          <Badge variant="secondary" className="text-xs">
            {subStates.length}
          </Badge>
        </div>
        <div className="space-y-2">
          {subStates.map((subState) => (
            subState && subState.id && subState.name ? (
              <Card
                key={subState.id}
                className={cn(
                  "cursor-pointer transition-colors hover:bg-muted/50",
                  selectedSubState?.id === subState.id && "ring-2 ring-primary"
                )}
                onClick={() => handleSubStateSelect(subState)}
              >
                <CardContent className="p-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {selectedSubState?.id === subState.id && (
                        <Check className="h-4 w-4 text-primary" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium truncate flex-1">{subState.name}</h4>
                        <Badge
                          variant="outline"
                          className={cn("text-xs shrink-0", getStateColor(subState.color))}
                        >
                          {subState.name}
                        </Badge>
                        {selectedSubState?.id === subState.id && (
                          <Check className="h-4 w-4 text-primary flex-shrink-0" />
                        )}
                      </div>

                      {subState.description && (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {subState.description}
                        </p>
                      )}

                      <div className="mt-1">
                        <span className="text-xs text-muted-foreground">
                          Order: {subState.order}
                          {subState.default && " (Default)"}
                        </span>
                      </div>
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
            <Tag className="h-4 w-4" />
            {selectedSubState ? selectedSubState.name : "Select State"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Tag className="h-5 w-5" />
            Select State
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search states..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedSubState && (
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
          ) : allSubStates.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No states found matching your search." : "No states available."}
            </div>
          ) : (
            <div className="space-y-4">
              {stateName ? (
                // Show only sub-states from the specified state
                renderSubStatesByState(stateName, stateName)
              ) : (
                // Show all states and their sub-states dynamically from API response
                <>
                  {Object.entries(subStatesByState).map(([stateName, subStates]) => (
                    renderSubStatesByState(stateName, stateName)
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default SubStateSelector;
