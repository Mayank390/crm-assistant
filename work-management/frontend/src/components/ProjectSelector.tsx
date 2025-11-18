import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Loader2, Briefcase, Search, Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getProjects, type Project } from "@/api/projects";
import { getAllProjectData } from "@/api/projectData";

export type ProjectSelectorProps = {
  selectedProject?: Project | null;
  onProjectSelect: (project: Project | null) => void;
  trigger?: React.ReactNode;
  className?: string;
};

export const ProjectSelector: React.FC<ProjectSelectorProps> = ({
  selectedProject,
  onProjectSelect,
  trigger,
  className
}) => {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open) {
      loadProjects();
    }
  }, [open]);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const response = await getProjects();
      setProjects(response.data);
    } catch (error) {
      // Failed to load projects
      setProjects([]);
    } finally {
      setLoading(false);
    }
  };

  const filteredProjects = projects.filter(project =>
    project.projectName.toLowerCase().includes(searchTerm.toLowerCase()) ||
    project.projectDisplayId.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleProjectSelect = async (project: Project) => {
    onProjectSelect(project);

    // Pre-load project data in the background (in case it wasn't already loaded)
    try {
      await getAllProjectData(project.projectId);
    } catch (error) {
      // Failed to load data for selected project - continue anyway
    }

    setOpen(false);
  };

  const handleClearSelection = () => {
    onProjectSelect(null);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className={cn("gap-2", className)}>
            <Briefcase className="h-4 w-4" />
            {selectedProject ? selectedProject.projectName : "Select Project"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Briefcase className="h-5 w-5" />
            Select Project
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search projects..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedProject && (
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
          ) : filteredProjects.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No projects found matching your search." : "No projects available."}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredProjects.map((project) => (
                <Card
                  key={project.projectId}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-muted/50",
                    selectedProject?.projectId === project.projectId && "ring-2 ring-primary"
                  )}
                  onClick={() => handleProjectSelect(project)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <Avatar className="h-10 w-10">
                        {project.imageUrl ? (
                          <AvatarImage src={project.imageUrl} alt={project.projectName} />
                        ) : (
                          <AvatarFallback className="text-lg">
                            {project.icon || project.projectDisplayId.slice(0, 2).toUpperCase()}
                          </AvatarFallback>
                        )}
                      </Avatar>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <h4 className="font-medium truncate">{project.projectName}</h4>
                          {selectedProject?.projectId === project.projectId && (
                            <Check className="h-4 w-4 text-primary flex-shrink-0" />
                          )}
                        </div>

                        <div className="flex items-center gap-2 mb-2">
                          <Badge variant="secondary" className="text-xs">
                            {project.projectDisplayId}
                          </Badge>
                          <Badge variant="outline" className="text-xs">
                            {project.accessType}
                          </Badge>
                          {project.lead && (
                            <Badge variant="outline" className="text-xs">
                              Lead: {project.lead.name}
                            </Badge>
                          )}
                        </div>

                        {project.projectDescription && (
                          <p className="text-sm text-muted-foreground line-clamp-2 mb-2">
                            {project.projectDescription}
                          </p>
                        )}

                        <div className="flex flex-wrap gap-1">
                          {project.features.cycles && (
                            <Badge variant="outline" className="text-xs px-1.5 py-0.5">
                              Cycles
                            </Badge>
                          )}
                          {project.features.modules && (
                            <Badge variant="outline" className="text-xs px-1.5 py-0.5">
                              Modules
                            </Badge>
                          )}
                          {project.features.pages && (
                            <Badge variant="outline" className="text-xs px-1.5 py-0.5">
                              Pages
                            </Badge>
                          )}
                          {project.features.timeTracking && (
                            <Badge variant="outline" className="text-xs px-1.5 py-0.5">
                              Time Tracking
                            </Badge>
                          )}
                        </div>
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

export default ProjectSelector;
