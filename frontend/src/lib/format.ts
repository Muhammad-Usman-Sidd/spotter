const clockFormat = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const dateTimeFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatMiles(miles: number): string {
  return miles.toFixed(1);
}

export function formatDuration(minutes: number): string {
  const whole = Math.round(minutes);
  const hours = Math.floor(whole / 60);
  const remainder = whole % 60;
  return `${hours}h ${remainder.toString().padStart(2, '0')}m`;
}

export function formatClock(iso: string): string {
  return clockFormat.format(new Date(iso));
}

export function formatDateTime(date: Date): string {
  return dateTimeFormat.format(date);
}

export function formatOffset(hours: number): string {
  const totalMinutes = Math.round(hours * 60);
  const wholeHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `+${wholeHours}h ${minutes.toString().padStart(2, '0')}m`;
}

export function toLocalInputValue(date: Date): string {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function nextFullHour(from: Date = new Date()): Date {
  const next = new Date(from);
  next.setMinutes(0, 0, 0);
  next.setHours(next.getHours() + 1);
  return next;
}
