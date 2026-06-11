import { useState, useRef, useEffect, useMemo } from "react";
import * as THREE from "three";
import buildScene from "../scene/buildScene";

// Default branch label scale (matches buildScene makeLabel call)
const DEFAULT_LABEL_SCALE = [3, 0.75, 1];

function computeDensityScales(tree) {
  const densities = tree.branches.map(
    (b) => (b.links?.length || 0) + b.leaves.length
  );
  const min = Math.min(...densities);
  const max = Math.max(...densities);
  const range = max - min || 1;
  const BASE = 2.5;
  const MAX_S = 7.0;
  return tree.branches.map((b, i) => {
    const t = (densities[i] - min) / range;
    const s = BASE + t * (MAX_S - BASE);
    return [s, s * 0.25, 1];
  });
}

export default function useForestScene({ trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES } = {}) {
  const canvasRef = useRef(null);
  const frameRef = useRef(0);
  const sceneRef = useRef(null);
  const exitFocusRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [info, setInfo] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [focusedTree, setFocusedTree] = useState(null);
  const [selectedHouse, setSelectedHouse] = useState(null);
  const [selectedDb, setSelectedDb] = useState(null);

  // Expose setters to the animation loop without re-running the effect
  const hoveredRef = useRef(null);
  const autoRotateRef = useRef(true);
  const focusedTreeRef = useRef(null);
  useEffect(() => { hoveredRef.current = hovered; }, [hovered]);
  useEffect(() => { autoRotateRef.current = autoRotate; }, [autoRotate]);
  useEffect(() => { focusedTreeRef.current = focusedTree; }, [focusedTree]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = canvas.parentElement.clientWidth;
    const H = canvas.parentElement.clientHeight;
    const ctx = buildScene(canvas, W, H, { trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES });
    sceneRef.current = ctx;

    // Camera state: spherical coords around a target
    const target = new THREE.Vector3(0, 1.4, 0);
    const spherical = new THREE.Spherical(55, Math.PI / 3, Math.PI / 4);

    // Goal values for smooth camera animation
    const goalTarget = target.clone();
    const goalSpherical = { radius: spherical.radius, phi: spherical.phi, theta: spherical.theta };

    // Saved forest camera state (restored when exiting focus)
    const savedTarget = new THREE.Vector3(0, 1.4, 0);
    const savedSpherical = { radius: 55, phi: Math.PI / 3, theta: Math.PI / 4 };

    const applyCamera = () => {
      const offset = new THREE.Vector3().setFromSpherical(spherical);
      ctx.camera.position.copy(target).add(offset);
      ctx.camera.lookAt(target);
    };
    applyCamera();

    // Raycasting
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();

    // Mouse state
    let isDragging = false;
    let isPanning = false;
    let lastX = 0;
    let lastY = 0;
    let downX = 0;
    let downY = 0;
    let downTime = 0;
    const DRAG_THRESHOLD = 5;

    const pickAt = (clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(ndc, ctx.camera);
      const hits = raycaster.intersectObjects(ctx.pickables, false);
      return hits.length ? hits[0].object.userData : null;
    };

    const enterFocus = (treeId) => {
      // Save current camera for restoring later
      savedTarget.copy(target);
      savedSpherical.radius = spherical.radius;
      savedSpherical.phi = spherical.phi;
      savedSpherical.theta = spherical.theta;

      // Set goal: fly to tree
      const tree = TREES.find((t) => t.id === treeId);
      if (!tree) return;
      const base = new THREE.Vector3(tree.pos[0], 1.4, tree.pos[2]);
      goalTarget.copy(base);
      goalSpherical.radius = 10;
      goalSpherical.phi = Math.PI / 3;
      goalSpherical.theta = Math.PI / 4;

      focusedTreeRef.current = treeId;
      setFocusedTree(treeId);
      autoRotateRef.current = false;
      setAutoRotate(false);
    };

    const exitFocus = () => {
      goalTarget.copy(savedTarget);
      goalSpherical.radius = savedSpherical.radius;
      goalSpherical.phi = savedSpherical.phi;
      goalSpherical.theta = savedSpherical.theta;

      // Restore branch label scales
      Object.entries(ctx.branchLabels).forEach(([, sprite]) => {
        sprite.scale.set(DEFAULT_LABEL_SCALE[0], DEFAULT_LABEL_SCALE[1], DEFAULT_LABEL_SCALE[2]);
      });

      focusedTreeRef.current = null;
      setFocusedTree(null);
    };

    exitFocusRef.current = exitFocus;

    const onPointerDown = (e) => {
      canvas.setPointerCapture?.(e.pointerId);
      isDragging = true;
      isPanning = e.button === 2 || e.shiftKey;
      lastX = e.clientX;
      lastY = e.clientY;
      downX = e.clientX;
      downY = e.clientY;
      downTime = performance.now();
      if (!focusedTreeRef.current) {
        autoRotateRef.current = false;
        setAutoRotate(false);
      }
    };

    const onPointerMove = (e) => {
      if (isDragging) {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;

        if (isPanning) {
          const panSpeed = spherical.radius * 0.0015;
          const right = new THREE.Vector3().setFromMatrixColumn(ctx.camera.matrix, 0);
          const up = new THREE.Vector3().setFromMatrixColumn(ctx.camera.matrix, 1);
          goalTarget.addScaledVector(right, -dx * panSpeed);
          goalTarget.addScaledVector(up, dy * panSpeed);
        } else {
          goalSpherical.theta -= dx * 0.005;
          goalSpherical.phi -= dy * 0.005;
          goalSpherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, goalSpherical.phi));
        }
      } else {
        // Hover raycast — prefer branchId, fall back to houseId or treeId
        const hit = pickAt(e.clientX, e.clientY);
        const branchId = hit?.branchId || null;
        const houseId = hit?.houseId || null;
        const dbId = hit?.dbId || null;
        const treeId = hit?.treeId || null;
        const hoverKey = branchId || houseId || dbId || treeId;
        if (hoverKey !== hoveredRef.current) {
          hoveredRef.current = hoverKey;
          setHovered(hoverKey);
          canvas.style.cursor = hoverKey ? "pointer" : "grab";
        }
      }
    };

    const onPointerUp = (e) => {
      if (!isDragging) return;
      isDragging = false;
      canvas.releasePointerCapture?.(e.pointerId);
      const dx = e.clientX - downX;
      const dy = e.clientY - downY;
      const dt = performance.now() - downTime;
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD && dt < 400) {
        const hit = pickAt(e.clientX, e.clientY);

        if (focusedTreeRef.current) {
          // In focus mode
          if (hit?.branchId) {
            setSelectedHouse(null);
            setSelectedDb(null);
            setInfo((prev) => (prev === hit.branchId ? null : hit.branchId));
          } else if (!hit) {
            setInfo(null);
            setSelectedHouse(null);
            setSelectedDb(null);
            exitFocus();
          }
        } else {
          // In forest mode
          if (hit?.branchId) {
            setSelectedHouse(null);
            setSelectedDb(null);
            setInfo((prev) => (prev === hit.branchId ? null : hit.branchId));
          } else if (hit?.houseId) {
            setInfo(null);
            setSelectedDb(null);
            setSelectedHouse((prev) => (prev === hit.houseId ? null : hit.houseId));
          } else if (hit?.dbId) {
            setInfo(null);
            setSelectedHouse(null);
            setSelectedDb((prev) => (prev ? null : true));
          } else if (hit?.treeId && !hit?.branchId) {
            setInfo(null);
            setSelectedHouse(null);
            setSelectedDb(null);
            enterFocus(hit.treeId);
          } else if (!hit) {
            setInfo(null);
            setSelectedHouse(null);
            setSelectedDb(null);
          }
        }
      }
    };

    const onWheel = (e) => {
      e.preventDefault();
      const scale = Math.exp(e.deltaY * 0.001);
      const minR = focusedTreeRef.current ? 4 : 10;
      const maxR = focusedTreeRef.current ? 25 : 160;
      goalSpherical.radius = Math.max(minR, Math.min(maxR, goalSpherical.radius * scale));
    };

    const onContextMenu = (e) => e.preventDefault();

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointerleave", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("contextmenu", onContextMenu);
    canvas.style.cursor = "grab";

    // Track whether density labels have been applied for the current focus
    let densityAppliedFor = null;

    // Animation loop
    function animate() {
      frameRef.current = requestAnimationFrame(animate);

      if (autoRotateRef.current && !isDragging) {
        goalSpherical.theta += 0.0018;
      }

      // Smooth LERP camera toward goals
      const lerpSpeed = 0.08;
      target.lerp(goalTarget, lerpSpeed);
      spherical.radius += (goalSpherical.radius - spherical.radius) * lerpSpeed;
      spherical.phi += (goalSpherical.phi - spherical.phi) * lerpSpeed;
      spherical.theta += (goalSpherical.theta - spherical.theta) * lerpSpeed;
      applyCamera();

      const focused = focusedTreeRef.current;

      // Visibility management
      Object.entries(ctx.treeGroups).forEach(([id, g]) => {
        g.visible = !focused || id === focused;
      });
      ctx.crossLinks.forEach((l) => { l.visible = !focused; });
      Object.values(ctx.houseGroups).forEach((g) => { g.visible = !focused; });
      ctx.houseLinks.forEach((l) => { l.visible = !focused; });
      if (ctx.dbGroup) ctx.dbGroup.visible = !focused;
      if (ctx.dbLinks) ctx.dbLinks.forEach((l) => { l.visible = !focused; });
      ctx.gridGroup.visible = !focused;
      ctx.particles.visible = !focused;
      ctx.titleSprite.visible = !focused;
      Object.entries(ctx.treeLabelSprites).forEach(([id, sprites]) => {
        const vis = !focused || id === focused;
        sprites.forEach((s) => { s.visible = vis; });
      });

      // Apply density-based label sizing when focused
      if (focused && densityAppliedFor !== focused) {
        const tree = TREES.find((t) => t.id === focused);
        if (tree) {
          const scales = computeDensityScales(tree);
          tree.branches.forEach((b, i) => {
            const sprite = ctx.branchLabels[b.id];
            if (sprite) sprite.scale.set(scales[i][0], scales[i][1], scales[i][2]);
          });
          densityAppliedFor = focused;
        }
      } else if (!focused && densityAppliedFor) {
        densityAppliedFor = null;
      }

      // Highlight: branches scale on hover
      const hoverKey = hoveredRef.current;
      Object.entries(ctx.branchGroups).forEach(([id, g]) => {
        const target = id === hoverKey ? 1.25 : 1.0;
        g.scale.x += (target - g.scale.x) * 0.18;
        g.scale.y += (target - g.scale.y) * 0.18;
        g.scale.z += (target - g.scale.z) * 0.18;
      });
      // Houses + DB scale on hover
      Object.entries(ctx.houseGroups).forEach(([id, g]) => {
        const target = id === hoverKey ? 1.25 : 1.0;
        g.scale.x += (target - g.scale.x) * 0.18;
        g.scale.y += (target - g.scale.y) * 0.18;
        g.scale.z += (target - g.scale.z) * 0.18;
      });
      if (ctx.dbGroup) {
        const target = hoverKey === "db:forest" ? 1.25 : 1.0;
        ctx.dbGroup.scale.x += (target - ctx.dbGroup.scale.x) * 0.18;
        ctx.dbGroup.scale.y += (target - ctx.dbGroup.scale.y) * 0.18;
        ctx.dbGroup.scale.z += (target - ctx.dbGroup.scale.z) * 0.18;
      }

      // Animate particles
      if (ctx.particles.visible) {
        const pos = ctx.particles.geometry.attributes.position.array;
        for (let i = 0; i < pos.length; i += 3) {
          pos[i + 1] += Math.sin(Date.now() * 0.001 + pos[i] * 0.5) * 0.002;
        }
        ctx.particles.geometry.attributes.position.needsUpdate = true;
      }

      ctx.renderer.render(ctx.scene, ctx.camera);
    }
    animate();

    const onResize = () => {
      const w = canvas.parentElement.clientWidth;
      const h = canvas.parentElement.clientHeight;
      ctx.renderer.setSize(w, h);
      ctx.camera.aspect = w / h;
      ctx.camera.updateProjectionMatrix();
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
      canvas.removeEventListener("contextmenu", onContextMenu);
      // Dispose all geometries, materials, and textures to prevent GPU memory leaks
      ctx.scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) {
            obj.material.forEach((m) => {
              if (m.map) m.map.dispose();
              m.dispose();
            });
          } else {
            if (obj.material.map) obj.material.map.dispose();
            obj.material.dispose();
          }
        }
      });
      ctx.renderer.dispose();
    };
  }, [TREES, BRANCH_INDEX, HOUSES]);

  const selected = useMemo(() => {
    if (!info || !BRANCH_INDEX) return null;
    return BRANCH_INDEX[info] || null;
  }, [info, BRANCH_INDEX]);

  const inboundLinks = useMemo(() => {
    if (!TREES) return {};
    const map = {};
    TREES.forEach((t) =>
      t.branches.forEach((b) =>
        (b.links || []).forEach((link) => {
          if (!map[link.id]) map[link.id] = [];
          map[link.id].push(b.id);
        })
      )
    );
    return map;
  }, [TREES]);

  return {
    canvasRef, hovered, setHovered, info, setInfo,
    autoRotate, setAutoRotate, selected, inboundLinks,
    focusedTree, exitFocusMode: () => { exitFocusRef.current?.(); },
    selectedHouse, setSelectedHouse,
    selectedDb, setSelectedDb,
  };
}
