import Link from "next/link";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

const variants = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-bg-elevated text-text-primary border border-border hover:bg-bg-surface",
  ghost: "text-text-secondary hover:text-text-primary hover:bg-bg-elevated",
};

const sizes = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-base",
};

type SharedProps = {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  className?: string;
  children?: ReactNode;
};

type ButtonProps = SharedProps & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  href?: never;
};

type LinkButtonProps = SharedProps & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "children"> & {
  href: string;
};

export function Button(props: ButtonProps | LinkButtonProps) {
  const { variant = "primary", size = "md", className, children } = props;
  const classes = twMerge(
    clsx(
      "inline-flex items-center justify-center rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
      variants[variant],
      sizes[size],
      className,
    ),
  );

  if ("href" in props && props.href) {
    const { href, ...rest } = props as LinkButtonProps;
    return (
      <Link href={href} className={classes} {...rest}>
        {children}
      </Link>
    );
  }

  const buttonProps = props as ButtonProps;
  return (
    <button className={classes} {...buttonProps}>
      {children}
    </button>
  );
}
