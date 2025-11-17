import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface TaskCardProps {
  name: string;
  description?: string;
  priority?: string;
  taskStatus?: string;
  dueDate?: string;
  className?: string;
}

export const TaskCard = ({ name, description, priority, taskStatus, dueDate, className }: TaskCardProps) => {
  return (
    <Card className={cn("mt-1", className)}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>{name}</span>
          {taskStatus && <Badge variant="secondary">{taskStatus}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
        <div className="flex gap-2">
          {priority && <Badge variant="outline">Priority: {priority}</Badge>}
          {dueDate && <Badge variant="outline">Due: {dueDate}</Badge>}
        </div>
      </CardContent>
    </Card>
  );
};
