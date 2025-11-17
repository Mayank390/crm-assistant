import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { createNote } from "@/api/notes";
import { toast } from "@/components/ui/use-toast";

interface NoteCreateInlineProps {
  subject: string;
  description: string;
  leadId?: string;
  onSave?: (note: any) => void;
  onDiscard?: () => void;
  className?: string;
}

export const NoteCreateInline = ({ 
  subject, 
  description, 
  leadId, 
  onSave, 
  onDiscard, 
  className 
}: NoteCreateInlineProps) => {
  const [formData, setFormData] = useState({
    subject: subject || "",
    description: description || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      setSaving(true);
      const created = await createNote({
        subject: formData.subject,
        description: formData.description,
        leadId: leadId || undefined,
      });
      toast({ title: "Note created", description: "Your note has been created successfully." });
      onSave?.(created);
    } catch (e: any) {
      toast({ title: "Failed to create note", description: String(e?.message || e), variant: "destructive" as any });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={cn("mt-1", className)}>
      <CardContent className="p-4 space-y-4">
        <div className="space-y-2">
          <Label htmlFor="note-subject">Subject *</Label>
          <Input
            id="note-subject"
            value={formData.subject}
            onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
            placeholder="Note subject"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="note-description">Description *</Label>
          <Textarea
            id="note-description"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Note description"
            rows={5}
          />
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={!formData.subject.trim() || !formData.description.trim() || saving}>
            {saving ? "Saving..." : "Save Note"}
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
