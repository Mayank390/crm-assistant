import * as React from "react";
import Group from "../imports/Group1707484682";

interface LoaderProps {
  size?: "sm" | "md" | "lg";
  text?: string;
}

export function Loader({ size = "md", text }: LoaderProps) {
  const sizeClasses = {
    sm: "w-12 h-12",
    md: "w-20 h-20",
    lg: "w-32 h-32"
  };

  return (
    <div className="flex flex-col items-center justify-center gap-4">
      <div className={sizeClasses[size]}>
        <Group />
      </div>
      {text && (
        <p className="text-gray-400 animate-pulse">
          {text}
        </p>
      )}
    </div>
  );
}
