export const SEVERITY_META = {
  high: { label: "High" },
  medium: { label: "Medium" },
  low: { label: "Low" },
};

export const ISSUE_TYPE_META = {
  css_conflict: { label: "CSS Conflict", short: "Conflict" },
  partial_overlap_class: { label: "Partial Overlap", short: "Partial overlap" },
  duplicate_class: { label: "Duplicate Class", short: "Duplicate" },
  unused_css_class: { label: "Unused CSS Class", short: "Unused" },
  undefined_css_class: { label: "Undefined CSS Class", short: "Undefined" },
  unimported_css_file: { label: "Unimported CSS File", short: "Unimported file" },
  tailwind_utility_conflict: { label: "Tailwind Utility Conflict", short: "Tailwind conflict" },
};

// Issue types where `class_name` holds something other than a single CSS
// class name (a whole file path, or — for Tailwind conflicts — a list of
// colliding utility classes) — the UI shouldn't prefix these with "." like
// a plain class name.
export const FILE_LEVEL_ISSUE_TYPES = new Set(["unimported_css_file", "tailwind_utility_conflict"]);

export const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };