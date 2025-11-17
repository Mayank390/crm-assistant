import React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import MDEditor from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Calendar, Hash, Users, Tag, CalendarClock, CalendarDays, Shuffle, Boxes, Plus, Wand2, Briefcase } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";
import ProjectSelector from "@/components/ProjectSelector";
import MemberSelector from "@/components/MemberSelector";
import LabelSelector from "@/components/LabelSelector";
import { DateRangePicker, DateRange } from "@/components/ui/date-range-picker";
import { type Project } from "@/api/projects";
import { type ProjectMember } from "@/api/members";
import { type ProjectLabel } from "@/api/labels";
import { type Cycle } from "@/api/cycles";
import { type SubState } from "@/api/substates";
import { type Module } from "@/api/modules";
import CycleSelector from "@/components/CycleSelector";
import SubStateSelector from "@/components/SubStateSelector";
import ModuleSelector from "@/components/ModuleSelector";
import { getAllProjectData, sendProjectDataToConversation } from "@/api/projectData";
import { getBusinessId } from "@/config";

export type WorkItemCreateInlineProps = {
  title?: string;
  description?: string;
  selectedProject?: Project | null;
  selectedAssignees?: ProjectMember[];
  selectedLabels?: ProjectLabel[];
  selectedDateRange?: DateRange;
  selectedCycle?: Cycle | null;
  selectedSubState?: SubState | null;
  selectedModule?: Module | null;
  onProjectSelect?: (project: Project | null) => void;
  onAssigneesSelect?: (assignees: ProjectMember[]) => void;
  onLabelsSelect?: (labels: ProjectLabel[]) => void;
  onDateSelect?: (dateRange: DateRange | undefined) => void;
  onCycleSelect?: (cycle: Cycle | null) => void;
  onSubStateSelect?: (subState: SubState | null) => void;
  onModuleSelect?: (module: Module | null) => void;
  onSave?: (values: { title: string; description: string; project?: Project | null; assignees?: ProjectMember[]; labels?: ProjectLabel[]; cycle?: Cycle | null; subState?: SubState | null; module?: Module | null; startDate?: string; endDate?: string }) => void;
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

export const WorkItemCreateInline: React.FC<WorkItemCreateInlineProps> = ({
  title = "",
  description = "",
  selectedProject = null,
  selectedAssignees = [],
  selectedLabels = [],
  selectedDateRange,
  selectedCycle = null,
  selectedSubState = null,
  selectedModule = null,
  onProjectSelect,
  onAssigneesSelect,
  onLabelsSelect,
  onDateSelect,
  onCycleSelect,
  onSubStateSelect,
  onModuleSelect,
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
    onSave?.({ title: name.trim(), description: desc, project: selectedProject, assignees: selectedAssignees, labels: selectedLabels, cycle: selectedCycle, subState: selectedSubState, module: selectedModule, startDate, endDate });
  };

  const handleProjectSelect = async (project: Project | null) => {
    // Call the original onProjectSelect handler
    onProjectSelect?.(project);

    // If a project is selected, fetch all project data and send to conversation
    if (project) {
      try {
        const projectData = await getAllProjectData(project.projectId);
        const message = await sendProjectDataToConversation(
          projectData,
          project.projectName,
          project.projectDisplayId,
          conversationId
        );
        // Call the callback to notify the parent component
        onProjectDataLoaded?.(message);
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
            {selectedProject ? (
              <SubStateSelector
                projectId={selectedProject.projectId}
                selectedSubState={selectedSubState}
                onSubStateSelect={onSubStateSelect || (() => {})}
                trigger={
                  <FieldChip
                    icon={<Shuffle className="h-3.5 w-3.5" />}
                    className={selectedSubState ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {selectedSubState ? selectedSubState.name : "State"}
                  </FieldChip>
                }
              />
            ) : (
              <FieldChip icon={<Shuffle className="h-3.5 w-3.5" />}>State</FieldChip>
            )}
            {selectedProject && (
              <MemberSelector
                projectId={selectedProject.projectId}
                selectedMembers={selectedAssignees}
                onMembersSelect={onAssigneesSelect || (() => {})}
                mode="multiple"
                title="Select Assignees"
                placeholder="Assignees"
                trigger={
                  <FieldChip
                    icon={<Users className="h-3.5 w-3.5" />}
                    className={selectedAssignees.length > 0 ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {selectedAssignees.length > 0
                      ? `${selectedAssignees.length} assignee${selectedAssignees.length > 1 ? 's' : ''}`
                      : "Assignees"
                    }
                  </FieldChip>
                }
              />
            )}
            {!selectedProject && (
              <FieldChip icon={<Users className="h-3.5 w-3.5" />}>Assignees</FieldChip>
            )}
            {selectedProject ? (
              <LabelSelector
                projectId={selectedProject.projectId}
                selectedLabels={selectedLabels}
                onLabelsSelect={onLabelsSelect || (() => {})}
                mode="multiple"
                title="Select Labels"
                placeholder="Labels"
                trigger={
                  <FieldChip
                    icon={<Tag className="h-3.5 w-3.5" />}
                    className={selectedLabels.length > 0 ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {selectedLabels.length === 0 ? "Labels" :
                     selectedLabels.length === 1 ? selectedLabels[0].label :
                     `${selectedLabels.length} labels`}
                  </FieldChip>
                }
              />
            ) : (
              <FieldChip icon={<Tag className="h-3.5 w-3.5" />}>Labels</FieldChip>
            )}
            <DateRangePicker
              date={selectedDateRange}
              onDateChange={onDateSelect}
              placeholder="Duration"
              icon={<Calendar className="h-3.5 w-3.5" />}
            />
            {selectedProject ? (
              <CycleSelector
                projectId={selectedProject.projectId}
                selectedCycle={selectedCycle}
                onCycleSelect={onCycleSelect || (() => {})}
                trigger={
                  <FieldChip
                    icon={<CalendarClock className="h-3.5 w-3.5" />}
                    className={selectedCycle ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {selectedCycle ? selectedCycle.title : "Cycle"}
                  </FieldChip>
                }
              />
            ) : (
              <FieldChip icon={<CalendarClock className="h-3.5 w-3.5" />}>Cycle</FieldChip>
            )}
            {selectedProject ? (
              <ModuleSelector
                projectId={selectedProject.projectId}
                selectedModule={selectedModule}
                onModuleSelect={onModuleSelect || (() => {})}
                trigger={
                  <FieldChip
                    icon={<Boxes className="h-3.5 w-3.5" />}
                    className={selectedModule ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {selectedModule ? selectedModule.title : "Modules"}
                  </FieldChip>
                }
              />
            ) : (
              <FieldChip icon={<Boxes className="h-3.5 w-3.5" />}>Modules</FieldChip>
            )}
            <FieldChip icon={<Plus className="h-3.5 w-3.5" />}>Add parent</FieldChip>
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

export default WorkItemCreateInline;


