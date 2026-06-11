/**
 * Root component for Demo Mode.
 * Split-screen: Kibo (left, static) vs Nzyme (right, animated).
 * Controlled by simulation playback.
 */
import { useRef, useEffect } from "react";
import * as THREE from "three";
import buildDemoScene from "../scene/buildDemoScene";
import useSimulationPlayback from "../hooks/useSimulationPlayback";
import { generateCheckpoints } from "./checkpointGenerator";
import SimulationController from "../components/SimulationController";
import DemoInfoPanel from "../components/DemoInfoPanel";
import "../App.css";

// Pre-compute checkpoints at module load (deterministic, instant)
const CHECKPOINTS = generateCheckpoints();

const labelStyle = {
  position: "absolute",
  top: 16,
  padding: "6px 14px",
  background: "rgba(255,255,255,0.9)",
  border: "1px solid #d8d8d8",
  fontSize: 12,
  fontWeight: 600,
  letterSpacing: "0.03em",
  color: "#333",
  fontFamily: "inherit",
  zIndex: 50,
};

export default function DemoApp({ onExit }) {
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const frameRef = useRef(0);

  const {
    checkpoint,
    checkpointIndex,
    totalCheckpoints,
    isPlaying,
    speed,
    setSpeed,
    stepForward,
    stepBackward,
    togglePlay,
  } = useSimulationPlayback(CHECKPOINTS);

  // Build the scene on mount
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = canvas.parentElement.clientWidth;
    const H = canvas.parentElement.clientHeight;

    const ctx = buildDemoScene(canvas, W, H);
    sceneRef.current = ctx;

    // Camera orbit state
    const target = new THREE.Vector3(0, 1.4, 0);
    const spherical = new THREE.Spherical(50, Math.PI / 3, Math.PI / 4);

    const applyCamera = () => {
      const offset = new THREE.Vector3().setFromSpherical(spherical);
      const pos = target.clone().add(offset);
      ctx.setCameraPosition(pos, target);
    };
    applyCamera();

    // Orbit controls
    let isDragging = false;
    let lastX = 0;
    let lastY = 0;

    const onPointerDown = (e) => {
      isDragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    };

    const onPointerMove = (e) => {
      if (!isDragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      spherical.theta -= dx * 0.005;
      spherical.phi -= dy * 0.005;
      spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi));
    };

    const onPointerUp = () => {
      isDragging = false;
    };

    const onWheel = (e) => {
      e.preventDefault();
      const scale = Math.exp(e.deltaY * 0.001);
      spherical.radius = Math.max(15, Math.min(120, spherical.radius * scale));
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointerleave", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.style.cursor = "grab";

    // Auto-rotate
    let lastTime = performance.now();

    function animate() {
      frameRef.current = requestAnimationFrame(animate);
      const now = performance.now();
      const dt = (now - lastTime) / 1000;
      lastTime = now;

      if (!isDragging) {
        spherical.theta += 0.15 * dt; // Slow auto-rotate
      }
      applyCamera();

      // Animate particles in Kibo scene
      if (ctx.kiboScene?.particles?.visible) {
        const pos = ctx.kiboScene.particles.geometry.attributes.position.array;
        for (let i = 0; i < pos.length; i += 3) {
          pos[i + 1] += Math.sin(now * 0.001 + pos[i] * 0.5) * 0.002;
        }
        ctx.kiboScene.particles.geometry.attributes.position.needsUpdate = true;
      }

      ctx.render();
    }
    animate();

    const onResize = () => {
      const w = canvas.parentElement.clientWidth;
      const h = canvas.parentElement.clientHeight;
      ctx.resize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointerleave", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
      ctx.dispose();
    };
  }, []);

  // Update Nzyme scene when checkpoint changes
  useEffect(() => {
    if (!sceneRef.current || !checkpoint) return;
    sceneRef.current.setCheckpoint(checkpoint);
  }, [checkpoint]);

  return (
    <div className="forest-root">
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />

      {/* Side labels */}
      <div style={{ ...labelStyle, left: 16 }}>
        Kibo (Investment Fund)
      </div>
      <div style={{ ...labelStyle, right: 240 }}>
        Nzyme (Regulatory Intel)
      </div>

      {/* Vertical divider hint */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: "50%",
          transform: "translateX(-50%)",
          width: 1,
          height: "100%",
          background: "rgba(0,0,0,0.06)",
          pointerEvents: "none",
          zIndex: 40,
        }}
      />

      {/* Info panel */}
      <DemoInfoPanel checkpoint={checkpoint} checkpointIndex={checkpointIndex} />

      {/* Playback controls */}
      <SimulationController
        checkpointIndex={checkpointIndex}
        totalCheckpoints={totalCheckpoints}
        isPlaying={isPlaying}
        speed={speed}
        onTogglePlay={togglePlay}
        onStepForward={stepForward}
        onStepBackward={stepBackward}
        onSetSpeed={setSpeed}
        queryCount={checkpoint?.queryIndex || 0}
        onExit={onExit}
      />
    </div>
  );
}
