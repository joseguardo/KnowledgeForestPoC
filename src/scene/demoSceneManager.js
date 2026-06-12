/**
 * Persistent Three.js scene for the Forest Creation demo.
 *
 * Nothing is torn down between simulation steps: pointers, branches and
 * trees are long-lived objects keyed by stable uids and animated with
 * tweens. Co-access edges live in ONE preallocated LineSegments whose
 * vertex colors encode pair strength (white → gold, on a white background).
 *
 * API: playEvent(ev), snapTo(stepCount), update(dt, elapsed), render(),
 *      resize(w, h), dispose(), treeCount()
 */
import * as THREE from "three";
import { POINTER_MAP } from "../demo/demoGraph.js";
import { DEMO_GEOM } from "../demo/layoutEngine.js";

const GOLD = new THREE.Color(0xc89418);
const WHITE = new THREE.Color(0xffffff);

const COMET_POOL = 6;
const TRAIL_POINTS = 40;
const TRAIL_FRACTION = 0.42;

// ─── Label sprites ──────────────────────────────────────────────

function makeLabelTexture(text, fontSize, color) {
  const cvs = document.createElement("canvas");
  cvs.width = 512;
  cvs.height = 128;
  const ctx = cvs.getContext("2d");
  ctx.clearRect(0, 0, 512, 128);
  ctx.font = `${fontSize}px Aptos, "Aptos Display", "Segoe UI", system-ui, sans-serif`;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 256, 64);
  const tex = new THREE.CanvasTexture(cvs);
  tex.needsUpdate = true;
  return tex;
}

function makeLabel(text, { fontSize = 44, color = "#222222", scale = [3, 0.75, 1], opacity = 0.9 } = {}) {
  const mat = new THREE.SpriteMaterial({
    map: makeLabelTexture(text, fontSize, color),
    transparent: true,
    opacity,
    depthTest: false,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(scale[0], scale[1], scale[2]);
  return sprite;
}

function setLabelText(sprite, text, fontSize, color) {
  const old = sprite.material.map;
  sprite.material.map = makeLabelTexture(text, fontSize, color);
  if (old) old.dispose();
}

function disposeLabel(sprite) {
  if (sprite.material.map) sprite.material.map.dispose();
  sprite.material.dispose();
}

// ─── Comet head textures (per theme color) ──────────────────────

const headTextureCache = new Map();
function headTexture(color) {
  if (!headTextureCache.has(color)) {
    const cvs = document.createElement("canvas");
    cvs.width = 64;
    cvs.height = 64;
    const ctx = cvs.getContext("2d");
    const g = ctx.createRadialGradient(32, 32, 2, 32, 32, 30);
    g.addColorStop(0, color);
    g.addColorStop(0.4, color + "cc");
    g.addColorStop(1, color + "00");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(cvs);
    headTextureCache.set(color, tex);
  }
  return headTextureCache.get(color);
}

// ─── Scene manager ──────────────────────────────────────────────

export function createDemoScene(canvas, width, height, timeline, tweens) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xffffff);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xffffff, 70, 170);

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 500);
  camera.position.set(0, 18, 34);
  camera.lookAt(0, 0, 0);

  // Lights
  scene.add(new THREE.AmbientLight(0xffffff, 0.45));
  const dir = new THREE.DirectionalLight(0xffffff, 0.85);
  dir.position.set(6, 14, 8);
  scene.add(dir);
  const point = new THREE.PointLight(0xffffff, 0.35, 60);
  point.position.set(-6, 10, -6);
  scene.add(point);

  // Grid
  {
    const gridSize = 110;
    const gridDiv = 110;
    const gridGeo = new THREE.BufferGeometry();
    const pts = [];
    const half = gridSize / 2;
    const step = gridSize / gridDiv;
    for (let i = 0; i <= gridDiv; i++) {
      const v = -half + i * step;
      pts.push(-half, -0.01, v, half, -0.01, v);
      pts.push(v, -0.01, -half, v, -0.01, half);
    }
    gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    scene.add(
      new THREE.LineSegments(
        gridGeo,
        new THREE.LineBasicMaterial({ color: 0xe2e2e2, transparent: true, opacity: 0.55 })
      )
    );
  }

  // Ambient drifting particles
  let particles;
  {
    const n = 110;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 80;
      pos[i * 3 + 1] = Math.random() * 8;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 80;
    }
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    particles = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ color: 0xaaaaaa, size: 0.05, transparent: true, opacity: 0.45 })
    );
    scene.add(particles);
  }

  // Shared geometries / materials
  const sphereGeo = new THREE.SphereGeometry(1, 20, 14);
  const wireSphereGeo = new THREE.SphereGeometry(1, 9, 6); // coarse so wireframe reads as lines, not a blob
  const cylGeo = new THREE.CylinderGeometry(0.05, 0.075, 1, 8);
  const tetraGeo = new THREE.TetrahedronGeometry(1, 0);
  const ringGeo = new THREE.RingGeometry(1, 1.12, 48);

  const matScattered = new THREE.MeshStandardMaterial({ color: 0x8a8a8a, roughness: 0.55 });
  const matAssigned = new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.5 });
  const matGhostCard = new THREE.MeshStandardMaterial({
    color: 0xc89418,
    roughness: 0.55,
    transparent: true,
    opacity: 0.45,
  });
  const tetherMat = new THREE.LineBasicMaterial({ color: 0xc89418, transparent: true, opacity: 0.35 });
  const matBranch = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.5, metalness: 0.05 });
  const matTrunk = new THREE.MeshStandardMaterial({ color: 0x666666, roughness: 0.6 });
  const matWire = new THREE.MeshStandardMaterial({ color: 0x111111, wireframe: true, transparent: true, opacity: 0.5 });
  const trunkLineMat = new THREE.LineBasicMaterial({ color: 0xb5b5b5, transparent: true, opacity: 0.85 });

  // ─── Co-access edges: single LineSegments ─────────────────────
  const pairCount = timeline.pairCount;
  const edgePositions = new Float32Array(pairCount * 2 * 3);
  const edgeColors = new Float32Array(pairCount * 2 * 3).fill(1); // start white (invisible)
  const edgeGeo = new THREE.BufferGeometry();
  edgeGeo.setAttribute("position", new THREE.BufferAttribute(edgePositions, 3));
  edgeGeo.setAttribute("color", new THREE.BufferAttribute(edgeColors, 3));
  edgeGeo.setDrawRange(0, pairCount * 2);
  const edgeLines = new THREE.LineSegments(
    edgeGeo,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.42 })
  );
  edgeLines.frustumCulled = false;
  scene.add(edgeLines);

  const edgeCurrent = new Float32Array(pairCount).fill(0); // current displayed strength 0..1

  function strengthFor(weight) {
    // Slightly superlinear so weak pairs stay faint and the threshold pops
    return Math.pow(Math.min(1, weight / timeline.threshold), 1.15);
  }

  function writeEdgeColor(idx, s) {
    edgeCurrent[idx] = s;
    const c = new THREE.Color().copy(WHITE).lerp(GOLD, s);
    const o = idx * 6;
    edgeColors[o] = c.r;
    edgeColors[o + 1] = c.g;
    edgeColors[o + 2] = c.b;
    edgeColors[o + 3] = c.r;
    edgeColors[o + 4] = c.g;
    edgeColors[o + 5] = c.b;
  }

  // ─── Registries ───────────────────────────────────────────────
  const pointers = new Map(); // pid -> { mesh, label, home, state, flying, bobPhase }
  const branches = new Map(); // uid -> { group, sphere, label, trunkLine, treeUid, name, size }
  const trees = new Map(); // uid -> { group, trunk, rootWire, core, label, sublabel, label as text }
  const ghosts = new Map(); // "pid|branchUid" -> { mesh, tether, pid, branchUid }

  // Create all pointers up-front at their scatter homes
  for (const [pid, ptr] of Object.entries(POINTER_MAP)) {
    const home = timelineScatterHome(pid);
    const mesh = new THREE.Mesh(sphereGeo, matScattered);
    mesh.scale.setScalar(DEMO_GEOM.POINTER_R);
    mesh.position.set(home[0], home[1], home[2]);
    scene.add(mesh);

    const label = makeLabel(ptr.label, {
      fontSize: 34,
      color: "#777777",
      scale: [2.4, 0.6, 1],
      opacity: 0.55,
    });
    label.position.set(home[0], home[1] + 0.55, home[2]);
    scene.add(label);

    pointers.set(pid, {
      mesh,
      label,
      home,
      state: "scattered",
      flying: false,
      bobPhase: Math.random() * Math.PI * 2,
    });
  }

  function timelineScatterHome(pid) {
    // Scatter homes are baked into the timeline layout via structure
    // snapshots only for assigned pointers; for homes we use the layout's
    // deterministic generator exposed through timeline.scatterHomes.
    return timeline.scatterHomes[pid];
  }

  // ─── Pointer motion ───────────────────────────────────────────

  function flyPointer(pid, to, { duration = 0.7, delay = 0, arc = 1.6, onDone } = {}) {
    const p = pointers.get(pid);
    if (!p) return;
    tweens.killByTag(`ptr:${pid}`);
    p.flying = true;
    const from = p.mesh.position.clone();
    const target = new THREE.Vector3(to[0], to[1], to[2]);
    tweens.add({
      duration,
      delay,
      ease: "easeInOutQuad",
      tag: `ptr:${pid}`,
      onUpdate: (k) => {
        p.mesh.position.lerpVectors(from, target, k);
        p.mesh.position.y += Math.sin(k * Math.PI) * arc;
        p.label.position.set(p.mesh.position.x, p.mesh.position.y + 0.55, p.mesh.position.z);
      },
      onComplete: () => {
        p.flying = false;
        p.mesh.position.copy(target);
        p.label.position.set(target.x, target.y + 0.55, target.z);
        if (onDone) onDone();
      },
    });
  }

  function pulsePointer(pid, intensity = 1.7) {
    const p = pointers.get(pid);
    if (!p) return;
    const base = p.state === "assigned" ? DEMO_GEOM.POINTER_R * 0.8 : DEMO_GEOM.POINTER_R;
    tweens.killByTag(`pulse:${pid}`);
    tweens.add({
      duration: 0.45,
      tag: `pulse:${pid}`,
      ease: "easeOutCubic",
      onUpdate: (k) => {
        const s = base * (1 + (intensity - 1) * Math.sin(k * Math.PI));
        p.mesh.scale.setScalar(s);
      },
      onComplete: () => p.mesh.scale.setScalar(base),
    });
  }

  function setPointerState(pid, state) {
    const p = pointers.get(pid);
    if (!p) return;
    p.state = state;
    p.mesh.material = state === "assigned" ? matAssigned : matScattered;
    p.mesh.scale.setScalar(state === "assigned" ? DEMO_GEOM.POINTER_R * 0.8 : DEMO_GEOM.POINTER_R);
    tweens.add({
      duration: 0.4,
      tag: `ptrlabel:${pid}`,
      onUpdate: (k) => {
        const target = state === "assigned" ? 0.14 : 0.55;
        p.label.material.opacity += (target - p.label.material.opacity) * k;
      },
    });
  }

  // ─── Branch / tree builders ───────────────────────────────────

  function branchScale(size) {
    return DEMO_GEOM.BRANCH_R * (0.75 + 0.28 * Math.sqrt(size));
  }

  function ensureBranch(uid, ev, animate) {
    let b = branches.get(uid);
    if (b) return b;

    const group = new THREE.Group();
    group.position.set(ev.world[0], ev.world[1], ev.world[2]);
    scene.add(group);

    const sphere = new THREE.Mesh(sphereGeo, matBranch);
    sphere.scale.setScalar(animate ? 0.001 : branchScale(ev.size));
    group.add(sphere);

    const label = makeLabel(ev.name, { fontSize: 42, color: "#111111", scale: [3.4, 0.85, 1], opacity: animate ? 0 : 0.95 });
    label.position.set(0, 0.85, 0);
    group.add(label);

    // Trunk-top to branch line
    const treePos = treePosOf(ev.treeUid);
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(treePos[0], treePos[1] + DEMO_GEOM.TRUNK_H, treePos[2]),
      new THREE.Vector3(ev.world[0], ev.world[1], ev.world[2]),
    ]);
    const trunkLine = new THREE.Line(lineGeo, trunkLineMat.clone());
    trunkLine.material.opacity = animate ? 0 : 0.85;
    scene.add(trunkLine);

    b = { group, sphere, label, trunkLine, treeUid: ev.treeUid, name: ev.name, size: ev.size };
    branches.set(uid, b);

    if (animate) {
      tweens.add({
        duration: 0.55,
        ease: "easeOutBack",
        tag: `branch:${uid}`,
        onUpdate: (k) => sphere.scale.setScalar(Math.max(0.001, branchScale(ev.size) * k)),
      });
      tweens.add({
        duration: 0.6,
        delay: 0.25,
        tag: `branch:${uid}`,
        onUpdate: (k) => {
          b.label.material.opacity = 0.95 * k;
          b.trunkLine.material.opacity = 0.85 * k;
        },
      });
    }
    return b;
  }

  function updateTrunkLine(b) {
    const treePos = treePosOf(b.treeUid);
    const arr = b.trunkLine.geometry.attributes.position.array;
    arr[0] = treePos[0];
    arr[1] = treePos[1] + DEMO_GEOM.TRUNK_H;
    arr[2] = treePos[2];
    arr[3] = b.group.position.x;
    arr[4] = b.group.position.y;
    arr[5] = b.group.position.z;
    b.trunkLine.geometry.attributes.position.needsUpdate = true;
  }

  function removeBranch(uid, animate) {
    const b = branches.get(uid);
    if (!b) return;
    branches.delete(uid);
    tweens.killByTag(`branch:${uid}`);
    // Ghost cards living on this branch go with it
    for (const [key, g] of [...ghosts]) {
      if (g.branchUid === uid) removeGhost(key, false);
    }
    const finish = () => {
      scene.remove(b.group);
      scene.remove(b.trunkLine);
      disposeLabel(b.label);
      b.trunkLine.geometry.dispose();
      b.trunkLine.material.dispose();
    };
    if (animate) {
      const s0 = b.sphere.scale.x;
      tweens.add({
        duration: 0.5,
        tag: `branchout:${uid}`,
        onUpdate: (k) => {
          b.sphere.scale.setScalar(Math.max(0.001, s0 * (1 - k)));
          b.label.material.opacity = 0.95 * (1 - k);
          b.trunkLine.material.opacity = 0.85 * (1 - k);
        },
        onComplete: finish,
      });
    } else {
      finish();
    }
  }

  function treePosOf(treeUid) {
    const t = trees.get(treeUid);
    if (t) return t.pos;
    return [0, 0, 0];
  }

  // ─── Ghost cards (multi-cluster membership) ───────────────────
  // A card's primary instance lives at its branch satellite; when it also
  // belongs to another cluster, a translucent gold copy sits on that branch,
  // tethered to the primary card.

  function ensureGhost(pid, branchUid, local, animate) {
    const key = `${pid}|${branchUid}`;
    if (ghosts.has(key)) return ghosts.get(key);
    const b = branches.get(branchUid);
    const p = pointers.get(pid);
    if (!b || !p) return null;

    const mesh = new THREE.Mesh(sphereGeo, matGhostCard);
    mesh.scale.setScalar(animate ? 0.001 : DEMO_GEOM.POINTER_R * 0.7);
    b.group.add(mesh);

    const tetherGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(),
    ]);
    const tether = new THREE.Line(tetherGeo, tetherMat);
    tether.frustumCulled = false;
    scene.add(tether);

    const g = { mesh, tether, pid, branchUid };
    ghosts.set(key, g);

    if (animate) {
      // Spawn at the primary card and split off toward the ghost slot
      const startLocal = b.group.worldToLocal(p.mesh.position.clone());
      mesh.position.copy(startLocal);
      const target = new THREE.Vector3(local[0], local[1], local[2]);
      tweens.add({
        duration: 0.7,
        ease: "easeInOutQuad",
        tag: `ghost:${key}`,
        onUpdate: (k) => {
          mesh.position.lerpVectors(startLocal, target, k);
          mesh.scale.setScalar(Math.max(0.001, DEMO_GEOM.POINTER_R * 0.7 * Math.min(1, k * 2)));
        },
        onComplete: () => mesh.position.copy(target),
      });
    } else {
      mesh.position.set(local[0], local[1], local[2]);
    }
    return g;
  }

  function removeGhost(key, animate) {
    const g = ghosts.get(key);
    if (!g) return;
    ghosts.delete(key);
    tweens.killByTag(`ghost:${key}`);
    const finish = () => {
      g.mesh.parent?.remove(g.mesh);
      scene.remove(g.tether);
      g.tether.geometry.dispose();
    };
    if (animate) {
      const s0 = g.mesh.scale.x;
      tweens.add({
        duration: 0.4,
        tag: `ghostout:${key}`,
        onUpdate: (k) => g.mesh.scale.setScalar(Math.max(0.001, s0 * (1 - k))),
        onComplete: finish,
      });
    } else {
      finish();
    }
  }

  function ensureTree(uid, ev, animate) {
    let t = trees.get(uid);
    if (t) return t;

    const group = new THREE.Group();
    group.position.set(ev.pos[0], ev.pos[1], ev.pos[2]);
    scene.add(group);

    const trunk = new THREE.Mesh(cylGeo, matTrunk);
    trunk.scale.set(1, animate ? 0.001 : DEMO_GEOM.TRUNK_H, 1);
    trunk.position.y = animate ? 0 : DEMO_GEOM.TRUNK_H / 2;
    group.add(trunk);

    const rootWire = new THREE.Mesh(ev.treeType === "system" ? tetraGeo : wireSphereGeo, matWire);
    rootWire.scale.setScalar(animate ? 0.001 : DEMO_GEOM.ROOT_R);
    group.add(rootWire);

    const core = new THREE.Mesh(sphereGeo, matBranch);
    core.scale.setScalar(DEMO_GEOM.ROOT_R * 0.35);
    group.add(core);

    const label = makeLabel(ev.label, { fontSize: 54, color: "#000000", scale: [4.6, 1.15, 1], opacity: animate ? 0 : 0.95 });
    label.position.y = DEMO_GEOM.TRUNK_H + 3.1;
    group.add(label);

    t = { group, trunk, rootWire, core, label, pos: ev.pos, labelText: ev.label };
    trees.set(uid, t);

    if (animate) {
      tweens.add({
        duration: 0.9,
        ease: "easeOutCubic",
        tag: `tree:${uid}`,
        onUpdate: (k) => {
          trunk.scale.y = Math.max(0.001, DEMO_GEOM.TRUNK_H * k);
          trunk.position.y = (DEMO_GEOM.TRUNK_H * k) / 2;
        },
      });
      tweens.add({
        duration: 0.6,
        delay: 0.3,
        ease: "easeOutBack",
        tag: `tree:${uid}`,
        onUpdate: (k) => rootWire.scale.setScalar(Math.max(0.001, DEMO_GEOM.ROOT_R * k)),
      });
      tweens.add({
        duration: 0.5,
        delay: 0.55,
        tag: `tree:${uid}`,
        onUpdate: (k) => (label.material.opacity = 0.95 * k),
      });
      ringPulse(ev.pos);
    }
    return t;
  }

  function removeTree(uid, animate) {
    const t = trees.get(uid);
    if (!t) return;
    trees.delete(uid);
    tweens.killByTag(`tree:${uid}`);
    const finish = () => {
      scene.remove(t.group);
      disposeLabel(t.label);
    };
    if (animate) {
      tweens.add({
        duration: 0.6,
        tag: `treeout:${uid}`,
        onUpdate: (k) => {
          const s = 1 - k;
          t.trunk.scale.y = Math.max(0.001, DEMO_GEOM.TRUNK_H * s);
          t.trunk.position.y = (DEMO_GEOM.TRUNK_H * s) / 2;
          t.rootWire.scale.setScalar(Math.max(0.001, DEMO_GEOM.ROOT_R * s));
          t.label.material.opacity = 0.95 * s;
        },
        onComplete: finish,
      });
    } else {
      finish();
    }
  }

  function ringPulse(pos) {
    const mat = new THREE.MeshBasicMaterial({
      color: 0x444444,
      transparent: true,
      opacity: 0.5,
      side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, mat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(pos[0], 0.02, pos[2]);
    ring.scale.setScalar(0.6);
    scene.add(ring);
    tweens.add({
      duration: 1.1,
      ease: "easeOutCubic",
      onUpdate: (k) => {
        ring.scale.setScalar(0.6 + k * 4.5);
        mat.opacity = 0.5 * (1 - k);
      },
      onComplete: () => {
        scene.remove(ring);
        mat.dispose();
      },
    });
  }

  // ─── Comets ───────────────────────────────────────────────────
  const comets = [];
  for (let i = 0; i < COMET_POOL; i++) {
    const head = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: null, transparent: true, opacity: 0, depthTest: false })
    );
    head.scale.set(1.5, 1.5, 1);
    scene.add(head);

    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3), 3));
    trailGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3).fill(1), 3));
    const trail = new THREE.Line(
      trailGeo,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 })
    );
    trail.frustumCulled = false;
    trail.visible = false;
    scene.add(trail);

    comets.push({
      head,
      trail,
      active: false,
      t: 0,
      duration: 1,
      waypoints: [],
      color: new THREE.Color(0xffffff),
      pulsed: new Set(),
      startedAt: 0,
    });
  }

  function spawnComet(ev) {
    let c = comets.find((x) => !x.active);
    if (!c) {
      // Reuse the oldest active comet
      c = comets.reduce((a, b) => (a.startedAt < b.startedAt ? a : b));
      endComet(c);
    }
    c.active = true;
    c.t = 0;
    c.duration = ev.travel;
    c.waypoints = ev.pointerIds.filter((pid) => pointers.has(pid));
    if (c.waypoints.length < 2) {
      c.active = false;
      return;
    }
    c.color.set(ev.themeColor);
    c.head.material.map = headTexture(ev.themeColor);
    c.head.material.opacity = 0.95;
    c.trail.visible = true;
    c.pulsed = new Set();
    c.startedAt = performance.now();
  }

  function endComet(c) {
    c.active = false;
    c.head.material.opacity = 0;
    c.trail.visible = false;
  }

  const cometCurve = new THREE.CatmullRomCurve3([new THREE.Vector3(), new THREE.Vector3()]);

  function updateComet(c, dt) {
    c.t += dt;
    const k = c.t / c.duration;
    if (k >= 1.15) {
      endComet(c);
      return;
    }
    const pts = c.waypoints.map((pid) => pointers.get(pid).mesh.position);
    cometCurve.points = pts;
    const kk = Math.min(1, k);

    // Head
    const headPos = cometCurve.getPoint(kk);
    c.head.position.copy(headPos);
    c.head.position.y += 0.15;
    c.head.material.opacity = k > 1 ? Math.max(0, 0.95 * (1 - (k - 1) / 0.15)) : 0.95;

    // Trail: from kk-TRAIL back to kk, colors fading to white
    const posAttr = c.trail.geometry.attributes.position;
    const colAttr = c.trail.geometry.attributes.color;
    const tail = Math.max(0, kk - TRAIL_FRACTION);
    const tmp = new THREE.Vector3();
    for (let i = 0; i < TRAIL_POINTS; i++) {
      const f = i / (TRAIL_POINTS - 1);
      const u = tail + (kk - tail) * f;
      cometCurve.getPoint(Math.max(0, u), tmp);
      posAttr.array[i * 3] = tmp.x;
      posAttr.array[i * 3 + 1] = tmp.y + 0.12;
      posAttr.array[i * 3 + 2] = tmp.z;
      const fade = f * f; // strongest near the head
      colAttr.array[i * 3] = 1 + (c.color.r - 1) * fade;
      colAttr.array[i * 3 + 1] = 1 + (c.color.g - 1) * fade;
      colAttr.array[i * 3 + 2] = 1 + (c.color.b - 1) * fade;
    }
    posAttr.needsUpdate = true;
    colAttr.needsUpdate = true;

    // Pulse pointers as the head passes
    const n = c.waypoints.length;
    for (let i = 0; i < n; i++) {
      if (!c.pulsed.has(i) && kk >= i / (n - 1) - 0.02) {
        c.pulsed.add(i);
        pulsePointer(c.waypoints[i], 1.6);
      }
    }
  }

  // ─── Event playback ───────────────────────────────────────────

  function playEvent(ev) {
    switch (ev.type) {
      case "QUERY": {
        spawnComet(ev);
        // Edge strength updates land as the comet completes
        for (const [idx, w] of ev.deltas) {
          const from = edgeCurrent[idx];
          const to = strengthFor(w);
          if (to - from < 0.005) continue;
          tweens.add({
            duration: 0.35,
            delay: ev.travel * 0.7,
            tag: "edges",
            onUpdate: (k) => writeEdgeColor(idx, from + (to - from) * k),
          });
        }
        markEdgeColorsDirty();
        break;
      }
      case "TREE_FORMED":
        ensureTree(ev.treeUid, ev, true);
        break;
      case "TREE_RENAMED": {
        const t = trees.get(ev.treeUid);
        if (t && t.labelText !== ev.label) {
          t.labelText = ev.label;
          setLabelText(t.label, ev.label, 54, "#000000");
        }
        break;
      }
      case "TREE_DISSOLVED":
        removeTree(ev.treeUid, true);
        break;
      case "BRANCH_FORMED": {
        const b = ensureBranch(ev.branchUid, ev, true);
        let i = 0;
        for (const pid of ev.pointerIds) {
          pulsePointer(pid, 2.0);
          flyPointer(pid, ev.satellites[pid], { delay: 0.15 + i * 0.06 });
          setPointerState(pid, "assigned");
          i++;
        }
        b.size = ev.size;
        break;
      }
      case "BRANCH_GREW": {
        const b = branches.get(ev.branchUid);
        if (!b) break;
        b.size = ev.size;
        if (ev.name && b.name !== ev.name) {
          b.name = ev.name;
          setLabelText(b.label, ev.name, 42, "#111111");
        }
        const s0 = b.sphere.scale.x;
        const s1 = branchScale(ev.size);
        tweens.add({
          duration: 0.45,
          ease: "easeOutBack",
          tag: `branch:${ev.branchUid}`,
          onUpdate: (k) => b.sphere.scale.setScalar(s0 + (s1 - s0) * k),
        });
        let i = 0;
        for (const pid of ev.addedPointerIds) {
          pulsePointer(pid, 1.9);
          flyPointer(pid, ev.satellites[pid], { delay: 0.1 + i * 0.06 });
          setPointerState(pid, "assigned");
          i++;
        }
        break;
      }
      case "BRANCH_RENAMED": {
        const b = branches.get(ev.branchUid);
        if (b && b.name !== ev.name) {
          b.name = ev.name;
          setLabelText(b.label, ev.name, 42, "#111111");
        }
        break;
      }
      case "BRANCH_MOVED_TREE": {
        const b = branches.get(ev.branchUid);
        if (!b) break;
        b.treeUid = ev.treeUid;
        const from = b.group.position.clone();
        const to = new THREE.Vector3(ev.world[0], ev.world[1], ev.world[2]);
        tweens.add({
          duration: 0.8,
          ease: "easeInOutQuad",
          tag: `branch:${ev.branchUid}`,
          onUpdate: (k) => {
            b.group.position.lerpVectors(from, to, k);
            updateTrunkLine(b);
          },
        });
        for (const pid of ev.pointerIds) {
          flyPointer(pid, ev.satellites[pid], { duration: 0.8, arc: 0.6 });
        }
        break;
      }
      case "BRANCH_DISSOLVED":
        removeBranch(ev.branchUid, true);
        break;
      case "POINTERS_RELEASED": {
        for (const pid of ev.pointerIds) {
          const p = pointers.get(pid);
          if (!p) continue;
          setPointerState(pid, "scattered");
          flyPointer(pid, p.home, { duration: 0.9, arc: 1.2 });
        }
        break;
      }
      case "POINTER_LINKED": {
        ensureGhost(ev.pointerId, ev.branchUid, ev.local, true);
        pulsePointer(ev.pointerId, 2.0);
        break;
      }
      case "POINTER_UNLINKED":
        removeGhost(`${ev.pointerId}|${ev.branchUid}`, true);
        break;
      default:
        break; // PHASE handled by the HUD
    }
  }

  function markEdgeColorsDirty() {
    edgeGeo.attributes.color.needsUpdate = true;
  }

  // ─── Snap (scrub) ─────────────────────────────────────────────

  function snapTo(stepCount) {
    tweens.clear();
    for (const c of comets) endComet(c);

    const snap = timeline.snapshotAt(stepCount);
    const structure = snap.structure;

    const wantTrees = new Map();
    const wantBranches = new Map();
    const assignedPos = new Map(); // pid -> [x,y,z]

    if (structure) {
      for (const t of structure.trees) wantTrees.set(t.uid, t);
      for (const b of structure.branches) {
        wantBranches.set(b.uid, b);
        for (const pid of b.pointerIds) assignedPos.set(pid, b.satellites[pid]);
      }
    }

    // Trees
    for (const uid of [...trees.keys()]) {
      if (!wantTrees.has(uid)) removeTree(uid, false);
    }
    for (const [uid, t] of wantTrees) {
      const existing = trees.get(uid);
      if (!existing) {
        ensureTree(uid, { pos: t.pos, label: t.label, treeType: t.treeType, treeUid: uid }, false);
      } else if (existing.labelText !== t.label) {
        existing.labelText = t.label;
        setLabelText(existing.label, t.label, 54, "#000000");
      }
      // Restore full-grown state in case a formation tween was interrupted
      const tt = trees.get(uid);
      tt.trunk.scale.y = DEMO_GEOM.TRUNK_H;
      tt.trunk.position.y = DEMO_GEOM.TRUNK_H / 2;
      tt.rootWire.scale.setScalar(DEMO_GEOM.ROOT_R);
      tt.label.material.opacity = 0.95;
    }

    // Branches
    for (const uid of [...branches.keys()]) {
      if (!wantBranches.has(uid)) removeBranch(uid, false);
    }
    for (const [uid, b] of wantBranches) {
      let existing = branches.get(uid);
      if (!existing) {
        existing = ensureBranch(
          uid,
          { world: b.world, name: b.name, treeUid: b.treeUid, size: b.pointerIds.length },
          false
        );
      }
      existing.treeUid = b.treeUid;
      existing.size = b.pointerIds.length;
      existing.group.position.set(b.world[0], b.world[1], b.world[2]);
      existing.sphere.scale.setScalar(branchScale(b.pointerIds.length));
      existing.label.material.opacity = 0.95;
      existing.trunkLine.material.opacity = 0.85;
      if (existing.name !== b.name) {
        existing.name = b.name;
        setLabelText(existing.label, b.name, 42, "#111111");
      }
      updateTrunkLine(existing);
    }

    // Pointers
    for (const [pid, p] of pointers) {
      const pos = assignedPos.get(pid);
      p.flying = false;
      if (pos) {
        p.state = "assigned";
        p.mesh.material = matAssigned;
        p.mesh.scale.setScalar(DEMO_GEOM.POINTER_R * 0.8);
        p.mesh.position.set(pos[0], pos[1], pos[2]);
        p.label.material.opacity = 0.14;
      } else {
        p.state = "scattered";
        p.mesh.material = matScattered;
        p.mesh.scale.setScalar(DEMO_GEOM.POINTER_R);
        p.mesh.position.set(p.home[0], p.home[1], p.home[2]);
        p.label.material.opacity = 0.55;
      }
      p.label.position.set(p.mesh.position.x, p.mesh.position.y + 0.55, p.mesh.position.z);
    }

    // Ghosts (multi-cluster cards)
    const wantGhosts = new Map();
    if (structure) {
      for (const sec of structure.secondaries || []) {
        wantGhosts.set(`${sec.pid}|${sec.branchUid}`, sec);
      }
    }
    for (const key of [...ghosts.keys()]) {
      if (!wantGhosts.has(key)) removeGhost(key, false);
    }
    for (const [key, sec] of wantGhosts) {
      const existing = ghosts.get(key);
      if (existing) {
        existing.mesh.position.set(sec.local[0], sec.local[1], sec.local[2]);
        existing.mesh.scale.setScalar(DEMO_GEOM.POINTER_R * 0.7);
      } else {
        ensureGhost(sec.pid, sec.branchUid, sec.local, false);
      }
    }

    // Edges
    for (let i = 0; i < pairCount; i++) {
      const w = snap.weights.get(i) || 0;
      writeEdgeColor(i, strengthFor(w));
    }
    markEdgeColorsDirty();
  }

  // ─── Per-frame update ─────────────────────────────────────────

  function update(dt, elapsed) {
    // Bobbing for scattered pointers
    for (const p of pointers.values()) {
      if (p.state === "scattered" && !p.flying) {
        const y = p.home[1] + Math.sin(elapsed * 1.1 + p.bobPhase) * 0.07;
        p.mesh.position.y = y;
        p.label.position.y = y + 0.55;
      }
    }

    // Comets
    for (const c of comets) {
      if (c.active) updateComet(c, dt);
    }

    // Ghost tethers track both endpoints
    if (ghosts.size > 0) {
      const gw = new THREE.Vector3();
      for (const g of ghosts.values()) {
        const p = pointers.get(g.pid);
        if (!p) continue;
        g.mesh.getWorldPosition(gw);
        const arr = g.tether.geometry.attributes.position.array;
        arr[0] = gw.x;
        arr[1] = gw.y;
        arr[2] = gw.z;
        arr[3] = p.mesh.position.x;
        arr[4] = p.mesh.position.y;
        arr[5] = p.mesh.position.z;
        g.tether.geometry.attributes.position.needsUpdate = true;
      }
    }

    // Edge endpoints follow pointer positions
    const ends = timeline.pairEndpoints;
    for (let i = 0; i < pairCount; i++) {
      if (edgeCurrent[i] <= 0.01) continue;
      const a = pointers.get(ends[i][0]);
      const b = pointers.get(ends[i][1]);
      if (!a || !b) continue;
      const o = i * 6;
      edgePositions[o] = a.mesh.position.x;
      edgePositions[o + 1] = a.mesh.position.y;
      edgePositions[o + 2] = a.mesh.position.z;
      edgePositions[o + 3] = b.mesh.position.x;
      edgePositions[o + 4] = b.mesh.position.y;
      edgePositions[o + 5] = b.mesh.position.z;
    }
    edgeGeo.attributes.position.needsUpdate = true;

    // Particle drift
    const pp = particles.geometry.attributes.position.array;
    for (let i = 1; i < pp.length; i += 3) {
      pp[i] += Math.sin(elapsed * 0.6 + pp[i - 1]) * 0.0015;
    }
    particles.geometry.attributes.position.needsUpdate = true;
  }

  function render() {
    renderer.render(scene, camera);
  }

  function resize(w, h) {
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function treeCount() {
    return trees.size;
  }

  function dispose() {
    tweens.clear();
    scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        for (const m of mats) {
          if (m.map) m.map.dispose();
          m.dispose();
        }
      }
    });
    for (const tex of headTextureCache.values()) tex.dispose();
    headTextureCache.clear();
    renderer.dispose();
  }

  return {
    camera,
    playEvent,
    snapTo,
    update,
    render,
    resize,
    treeCount,
    dispose,
  };
}
