/**
 * Forest Creation demo — single-tenant (Nzyme), full-screen cinematic.
 *
 * A precomputed event timeline (simulationTimeline.js) drives a persistent
 * Three.js scene (demoSceneManager.js): queries stream as theme-colored
 * comets, co-access edges turn gold as they strengthen, and branches/trees
 * grow in place with tweens. A directed camera pushes in on formation
 * moments; drag/wheel takes over, scrubbing snaps the whole scene.
 */
import { useRef, useEffect, useMemo, useCallback } from "react";
import { createDemoScene } from "../scene/demoSceneManager.js";
import { createCameraDirector } from "./cameraDirector.js";
import { Tweens } from "./tween.js";
import { TIMELINE } from "./simulationTimeline.js";
import useDemoPlayback from "../hooks/useDemoPlayback.js";
import DemoHud from "../components/DemoHud.jsx";
import "../App.css";
import "./demo.css";

export default function DemoApp({ onExit }) {
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const directorRef = useRef(null);
  const playback = useDemoPlayback(TIMELINE);

  // advance/scrubTo are stable callbacks; keep latest in a ref for the loop
  const advanceRef = useRef(playback.advance);
  advanceRef.current = playback.advance;

  const ticks = useMemo(
    () =>
      TIMELINE.events
        .filter((ev) => ev.featured)
        .map((ev) => ({ t: ev.t, kind: ev.type === "TREE_FORMED" ? "tree" : "branch" })),
    []
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = canvas.parentElement.clientWidth;
    const H = canvas.parentElement.clientHeight;

    const tweens = new Tweens();
    const scene = createDemoScene(canvas, W, H, TIMELINE, tweens);
    const director = createCameraDirector(scene.camera);
    sceneRef.current = scene;
    directorRef.current = director;

    // ── Input → camera director
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    const onPointerDown = (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      director.setDragging(true);
      canvas.style.cursor = "grabbing";
    };
    const onPointerMove = (e) => {
      if (!dragging) return;
      director.userDrag(e.clientX - lastX, e.clientY - lastY);
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onPointerUp = () => {
      dragging = false;
      director.setDragging(false);
      canvas.style.cursor = "grab";
    };
    const onWheel = (e) => {
      e.preventDefault();
      director.userZoom(e.deltaY);
    };
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointerleave", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.style.cursor = "grab";

    // ── Main loop
    let frame = 0;
    let last = performance.now();
    let elapsed = 0;

    const loop = () => {
      frame = requestAnimationFrame(loop);
      const now = performance.now();
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      elapsed += dt;

      const { events, simDt } = advanceRef.current(dt);
      for (const ev of events) {
        if (ev.type === "PHASE") continue;
        scene.playEvent(ev);
        if (ev.featured) {
          const focus = ev.world || ev.pos;
          if (focus) {
            // Hold is timeline-time; convert to wall-clock for the director
            const hold = (ev.type === "TREE_FORMED" ? 2.4 : 1.9) / Math.max(1, simDt / dt || 1);
            director.setShot(focus, ev.type === "TREE_FORMED" ? 23 : 19, hold);
          }
        }
      }

      tweens.update(simDt);
      scene.update(simDt, elapsed);
      director.setOverview({
        radius: Math.min(56, 34 + scene.treeCount() * 2.0),
        height: 1.5 + scene.treeCount() * 0.12,
      });
      director.update(dt, elapsed);
      scene.render();
    };
    loop();

    const onResize = () => {
      scene.resize(canvas.parentElement.clientWidth, canvas.parentElement.clientHeight);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointerleave", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
      scene.dispose();
      sceneRef.current = null;
    };
  }, []);

  const handleScrub = useCallback(
    (time) => {
      const stepCount = playback.scrubTo(time);
      sceneRef.current?.snapTo(stepCount);
      directorRef.current?.resetToOverview();
    },
    [playback.scrubTo]
  );

  const handleTogglePlay = useCallback(() => {
    if (playback.hud.ended && !playback.isPlaying) {
      handleScrub(0);
    }
    playback.togglePlay();
  }, [playback, handleScrub]);

  return (
    <div className="forest-root demo-root">
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />
      <DemoHud
        hud={playback.hud}
        isPlaying={playback.isPlaying}
        speed={playback.speed}
        totalDuration={TIMELINE.totalDuration}
        ticks={ticks}
        onTogglePlay={handleTogglePlay}
        onSetSpeed={playback.setSpeed}
        onScrub={handleScrub}
        onExit={onExit}
      />
    </div>
  );
}
