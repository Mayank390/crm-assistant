import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { createMeeting } from "@/api/meetings";
import { toast } from "@/components/ui/use-toast";

interface MeetingCreateInlineProps {
  title: string;
  description?: string;
  meetingStatus?: string;
  meetingType?: string;
  leadId?: string;
  meetingLink?: string;
  onSave?: (meeting: any) => void;
  onDiscard?: () => void;
  className?: string;
}

export const MeetingCreateInline = ({ 
  title, 
  description, 
  meetingStatus, 
  meetingType, 
  leadId, 
  meetingLink, 
  onSave, 
  onDiscard, 
  className 
}: MeetingCreateInlineProps) => {
  const [formData, setFormData] = useState({
    title: title || "",
    description: description || "",
    meetingStatus: meetingStatus || "SCHEDULED",
    meetingType: meetingType || "VIRTUAL",
    meetingLink: meetingLink || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      setSaving(true);
      const created = await createMeeting({
        title: formData.title,
        description: formData.description || undefined,
        meetingStatus: formData.meetingStatus,
        meetingType: formData.meetingType,
        leadId: leadId || undefined,
        meetingLink: formData.meetingLink || undefined,
      });
      toast({ title: "Meeting created", description: "Your meeting has been created successfully." });
      onSave?.(created);
    } catch (e: any) {
      toast({ title: "Failed to create meeting", description: String(e?.message || e), variant: "destructive" as any });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={cn("mt-1", className)}>
      <CardContent className="p-4 space-y-4">
        <div className="space-y-2">
          <Label htmlFor="meeting-title">Meeting Title *</Label>
          <Input
            id="meeting-title"
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            placeholder="Meeting title"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="meeting-description">Description</Label>
          <Textarea
            id="meeting-description"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Meeting description"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="meeting-status">Status</Label>
            <Select value={formData.meetingStatus} onValueChange={(value) => setFormData({ ...formData, meetingStatus: value })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="SCHEDULED">Scheduled</SelectItem>
                <SelectItem value="COMPLETED">Completed</SelectItem>
                <SelectItem value="CANCELLED">Cancelled</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="meeting-type">Type</Label>
            <Select value={formData.meetingType} onValueChange={(value) => setFormData({ ...formData, meetingType: value })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="VIRTUAL">Virtual</SelectItem>
                <SelectItem value="IN_PERSON">In Person</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="meeting-link">Meeting Link</Label>
          <Input
            id="meeting-link"
            value={formData.meetingLink}
            onChange={(e) => setFormData({ ...formData, meetingLink: e.target.value })}
            placeholder="https://..."
          />
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={!formData.title.trim() || saving}>
            {saving ? "Saving..." : "Save Meeting"}
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
