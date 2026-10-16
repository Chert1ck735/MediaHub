import type { ReactNode } from "react";

type Props = {
  title?: ReactNode;
  note?: ReactNode;
  inset?: boolean;
  className?: string;
  style?: React.CSSProperties;
  children: ReactNode;
};

export function Card({ title, note, inset, className, style, children }: Props) {
  return (
    <div className={`an-card${inset ? " an-card--inset" : ""}${className ? ` ${className}` : ""}`} style={style}>
      {title && (
        <div className="an-card-head">
          <span className="an-card-title">{title}</span>
          {note && <span className="an-card-note">{note}</span>}
        </div>
      )}
      {children}
    </div>
  );
}
