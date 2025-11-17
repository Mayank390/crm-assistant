import React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { DateRangePicker, DateRange } from "@/components/ui/date-range-picker";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import MDEditor from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import { Briefcase, Calendar, Flag, User, Wand2, Tag } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";
import ProjectSelector from "@/components/ProjectSelector";
import MemberSelector from "@/components/MemberSelector";
import LabelSelector from "@/components/LabelSelector";
import { type Project } from "@/api/projects";
import { type ProjectMember } from "@/api/members";
import { type ProjectLabel } from "@/api/labels";
import { getAllProjectData, sendProjectDataToConversation } from "@/api/projectData";

export type EpicCreateInlineProps = {
  title?: string;
  description?: string;
  selectedProject?: Project | null;
  selectedPriority?: string | null;
  selectedState?: string | null;
  selectedAssignee?: ProjectMember | null;
  selectedLabels?: ProjectLabel[];
  selectedDateRange?: DateRange;
  onProjectSelect?: (project: Project | null) => void;
  onPrioritySelect?: (priority: string | null) => void;
  onStateSelect?: (state: string | null) => void;
  onAssigneeSelect?: (member: ProjectMember | null) => void;
  onLabelsSelect?: (labels: ProjectLabel[]) => void;
  onDateSelect?: (dateRange: DateRange | undefined) => void;
  onSave?: (values: {
    title: string;
    description: string;
    project?: Project | null;
    priority?: string | null;
    state?: string | null;
    assignee?: ProjectMember | null;
    labels?: ProjectLabel[];
    startDate?: string;
    dueDate?: string;
  }) => void;
  onDiscard?: () => void;
  className?: string;
  conversationId?: string;
  onProjectDataLoaded?: (message: string) => void;
};

const PRIORITY_OPTIONS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"];
const STATE_OPTIONS = ["BACKLOG", "PLANNED", "IN_PROGRESS", "COMPLETE"];

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

export const EpicCreateInline: React.FC<EpicCreateInlineProps> = ({
  title = "",
  description = "",
  selectedProject = null,
  selectedPriority = null,
  selectedState = null,
  selectedAssignee = null,
  selectedLabels = [],
  selectedDateRange,
  onProjectSelect,
  onPrioritySelect,
  onStateSelect,
  onAssigneeSelect,
  onLabelsSelect,
  onDateSelect,
  onSave,
  onDiscard,
  className,
  conversationId,
  onProjectDataLoaded
}) => {
  const [name, setName] = React.useState<string>(title);
  const [desc, setDesc] = React.useState<string>(description);
  const [priority, setPriority] = React.useState<string | null>(selectedPriority ?? null);
  const [state, setState] = React.useState<string | null>(selectedState ?? null);
  const [assignee, setAssignee] = React.useState<ProjectMember | null>(selectedAssignee ?? null);
  const [labels, setLabels] = React.useState<ProjectLabel[]>(selectedLabels ?? []);
  const [isEditingDesc, setIsEditingDesc] = React.useState<boolean>(true);

  const handleSave = () => {
    const startDate = selectedDateRange?.from?.toISOString().split("T")[0];
    const endDate = selectedDateRange?.to?.toISOString().split("T")[0];
    onSave?.({
      title: name.trim(),
      description: desc,
      project: selectedProject,
      priority,
      state,
      assignee,
      labels,
      startDate,
      dueDate: endDate,
    });
  };

  const handleProjectSelect = async (project: Project | null) => {
    onProjectSelect?.(project);

    if (project && conversationId) {
      try {
        const projectData = await getAllProjectData(project.projectId);
        const message = await sendProjectDataToConversation(
          projectData,
          project.projectName,
          project.projectDisplayId,
          conversationId
        );
        onProjectDataLoaded?.(message);
      } catch {
        // ignore errors fetching project data
      }
    }
  };

  const handlePrioritySelect = (value: string | null) => {
    setPriority(value);
    onPrioritySelect?.(value);
  };

  const handleStateSelect = (value: string | null) => {
    setState(value);
    onStateSelect?.(value);
  };

  const handleAssigneeSelect = (member: ProjectMember | null) => {
    setAssignee(member);
    onAssigneeSelect?.(member ?? null);
  };

  const handleLabelsSelect = (nextLabels: ProjectLabel[]) => {
    setLabels(nextLabels);
    onLabelsSelect?.(nextLabels);
  };

  return (
    <Card className={cn("border-muted/70", className)}>
      <CardContent className="p-0">
        <div className="px-5 pt-4">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Epic title"
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
              trigger={(<FieldChip icon={<Briefcase className="h-3.5 w-3.5" />} className={selectedProject ? "text-foreground border-primary/20 bg-primary/5" : undefined}>{selectedProject ? `${selectedProject.projectName} (${selectedProject.projectDisplayId})` : "Project"}</FieldChip>)}
            />

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <FieldChip
                  icon={<Flag className="h-3.5 w-3.5" />}
                  className={priority ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                >
                  {priority ?? "Priority"}
                </FieldChip>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-40">
                <DropdownMenuItem onSelect={(ev) => { ev.preventDefault(); handlePrioritySelect(null); }} className="text-xs text-muted-foreground">Clear</DropdownMenuItem>
                {PRIORITY_OPTIONS.map((option) => (
                  <DropdownMenuItem
                    key={option}
                    onSelect={(ev) => {
                      ev.preventDefault();
                      handlePrioritySelect(option);
                    }}
                    className={cn("text-xs", priority === option && "font-semibold text-primary")}
                  >
                    {option}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <FieldChip
                  icon={<Tag className="h-3.5 w-3.5" />}
                  className={state ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                >
                  {state ?? "State"}
                </FieldChip>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-40">
                <DropdownMenuItem onSelect={(ev) => { ev.preventDefault(); handleStateSelect(null); }} className="text-xs text-muted-foreground">Clear</DropdownMenuItem>
                {STATE_OPTIONS.map((option) => (
                  <DropdownMenuItem
                    key={option}
                    onSelect={(ev) => {
                      ev.preventDefault();
                      handleStateSelect(option);
                    }}
                    className={cn("text-xs", state === option && "font-semibold text-primary")}
                  >
                    {option}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {selectedProject ? (
              <MemberSelector
                projectId={selectedProject.projectId}
                selectedMembers={assignee ? [assignee] : []}
                onMembersSelect={(members) => handleAssigneeSelect(members[0] ?? null)}
                mode="single"
                title="Select Owner"
                placeholder="Assignee"
                trigger={(
                  <FieldChip
                    icon={<User className="h-3.5 w-3.5" />}
                    className={assignee ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {assignee ? assignee.displayName || assignee.name : "Assignee"}
                  </FieldChip>
                )}
              />
            ) : (
              <FieldChip icon={<User className="h-3.5 w-3.5" />}>Assignee</FieldChip>
            )}

            {selectedProject ? (
              <LabelSelector
                projectId={selectedProject.projectId}
                selectedLabels={labels}
                onLabelsSelect={handleLabelsSelect}
                mode="multiple"
                title="Select Labels"
                placeholder="Labels"
                trigger={(
                  <FieldChip
                    icon={<Tag className="h-3.5 w-3.5" />}
                    className={labels.length > 0 ? "text-foreground border-primary/20 bg-primary/5" : undefined}
                  >
                    {labels.length === 0 ? "Labels" : labels.length === 1 ? labels[0].label : `${labels.length} labels`}
                  </FieldChip>
                )}
              />
            ) : (
              <FieldChip icon={<Tag className="h-3.5 w-3.5" />}>Labels</FieldChip>
            )}

            <DateRangePicker
              date={selectedDateRange}
              onDateChange={onDateSelect}
              placeholder="Timeline"
              icon={<Calendar className="h-3.5 w-3.5" />}
            />
          </div>
        </div>

        <div className="px-5 py-4 border-t flex items-center justify-end">
          <div className="flex items-center gap-2">
            {onDiscard && (
              <Button variant="ghost" onClick={onDiscard}>Discard</Button>
            )}
            <Button onClick={handleSave}>Save</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export default EpicCreateInline;

