/**
 * Keep the first few ETA readings visible without forcing a long, scrollable
 * list into the initial route comparison. The complete list is one click away.
 */
export const DEFAULT_CHECKPOINT_PREVIEW = 5;

export function checkpointView(
  checkpoints,
  expanded = false,
  preview = DEFAULT_CHECKPOINT_PREVIEW,
) {
  const items = Array.isArray(checkpoints) ? checkpoints : [];
  const count =
    Number.isInteger(preview) && preview > 0
      ? preview
      : DEFAULT_CHECKPOINT_PREVIEW;
  return {
    items: expanded ? items : items.slice(0, count),
    total: items.length,
    hidden: expanded ? 0 : Math.max(0, items.length - count),
  };
}
