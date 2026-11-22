// Minimal inline icons (stroke style, 24x24 viewBox). No icon library needed for ~10 icons.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, className = "size-4", ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      {...props}
    >
      {children}
    </svg>
  );
}

export const PlusIcon = (p: IconProps) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>;
export const PauseIcon = (p: IconProps) => <Icon {...p}><path d="M9 5v14M15 5v14" /></Icon>;
export const PlayIcon = (p: IconProps) => <Icon {...p}><path d="M7 5l12 7-12 7V5z" /></Icon>;
export const PencilIcon = (p: IconProps) => <Icon {...p}><path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4" /></Icon>;
export const TrashIcon = (p: IconProps) => (
  <Icon {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Icon>
);
export const RefreshIcon = (p: IconProps) => (
  <Icon {...p}><path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" /></Icon>
);
export const ArrowLeftIcon = (p: IconProps) => <Icon {...p}><path d="M19 12H5M11 6l-6 6 6 6" /></Icon>;
export const ExternalLinkIcon = (p: IconProps) => (
  <Icon {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" /></Icon>
);
export const CheckIcon = (p: IconProps) => <Icon {...p}><path d="M5 12l5 5L20 7" /></Icon>;
export const SunIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);
export const MoonIcon = (p: IconProps) => <Icon {...p}><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></Icon>;
export const SearchIcon = (p: IconProps) => <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></Icon>;
export const XIcon = (p: IconProps) => <Icon {...p}><path d="M18 6L6 18M6 6l12 12" /></Icon>;
export const AlertIcon = (p: IconProps) => (
  <Icon {...p}><path d="M12 9v4M12 17h.01M10.3 3.9L2 18a2 2 0 001.7 3h16.6a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></Icon>
);
