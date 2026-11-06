import React from "react";

type IconProps = { size?: number; className?: string };

const base = (size: number, className: string) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  "aria-hidden": true as const,
  focusable: "false" as const,
  className,
});

/** GitHub's Octocat mark. */
export function GitHubIcon({ size = 16, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="currentColor">
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2.17c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
    </svg>
  );
}

export function DownloadIcon({ size = 16, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  );
}

export function PlayIcon({ size = 16, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="currentColor">
      <path d="M7 4.5v15a.75.75 0 0 0 1.14.64l12-7.5a.75.75 0 0 0 0-1.28l-12-7.5A.75.75 0 0 0 7 4.5Z" />
    </svg>
  );
}

export function HeartIcon({ size = 16, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
      <path d="M12 20.5s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.8a4.3 4.3 0 0 1 7.5 2.7c0 5.4-7.5 10-7.5 10Z" />
    </svg>
  );
}

export function StarIcon({ size = 16, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="currentColor">
      <path d="m12 2.8 2.7 5.7 6.3.8-4.6 4.3 1.2 6.2L12 16.8l-5.6 3 1.2-6.2L3 9.3l6.3-.8L12 2.8Z" />
    </svg>
  );
}

export function CheckIcon({ size = 14, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12.5 4.2 4.2L19 7.5" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 14, className = "" }: IconProps) {
  return (
    <svg {...base(size, className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14m-6-6 6 6-6 6" />
    </svg>
  );
}
