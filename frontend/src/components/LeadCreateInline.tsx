import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { createLead } from "@/api/leads";
import { toast } from "@/components/ui/use-toast";

interface LeadCreateInlineProps {
  name: string;
  email?: string;
  mobile?: string;
  leadStatus?: string;
  referenceNo?: string;
  onSave?: (lead: any) => void;
  onDiscard?: () => void;
  className?: string;
}

export const LeadCreateInline = ({ 
  name, 
  email, 
  mobile, 
  leadStatus, 
  referenceNo, 
  onSave, 
  onDiscard, 
  className 
}: LeadCreateInlineProps) => {
  const [formData, setFormData] = useState({
    name: name || "",
    email: email || "",
    mobile: mobile || "",
    leadStatus: leadStatus || "New",
    referenceNo: referenceNo || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      setSaving(true);
      const created = await createLead({
        name: formData.name,
        email: formData.email || undefined,
        mobile: formData.mobile || undefined,
        leadStatus: formData.leadStatus,
        referenceNo: formData.referenceNo || undefined,
      });
      toast({ title: "Lead created", description: "Your lead has been created successfully." });
      onSave?.(created);
    } catch (e: any) {
      toast({ title: "Failed to create lead", description: String(e?.message || e), variant: "destructive" as any });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={cn("mt-1", className)}>
      <CardContent className="p-4 space-y-4">
        <div className="space-y-2">
          <Label htmlFor="lead-name">Name *</Label>
          <Input
            id="lead-name"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="Lead name"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="lead-email">Email</Label>
          <Input
            id="lead-email"
            type="email"
            value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            placeholder="email@example.com"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="lead-mobile">Mobile</Label>
          <Input
            id="lead-mobile"
            value={formData.mobile}
            onChange={(e) => setFormData({ ...formData, mobile: e.target.value })}
            placeholder="+1234567890"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="lead-status">Status</Label>
          <Select value={formData.leadStatus} onValueChange={(value) => setFormData({ ...formData, leadStatus: value })}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="New">New</SelectItem>
              <SelectItem value="Contacted">Contacted</SelectItem>
              <SelectItem value="Qualified">Qualified</SelectItem>
              <SelectItem value="Converted">Converted</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={!formData.name.trim() || saving}>
            {saving ? "Saving..." : "Save Lead"}
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
