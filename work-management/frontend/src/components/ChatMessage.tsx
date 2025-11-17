import { useEffect, useState } from "react";
import { Bot, User, Copy, ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import SafeMarkdown from "@/components/SafeMarkdown";
import { Button } from "@/components/ui/button";
import { AgentActivity } from "@/components/AgentActivity";
import { usePersonalization } from "@/context/PersonalizationContext";
import { type Project } from "@/api/projects";
import { DateRange } from "@/components/ui/date-range-picker";

interface ChatMessageProps {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  liked?: boolean;
  onLike?: (messageId: string) => void;
  onDislike?: (messageId: string) => void;
  internalActivity?: {
    summary: string;
    bullets?: string[];
    doneLabel?: string;
    body?: string;
  };
  workItem?: {
    title: string;
    description?: string;
    projectIdentifier?: string;
    sequenceId?: string | number;
    link?: string;
  };
  page?: {
    title: string;
    blocks: { blocks: any[] };
  };
  cycle?: {
    title: string;
    description?: string;
    startDate?: string;
    endDate?: string;
  };
  module?: {
    title: string;
    description?: string;
    projectName?: string;
  };
  epic?: {
    title: string;
    description?: string;
    priority?: string;
    state?: string;
    assignee?: string;
    labels?: string[];
    startDate?: string;
    dueDate?: string;
    link?: string;
  };
  conversationId?: string;
}

import WorkItemCreateInline from "@/components/WorkItemCreateInline";
import WorkItemCard from "@/components/WorkItemCard";
import PageCreateInline from "@/components/PageCreateInline";
import PageCard from "@/components/PageCard";
import CycleCreateInline from "@/components/CycleCreateInline";
import CycleCard from "@/components/CycleCard";
import ModuleCreateInline from "@/components/ModuleCreateInline";
import ModuleCard from "@/components/ModuleCard";
import EpicCreateInline from "@/components/EpicCreateInline";
import EpicCard from "@/components/EpicCard";
import { createWorkItem, createWorkItemWithMembers } from "@/api/workitems";
import { createPage } from "@/api/pages";
import { createCycle } from "@/api/cycles";
import { createModule, createModuleWithMembers } from "@/api/modules";
import { createEpic } from "@/api/epics";
import { type ProjectMember } from "@/api/members";
import { type Cycle } from "@/api/cycles";
import { type SubState } from "@/api/substates";
import { type Module } from "@/api/modules";
import { type ProjectLabel } from "@/api/labels";
import { toast } from "@/components/ui/use-toast";
import { getBusinessId, getMemberId } from "@/config";
import { invalidateProjectCache } from "@/api/projectData";

export const ChatMessage = ({ id, role, content, isStreaming = false, liked, onLike, onDislike, internalActivity, workItem, page, cycle, module, epic, conversationId }: ChatMessageProps) => {
  const { settings } = usePersonalization();
  const [displayedContent, setDisplayedContent] = useState("");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [copied, setCopied] = useState(false);
  const canShowActions = role === "assistant" && !isStreaming && (displayedContent?.trim()?.length ?? 0) > 0;
  const [savedWorkItem, setSavedWorkItem] = useState<null | { id: string; title: string; description: string; projectIdentifier?: string; sequenceId?: string | number; link?: string; cycle?: any }>(null);
  const [saving, setSaving] = useState(false);
  const [savedPage, setSavedPage] = useState<null | { id: string; title: string; content: string; link?: string }>(null);
  const [savedCycle, setSavedCycle] = useState<null | { id: string; title: string; description: string; link?: string }>(null);
  const [savedModule, setSavedModule] = useState<null | { id: string; title: string; description: string; link?: string }>(null);
  const [savedEpic, setSavedEpic] = useState<null | { id: string; title: string; description: string; priority?: string | null; state?: string | null; assignee?: string | null; labels?: string[]; link?: string | null }>(null);

  // Module sub-state selection state
  const [selectedModuleSubState, setSelectedModuleSubState] = useState<SubState | null>(null);

  // Cycle selection state
  const [selectedCycle, setSelectedCycle] = useState<any>(null);

  // Project selection state
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  // Member selection state
  const [selectedAssignees, setSelectedAssignees] = useState<ProjectMember[]>([]);
  const [selectedLead, setSelectedLead] = useState<ProjectMember | null>(null);
  const [selectedMembers, setSelectedMembers] = useState<ProjectMember[]>([]);

  // Date range selection state
  const [selectedDateRange, setSelectedDateRange] = useState<DateRange | undefined>();

  // Epic-specific selection state
  const [selectedEpicPriority, setSelectedEpicPriority] = useState<string | null>(epic?.priority ?? null);
  const [selectedEpicState, setSelectedEpicState] = useState<string | null>(epic?.state ?? null);
  const [selectedEpicAssignee, setSelectedEpicAssignee] = useState<ProjectMember | null>(null);
  const [selectedEpicLabels, setSelectedEpicLabels] = useState<ProjectLabel[]>([]);
  const [selectedEpicDateRange, setSelectedEpicDateRange] = useState<DateRange | undefined>(
    epic?.startDate || epic?.dueDate
      ? {
          from: epic?.startDate ? new Date(epic.startDate) : undefined,
          to: epic?.dueDate ? new Date(epic.dueDate) : undefined,
        }
      : undefined
  );

  useEffect(() => {
    if (epic && !savedEpic) {
      setSelectedEpicPriority(epic.priority ?? null);
      setSelectedEpicState(epic.state ?? null);
      setSelectedEpicAssignee(null);
      setSelectedEpicLabels([]);
      setSelectedEpicDateRange(
        epic.startDate || epic.dueDate
          ? {
              from: epic.startDate ? new Date(epic.startDate) : undefined,
              to: epic.dueDate ? new Date(epic.dueDate) : undefined,
            }
          : undefined
      );
    }
  }, [epic, savedEpic]);

  // Sub-state selection state
  const [selectedSubState, setSelectedSubState] = useState<SubState | null>(null);

  // Module selection state
  const [selectedModule, setSelectedModule] = useState<Module | null>(null);

  useEffect(() => {
    if (role === "assistant" && isStreaming) {
      if (currentIndex < content.length) {
        const timeout = setTimeout(() => {
          setDisplayedContent(content.slice(0, currentIndex + 1));
          setCurrentIndex(currentIndex + 1);
        }, 20);
        return () => clearTimeout(timeout);
      }
    } else {
      setDisplayedContent(content);
    }
  }, [content, currentIndex, role, isStreaming]);

  const isUser = role === "user";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // Failed to copy text
    }
  };

  const handleThumbsUp = () => {
    if (isStreaming) return;
    onLike?.(id);
  };

  const handleThumbsDown = () => {
    if (isStreaming) return;
    onDislike?.(id);
  };

  const isLiked = liked === true;
  const isDisliked = liked === false;

  return (
    <div className="p-3 animate-fade-in">
      {isUser ? (
        <div className="flex gap-4 flex-row-reverse">
          <div className="flex-1 text-right">
            <div className="flex justify-end">
              <div className="inline-block max-w-[80%] px-5 py-2 rounded-full text-sm text-foreground leading-relaxed whitespace-pre-wrap bg-primary/10  text-right">
                {displayedContent}
                {isStreaming && currentIndex < content.length && (
                  <span className="inline-block w-1 h-4 ml-1 bg-primary animate-pulse" />
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {settings.showAgentInternals && internalActivity && (
            <AgentActivity
              summary={internalActivity.summary}
              bullets={internalActivity.bullets}
              doneLabel={internalActivity.doneLabel}
              body={internalActivity.body}
              defaultOpen={isStreaming}
              isStreaming={isStreaming}
            />
          )}

          {workItem ? (
            savedWorkItem ? (
              <WorkItemCard
                title={savedWorkItem.title}
                description={savedWorkItem.description}
                projectIdentifier={savedWorkItem.projectIdentifier}
                sequenceId={savedWorkItem.sequenceId}
                cycle={selectedCycle}
                subState={selectedSubState}
                link={savedWorkItem.link}
                className="mt-1"
              />
            ) : (
              <WorkItemCreateInline
                title={workItem.title}
                description={workItem.description}
                selectedProject={selectedProject}
                selectedAssignees={selectedAssignees}
                selectedDateRange={selectedDateRange}
                selectedCycle={selectedCycle}
                selectedSubState={selectedSubState}
                selectedModule={selectedModule}
                onProjectSelect={setSelectedProject}
                onAssigneesSelect={setSelectedAssignees}
                onDateSelect={setSelectedDateRange}
                onCycleSelect={setSelectedCycle}
                onSubStateSelect={setSelectedSubState}
                onModuleSelect={setSelectedModule}
                onSave={async ({ title, description, project, assignees, cycle, subState, module, startDate, endDate }) => {
                  try {
                    setSaving(true);
                    const businessId = getBusinessId();
                    const memberId = getMemberId();
                    const created = await createWorkItemWithMembers({
                      title,
                      description,
                      projectId: project?.projectId,
                      projectIdentifier: workItem.projectIdentifier,
                      cycleId: cycle?.id,
                      subStateId: subState?.id,
                      moduleId: module?.id,
                      assignees: assignees?.map(a => ({ id: a.id, name: a.displayName || a.name })),
                      labels: [], // Empty labels for now, can be added later
                      startDate,
                      endDate,
                      createdBy: { id: memberId, name: "" }
                    });
                    setSavedWorkItem(created);

                    // Invalidate cache for the project since new data was created
                    if (project?.projectId) {
                      invalidateProjectCache(project.projectId);
                    }

                    toast({ title: "Work item saved", description: "Your work item has been created." });
                  } catch (e: any) {
                    toast({ title: "Failed to save work item", description: String(e?.message || e), variant: "destructive" as any });
                  } finally {
                    setSaving(false);
                  }
                }}
                onDiscard={() => { /* no-op for now */ }}
                className="mt-1"
                conversationId={conversationId}
                onProjectDataLoaded={(message) => {
                  // Send the project data loaded message via WebSocket
                  if (conversationId && (window as any).chatSocket) {
                    (window as any).chatSocket.send({
                      message: message,
                      conversation_id: conversationId,
                    });
                  }
                }}
              />
            )
          ) : page ? (
            savedPage ? (
              <PageCard
                title={savedPage.title}
                content={savedPage.content}
                link={savedPage.link}
                className="mt-1"
              />
            ) : (
              <PageCreateInline
                initialEditorJs={page.blocks}
                selectedProject={selectedProject}
                onProjectSelect={setSelectedProject}
                onSave={async ({ title, editorJs, project }) => {
                  try {
                    setSaving(true);
                    const businessId = getBusinessId();
                    const memberId = getMemberId();
                    const created = await createPage({
                      title: title || "Untitled Page",
                      content: editorJs,
                      projectId: project?.projectId,
                      createdBy: { id: memberId, name: "" }
                    });
                    setSavedPage(created);

                    // Invalidate cache for the project since new data was created
                    if (project?.projectId) {
                      invalidateProjectCache(project.projectId);
                    }

                    toast({ title: "Page saved", description: "Your page has been created." });
                  } catch (e: any) {
                    toast({ title: "Failed to save page", description: String(e?.message || e), variant: "destructive" as any });
                  } finally {
                    setSaving(false);
                  }
                }}
                onDiscard={() => { /* no-op for now */ }}
                className="mt-1"
              />
            )
          ) : cycle ? (
            savedCycle ? (
              <CycleCard
                title={savedCycle.title}
                description={savedCycle.description}
                link={savedCycle.link}
                className="mt-1"
              />
            ) : (
              <CycleCreateInline
                title={cycle.title}
                description={cycle.description}
                selectedProject={selectedProject}
                selectedDateRange={selectedDateRange}
                onProjectSelect={setSelectedProject}
                onDateSelect={setSelectedDateRange}
                onSave={async ({ title, description, project, startDate, endDate }) => {
                  try {
                    setSaving(true);
                    const created = await createCycle({
                      title,
                      description,
                      projectId: project?.projectId,
                      startDate: startDate || cycle.startDate,
                      endDate: endDate || cycle.endDate
                    });
                    setSavedCycle(created);

                    // Invalidate cache for the project since new data was created
                    if (project?.projectId) {
                      invalidateProjectCache(project.projectId);
                    }

                    toast({ title: "Cycle saved", description: "Your cycle has been created." });
                  } catch (e: any) {
                    toast({ title: "Failed to save cycle", description: String(e?.message || e), variant: "destructive" as any });
                  } finally {
                    setSaving(false);
                  }
                }}
                onDiscard={() => { /* no-op for now */ }}
                className="mt-1"
                conversationId={conversationId}
                onProjectDataLoaded={(message) => {
                  // Send the project data loaded message via WebSocket
                  if (conversationId && (window as any).chatSocket) {
                    (window as any).chatSocket.send({
                      message: message,
                      conversation_id: conversationId,
                    });
                  }
                }}
              />
            )
          ) : module ? (
            savedModule ? (
              <ModuleCard
                title={savedModule.title}
                description={savedModule.description}
                subState={selectedModuleSubState}
                link={savedModule.link}
                className="mt-1"
              />
            ) : (
              <ModuleCreateInline
                title={module.title}
                description={module.description}
                selectedProject={selectedProject}
                selectedLead={selectedLead}
                selectedMembers={selectedMembers}
                selectedDateRange={selectedDateRange}
                selectedSubState={selectedModuleSubState}
                onProjectSelect={setSelectedProject}
                onLeadSelect={setSelectedLead}
                onMembersSelect={setSelectedMembers}
                onDateSelect={setSelectedDateRange}
                onSubStateSelect={setSelectedModuleSubState}
                onSave={async ({ title, description, project, lead, members, subState, startDate, endDate }) => {
                  try {
                    setSaving(true);
                    const created = await createModuleWithMembers({
                      title,
                      description,
                      projectId: project?.projectId,
                      subStateId: subState?.id,
                      lead,
                      members: members?.map(m => ({ id: m.id, name: m.displayName || m.name })),
                      startDate,
                      endDate
                    });
                    setSavedModule(created);

                    // Invalidate cache for the project since new data was created
                    if (project?.projectId) {
                      invalidateProjectCache(project.projectId);
                    }

                    toast({ title: "Module saved", description: "Your module has been created." });
                  } catch (e: any) {
                    toast({ title: "Failed to save module", description: String(e?.message || e), variant: "destructive" as any });
                  } finally {
                    setSaving(false);
                  }
                }}
                onDiscard={() => { /* no-op for now */ }}
                className="mt-1"
                conversationId={conversationId}
                onProjectDataLoaded={(message) => {
                  // Send the project data loaded message via WebSocket
                  if (conversationId && (window as any).chatSocket) {
                    (window as any).chatSocket.send({
                      message: message,
                      conversation_id: conversationId,
                    });
                  }
                }}
              />
            )
          ) : epic ? (
            savedEpic ? (
              <EpicCard
                title={savedEpic.title}
                description={savedEpic.description}
                priority={savedEpic.priority ?? epic.priority}
                state={savedEpic.state ?? epic.state}
                assigneeName={savedEpic.assignee ?? epic.assignee}
                labels={savedEpic.labels ?? epic.labels ?? []}
                link={savedEpic.link ?? epic.link}
                className="mt-1"
              />
            ) : (
              <EpicCreateInline
                title={epic.title}
                description={epic.description}
                selectedProject={selectedProject}
                selectedPriority={selectedEpicPriority}
                selectedState={selectedEpicState}
                selectedAssignee={selectedEpicAssignee}
                selectedLabels={selectedEpicLabels}
                selectedDateRange={selectedEpicDateRange}
                onProjectSelect={setSelectedProject}
                onPrioritySelect={setSelectedEpicPriority}
                onStateSelect={setSelectedEpicState}
                onAssigneeSelect={setSelectedEpicAssignee}
                onLabelsSelect={setSelectedEpicLabels}
                onDateSelect={setSelectedEpicDateRange}
                onSave={async ({ title, description, project, priority, state, assignee, labels, startDate, dueDate }) => {
                  try {
                    setSaving(true);
                    const labelNames = labels?.map((label) => label.label).filter(Boolean) ?? [];
                    const created = await createEpic({
                      title,
                      description,
                      projectId: project?.projectId,
                      priority: priority ?? undefined,
                      stateName: state ?? undefined,
                      assigneeName: assignee ? (assignee.displayName || assignee.name) : undefined,
                      labels: labelNames.length ? labelNames : undefined,
                      startDate,
                      dueDate,
                      createdBy: getMemberId(),
                    });

                    setSavedEpic({
                      id: created.id,
                      title: created.title,
                      description: created.description,
                      priority: priority ?? created.priority ?? null,
                      state: state ?? created.state ?? null,
                      assignee: assignee ? assignee.displayName || assignee.name : null,
                      labels: labelNames,
                      link: created.link ?? null,
                    });

                    if (project?.projectId) {
                      invalidateProjectCache(project.projectId);
                    }

                    toast({ title: "Epic saved", description: "Your epic has been created." });
                  } catch (e: any) {
                    toast({ title: "Failed to save epic", description: String(e?.message || e), variant: "destructive" as any });
                  } finally {
                    setSaving(false);
                  }
                }}
                onDiscard={() => { /* no-op for now */ }}
                className="mt-1"
                conversationId={conversationId}
                onProjectDataLoaded={(message) => {
                  if (conversationId && (window as any).chatSocket) {
                    (window as any).chatSocket.send({
                      message: message,
                      conversation_id: conversationId,
                    });
                  }
                }}
              />
            )
          ) : (
            <SafeMarkdown
              content={displayedContent}
              className="prose prose-sm max-w-none dark:prose-invert prose-headings:text-foreground prose-p:text-foreground prose-strong:text-foreground prose-li:text-foreground"
            />
          )}
          {isStreaming && currentIndex < content.length && (
            <span className="inline-block w-1 h-4 ml-1 bg-primary animate-pulse" />
          )}

          {/* Action buttons for assistant messages */}
          {canShowActions && (
            <div className="flex items-center gap-1 pt-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className={cn(
                  "h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-primary/10 transition-all duration-200 rounded-md",
                  copied && "text-green-600 bg-green-600/10"
                )}
              >
                <Copy className="h-4 w-4" />
              </Button>

              <Button
                variant="ghost"
                size="sm"
                onClick={handleThumbsUp}
                className={cn(
                  "h-8 px-2 transition-all duration-200 rounded-md",
                  isLiked
                    ? "text-green-600 hover:text-green-700 bg-green-600/10"
                    : "text-muted-foreground hover:text-foreground hover:bg-primary/10"
                )}
              >
                <ThumbsUp className={cn("h-4 w-4", isLiked && "fill-current")} />
              </Button>

              <Button
                variant="ghost"
                size="sm"
                onClick={handleThumbsDown}
                className={cn(
                  "h-8 px-2 transition-all duration-200 rounded-md",
                  isDisliked
                    ? "text-red-600 hover:text-red-700 bg-red-600/10"
                    : "text-muted-foreground hover:text-foreground hover:bg-primary/10"
                )}
              >
                <ThumbsDown className={cn("h-4 w-4", isDisliked && "fill-current")} />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
