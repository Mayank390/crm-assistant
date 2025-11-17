import * as React from "react";
import DatePicker from "react-datepicker";
import { Calendar } from "lucide-react";

import { cn } from "@/lib/utils";

// Export DateRange type for backward compatibility
export type DateRange = {
  from?: Date;
  to?: Date;
};

export interface DateRangePickerProps {
  date?: DateRange | null;
  onDateChange?: (date: DateRange | null) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  icon?: React.ReactNode;
}

export function DateRangePicker({
  date,
  onDateChange,
  placeholder = "Duration",
  className,
  disabled = false,
  icon,
}: DateRangePickerProps) {
  // Convert between different date formats
  const convertToInternalFormat = (input: DateRange | null | undefined) => {
    if (!input) return { start: null, end: null };

    return {
      start: input.from || null,
      end: input.to || null
    };
  };

  const internalDate = convertToInternalFormat(date);

  const [startDate, setStartDate] = React.useState<Date | null>(internalDate.start);
  const [endDate, setEndDate] = React.useState<Date | null>(internalDate.end);

  // Update internal state when external date changes
  React.useEffect(() => {
    const newInternalDate = convertToInternalFormat(date);
    setStartDate(newInternalDate.start);
    setEndDate(newInternalDate.end);
  }, [date]);

  const handleDateChange = (dates: [Date | null, Date | null]) => {
    const [start, end] = dates;
    setStartDate(start);
    setEndDate(end);

    if (start && end) {
      onDateChange?.({ from: start, to: end });
    } else if (!start && !end) {
      onDateChange?.(null);
    }
  };

  const formatDateRange = (): string => {
    if (!date) return placeholder;

    if (!date.from) return placeholder;
    if (date.to) {
      return `${date.from.toLocaleDateString()} - ${date.to.toLocaleDateString()}`;
    }
    return date.from.toLocaleDateString();
  };

  // Custom input component for the date picker trigger
  const CustomInput = React.forwardRef<
    HTMLDivElement,
    React.HTMLProps<HTMLDivElement>
  >(({ onClick }, ref) => (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs text-muted-foreground bg-background cursor-pointer hover:bg-muted/50 hover:border-primary/20 transition-colors",
        !date && "text-muted-foreground",
        date && "text-foreground border-primary/20 bg-primary/5",
        disabled && "cursor-not-allowed opacity-50",
        className
      )}
      onClick={!disabled ? onClick : undefined}
      ref={ref}
    >
      {icon || <Calendar className="h-3.5 w-3.5" />}
      <span className="whitespace-nowrap">{formatDateRange()}</span>
    </div>
  ));

  CustomInput.displayName = "CustomInput";

  return (
    <DatePicker
      selected={startDate}
      onChange={handleDateChange}
      startDate={startDate}
      endDate={endDate}
      selectsRange
      inline={false}
      monthsShown={2}
      showPopperArrow={false}
      customInput={<CustomInput />}
      disabled={disabled}
      calendarClassName="modern-calendar"
      wrapperClassName="date-picker-wrapper"
      popperClassName="date-picker-popper"
      dayClassName={(date) => {
        if (startDate && endDate && date >= startDate && date <= endDate) {
          return "react-datepicker__day--in-range";
        }
        if (startDate && date.getTime() === startDate.getTime()) {
          return "react-datepicker__day--range-start";
        }
        if (endDate && date.getTime() === endDate.getTime()) {
          return "react-datepicker__day--range-end";
        }
        return "";
      }}
    />
  );
}
