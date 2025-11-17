import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Loader2, Users, Search, Check, Crown, User } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { getProjectMembers, type ProjectMember } from "@/api/members";
import { getCachedMembers } from "@/api/projectData";

export type MemberSelectorProps = {
  projectId: string;
  selectedMembers?: ProjectMember[];
  onMembersSelect: (members: ProjectMember[]) => void;
  trigger?: React.ReactNode;
  className?: string;
  mode?: "single" | "multiple"; // single for lead, multiple for assignees/members
  title?: string;
  placeholder?: string;
  maxSelections?: number; // for multiple mode
};

export const MemberSelector: React.FC<MemberSelectorProps> = ({
  projectId,
  selectedMembers = [],
  onMembersSelect,
  trigger,
  className,
  mode = "multiple",
  title = "Select Members",
  placeholder = "Select members...",
  maxSelections,
}) => {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (open && projectId) {
      loadMembers();
    }
  }, [open, projectId]);

  const loadMembers = async () => {
    setLoading(true);
    try {
      // First check if data is cached
      const cachedMembers = getCachedMembers(projectId);
      if (cachedMembers) {
        setMembers(cachedMembers.data);
        setLoading(false);
        return;
      }

      // If not cached, fetch from API
      const response = await getProjectMembers(projectId);
      setMembers(response.data);
    } catch (error) {
      // Failed to load project members
      setMembers([]);
    } finally {
      setLoading(false);
    }
  };

  const filteredMembers = members.filter(member =>
    member.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    member.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (member.displayName && member.displayName.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const handleMemberToggle = (member: ProjectMember) => {
    if (mode === "single") {
      onMembersSelect([member]);
      setOpen(false);
      return;
    }

    // Multiple mode
    const isSelected = selectedMembers.some(m => m.id === member.id);
    let newSelection: ProjectMember[];

    if (isSelected) {
      newSelection = selectedMembers.filter(m => m.id !== member.id);
    } else {
      if (maxSelections && selectedMembers.length >= maxSelections) {
        return; // Don't allow more selections
      }
      newSelection = [...selectedMembers, member];
    }

    onMembersSelect(newSelection);
  };

  const handleClearSelection = () => {
    onMembersSelect([]);
  };

  const getDisplayName = (member: ProjectMember) => {
    return member.displayName || member.name;
  };

  const getInitials = (member: ProjectMember) => {
    const name = getDisplayName(member);
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  };

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case "ADMIN":
        return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
      case "MEMBER":
        return "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200";
      case "GUEST":
        return "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200";
      default:
        return "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200";
    }
  };

  const getSelectedMembersText = () => {
    if (selectedMembers.length === 0) {
      return mode === "single" ? "Select lead" : placeholder;
    }

    if (mode === "single") {
      return getDisplayName(selectedMembers[0]);
    }

    if (selectedMembers.length === 1) {
      return getDisplayName(selectedMembers[0]);
    }

    return `${selectedMembers.length} selected`;
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className={cn("gap-2", className)}>
            {mode === "single" ? <Crown className="h-4 w-4" /> : <Users className="h-4 w-4" />}
            {getSelectedMembersText()}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {mode === "single" ? <Crown className="h-5 w-5" /> : <Users className="h-5 w-5" />}
            {title}
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder={`Search ${mode === "single" ? "member" : "members"}...`}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          {selectedMembers.length > 0 && (
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
          ) : filteredMembers.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {searchTerm ? "No members found matching your search." : "No members available."}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredMembers.map((member) => {
                const isSelected = selectedMembers.some(m => m.id === member.id);

                return (
                  <Card
                    key={member.id}
                    className={cn(
                      "cursor-pointer transition-colors hover:bg-muted/50",
                      isSelected && "ring-2 ring-primary"
                    )}
                    onClick={() => handleMemberToggle(member)}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {mode === "multiple" && (
                            <Checkbox
                              checked={isSelected}
                              onChange={() => handleMemberToggle(member)}
                              className="mt-0.5"
                            />
                          )}
                          {mode === "single" && isSelected && (
                            <Check className="h-4 w-4 text-primary mt-0.5" />
                          )}
                        </div>

                        <Avatar className="h-10 w-10">
                          <AvatarFallback className="text-sm">
                            {getInitials(member)}
                          </AvatarFallback>
                        </Avatar>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h4 className="font-medium truncate">{getDisplayName(member)}</h4>
                            {mode === "single" && isSelected && (
                              <Check className="h-4 w-4 text-primary flex-shrink-0" />
                            )}
                          </div>

                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-sm text-muted-foreground">{member.email}</span>
                            <Badge className={cn("text-xs", getRoleBadgeColor(member.role))}>
                              {member.role}
                            </Badge>
                          </div>

                          {member.staff && (
                            <div className="text-xs text-muted-foreground">
                              Staff: {member.staff.name}
                            </div>
                          )}
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

export default MemberSelector;
