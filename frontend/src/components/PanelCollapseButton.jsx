import React from "react";

export default function PanelCollapseButton({ collapsed, onToggle }) {
  return (
    <button
      type="button"
      className="panel-toggle-button"
      onClick={onToggle}
      aria-expanded={!collapsed}
    >
      {collapsed ? "展开" : "折叠"}
    </button>
  );
}
