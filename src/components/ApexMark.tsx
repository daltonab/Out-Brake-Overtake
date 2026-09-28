export function OvertakeLines() {
  return (
    <div className="overtake-lines" aria-label="Abstract racing lines depicting an overtake" role="img">
      <svg viewBox="0 0 420 58" aria-hidden="true">
        <path className="line-muted" d="M5 39C98 39 122 40 182 36S260 23 415 23" />
        <path className="line-active" d="M5 22C104 22 137 24 189 29s79 12 226 12" />
        <path className="line-dash" d="M148 23c18 0 28 2 41 6" />
        <circle className="line-car muted" cx="180" cy="36" r="4" />
        <circle className="line-car active" cx="229" cy="32" r="4" />
      </svg>
    </div>
  )
}
