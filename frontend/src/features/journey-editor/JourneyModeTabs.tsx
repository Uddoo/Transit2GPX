type JourneyModeTabsProps = {
  mode: "metro" | "rail";
  onChange: (mode: "metro" | "rail") => void;
};

export function JourneyModeTabs({ mode, onChange }: JourneyModeTabsProps) {
  return (
    <div className="journey-mode-tabs" role="tablist" aria-label="交通方式">
      <button
        aria-selected={mode === "metro"}
        className={mode === "metro" ? "is-active" : undefined}
        onClick={() => onChange("metro")}
        role="tab"
        type="button"
      >
        地铁
      </button>
      <button
        aria-selected={mode === "rail"}
        className={mode === "rail" ? "is-active" : undefined}
        onClick={() => onChange("rail")}
        role="tab"
        type="button"
      >
        铁路 / 高铁
      </button>
    </div>
  );
}
