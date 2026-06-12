/**
 * HUD for the Forest Creation demo: phase title card, live stats + event
 * ticker, current-query chip, and the bottom playback bar with an
 * event-marked scrubber.
 */

const SPEEDS = [0.5, 1, 2, 4];

export default function DemoHud({
  hud,
  isPlaying,
  speed,
  totalDuration,
  ticks,
  onTogglePlay,
  onSetSpeed,
  onScrub,
  onExit,
}) {
  const pct = (hud.time / totalDuration) * 100;

  return (
    <>
      {/* Phase title card */}
      {hud.phase && (
        <div className="demo-phase" key={hud.phase.title}>
          <div className="demo-phase-title">{hud.phase.title}</div>
          <div className="demo-phase-sub">{hud.phase.subtitle}</div>
        </div>
      )}

      {/* Stats + event ticker */}
      <div className="demo-panel">
        <div className="demo-panel-header">Nzyme — Regulatory Intel</div>
        <div className="demo-stats">
          <div className="demo-stat">
            <span className="demo-stat-num">{hud.stats.treeCount}</span>
            <span className="demo-stat-label">trees</span>
          </div>
          <div className="demo-stat">
            <span className="demo-stat-num">{hud.stats.branchCount}</span>
            <span className="demo-stat-label">branches</span>
          </div>
          <div className="demo-stat">
            <span className="demo-stat-num">
              {hud.stats.assigned}
              <span className="demo-stat-dim">/{hud.stats.total}</span>
            </span>
            <span className="demo-stat-label">organized</span>
          </div>
          <div className="demo-stat">
            <span className="demo-stat-num demo-stat-gold">{hud.stats.shared ?? 0}</span>
            <span className="demo-stat-label">in 2+ clusters</span>
          </div>
        </div>
        {hud.recent.length > 0 && (
          <div className="demo-ticker">
            {hud.recent.map((m, i) => (
              <div key={`${m.text}-${i}`} className={`demo-ticker-row demo-ticker-${m.kind}`} style={{ opacity: 1 - i * 0.22 }}>
                {m.kind === "grew" ? "▲" : m.kind === "merge" ? "⇄" : "＋"} {m.text}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Current query chip */}
      {hud.query && !hud.ended && (
        <div className="demo-query">
          <span className="demo-query-dot" style={{ background: hud.query.color }} />
          <span className="demo-query-theme">{hud.query.label}</span>
          <span className="demo-query-text">{hud.query.text}</span>
        </div>
      )}

      {/* Playback bar */}
      <div className="demo-bar">
        <button className="demo-btn demo-btn-play" onClick={onTogglePlay} title={isPlaying ? "Pause" : "Play"}>
          {isPlaying ? "❚❚" : hud.ended ? "↺" : "▶"}
        </button>

        <div className="demo-scrub">
          <div className="demo-scrub-track">
            <div className="demo-scrub-fill" style={{ width: `${pct}%` }} />
            {ticks.map((tk, i) => (
              <div
                key={i}
                className={`demo-scrub-tick demo-scrub-tick-${tk.kind}`}
                style={{ left: `${(tk.t / totalDuration) * 100}%` }}
              />
            ))}
          </div>
          <input
            type="range"
            min={0}
            max={totalDuration}
            step={0.1}
            value={hud.time}
            onChange={(e) => onScrub(parseFloat(e.target.value))}
          />
        </div>

        <div className="demo-queries-count">
          {hud.queryIndex} <span>queries</span>
        </div>

        <div className="demo-speeds">
          {SPEEDS.map((s) => (
            <button
              key={s}
              className={`demo-btn demo-btn-speed ${s === speed ? "active" : ""}`}
              onClick={() => onSetSpeed(s)}
            >
              {s}x
            </button>
          ))}
        </div>

        <button className="demo-btn demo-btn-exit" onClick={onExit}>
          Exit
        </button>
      </div>
    </>
  );
}
