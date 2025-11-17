import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Boxes, Search, Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getAllModules, type Module } from "@/api/modules";
import { getCachedModules } from "@/api/projectData";

export type ModuleSelectorProps = {
  projectId: string;
  selectedModule?: Module | null;
  onModuleSelect: (module: Module | null) => void;
  trigger?: React.ReactNode;
  className?: string;
};

export const ModuleSelector: React.FC<ModuleSelectorProps> = ({
  projectId,
  selectedModule,
  onModuleSelect,
  trigger,
  className,
}) => {
  const [open, setOpen] = useState(false);
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open && projectId) {
      loadModules();
    }
  }, [open, projectId]);

  const loadModules = async () => {
    setLoading(true);
    try {
      // First check if data is cached
      const cachedModules = getCachedModules(projectId);
      if (cachedModules) {
        setModules(cachedModules.data);
        setLoading(false);
        return;
      }

      // If not cached, fetch from API
      const response = await getAllModules(projectId);
      setModules(response.data);
    } catch (error) {
      // Failed to load modules
      setModules([]);
    } finally {
      setLoading(false);
    }
  };

  const filteredModules = modules.filter(module =>
    module.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    module.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleModuleSelect = (module: Module) => {
    onModuleSelect(module);
    setOpen(false);
  };

  const handleClearSelection = () => {
    onModuleSelect(null);
    setOpen(false);
  };

  const formatDateRange = (module: Module) => {
    if (!module.startDate && !module.endDate) return null;

    try {
      const startDate = module.startDate ? new Date(module.startDate).toLocaleDateString() : null;
      const endDate = module.endDate ? new Date(module.endDate).toLocaleDateString() : null;

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

  const getDisplayName = (module: Module) => {
    return module.title;
  };

  const getSelectedModuleText = () => {
    if (!selectedModule) {
      return "Modules";
    }
    return getDisplayName(selectedModule);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className={cn("gap-2", className)}>
            <Boxes className="h-4 w-4" />
            {getSelectedModuleText()}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Boxes className="h-5 w-5" />
            Select Module
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search modules..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedModule && (
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
          ) : filteredModules.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No modules found matching your search." : "No modules available."}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredModules.map((module) => (
                <Card
                  key={module.id}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-muted/50",
                    selectedModule?.id === module.id && "ring-2 ring-primary"
                  )}
                  onClick={() => handleModuleSelect(module)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 mt-0.5">
                        {selectedModule?.id === module.id && (
                          <Check className="h-4 w-4 text-primary" />
                        )}
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <h4 className="font-medium truncate flex-1">{getDisplayName(module)}</h4>
                          {selectedModule?.id === module.id && (
                            <Check className="h-4 w-4 text-primary flex-shrink-0" />
                          )}
                        </div>

                        {formatDateRange(module) && (
                          <div className="flex items-center gap-1 mb-2">
                            <span className="text-xs text-muted-foreground">
                              {formatDateRange(module)}
                            </span>
                          </div>
                        )}

                        {module.description && (
                          <p className="text-sm text-muted-foreground line-clamp-2">
                            {module.description}
                          </p>
                        )}

                        {module.members && module.members.length > 0 && (
                          <div className="mt-2">
                            <Badge variant="outline" className="text-xs">
                              {module.members.length} member{module.members.length > 1 ? 's' : ''}
                            </Badge>
                          </div>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ModuleSelector;
