import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface NoteCardProps {
  subject: string;
  description: string;
  className?: string;
}

export const NoteCard = ({ subject, description, className }: NoteCardProps) => {
  return (
    <Card className={cn("mt-1", className)}>
      <CardHeader>
        <CardTitle>{subject}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
};
