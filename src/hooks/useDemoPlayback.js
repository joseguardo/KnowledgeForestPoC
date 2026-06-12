/**
 * Playback state for the Forest Creation demo.
 *
 * The master clock lives in a ref and is advanced from the rAF loop —
 * React state is only synced a few times per second for the HUD. Events
 * are dispatched through a monotonic cursor; scrubbing resets the cursor
 * with a binary search and returns the step count for the scene snap.
 */
import { useRef, useState, useCallback, useMemo } from "react";

const HUD_SYNC_INTERVAL = 0.15;
const EMPTY = Object.freeze({ events: [], simDt: 0 });

function tickerMessage(ev) {
  switch (ev.type) {
    case "TREE_FORMED":
      return { kind: "tree", text: `Tree formed: ${ev.label}` };
    case "TREE_RENAMED":
      return { kind: "rename", text: `Tree renamed: ${ev.label}` };
    case "BRANCH_FORMED":
      return { kind: "branch", text: `Branch formed: ${ev.name} (${ev.size} pointers)` };
    case "BRANCH_GREW":
      return { kind: "grew", text: `${ev.name} +${ev.addedPointerIds.length} pointer${ev.addedPointerIds.length > 1 ? "s" : ""}` };
    case "BRANCH_DISSOLVED":
      return { kind: "merge", text: "Branches merged" };
    case "POINTER_LINKED":
      return { kind: "link", text: `${ev.pointerLabel} also joined ${ev.branchName}` };
    default:
      return null;
  }
}

export default function useDemoPlayback(timeline) {
  const clockRef = useRef(0);
  const cursorRef = useRef(0);
  const playingRef = useRef(true);
  const speedRef = useRef(1);
  const accRef = useRef({
    recent: [],
    phase: null,
    query: null,
    lastQueryIndex: -1,
    lastSync: -1,
  });

  const [isPlaying, setIsPlaying] = useState(true);
  const [speed, setSpeedState] = useState(1);

  const initialStats = useMemo(
    () => ({
      treeCount: 0,
      branchCount: 0,
      assigned: 0,
      shared: 0,
      total: timeline.snapshotAt(0).stats.total,
    }),
    [timeline]
  );
  const [hud, setHud] = useState({
    time: 0,
    progress: 0,
    queryIndex: 0,
    stats: initialStats,
    recent: [],
    phase: null,
    query: null,
    ended: false,
  });

  const statsAtStep = useCallback(
    (stepCount) => {
      if (stepCount <= 0) return initialStats;
      const idx = timeline.steps[Math.min(stepCount, timeline.steps.length) - 1].structureIdx;
      return idx >= 0 ? timeline.structures[idx].stats : initialStats;
    },
    [timeline, initialStats]
  );

  const syncHud = useCallback(
    (ended) => {
      const acc = accRef.current;
      const t = clockRef.current;
      const stepCount = Math.max(0, acc.lastQueryIndex + 1);
      setHud({
        time: t,
        progress: t / timeline.totalDuration,
        queryIndex: stepCount,
        stats: statsAtStep(stepCount),
        recent: [...acc.recent],
        phase: acc.phase,
        query: acc.query,
        ended,
      });
    },
    [timeline, statsAtStep]
  );

  const ingest = useCallback((ev) => {
    const acc = accRef.current;
    if (ev.type === "PHASE") {
      acc.phase = { title: ev.title, subtitle: ev.subtitle };
      return;
    }
    if (ev.type === "QUERY") {
      acc.query = { color: ev.themeColor, label: ev.themeLabel, text: ev.text };
      acc.lastQueryIndex = ev.queryIndex;
      return;
    }
    const msg = tickerMessage(ev);
    if (msg) {
      acc.recent.unshift(msg);
      if (acc.recent.length > 4) acc.recent.length = 4;
    }
  }, []);

  /** Advance the clock from the rAF loop. Returns crossed events + sim dt. */
  const advance = useCallback(
    (dt) => {
      if (!playingRef.current) return EMPTY;
      const simDt = dt * speedRef.current;
      let t = clockRef.current + simDt;
      let ended = false;
      if (t >= timeline.totalDuration) {
        t = timeline.totalDuration;
        ended = true;
        playingRef.current = false;
        setIsPlaying(false);
      }
      clockRef.current = t;

      const evs = timeline.events;
      const out = [];
      while (cursorRef.current < evs.length && evs[cursorRef.current].t <= t) {
        const ev = evs[cursorRef.current++];
        ingest(ev);
        out.push(ev);
      }

      const acc = accRef.current;
      if (ended || t - acc.lastSync >= HUD_SYNC_INTERVAL) {
        acc.lastSync = t;
        syncHud(ended);
      }
      return { events: out, simDt };
    },
    [timeline, ingest, syncHud]
  );

  /** Jump to a time. Returns the step count the scene should snap to. */
  const scrubTo = useCallback(
    (time) => {
      const t = Math.max(0, Math.min(time, timeline.totalDuration));
      clockRef.current = t;

      // Cursor: first event with ev.t > t
      const evs = timeline.events;
      let lo = 0;
      let hi = evs.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (evs[mid].t <= t) lo = mid + 1;
        else hi = mid;
      }
      cursorRef.current = lo;

      // Rebuild HUD accumulators from history
      const acc = accRef.current;
      acc.phase = null;
      acc.query = null;
      acc.recent = [];
      for (let i = lo - 1; i >= 0; i--) {
        const ev = evs[i];
        if (!acc.phase && ev.type === "PHASE") acc.phase = { title: ev.title, subtitle: ev.subtitle };
        if (!acc.query && ev.type === "QUERY") {
          acc.query = { color: ev.themeColor, label: ev.themeLabel, text: ev.text };
        }
        if (acc.recent.length < 4) {
          const msg = tickerMessage(ev);
          if (msg) acc.recent.push(msg);
        }
        if (acc.phase && acc.query && acc.recent.length >= 4) break;
      }

      const stepCount = timeline.stepForTime(t);
      acc.lastQueryIndex = stepCount - 1;
      acc.lastSync = t;
      syncHud(t >= timeline.totalDuration);
      return stepCount;
    },
    [timeline, syncHud]
  );

  const togglePlay = useCallback(() => {
    playingRef.current = !playingRef.current;
    setIsPlaying(playingRef.current);
  }, []);

  const setSpeed = useCallback((s) => {
    speedRef.current = s;
    setSpeedState(s);
  }, []);

  return { isPlaying, speed, hud, advance, scrubTo, togglePlay, setSpeed };
}
