export function formatRelativeTime(value: string | null | undefined, now = Date.now()) {
  const timestamp = Date.parse(value || "");
  if (!Number.isFinite(timestamp)) return "时间未知";
  const diff = now - timestamp;
  const fmt = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(diff) < 60000) return "刚刚";
  const m = Math.round(diff / 60000);
  if (Math.abs(m) < 60) return fmt.format(-m, "minute");
  const h = Math.round(m / 60);
  if (Math.abs(h) < 24) return fmt.format(-h, "hour");
  return fmt.format(-Math.round(h / 24), "day");
}
