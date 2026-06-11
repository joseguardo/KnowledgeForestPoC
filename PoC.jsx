import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import * as THREE from "three";

// ── Data ────────────────────────────────────────────────────────────────
// Each TREE is a *category*. Each branch is an *instance* in that category.
// Leaves are properties of that instance. Cross-links connect branches across trees.
const TREES = [
  {
    id: "sectors",
    label: "SECTOR TREE",
    subtitle: "Sectors",
    type: "entity",
    pos: [-12, 0, -4],
    branches: [
      { id: "sector:cyber",   name: "Cybersecurity",      leaves: ["Market: $180B", "CAGR: 12%", "Conf: high"] },
      { id: "sector:fintech", name: "Fintech",            leaves: ["Market: $310B", "CAGR: 9%", "Conf: med"] },
      { id: "sector:biotech", name: "Biotech",            leaves: ["Market: $497B", "CAGR: 14%", "Conf: high"] },
      { id: "sector:consumer",name: "Consumer Tech",      leaves: ["Market: $1.2T", "CAGR: 6%"] },
      { id: "sector:ai-infra",name: "AI Infrastructure",  leaves: ["Market: $82B", "CAGR: 38%"] },
    ],
  },
  {
    id: "companies",
    label: "COMPANY TREE",
    subtitle: "Companies",
    type: "entity",
    pos: [0, 0, -9],
    branches: [
      { id: "company:crowdstrike", name: "CrowdStrike", leaves: ["Rev: $3.06B", "PE: 7.8", "CEO: Kurtz"], links: ["sector:cyber"] },
      { id: "company:wiz",         name: "Wiz",         leaves: ["Rev: $500M", "PE: 8.5", "CEO: Rappaport"], links: ["sector:cyber"] },
      { id: "company:apple",       name: "Apple",       leaves: ["Rev: $383B", "PE: 9.1", "CEO: Cook"], links: ["sector:consumer"] },
      { id: "company:stripe",      name: "Stripe",      leaves: ["Rev: $14.4B", "PE: 8.2", "CEO: Collison"], links: ["sector:fintech"] },
      { id: "company:nvidia",      name: "NVIDIA",      leaves: ["Rev: $60B", "PE: 9.4", "CEO: Huang"], links: ["sector:ai-infra"] },
      { id: "company:moderna",     name: "Moderna",     leaves: ["Rev: $6.8B", "PE: 6.2", "CEO: Bancel"], links: ["sector:biotech"] },
    ],
  },
  {
    id: "people",
    label: "PEOPLE TREE",
    subtitle: "People",
    type: "entity",
    pos: [12, 0, -4],
    branches: [
      { id: "person:kurtz",    name: "George Kurtz",    leaves: ["CEO CrowdStrike", "Austin, TX"], links: ["company:crowdstrike"] },
      { id: "person:cook",     name: "Tim Cook",        leaves: ["CEO Apple", "Cupertino"],         links: ["company:apple"] },
      { id: "person:collison", name: "Patrick Collison",leaves: ["CEO Stripe", "SF"],               links: ["company:stripe"] },
      { id: "person:huang",    name: "Jensen Huang",    leaves: ["CEO NVIDIA", "Santa Clara"],      links: ["company:nvidia"] },
    ],
  },
  {
    id: "executions",
    label: "EXECUTION TREE",
    subtitle: "Runs",
    type: "execution",
    pos: [-8, 0, 8],
    branches: [
      { id: "run:47", name: "run:47", leaves: ["cyber PE scan", "4m32s · $0.38", "Status: ✓"], links: ["plan:sector-analysis", "sector:cyber", "company:crowdstrike", "transform:growth-scorer"] },
      { id: "run:38", name: "run:38", leaves: ["fintech scan", "3m58s · $0.31", "Status: ✓"], links: ["plan:sector-analysis", "sector:fintech", "company:stripe"] },
      { id: "run:29", name: "run:29", leaves: ["ai-infra scan", "5m14s · $0.42", "Status: ✓"], links: ["plan:sector-analysis", "sector:ai-infra", "company:nvidia"] },
      { id: "run:52", name: "run:52", leaves: ["company deep-dive", "2m10s · $0.19"], links: ["plan:company-dd", "company:wiz"] },
    ],
  },
  {
    id: "plans",
    label: "PLAN TREE",
    subtitle: "Plans",
    type: "plan",
    pos: [0, 0, 11],
    branches: [
      { id: "plan:sector-analysis", name: "sector-analysis", leaves: ["Maturity: proven", "94% success", "16 runs"] },
      { id: "plan:company-dd",      name: "company-dd",      leaves: ["Maturity: proven", "88% success", "9 runs"] },
      { id: "plan:people-network",  name: "people-network",  leaves: ["Maturity: beta", "4 runs"] },
    ],
  },
  {
    id: "transforms",
    label: "TRANSFORM TREE",
    subtitle: "Transforms",
    type: "transform",
    pos: [8, 0, 8],
    branches: [
      { id: "transform:growth-scorer", name: "growth-scorer", leaves: ["v3 · 12/12 ✓", "deterministic", "Python"] },
      { id: "transform:tam-calc",      name: "tam-calculator",leaves: ["v2 · 8/8 ✓",  "deterministic"] },
      { id: "transform:ebitda-norm",   name: "ebitda-norm",   leaves: ["v1 · 6/6 ✓",  "deterministic"] },
      { id: "transform:entity-dedupe", name: "entity-dedupe", leaves: ["v4 · 20/20 ✓","deterministic"] },
    ],
  },
];

// Flat lookup: branchId → { tree, branch }
const BRANCH_INDEX = {};
TREES.forEach((t) => t.branches.forEach((b) => { BRANCH_INDEX[b.id] = { tree: t, branch: b }; }));

// ── Helpers ──────────────────────────────────────────────────────────────
const SCALE = 1.0;
const NODE_R = 0.18;
const BRANCH_R = 0.13;
const LEAF_R = 0.075;
const TRUNK_H = 2.0;
const BRANCH_LEN = 2.2;

function vec3(arr) {
  return new THREE.Vector3(arr[0] * SCALE, arr[1] * SCALE, arr[2] * SCALE);
}

// ── Scene builder ───────────────────────────────────────────────────────
function buildScene(canvas, width, height) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xffffff);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0xffffff, 0.04);

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 200);
  camera.position.set(0, 14, 16);
  camera.lookAt(0, 0, 0);

  // Lights
  const ambient = new THREE.AmbientLight(0xffffff, 0.35);
  scene.add(ambient);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(5, 12, 8);
  scene.add(dir);
  const point = new THREE.PointLight(0xffffff, 0.4, 40);
  point.position.set(-4, 8, -4);
  scene.add(point);

  // ── Grid ────────────────────────────────────────────────────────────
  const gridSize = 40;
  const gridDiv = 40;
  const gridGeo = new THREE.BufferGeometry();
  const gridPts = [];
  const half = gridSize / 2;
  const step = gridSize / gridDiv;
  for (let i = 0; i <= gridDiv; i++) {
    const v = -half + i * step;
    gridPts.push(-half, -0.01, v, half, -0.01, v);
    gridPts.push(v, -0.01, -half, v, -0.01, half);
  }
  gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(gridPts, 3));
  const gridMat = new THREE.LineBasicMaterial({ color: 0xdddddd, transparent: true, opacity: 0.8 });
  scene.add(new THREE.LineSegments(gridGeo, gridMat));

  // Subtle axis lines
  const axisGeo = new THREE.BufferGeometry();
  axisGeo.setAttribute(
    "position",
    new THREE.Float32BufferAttribute([-half, -0.005, 0, half, -0.005, 0, 0, -0.005, -half, 0, -0.005, half], 3)
  );
  scene.add(new THREE.LineSegments(axisGeo, new THREE.LineBasicMaterial({ color: 0xcccccc })));

  // ── Materials ───────────────────────────────────────────────────────
  const matWhite = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.5, metalness: 0.05 });
  const matGhost = new THREE.MeshStandardMaterial({ color: 0x666666, roughness: 0.6, metalness: 0.0 });
  const matWire = new THREE.MeshStandardMaterial({ color: 0x111111, wireframe: true, transparent: true, opacity: 0.55 });
  const lineMat = new THREE.LineBasicMaterial({ color: 0xbbbbbb, transparent: true, opacity: 0.85 });
  const linkMat = new THREE.LineDashedMaterial({ color: 0x888888, dashSize: 0.25, gapSize: 0.15, transparent: true, opacity: 0.7 });

  // Shared geos
  const sphereGeo = new THREE.SphereGeometry(1, 20, 14);
  const octaGeo = new THREE.OctahedronGeometry(1, 0);
  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  const cylGeo = new THREE.CylinderGeometry(0.035, 0.05, 1, 8);

  // ── Collect positions for cross-branch links ────────────────────────
  const branchPositions = {}; // branchId → world Vector3
  const branchGroups = {};    // branchId → THREE.Group (for branch highlight)
  const pickables = [];       // meshes raycast can hit (have userData)
  const treeGroups = {};      // treeId → THREE.Group (tree-level highlight)

  function addSphere(pos, r, mat, parent) {
    const m = new THREE.Mesh(sphereGeo, mat);
    m.scale.setScalar(r);
    m.position.copy(pos);
    parent.add(m);
    return m;
  }

  function addLine(a, b, material, parent) {
    const geo = new THREE.BufferGeometry().setFromPoints([a, b]);
    const line = new THREE.Line(geo, material);
    if (material.isLineDashedMaterial) line.computeLineDistances();
    parent.add(line);
  }

  function typeGeo(type) {
    if (type === "execution") return octaGeo;
    if (type === "transform") return boxGeo;
    return sphereGeo;
  }

  // ── Build each tree ─────────────────────────────────────────────────
  TREES.forEach((tree) => {
    const group = new THREE.Group();
    const base = vec3(tree.pos);
    group.position.copy(base);
    scene.add(group);
    treeGroups[tree.id] = group;

    const origin = new THREE.Vector3(0, 0, 0);

    // Root node — wireframe for type distinction
    const rootMesh = new THREE.Mesh(typeGeo(tree.type), matWire);
    rootMesh.scale.setScalar(NODE_R * 3.2);
    rootMesh.position.copy(origin);
    rootMesh.userData = { treeId: tree.id, kind: "root" };
    group.add(rootMesh);
    pickables.push(rootMesh);

    // Small solid core
    const core = addSphere(origin, NODE_R, matWhite, group);
    core.userData = { treeId: tree.id, kind: "root" };
    pickables.push(core);

    // Invisible generous hitbox so the whole tree is easy to click
    const hit = new THREE.Mesh(
      new THREE.CylinderGeometry(2.4, 2.0, TRUNK_H + 2.2, 12),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    hit.position.set(0, (TRUNK_H + 1.0) / 2, 0);
    hit.userData = { treeId: tree.id, kind: "hit" };
    group.add(hit);
    pickables.push(hit);

    // Vertical trunk
    const trunk = new THREE.Mesh(cylGeo, matGhost);
    trunk.scale.set(1, TRUNK_H, 1);
    trunk.position.set(0, TRUNK_H / 2, 0);
    trunk.userData = { treeId: tree.id, kind: "trunk" };
    group.add(trunk);
    pickables.push(trunk);

    const trunkTop = new THREE.Vector3(0, TRUNK_H, 0);

    // Branches fan out 360° from trunk top. Each branch = one instance.
    const branchCount = tree.branches.length;
    tree.branches.forEach((br, bi) => {
      const angle = (bi / branchCount) * Math.PI * 2;
      const elevation = 0.6 + (bi % 3) * 0.45;
      const reach = BRANCH_LEN;
      const bDir = new THREE.Vector3(
        Math.cos(angle) * reach,
        elevation,
        Math.sin(angle) * reach
      );
      const bp = trunkTop.clone().add(bDir);

      // Sub-group so branches can be highlighted/scaled independently
      const bGroup = new THREE.Group();
      bGroup.position.copy(bp);
      group.add(bGroup);
      branchGroups[br.id] = bGroup;

      // Branch node at bGroup origin
      const bMesh = addSphere(new THREE.Vector3(0, 0, 0), BRANCH_R, matWhite, bGroup);
      bMesh.userData = { treeId: tree.id, branchId: br.id, kind: "branch", label: br.name };
      addLine(trunkTop, bp, lineMat, group);
      pickables.push(bMesh);

      // Branch hit-proxy (generous cube) so small branches are still easy to click
      const bhit = new THREE.Mesh(
        new THREE.SphereGeometry(0.7, 8, 6),
        new THREE.MeshBasicMaterial({ visible: false })
      );
      bhit.userData = { treeId: tree.id, branchId: br.id, kind: "branchHit" };
      bGroup.add(bhit);
      pickables.push(bhit);

      // Record world position for cross-tree links
      branchPositions[br.id] = bp.clone().add(base);

      // Branch label (instance name)
      const nameLabel = makeLabel(br.name, new THREE.Vector3(0, BRANCH_R + 0.2, 0), 44, "#222222");
      nameLabel.position.copy(new THREE.Vector3(0, BRANCH_R + 0.25, 0));
      bGroup.add(nameLabel);

      // Leaves — properties of this instance, cluster at the branch tip
      const leafCount = br.leaves.length;
      const outward = bDir.clone().normalize();
      const up = new THREE.Vector3(0, 1, 0);
      const side = new THREE.Vector3().crossVectors(outward, up).normalize();
      const top = new THREE.Vector3().crossVectors(side, outward).normalize();
      br.leaves.forEach((_, li) => {
        const tAngle = (li / Math.max(leafCount, 1)) * Math.PI * 2;
        const tRad = 0.45 + (li % 2) * 0.1;
        const lp = new THREE.Vector3()
          .addScaledVector(side, Math.cos(tAngle) * tRad)
          .addScaledVector(top, Math.sin(tAngle) * tRad + 0.1)
          .addScaledVector(outward, 0.2);
        addSphere(lp, LEAF_R, matGhost, bGroup);
        addLine(new THREE.Vector3(0, 0, 0), lp, lineMat, bGroup);
      });
    });
  });


  // ── Cross-branch links (dashed arcs between instances) ──────────────
  TREES.forEach((tree) => {
    tree.branches.forEach((br) => {
      const selfPos = branchPositions[br.id];
      if (!selfPos || !br.links) return;
      br.links.forEach((targetId) => {
        const targetPos = branchPositions[targetId];
        if (!targetPos) return;
        // Lift midpoint so arcs don't lie flat across the grid
        const dist = selfPos.distanceTo(targetPos);
        const mid = selfPos.clone().add(targetPos).multiplyScalar(0.5);
        mid.y += Math.min(3, dist * 0.25);
        const curve = new THREE.QuadraticBezierCurve3(selfPos, mid, targetPos);
        const pts = curve.getPoints(28);
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const line = new THREE.Line(geo, linkMat);
        line.computeLineDistances();
        line.userData = { kind: "link", from: br.id, to: targetId };
        scene.add(line);
      });
    });
  });

  // ── Labels (sprite text) ────────────────────────────────────────────
  function makeLabel(text, position, fontSize = 48, color = "#111111", scale = [3, 0.75, 1]) {
    const cvs = document.createElement("canvas");
    const ctx = cvs.getContext("2d");
    cvs.width = 512;
    cvs.height = 128;
    ctx.clearRect(0, 0, 512, 128);
    ctx.font = `${fontSize}px Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif`;
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 256, 64);
    const tex = new THREE.CanvasTexture(cvs);
    tex.needsUpdate = true;
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.9, depthTest: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(scale[0], scale[1], scale[2]);
    sprite.position.copy(position);
    return sprite;
  }

  // Tree-level category labels
  TREES.forEach((tree) => {
    const base = vec3(tree.pos);
    const sub = makeLabel(tree.subtitle, base.clone().add(new THREE.Vector3(0, TRUNK_H + 1.6, 0)), 54, "#111111");
    const cat = makeLabel(tree.label,    base.clone().add(new THREE.Vector3(0, TRUNK_H + 2.15, 0)), 32, "#888888", [2.4, 0.6, 1]);
    scene.add(sub);
    scene.add(cat);
  });

  // Title
  scene.add(makeLabel("KNOWLEDGE FOREST", new THREE.Vector3(0, 8, -14), 56, "#aaaaaa"));

  // ── Floating particles ──────────────────────────────────────────────
  const particleCount = 200;
  const pGeo = new THREE.BufferGeometry();
  const pPositions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i++) {
    pPositions[i * 3] = (Math.random() - 0.5) * 30;
    pPositions[i * 3 + 1] = Math.random() * 6;
    pPositions[i * 3 + 2] = (Math.random() - 0.5) * 20;
  }
  pGeo.setAttribute("position", new THREE.Float32BufferAttribute(pPositions, 3));
  const pMat = new THREE.PointsMaterial({ color: 0xaaaaaa, size: 0.04, transparent: true, opacity: 0.7 });
  const particles = new THREE.Points(pGeo, pMat);
  scene.add(particles);

  return { renderer, scene, camera, particles, pickables, treeGroups, branchGroups, branchPositions };
}

// ── React Component ─────────────────────────────────────────────────────
export default function KnowledgeForest() {
  const canvasRef = useRef(null);
  const frameRef = useRef(0);
  const sceneRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [info, setInfo] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);

  // Expose setters to the animation loop without re-running the effect
  const hoveredRef = useRef(null);
  const autoRotateRef = useRef(true);
  useEffect(() => { hoveredRef.current = hovered; }, [hovered]);
  useEffect(() => { autoRotateRef.current = autoRotate; }, [autoRotate]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = canvas.parentElement.clientWidth;
    const H = canvas.parentElement.clientHeight;
    const ctx = buildScene(canvas, W, H);
    sceneRef.current = ctx;

    // ── Camera state: spherical coords around a target ─────────────────
    const target = new THREE.Vector3(0, 1.4, 0);
    const spherical = new THREE.Spherical(30, Math.PI / 3, Math.PI / 4);
    const applyCamera = () => {
      const offset = new THREE.Vector3().setFromSpherical(spherical);
      ctx.camera.position.copy(target).add(offset);
      ctx.camera.lookAt(target);
    };
    applyCamera();

    // ── Raycasting ─────────────────────────────────────────────────────
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();

    // ── Mouse state ────────────────────────────────────────────────────
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

    const onPointerDown = (e) => {
      canvas.setPointerCapture?.(e.pointerId);
      isDragging = true;
      isPanning = e.button === 2 || e.shiftKey;
      lastX = e.clientX;
      lastY = e.clientY;
      downX = e.clientX;
      downY = e.clientY;
      downTime = performance.now();
      autoRotateRef.current = false;
      setAutoRotate(false);
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
          target.addScaledVector(right, -dx * panSpeed);
          target.addScaledVector(up, dy * panSpeed);
        } else {
          spherical.theta -= dx * 0.005;
          spherical.phi -= dy * 0.005;
          spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi));
        }
        applyCamera();
      } else {
        // Hover raycast — prefer branchId, fall back to treeId
        const hit = pickAt(e.clientX, e.clientY);
        const branchId = hit?.branchId || null;
        const treeId = hit?.treeId || null;
        const hoverKey = branchId || treeId;
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
        if (hit?.branchId) {
          // Click a branch → open that instance
          setInfo((prev) => (prev === hit.branchId ? null : hit.branchId));
        } else if (hit?.treeId && hit.kind !== "branchHit") {
          // Click root/trunk → no-op for now (tree has no instance data)
        }
      }
    };

    const onWheel = (e) => {
      e.preventDefault();
      const scale = Math.exp(e.deltaY * 0.001);
      spherical.radius = Math.max(8, Math.min(80, spherical.radius * scale));
      applyCamera();
    };

    const onContextMenu = (e) => e.preventDefault();

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointerleave", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("contextmenu", onContextMenu);
    canvas.style.cursor = "grab";

    // ── Animation loop ─────────────────────────────────────────────────
    function animate() {
      frameRef.current = requestAnimationFrame(animate);

      // Auto-rotate only when idle (no drag, nothing hovered or selected)
      if (autoRotateRef.current && !isDragging) {
        spherical.theta += 0.0018;
        applyCamera();
      }

      // Highlight: branches scale on hover, trees stay at 1
      const hoverKey = hoveredRef.current;
      Object.entries(ctx.branchGroups).forEach(([id, g]) => {
        const target = id === hoverKey ? 1.25 : 1.0;
        g.scale.x += (target - g.scale.x) * 0.18;
        g.scale.y += (target - g.scale.y) * 0.18;
        g.scale.z += (target - g.scale.z) * 0.18;
      });

      // Animate particles
      const pos = ctx.particles.geometry.attributes.position.array;
      for (let i = 0; i < pos.length; i += 3) {
        pos[i + 1] += Math.sin(Date.now() * 0.001 + pos[i] * 0.5) * 0.002;
      }
      ctx.particles.geometry.attributes.position.needsUpdate = true;

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
      ctx.renderer.dispose();
    };
  }, []);

  const selected = useMemo(() => {
    if (!info) return null;
    return BRANCH_INDEX[info] || null;
  }, [info]);

  // Build a reverse index: for a given branchId, which other branches link TO it?
  const inboundLinks = useMemo(() => {
    const map = {};
    TREES.forEach((t) =>
      t.branches.forEach((b) =>
        (b.links || []).forEach((targetId) => {
          if (!map[targetId]) map[targetId] = [];
          map[targetId].push(b.id);
        })
      )
    );
    return map;
  }, []);

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#ffffff", position: "relative", overflow: "hidden", fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif' }}>
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />

      {/* Legend */}
      <div
        style={{
          position: "absolute",
          bottom: 24,
          left: 24,
          color: "#555",
          fontSize: 12,
          lineHeight: "20px",
          letterSpacing: "0.02em",
          fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
        }}
      >
        <div style={{ color: "#333", marginBottom: 8, fontSize: 13, fontWeight: 600 }}>Node types</div>
        <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 14 }}>
          <span>&#9675; Entity</span>
          <span>&#9671; Execution</span>
          <span>&#9633; Transform</span>
          <span style={{ borderBottom: "1px dashed #888", paddingBottom: 1 }}>--- Cross-link</span>
        </div>
        <div style={{ color: "#333", marginBottom: 6, fontSize: 13, fontWeight: 600 }}>Controls</div>
        <div style={{ color: "#777", fontSize: 11, lineHeight: "17px" }}>
          <div>Drag — orbit · Shift+drag — pan · Scroll — zoom</div>
          <div>Hover a tree to highlight · Click to open details</div>
        </div>
        <button
          onClick={() => setAutoRotate((v) => !v)}
          style={{
            marginTop: 10,
            background: autoRotate ? "#111" : "#ffffff",
            color: autoRotate ? "#fff" : "#333",
            border: "1px solid #cccccc",
            padding: "5px 12px",
            fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          {autoRotate ? "◐ Auto-rotate: on" : "◑ Auto-rotate: off"}
        </button>
      </div>

      {/* Instance browser — grouped by tree */}
      <div
        style={{
          position: "absolute",
          top: 24,
          right: 24,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          maxHeight: "calc(100vh - 48px)",
          overflowY: "auto",
          paddingRight: 4,
        }}
      >
        {TREES.map((t) => (
          <div key={t.id}>
            <div
              style={{
                color: "#888",
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                marginBottom: 4,
                fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
              }}
            >
              {t.subtitle}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {t.branches.map((b) => (
                <button
                  key={b.id}
                  onClick={() => setInfo(info === b.id ? null : b.id)}
                  onMouseEnter={() => setHovered(b.id)}
                  onMouseLeave={() => setHovered(null)}
                  style={{
                    background: info === b.id ? "#111" : hovered === b.id ? "#f4f4f4" : "#ffffff",
                    color: info === b.id ? "#fff" : "#333",
                    border: "1px solid #cccccc",
                    padding: "5px 11px",
                    fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
                    fontSize: 12,
                    cursor: "pointer",
                    textAlign: "left",
                    letterSpacing: "0.01em",
                    transition: "background 0.12s",
                  }}
                >
                  {b.name}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Info panel */}
      {selected && (
        <div
          style={{
            position: "absolute",
            top: 24,
            left: 24,
            background: "rgba(255,255,255,0.96)",
            border: "1px solid #d8d8d8",
            boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
            padding: 20,
            maxWidth: 340,
            color: "#333",
            fontSize: 13,
            lineHeight: "19px",
            letterSpacing: "0.01em",
            fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
          }}
        >
          <div style={{ color: "#888", fontSize: 10, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            {selected.tree.subtitle} / {selected.tree.label.replace(" TREE", "")}
          </div>
          <div style={{ color: "#111", fontSize: 20, marginBottom: 4, fontWeight: 600 }}>
            {selected.branch.name}
          </div>
          <div style={{ color: "#aaa", fontSize: 10, fontFamily: "monospace", marginBottom: 14 }}>
            {selected.branch.id}
          </div>

          <div style={{ color: "#888", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
            Properties
          </div>
          <div style={{ color: "#333", marginBottom: 14 }}>
            {selected.branch.leaves.map((l, i) => (
              <div key={i} style={{ marginBottom: 3, paddingLeft: 2 }}>
                {"· "}{l}
              </div>
            ))}
          </div>

          {(selected.branch.links || []).length > 0 && (
            <>
              <div style={{ color: "#888", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
                Outbound links
              </div>
              <div style={{ marginBottom: 12 }}>
                {selected.branch.links.map((id) => {
                  const t = BRANCH_INDEX[id];
                  return (
                    <button
                      key={id}
                      onClick={() => setInfo(id)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        background: "transparent",
                        border: "none",
                        padding: "2px 0",
                        color: "#222",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "inherit",
                      }}
                    >
                      {"→ "}
                      <span style={{ textDecoration: "underline" }}>{t ? t.branch.name : id}</span>
                      {t && <span style={{ color: "#999", fontSize: 10 }}> · {t.tree.subtitle}</span>}
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {(inboundLinks[selected.branch.id] || []).length > 0 && (
            <>
              <div style={{ color: "#888", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
                Inbound links
              </div>
              <div style={{ marginBottom: 12 }}>
                {inboundLinks[selected.branch.id].map((id) => {
                  const t = BRANCH_INDEX[id];
                  return (
                    <button
                      key={id}
                      onClick={() => setInfo(id)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        background: "transparent",
                        border: "none",
                        padding: "2px 0",
                        color: "#222",
                        fontSize: 12,
                        cursor: "pointer",
                        fontFamily: "inherit",
                      }}
                    >
                      {"← "}
                      <span style={{ textDecoration: "underline" }}>{t ? t.branch.name : id}</span>
                      {t && <span style={{ color: "#999", fontSize: 10 }}> · {t.tree.subtitle}</span>}
                    </button>
                  );
                })}
              </div>
            </>
          )}

          <button
            onClick={() => setInfo(null)}
            style={{
              marginTop: 4,
              background: "#ffffff",
              border: "1px solid #cccccc",
              color: "#555",
              padding: "5px 12px",
              fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            close
          </button>
        </div>
      )}

      {/* Projection demo */}
      <div
        style={{
          position: "absolute",
          bottom: 24,
          right: 24,
          color: "#777",
          fontSize: 11,
          textAlign: "right",
          lineHeight: "16px",
          maxWidth: 260,
          fontFamily: 'Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif',
        }}
      >
        <div style={{ color: "#333", marginBottom: 4, fontWeight: 600 }}>Forest projection</div>
        <div>forest.project("company:crowdstrike",</div>
        <div style={{ paddingLeft: 8 }}>["revenue", "ebitda", "growth_rate"])</div>
        <div style={{ color: "#999", marginTop: 4, fontStyle: "italic" }}>→ schema-free · provenance-tracked</div>
      </div>
    </div>
  );
}