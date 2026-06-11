/**
 * Split-screen demo scene: Kibo (left, static) vs Nzyme (right, animated).
 * Uses dual viewports via renderer.setScissor/setViewport.
 */
import * as THREE from "three";
import { TREES as KIBO_TREES, NODE_R, BRANCH_R, LEAF_R, TRUNK_H, BRANCH_LEN } from "../data/trees";
import { POINTER_MAP } from "../demo/knowledgeGraph";

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

// Shared geometries (reused across scenes; disposed only on full teardown)
const sphereGeo = new THREE.SphereGeometry(1, 20, 14);
const cylGeo = new THREE.CylinderGeometry(0.035, 0.05, 1, 8);
const tetraGeo = new THREE.TetrahedronGeometry(1, 0);
const sharedGeos = new Set([sphereGeo, cylGeo, tetraGeo]);

function typeGeo(type) {
  if (type === "system") return tetraGeo;
  return sphereGeo;
}

/**
 * Build a forest scene from a TREES array. Returns the scene + metadata.
 * Used for both left (Kibo) and right (Nzyme) viewports.
 */
function buildForestScene(trees, options = {}) {
  const scene = new THREE.Scene();
  const dimFactor = options.dimmed ? 0.4 : 1.0;

  // Lights
  const ambient = new THREE.AmbientLight(0xffffff, 0.35 * dimFactor);
  scene.add(ambient);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8 * dimFactor);
  dir.position.set(5, 12, 8);
  scene.add(dir);
  const point = new THREE.PointLight(0xffffff, 0.4 * dimFactor, 40);
  point.position.set(-4, 8, -4);
  scene.add(point);

  // Grid
  const gridGroup = new THREE.Group();
  const gridSize = 80;
  const gridDiv = 80;
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
  const gridMat = new THREE.LineBasicMaterial({ color: 0xdddddd, transparent: true, opacity: 0.6 });
  gridGroup.add(new THREE.LineSegments(gridGeo, gridMat));
  scene.add(gridGroup);

  // Materials
  const matWhite = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.5, metalness: 0.05 });
  const matGhost = new THREE.MeshStandardMaterial({ color: 0x666666, roughness: 0.6, metalness: 0.0 });
  const matWire = new THREE.MeshStandardMaterial({ color: 0x111111, wireframe: true, transparent: true, opacity: 0.55 });
  const lineMat = new THREE.LineBasicMaterial({ color: 0xbbbbbb, transparent: true, opacity: 0.85 });
  const linkMat = new THREE.LineDashedMaterial({ color: 0x888888, dashSize: 0.25, gapSize: 0.15, transparent: true, opacity: 0.5 });

  const treeGroups = {};
  const branchGroups = {};
  const branchPositions = {};
  const branchLabels = {};

  // Build trees
  trees.forEach((tree) => {
    const group = new THREE.Group();
    const base = new THREE.Vector3(tree.pos[0], tree.pos[1] || 0, tree.pos[2]);
    group.position.copy(base);
    scene.add(group);
    treeGroups[tree.id] = group;

    // Root node
    const rootMesh = new THREE.Mesh(typeGeo(tree.type), matWire);
    rootMesh.scale.setScalar(NODE_R * 3.2);
    group.add(rootMesh);

    const core = new THREE.Mesh(sphereGeo, matWhite);
    core.scale.setScalar(NODE_R);
    group.add(core);

    // Trunk
    const trunk = new THREE.Mesh(cylGeo, matGhost);
    trunk.scale.set(1, TRUNK_H, 1);
    trunk.position.set(0, TRUNK_H / 2, 0);
    group.add(trunk);

    const trunkTop = new THREE.Vector3(0, TRUNK_H, 0);

    // Branches
    const branchCount = tree.branches.length;
    tree.branches.forEach((br, bi) => {
      const angle = (bi / branchCount) * Math.PI * 2;
      const elevation = 0.6 + (bi % 3) * 0.45;
      const bDir = new THREE.Vector3(
        Math.cos(angle) * BRANCH_LEN,
        elevation,
        Math.sin(angle) * BRANCH_LEN
      );
      const bp = trunkTop.clone().add(bDir);

      const bGroup = new THREE.Group();
      bGroup.position.copy(bp);
      group.add(bGroup);
      branchGroups[br.id] = bGroup;

      // Branch sphere
      const bMesh = new THREE.Mesh(sphereGeo, matWhite);
      bMesh.scale.setScalar(BRANCH_R);
      bGroup.add(bMesh);

      // Line from trunk to branch
      const lineGeo = new THREE.BufferGeometry().setFromPoints([trunkTop, bp]);
      group.add(new THREE.Line(lineGeo, lineMat));

      // World position for cross-links
      branchPositions[br.id] = bp.clone().add(base);

      // Branch label
      const nameLabel = makeLabel(br.name, new THREE.Vector3(0, BRANCH_R + 0.25, 0), 44, "#222222");
      bGroup.add(nameLabel);
      branchLabels[br.id] = nameLabel;

      // Leaves
      const leafCount = (br.leaves || []).length;
      if (leafCount > 0) {
        const outward = bDir.clone().normalize();
        const up = new THREE.Vector3(0, 1, 0);
        const side = new THREE.Vector3().crossVectors(outward, up).normalize();
        const top = new THREE.Vector3().crossVectors(side, outward).normalize();

        for (let li = 0; li < leafCount; li++) {
          const tAngle = (li / Math.max(leafCount, 1)) * Math.PI * 2;
          const tRad = 0.45 + (li % 2) * 0.1;
          const lp = new THREE.Vector3()
            .addScaledVector(side, Math.cos(tAngle) * tRad)
            .addScaledVector(top, Math.sin(tAngle) * tRad + 0.1)
            .addScaledVector(outward, 0.2);

          const leafMesh = new THREE.Mesh(sphereGeo, matGhost);
          leafMesh.scale.setScalar(LEAF_R);
          leafMesh.position.copy(lp);
          bGroup.add(leafMesh);

          const leafLine = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), lp]);
          bGroup.add(new THREE.Line(leafLine, lineMat));
        }
      }
    });
  });

  // Cross-links
  const crossLinks = [];
  trees.forEach((tree) => {
    tree.branches.forEach((br) => {
      const selfPos = branchPositions[br.id];
      if (!selfPos || !br.links) return;
      br.links.forEach((link) => {
        const targetPos = branchPositions[link.id];
        if (!targetPos) return;
        const dist = selfPos.distanceTo(targetPos);
        const mid = selfPos.clone().add(targetPos).multiplyScalar(0.5);
        mid.y += Math.min(3, dist * 0.25);
        const curve = new THREE.QuadraticBezierCurve3(selfPos, mid, targetPos);
        const pts = curve.getPoints(28);
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const line = new THREE.Line(geo, linkMat);
        line.computeLineDistances();
        scene.add(line);
        crossLinks.push(line);
      });
    });
  });

  // Tree labels
  trees.forEach((tree) => {
    const base = new THREE.Vector3(tree.pos[0], 0, tree.pos[2]);
    scene.add(makeLabel(tree.subtitle, base.clone().add(new THREE.Vector3(0, TRUNK_H + 1.6, 0)), 56, "#000000", [3.5, 0.9, 1]));
    scene.add(makeLabel(tree.label, base.clone().add(new THREE.Vector3(0, TRUNK_H + 2.1, 0)), 36, "#555555", [2.8, 0.7, 1]));
  });

  // Particles
  const particleCount = 120;
  const pGeo = new THREE.BufferGeometry();
  const pPositions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i++) {
    pPositions[i * 3] = (Math.random() - 0.5) * 60;
    pPositions[i * 3 + 1] = Math.random() * 6;
    pPositions[i * 3 + 2] = (Math.random() - 0.5) * 60;
  }
  pGeo.setAttribute("position", new THREE.Float32BufferAttribute(pPositions, 3));
  const pMat = new THREE.PointsMaterial({ color: 0xaaaaaa, size: 0.04, transparent: true, opacity: 0.5 });
  const particles = new THREE.Points(pGeo, pMat);
  scene.add(particles);

  return {
    scene,
    treeGroups,
    branchGroups,
    branchPositions,
    branchLabels,
    crossLinks,
    particles,
    gridGroup,
  };
}

/**
 * Build scattered pointer nodes for the empty-forest state (checkpoint 0).
 * Places 58 small spheres in a grid on the ground plane.
 */
function buildScatteredPointers(pointerIds) {
  const group = new THREE.Group();
  const positions = {};
  const cols = Math.ceil(Math.sqrt(pointerIds.length));

  const matNode = new THREE.MeshStandardMaterial({ color: 0x888888, roughness: 0.5 });

  pointerIds.forEach((pid, i) => {
    const row = Math.floor(i / cols);
    const col = i % cols;
    const x = (col - cols / 2) * 2.5;
    const z = (row - cols / 2) * 2.5;

    const mesh = new THREE.Mesh(sphereGeo, matNode);
    mesh.scale.setScalar(0.15);
    mesh.position.set(x, 0.15, z);
    group.add(mesh);

    // Label
    const ptr = POINTER_MAP[pid];
    if (ptr) {
      const label = makeLabel(ptr.label, new THREE.Vector3(x, 0.5, z), 32, "#999999", [2, 0.5, 1]);
      group.add(label);
    }

    positions[pid] = new THREE.Vector3(x, 0.15, z);
  });

  return { group, positions };
}

/**
 * Build the complete demo scene with dual viewports.
 */
export default function buildDemoScene(canvas, width, height) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xffffff);
  renderer.setScissorTest(true);

  // Two cameras
  const aspect = (width / 2) / height;
  const leftCamera = new THREE.PerspectiveCamera(50, aspect, 0.1, 500);
  leftCamera.position.set(0, 14, 16);
  leftCamera.lookAt(0, 0, 0);

  const rightCamera = new THREE.PerspectiveCamera(50, aspect, 0.1, 500);
  rightCamera.position.set(0, 14, 16);
  rightCamera.lookAt(0, 0, 0);

  // Left scene: Kibo (static, dimmed)
  const kiboScene = buildForestScene(KIBO_TREES, { dimmed: true });

  // Right scene: starts empty, will be rebuilt per checkpoint
  let nzymeScene = null;
  let scatteredPointers = null;

  // State
  const state = {
    nzymeTrees: [],
    nzymeSceneData: null,
  };

  /**
   * Set the Nzyme checkpoint data. Rebuilds the right scene.
   */
  function disposeSceneObjects(scene, preserveShared) {
    scene.traverse((obj) => {
      if (obj.geometry && !(preserveShared && sharedGeos.has(obj.geometry))) obj.geometry.dispose();
      if (obj.material) {
        if (Array.isArray(obj.material)) obj.material.forEach((m) => { if (m.map) m.map.dispose(); m.dispose(); });
        else { if (obj.material.map) obj.material.map.dispose(); obj.material.dispose(); }
      }
    });
  }

  function setCheckpoint(checkpoint) {
    // Clean up old Nzyme scene (preserve shared geometries used by Kibo)
    if (nzymeScene) {
      disposeSceneObjects(nzymeScene.scene, true);
    }
    if (scatteredPointers) {
      disposeSceneObjects(scatteredPointers.group, true);
      scatteredPointers = null;
    }

    state.nzymeTrees = checkpoint.trees;

    if (checkpoint.trees.length === 0) {
      // Empty state: show scattered pointers
      const emptyScene = new THREE.Scene();
      emptyScene.add(new THREE.AmbientLight(0xffffff, 0.35));
      const d = new THREE.DirectionalLight(0xffffff, 0.8);
      d.position.set(5, 12, 8);
      emptyScene.add(d);

      // Grid
      const gridSize = 80;
      const gridDiv = 80;
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
      emptyScene.add(new THREE.LineSegments(gridGeo, new THREE.LineBasicMaterial({ color: 0xdddddd, transparent: true, opacity: 0.6 })));

      scatteredPointers = buildScatteredPointers(checkpoint.unassignedPointers);
      emptyScene.add(scatteredPointers.group);

      nzymeScene = { scene: emptyScene };
    } else {
      // Build forest from checkpoint trees
      nzymeScene = buildForestScene(checkpoint.trees);

      // Add co-access lines for edges above threshold
      const coAccessGroup = new THREE.Group();
      const goldMat = new THREE.LineBasicMaterial({ color: 0xd4a017, transparent: true, opacity: 0.3 });

      for (const edge of checkpoint.coAccessEdges) {
        if (!edge.aboveThreshold) continue;
        const posA = nzymeScene.branchPositions[edge.a] || findPointerInBranches(checkpoint.trees, edge.a);
        const posB = nzymeScene.branchPositions[edge.b] || findPointerInBranches(checkpoint.trees, edge.b);
        if (!posA || !posB) continue;

        const geo = new THREE.BufferGeometry().setFromPoints([posA, posB]);
        const line = new THREE.Line(geo, goldMat);
        coAccessGroup.add(line);
      }
      nzymeScene.scene.add(coAccessGroup);
    }
  }

  // Helper: find a pointer's approximate position in a tree
  function findPointerInBranches(trees, pointerId) {
    for (const tree of trees) {
      for (const branch of tree.branches) {
        if (branch.pointerIds && branch.pointerIds.includes(pointerId)) {
          const bp = nzymeScene?.branchPositions?.[branch.id];
          if (bp) return bp;
        }
      }
    }
    return null;
  }

  /**
   * Render one frame (called from animation loop).
   */
  function render() {
    const w = renderer.domElement.width;
    const h = renderer.domElement.height;
    const halfW = Math.floor(w / 2);

    // Left viewport: Kibo
    renderer.setViewport(0, 0, halfW, h);
    renderer.setScissor(0, 0, halfW, h);
    renderer.render(kiboScene.scene, leftCamera);

    // Right viewport: Nzyme
    renderer.setViewport(halfW, 0, w - halfW, h);
    renderer.setScissor(halfW, 0, w - halfW, h);
    if (nzymeScene) {
      renderer.render(nzymeScene.scene, rightCamera);
    }
  }

  /**
   * Synchronize camera position for both viewports.
   */
  function setCameraPosition(position, lookAt) {
    leftCamera.position.copy(position);
    leftCamera.lookAt(lookAt);
    rightCamera.position.copy(position);
    rightCamera.lookAt(lookAt);
  }

  /**
   * Handle resize.
   */
  function resize(w, h) {
    renderer.setSize(w, h);
    const aspect = (w / 2) / h;
    leftCamera.aspect = aspect;
    leftCamera.updateProjectionMatrix();
    rightCamera.aspect = aspect;
    rightCamera.updateProjectionMatrix();
  }

  /**
   * Dispose everything.
   */
  function dispose() {
    [kiboScene, nzymeScene].forEach((s) => {
      if (!s) return;
      disposeSceneObjects(s.scene, false); // full teardown: dispose shared geos too
    });
    renderer.dispose();
  }

  return {
    renderer,
    leftCamera,
    rightCamera,
    kiboScene,
    render,
    setCameraPosition,
    setCheckpoint,
    resize,
    dispose,
  };
}
