import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

interface MeetingCardProps {
  title: string;
  description?: string;
  meetingStatus?: string;
  meetingType?: string;
  meetingLink?: string;
  className?: string;
}

export const MeetingCard = ({ title, description, meetingStatus, meetingType, meetingLink, className }: MeetingCardProps) => {
  return (
    <Card className={cn("mt-1", className)}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>{title}</span>
          {meetingStatus && <Badge variant="secondary">{meetingStatus}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
        <div className="flex gap-2">
          {meetingType && <Badge variant="outline">Type: {meetingType}</Badge>}
        </div>
        {meetingLink && (
          <a href={meetingLink} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline flex items-center gap-1">
            <ExternalLink className="h-3 w-3" />
            Meeting Link
          </a>
        )}
      </CardContent>
    </Card>
  );
};
