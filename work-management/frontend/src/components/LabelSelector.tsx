import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Tag, Search, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { getProjectLabels, type ProjectLabel } from "@/api/labels";
import { getCachedLabels } from "@/api/projectData";

export type LabelSelectorProps = {
  projectId: string;
  selectedLabels?: ProjectLabel[];
  onLabelsSelect: (labels: ProjectLabel[]) => void;
  trigger?: React.ReactNode;
  className?: string;
  mode?: "single" | "multiple";
  title?: string;
  placeholder?: string;
  maxSelections?: number;
};

export const LabelSelector: React.FC<LabelSelectorProps> = ({
  projectId,
  selectedLabels = [],
  onLabelsSelect,
  trigger,
  className,
  mode = "multiple",
  title = "Select Labels",
  placeholder = "Select labels...",
  maxSelections,
}) => {
  const [open, setOpen] = useState(false);
  const [labels, setLabels] = useState<ProjectLabel[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open && projectId) {
      loadLabels();
    }
  }, [open, projectId]);

  const loadLabels = async () => {
    setLoading(true);
    try {
      // First check if data is cached
      const cachedLabels = getCachedLabels(projectId);
      if (cachedLabels) {
        setLabels(cachedLabels.data || []);
        setLoading(false);
        return;
      }

      // If not cached, fetch from API
      const response = await getProjectLabels(projectId);
      setLabels(response.data || []);
    } catch (error) {
      // Failed to load project labels
      setLabels([]);
    } finally {
      setLoading(false);
    }
  };

  const filteredLabels = labels.filter(label =>
    label.label.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleLabelToggle = (label: ProjectLabel) => {
    if (mode === "single") {
      onLabelsSelect([label]);
      setOpen(false);
      return;
    }

    // Multiple mode
    const isSelected = selectedLabels.some(l => l.id === label.id);
    let newSelection: ProjectLabel[];

    if (isSelected) {
      newSelection = selectedLabels.filter(l => l.id !== label.id);
    } else {
      if (maxSelections && selectedLabels.length >= maxSelections) {
        return; // Don't allow more selections
      }
      newSelection = [...selectedLabels, label];
    }

    onLabelsSelect(newSelection);
  };

  const handleClearSelection = () => {
    onLabelsSelect([]);
  };

  const getSelectedLabelsText = () => {
    if (selectedLabels.length === 0) {
      return placeholder;
    }

    if (mode === "single") {
      return selectedLabels[0]?.label || "Label";
    }

    if (selectedLabels.length === 1) {
      return selectedLabels[0]?.label || "Label";
    }

    return `${selectedLabels.length} labels`;
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className={cn("gap-2", className)}>
            <Tag className="h-4 w-4" />
            {getSelectedLabelsText()}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Tag className="h-5 w-5" />
            {title}
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search labels..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedLabels.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleClearSelection}>
              <X className="h-4 w-4 mr-1" />
              Clear
            </Button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : filteredLabels.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No labels found matching your search." : "No labels available."}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredLabels.map((label) => {
                const isSelected = selectedLabels.some(l => l.id === label.id);

                return (
                  <Card
                    key={label.id}
                    className={cn(
                      "cursor-pointer transition-colors hover:bg-muted/50",
                      isSelected && "ring-2 ring-primary"
                    )}
                    onClick={() => handleLabelToggle(label)}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {mode === "multiple" && (
                            <Checkbox
                              checked={isSelected}
                              onChange={() => handleLabelToggle(label)}
                              className="mt-0.5"
                            />
                          )}
                          {mode === "single" && isSelected && (
                            <Check className="h-4 w-4 text-primary mt-0.5" />
                          )}
                        </div>

                        <div
                          className="w-4 h-4 rounded-full border border-gray-300 flex-shrink-0"
                          style={{ backgroundColor: label.color }}
                        />

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h4 className="font-medium truncate">{label.label}</h4>
                            {mode === "single" && isSelected && (
                              <Check className="h-4 w-4 text-primary flex-shrink-0" />
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            #{label.color}
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default LabelSelector;
