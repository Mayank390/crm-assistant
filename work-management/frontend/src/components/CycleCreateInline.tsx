import React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import MDEditor from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import { Card, CardContent } from "@/components/ui/card";
import { Calendar, Wand2, Briefcase } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";
import ProjectSelector from "@/components/ProjectSelector";
import { DateRangePicker, DateRange } from "@/components/ui/date-range-picker";
import { type Project } from "@/api/projects";
import { getAllProjectData, sendProjectDataToConversation } from "@/api/projectData";

export type CycleCreateInlineProps = {
  title?: string;
  description?: string;
  selectedProject?: Project | null;
  selectedDateRange?: DateRange;
  onProjectSelect?: (project: Project | null) => void;
  onDateSelect?: (dateRange: DateRange | undefined) => void;
  onSave?: (values: { title: string; description: string; project?: Project | null; startDate?: string; endDate?: string }) => void;
  onDiscard?: () => void;
  className?: string;
  conversationId?: string;
  onProjectDataLoaded?: (message: string) => void;
};

const FieldChip: React.FC<React.PropsWithChildren<{ icon?: React.ReactNode; onClick?: () => void; className?: string }>> = ({ icon, children, onClick, className }) => (
  <div
    className={cn(
      "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs text-muted-foreground bg-background",
      onClick && "cursor-pointer hover:bg-muted/50 hover:border-primary/20 transition-colors",
      className
    )}
    onClick={onClick}
  >
    {icon}
    <span className="whitespace-nowrap">{children}</span>
  </div>
);

export const CycleCreateInline: React.FC<CycleCreateInlineProps> = ({
  title = "",
  description = "",
  selectedProject = null,
  selectedDateRange,
  onProjectSelect,
  onDateSelect,
  onSave,
  onDiscard,
  className,
  conversationId,
  onProjectDataLoaded
}) => {
  const [name, setName] = React.useState<string>(title);
  const [desc, setDesc] = React.useState<string>(description);
  const [isEditingDesc, setIsEditingDesc] = React.useState<boolean>(true);

  const handleSave = () => {
    const startDate = selectedDateRange?.from?.toISOString().split('T')[0];
    const endDate = selectedDateRange?.to?.toISOString().split('T')[0];
    onSave?.({ title: name.trim(), description: desc, project: selectedProject, startDate, endDate });
  };

  const handleProjectSelect = async (project: Project | null) => {
    // Call the original onProjectSelect handler
    onProjectSelect?.(project);

    // If a project is selected, fetch all project data and send to conversation
    if (project && conversationId) {
      try {
        const projectData = await getAllProjectData(project.projectId);
        await sendProjectDataToConversation(
          projectData,
          project.projectName,
          project.projectDisplayId,
          conversationId
        );
      } catch (error) {
        // Failed to fetch project data
      }
    }
  };

  return (
    <Card className={cn("border-muted/70", className)}>
      <CardContent className="p-0">
        <div className="px-5 pt-4">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Title"
            className="h-11 text-base"
          />
        </div>

        <div className="px-5 pt-4">
          <div className="relative" data-color-mode="light">
          <MDEditor value={desc} onChange={(v) => setDesc(v || "")} height={260} preview={isEditingDesc ? "edit" : "preview"} hideToolbar={true} />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="absolute bottom-3 right-3 h-7 gap-1"
              onClick={() => setIsEditingDesc((s) => !s)}
              title={isEditingDesc ? "Preview" : "Edit"}
            >
              <Wand2 className="h-4 w-4" />
              {isEditingDesc ? "Preview" : "Edit"}
            </Button>
          </div>
          {!isEditingDesc && (
            <div className="sr-only">
              <SafeMarkdown content={desc} />
            </div>
          )}
        </div>

        <div className="px-5 pb-4 pt-3">
          <div className="flex flex-wrap gap-2">
            <ProjectSelector
              selectedProject={selectedProject}
              onProjectSelect={handleProjectSelect}
              trigger={(
                <FieldChip
                  icon={<Briefcase className="h-3.5 w-3.5" />}
                  className={selectedProject ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                >
                  {selectedProject ? `${selectedProject.projectName} (${selectedProject.projectDisplayId})` : "Project"}
                </FieldChip>
              )}
            />
            <DateRangePicker
              date={selectedDateRange}
              onDateChange={onDateSelect}
              placeholder="Duration"
              icon={<Calendar className="h-3.5 w-3.5" />}
            />
          </div>
        </div>

        <div className="px-5 py-4 border-t flex items-center justify-end">
          <div className="flex items-center gap-2">
            <Button onClick={handleSave}>Save</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export default CycleCreateInline;
