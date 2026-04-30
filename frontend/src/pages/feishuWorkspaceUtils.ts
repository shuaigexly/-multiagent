export function formatDateTime(value: string | null | undefined) {
  if (!value) return null;
  const normalized = value.trim();
  if (!normalized) return null;
  const ts = Number(normalized);
  if (!Number.isFinite(ts) || ts <= 0) return null;
  return new Date(ts * 1000);
}

export function formatCalendarRange(start: string | null | undefined, end: string | null | undefined) {
  const startDate = formatDateTime(start);
  const endDate = formatDateTime(end);
  if (!startDate || !endDate) return "时间未知";

  const datePart = startDate.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
  const startPart = startDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const endPart = endDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  return `${datePart} ${startPart} – ${endPart}`;
}

export function formatDisplayTime(value: string | null | undefined) {
  const date = formatDateTime(value);
  if (!date) return null;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
