import type { ReactNode } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
  disabled?: boolean;
}

export interface TabsProps extends Omit<WidgetBaseProps, "label"> {
  label: string;
  tabs: TabItem[];
  activeTabId: string;
  onChange: (tabId: string) => void;
}

export function Tabs({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  tabs,
  activeTabId,
  onChange,
}: TabsProps) {
  const isDisabled = disabled || loading;
  const activeTab = tabs.find((t) => t.id === activeTabId) ?? tabs[0];

  return (
    <div
      className={`widget widget--tabs widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`tabs-${id}`, testId)}
    >
      <span className="widget__label" id={`${id}-label`}>
        {label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div className="widget-tabs">
        <div
          role="tablist"
          aria-labelledby={`${id}-label`}
          aria-describedby={description ? `${id}-desc` : undefined}
          className="widget-tabs__list"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`${id}-tab-${tab.id}`}
              className={`widget-tabs__tab${activeTabId === tab.id ? " widget-tabs__tab--active" : ""}`}
              aria-selected={activeTabId === tab.id}
              aria-controls={`${id}-panel-${tab.id}`}
              disabled={isDisabled || tab.disabled}
              tabIndex={activeTabId === tab.id ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(e) => {
                const idx = tabs.findIndex((t) => t.id === tab.id);
                if (e.key === "ArrowRight" && idx < tabs.length - 1) {
                  e.preventDefault();
                  onChange(tabs[idx + 1].id);
                } else if (e.key === "ArrowLeft" && idx > 0) {
                  e.preventDefault();
                  onChange(tabs[idx - 1].id);
                }
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {activeTab ? (
          <div
            role="tabpanel"
            id={`${id}-panel-${activeTab.id}`}
            aria-labelledby={`${id}-tab-${activeTab.id}`}
            className="widget-tabs__panel"
            tabIndex={0}
          >
            {activeTab.content}
          </div>
        ) : null}
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
