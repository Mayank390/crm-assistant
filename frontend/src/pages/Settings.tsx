import { usePersonalization } from "@/context/PersonalizationContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Lock, AlertCircle } from "lucide-react";

const Settings = () => {
  const { settings, updateSettings, resetSettings } = usePersonalization();

  return (
    <div className="min-h-screen w-full flex items-start justify-center pt-0 pb-5">
      <div className="w-full max-w-3xl space-y-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">AI Agent Personalization</h1>
          <p className="text-sm text-muted-foreground">Control how the agent remembers and responds, and provide context it can learn from.</p>
        </div>

        <Card>
          <CardHeader className="pb-3 md:p-6 p-4">
            <CardTitle>Memory</CardTitle>
            <CardDescription>Choose whether your agent should retain context across sessions.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 md:p-6 p-4 pt-0">
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="remember">Remember context</Label>
                <p className="text-xs text-muted-foreground">Enable to let the agent learn from your saved context.</p>
              </div>
              <Switch id="remember" checked={settings.rememberLongTermContext} onCheckedChange={(checked) => updateSettings({ rememberLongTermContext: checked })} />
            </div>
          </CardContent>
        </Card>

        <Card className={`relative ${!settings.rememberLongTermContext ? "bg-muted/30 border-dashed" : ""}`}>
          {!settings.rememberLongTermContext && (
            <div className="absolute inset-0 bg-background/80 backdrop-blur-[1px] z-10 flex items-center justify-center rounded-lg">
              <div className="flex items-center gap-2 px-4 py-2 bg-muted rounded-md border text-sm text-muted-foreground">
                <Lock className="h-4 w-4" />
                <span>Enable memory to access</span>
              </div>
            </div>
          )}
          <CardHeader className={`pb-3 md:p-6 p-4 ${!settings.rememberLongTermContext ? "opacity-50" : ""}`}>
            <div className="flex items-center gap-2">
              <CardTitle className={!settings.rememberLongTermContext ? "text-muted-foreground" : ""}>
                 Context
              </CardTitle>
              {!settings.rememberLongTermContext && (
                <div className="flex items-center gap-1 px-2 py-1 bg-muted/50 rounded-full text-xs text-muted-foreground">
                  <AlertCircle className="h-3 w-3" />
                  Disabled
                </div>
              )}
            </div>
            <CardDescription className={!settings.rememberLongTermContext ? "text-muted-foreground" : ""}>
              {!settings.rememberLongTermContext
                ? "Enable memory above to provide context for the agent."
                : "Provide background, preferences, team norms, or CRM details the agent should consider."
              }
            </CardDescription>
          </CardHeader>
          <CardContent className={`space-y-3 md:p-6 p-4 pt-0 ${!settings.rememberLongTermContext ? "opacity-50" : ""}`}>
            <Textarea
              value={settings.longTermContext}
              onChange={(e) => updateSettings({ longTermContext: e.target.value })}
              placeholder={!settings.rememberLongTermContext ? "Enable memory to edit context..." : "e.g., Our team focuses on B2B sales; we prioritize leads from tech companies; follow-up calls should be scheduled within 24 hours; tone should be professional and consultative."}
              className="min-h-[120px]"
              disabled={!settings.rememberLongTermContext}
            />
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => updateSettings({ longTermContext: "" })}
                disabled={!settings.rememberLongTermContext}
              >
                Clear
              </Button>
              <Button
                variant="outline"
                onClick={resetSettings}
                disabled={!settings.rememberLongTermContext}
              >
                Reset all
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3 md:p-6 p-4">
            <CardTitle>Response Style</CardTitle>
            <CardDescription>Control the tone and style of the agent's responses.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 md:p-6 p-4 pt-0">
            <div className="space-y-2">
              <Label>Response Tone</Label>
              <Select value={settings.responseTone} onValueChange={(value: any) => updateSettings({ responseTone: value })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="professional">Professional</SelectItem>
                  <SelectItem value="friendly">Friendly</SelectItem>
                  <SelectItem value="concise">Concise</SelectItem>
                  <SelectItem value="detailed">Detailed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Domain Focus</Label>
              <Select value={settings.domainFocus} onValueChange={(value: any) => updateSettings({ domainFocus: value })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general">General</SelectItem>
                  <SelectItem value="sales">Sales</SelectItem>
                  <SelectItem value="customer_service">Customer Service</SelectItem>
                  <SelectItem value="marketing">Marketing</SelectItem>
                  <SelectItem value="management">Management</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Settings;
