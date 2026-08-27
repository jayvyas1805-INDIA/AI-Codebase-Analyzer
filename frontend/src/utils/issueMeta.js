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
};

// Issue types where `class_name` holds a whole file path rather than a
// CSS class name — the UI shouldn't prefix these with "." like a class.
export const FILE_LEVEL_ISSUE_TYPES = new Set(["unimported_css_file"]);

export const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };
