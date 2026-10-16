export function RefreshIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <path d="M13.2 7.2a5.2 5.2 0 1 0-.55 3.1" />
        <polyline points="13.4,3.2 13.4,7.2 9.4,7.2" strokeLinejoin="round" />
      </g>
    </svg>
  );
}
