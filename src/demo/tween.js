/**
 * Minimal tween manager for the demo animation. Tweens are issued in
 * timeline-seconds and advanced with dt * playbackSpeed, so everything
 * scales coherently with the speed control.
 */

export const Easings = {
  linear: (t) => t,
  easeOutCubic: (t) => 1 - Math.pow(1 - t, 3),
  easeInOutQuad: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
  easeOutBack: (t) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
};

export class Tweens {
  constructor() {
    this.list = [];
  }

  /**
   * add({ duration, delay, ease, onUpdate(k), onComplete, tag })
   * onUpdate receives the eased progress k in [0, 1].
   */
  add({ duration, delay = 0, ease = "easeOutCubic", onUpdate, onComplete, tag }) {
    const tw = {
      t: -delay,
      duration: Math.max(duration, 0.0001),
      ease: typeof ease === "function" ? ease : Easings[ease] || Easings.easeOutCubic,
      onUpdate,
      onComplete,
      tag,
      done: false,
    };
    this.list.push(tw);
    return tw;
  }

  update(dt) {
    let anyDone = false;
    for (const tw of this.list) {
      if (tw.done) continue;
      tw.t += dt;
      if (tw.t < 0) continue;
      const k = Math.min(1, tw.t / tw.duration);
      if (tw.onUpdate) tw.onUpdate(tw.ease(k));
      if (k >= 1) {
        tw.done = true;
        anyDone = true;
        if (tw.onComplete) tw.onComplete();
      }
    }
    if (anyDone) this.list = this.list.filter((t) => !t.done);
  }

  killByTag(tag) {
    this.list = this.list.filter((t) => t.tag !== tag);
  }

  clear() {
    this.list = [];
  }
}
