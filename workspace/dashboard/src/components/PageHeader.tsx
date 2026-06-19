import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  subtitle?: ReactNode;
  meta?: ReactNode;
};

export default function PageHeader({ title, subtitle, meta }: PageHeaderProps) {
  return (
    <header className="page-header page-header-bis">
      <div className="page-header-bis-row">
        <div className="page-header-bis-text">
          <h2 className="title">{title}</h2>
          {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
        </div>
        {meta ? <div className="page-meta">{meta}</div> : null}
      </div>
    </header>
  );
}
