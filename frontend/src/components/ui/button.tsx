import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control font-semibold " +
    "transition-[background-color,box-shadow,color,transform] duration-150 ease-standard " +
    "active:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent-strong text-on-accent shadow-e1 hover:bg-accent-strong-hover",
        secondary: "border border-border bg-surface text-fg shadow-e1 hover:bg-surface-2",
        soft: "bg-accent-soft text-accent-soft-fg hover:brightness-95",
        ghost: "text-fg-muted hover:bg-surface-2 hover:text-fg",
        danger: "border border-loss/30 bg-loss-soft text-loss-soft-fg hover:brightness-95",
      },
      size: {
        sm: "h-9 px-3 text-small",
        md: "h-11 px-4 text-[14px]",
        icon: "size-11",
        "icon-sm": "size-9",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild, type, ...props }: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...(asChild ? {} : { type: type ?? "button" })}
      {...props}
    />
  );
}
