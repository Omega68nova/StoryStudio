import type { ReactNode } from "react";

type RuleIconProps = {
  icon?: string | null;
  label: string;
  fallback?: ReactNode;
  size?: "small" | "medium" | "large";
};

const imageLike = (value: string) =>
  /^(https?:\/\/|\/|data:image\/|blob:)/i.test(value);

export function RuleIcon({
  icon,
  label,
  fallback,
  size = "medium",
}: RuleIconProps) {
  const value = icon?.trim() ?? "";
  const fallbackValue = fallback ?? label.slice(0, 1).toUpperCase();

  return (
    <span
      className={`rule-icon rule-icon-${size} ${value ? "has-icon" : "fallback"}`}
      title={value && !imageLike(value) ? `${label} · icon: ${value}` : label}
      aria-hidden="true"
    >
      {value
        ? imageLike(value)
          ? <img src={value} alt="" />
          : <span className="rule-icon-text">{value.length <= 3 ? value : value.slice(0, 2).toUpperCase()}</span>
        : <span className="rule-icon-text">{fallbackValue}</span>}
    </span>
  );
}
