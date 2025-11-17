import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { createTask } from "@/api/tasks";
import { toast } from "@/components/ui/use-toast";

interface TaskCreateInlineProps {
  name: string;
  description?: string;
  priority?: string;
  taskStatus?: string;
  dueDate?: string;
  leadId?: string;
  onSave?: (task: any) => void;
  onDiscard?: () => void;
  className?: string;
}

export const TaskCreateInline = ({ 
  name, 
  description, 
  priority, 
  taskStatus, 
  dueDate, 
  leadId, 
  onSave, 
  onDiscard, 
  className 
}: TaskCreateInlineProps) => {
  const [formData, setFormData] = useState({
    name: name || "",
    description: description || "",
    priority: priority || "MEDIUM",
    taskStatus: taskStatus || "NEW",
    dueDate: dueDate || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      setSaving(true);
      const created = await createTask({
        name: formData.name,
        description: formData.description || undefined,
        priority: formData.priority,
        taskStatus: formData.taskStatus,
        dueDate: formData.dueDate || undefined,
        leadId: leadId || undefined,
      });
      toast({ title: "Task created", description: "Your task has been created successfully." });
      onSave?.(created);
    } catch (e: any) {
      toast({ title: "Failed to create task", description: String(e?.message || e), variant: "destructive" as any });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={cn("mt-1", className)}>
      <CardContent className="p-4 space-y-4">
        <div className="space-y-2">
          <Label htmlFor="task-name">Task Name *</Label>
          <Input
            id="task-name"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="Task name"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="task-description">Description</Label>
          <Textarea
            id="task-description"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Task description"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="task-priority">Priority</Label>
            <Select value={formData.priority} onValueChange={(value) => setFormData({ ...formData, priority: value })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="LOW">Low</SelectItem>
                <SelectItem value="MEDIUM">Medium</SelectItem>
                <SelectItem value="HIGH">High</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-status">Status</Label>
            <Select value={formData.taskStatus} onValueChange={(value) => setFormData({ ...formData, taskStatus: value })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NEW">New</SelectItem>
                <SelectItem value="IN_PROGRESS">In Progress</SelectItem>
                <SelectItem value="COMPLETED">Completed</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={!formData.name.trim() || saving}>
            {saving ? "Saving..." : "Save Task"}
          </Button>
          {onDiscard && (
            <Button variant="outline" onClick={onDiscard}>
              Discard
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
};
