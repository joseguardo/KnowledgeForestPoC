import { useState, useEffect, useCallback } from "react";

/**
 * Manages demo simulation playback state.
 * Controls which checkpoint is displayed and auto-advance timing.
 */
export default function useSimulationPlayback(checkpoints) {
  const [checkpointIndex, setCheckpointIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);

  const maxIndex = checkpoints.length - 1;

  // Auto-advance when playing
  useEffect(() => {
    if (!isPlaying) return;
    if (checkpointIndex >= maxIndex) {
      setIsPlaying(false);
      return;
    }

    const interval = setInterval(() => {
      setCheckpointIndex((i) => {
        const next = Math.min(i + 1, maxIndex);
        if (next >= maxIndex) setIsPlaying(false);
        return next;
      });
    }, 4000 / speed);

    return () => clearInterval(interval);
  }, [isPlaying, speed, checkpointIndex, maxIndex]);

  const stepForward = useCallback(() => {
    setCheckpointIndex((i) => Math.min(i + 1, maxIndex));
  }, [maxIndex]);

  const stepBackward = useCallback(() => {
    setCheckpointIndex((i) => Math.max(i - 1, 0));
  }, []);

  const jumpTo = useCallback((i) => {
    setCheckpointIndex(Math.max(0, Math.min(i, maxIndex)));
  }, [maxIndex]);

  const togglePlay = useCallback(() => {
    setIsPlaying((p) => {
      // If at end, restart from beginning
      if (!p && checkpointIndex >= maxIndex) {
        setCheckpointIndex(0);
      }
      return !p;
    });
  }, [checkpointIndex, maxIndex]);

  return {
    checkpoint: checkpoints[checkpointIndex],
    checkpointIndex,
    totalCheckpoints: checkpoints.length,
    isPlaying,
    speed,
    setSpeed,
    stepForward,
    stepBackward,
    jumpTo,
    togglePlay,
  };
}
