export type DisplayZone = 'UTC' | 'Central'

export function formatTime(iso: string, zone: DisplayZone): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: zone === 'UTC' ? 'UTC' : 'America/Chicago',
    year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  }).format(new Date(iso))
}

export function minuteInputToUtc(value: string): string {
  return `${value}:00Z`
}
