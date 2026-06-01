import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  subtitle?: ReactNode;
  meta?: ReactNode;
};

export default function PageHeader({ title, subtitle, meta }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h2 className="title">{title}</h2>
      {subtitle ? <p className="muted page-subtitle">{subtitle}</p> : null}
      {meta ? <div className="page-meta">{meta}</div> : null}
    </header>
  );
}
