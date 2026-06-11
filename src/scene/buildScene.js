import * as THREE from "three";
import { HOUSES as DEFAULT_HOUSES, DB_TABLES, vec3, NODE_R, BRANCH_R, LEAF_R, TRUNK_H, BRANCH_LEN } from "../data/trees";

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

export default function buildScene(canvas, width, height, { trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES } = {}) {
  TREES = TREES || [];
  BRANCH_INDEX = BRANCH_INDEX || {};
  HOUSES = HOUSES || DEFAULT_HOUSES;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xffffff);

  const scene = new THREE.Scene();
  // No fog — keep uniform opacity at all distances

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 500);
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

  // Grid + axis wrapped in a group for toggling
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
  const gridMat = new THREE.LineBasicMaterial({ color: 0xdddddd, transparent: true, opacity: 0.8 });
  gridGroup.add(new THREE.LineSegments(gridGeo, gridMat));

  // Subtle axis lines
  const axisGeo = new THREE.BufferGeometry();
  axisGeo.setAttribute(
    "position",
    new THREE.Float32BufferAttribute([-half, -0.005, 0, half, -0.005, 0, 0, -0.005, -half, 0, -0.005, half], 3)
  );
  gridGroup.add(new THREE.LineSegments(axisGeo, new THREE.LineBasicMaterial({ color: 0xcccccc })));
  scene.add(gridGroup);

  // Materials
  const matWhite = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.5, metalness: 0.05 });
  const matGhost = new THREE.MeshStandardMaterial({ color: 0x666666, roughness: 0.6, metalness: 0.0 });
  const matWire = new THREE.MeshStandardMaterial({ color: 0x111111, wireframe: true, transparent: true, opacity: 0.55 });
  const lineMat = new THREE.LineBasicMaterial({ color: 0xbbbbbb, transparent: true, opacity: 0.85 });
  const linkMat = new THREE.LineDashedMaterial({ color: 0x888888, dashSize: 0.25, gapSize: 0.15, transparent: true, opacity: 0.7 });
  const intraLinkMat = new THREE.LineDashedMaterial({ color: 0xe04040, dashSize: 0.05, gapSize: 0.2, transparent: true, opacity: 0.85, linewidth: 2 });

  // Shared geos
  const sphereGeo = new THREE.SphereGeometry(1, 20, 14);
  const octaGeo = new THREE.OctahedronGeometry(1, 0);
  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  const tetraGeo = new THREE.TetrahedronGeometry(1, 0);
  const cylGeo = new THREE.CylinderGeometry(0.035, 0.05, 1, 8);

  // Collect positions for cross-branch links
  const branchPositions = {};
  const branchGroups = {};
  const branchLabels = {};
  const pickables = [];
  const treeGroups = {};

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
    if (type === "system") return tetraGeo;
    return sphereGeo;
  }

  // Build each tree
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

    // Branches fan out 360° from trunk top
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

      // Branch hit-proxy
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
      branchLabels[br.id] = nameLabel;

      // Leaves — properties of this instance
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

  // Cross-branch links (dashed arcs between instances)
  const crossLinks = [];
  TREES.forEach((tree) => {
    tree.branches.forEach((br) => {
      const selfPos = branchPositions[br.id];
      if (!selfPos || !br.links) return;
      br.links.forEach((link) => {
        const targetId = link.id;
        const targetPos = branchPositions[targetId];
        if (!targetPos) return;
        const dist = selfPos.distanceTo(targetPos);
        const mid = selfPos.clone().add(targetPos).multiplyScalar(0.5);
        mid.y += Math.min(3, dist * 0.25);
        const curve = new THREE.QuadraticBezierCurve3(selfPos, mid, targetPos);
        const pts = curve.getPoints(28);
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const isIntraTree = BRANCH_INDEX[targetId]?.tree.id === tree.id;
        const line = new THREE.Line(geo, isIntraTree ? intraLinkMat : linkMat);
        line.computeLineDistances();
        line.userData = { kind: "link", from: br.id, to: targetId };
        scene.add(line);
        crossLinks.push(line);
      });
    });
  });

  // Tree-level category labels
  const treeLabelSprites = {};
  TREES.forEach((tree) => {
    const base = vec3(tree.pos);
    const sub = makeLabel(tree.subtitle, base.clone().add(new THREE.Vector3(0, TRUNK_H + 1.6, 0)), 64, "#000000", [4, 1, 1]);
    const cat = makeLabel(tree.label,    base.clone().add(new THREE.Vector3(0, TRUNK_H + 2.15, 0)), 40, "#555555", [3.2, 0.8, 1]);
    scene.add(sub);
    scene.add(cat);
    treeLabelSprites[tree.id] = [sub, cat];
  });

  // Title
  const titleSprite = makeLabel("KNOWLEDGE FOREST", new THREE.Vector3(0, 8, -14), 56, "#aaaaaa");
  scene.add(titleSprite);

  // Houses — static data tables on the forest floor
  const HOUSE_W = 1.0;
  const HOUSE_H = 0.7;
  const ROOF_H = 0.5;
  const houseBodyGeo = new THREE.BoxGeometry(HOUSE_W, HOUSE_H, HOUSE_W);
  const houseRoofGeo = new THREE.ConeGeometry(HOUSE_W * 0.75, ROOF_H, 4);
  const matHouseBody = new THREE.MeshStandardMaterial({ color: 0x444444, roughness: 0.4, metalness: 0.1 });
  const matHouseRoof = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.3, metalness: 0.15 });
  const houseLinkMat = new THREE.LineDashedMaterial({ color: 0x999999, dashSize: 0.3, gapSize: 0.2, transparent: true, opacity: 0.5 });

  const houseGroups = {};
  const houseLinks = [];

  HOUSES.forEach((house) => {
    const group = new THREE.Group();
    const base = vec3(house.pos);
    group.position.copy(base);
    scene.add(group);
    houseGroups[house.id] = group;

    // Box body
    const body = new THREE.Mesh(houseBodyGeo, matHouseBody);
    body.position.set(0, HOUSE_H / 2, 0);
    body.userData = { houseId: house.id, kind: "house" };
    group.add(body);
    pickables.push(body);

    // Pyramid roof
    const roof = new THREE.Mesh(houseRoofGeo, matHouseRoof);
    roof.position.set(0, HOUSE_H + ROOF_H / 2, 0);
    roof.rotation.y = Math.PI / 4;
    roof.userData = { houseId: house.id, kind: "house" };
    group.add(roof);
    pickables.push(roof);

    // Invisible hitbox
    const hHit = new THREE.Mesh(
      new THREE.BoxGeometry(HOUSE_W * 1.6, HOUSE_H + ROOF_H + 0.5, HOUSE_W * 1.6),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    hHit.position.set(0, (HOUSE_H + ROOF_H) / 2, 0);
    hHit.userData = { houseId: house.id, kind: "houseHit" };
    group.add(hHit);
    pickables.push(hHit);

    // Label above house
    const label = makeLabel(house.name, new THREE.Vector3(0, HOUSE_H + ROOF_H + 0.5, 0), 40, "#333333", [3, 0.75, 1]);
    group.add(label);

    // Dashed lines to related trees
    const houseCenter = base.clone().add(new THREE.Vector3(0, HOUSE_H / 2, 0));
    house.relatedTrees.forEach((treeId) => {
      const treeData = TREES.find((t) => t.id === treeId);
      if (!treeData) return;
      const treeBase = vec3(treeData.pos);
      const treeCenter = treeBase.clone().add(new THREE.Vector3(0, TRUNK_H * 0.5, 0));
      const dist = houseCenter.distanceTo(treeCenter);
      const mid = houseCenter.clone().add(treeCenter).multiplyScalar(0.5);
      mid.y += Math.min(2, dist * 0.1);
      const curve = new THREE.QuadraticBezierCurve3(houseCenter, mid, treeCenter);
      const pts = curve.getPoints(20);
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const line = new THREE.Line(geo, houseLinkMat);
      line.computeLineDistances();
      line.userData = { kind: "houseLink", houseId: house.id, treeId };
      scene.add(line);
      houseLinks.push(line);
    });
  });

  // Database — knowledge forest DB on the forest floor
  const dbGroup = new THREE.Group();
  const dbBase = vec3(DB_TABLES.pos);
  dbGroup.position.copy(dbBase);
  scene.add(dbGroup);

  const dbBody = new THREE.Mesh(houseBodyGeo, matHouseBody);
  dbBody.position.set(0, HOUSE_H / 2, 0);
  dbBody.userData = { dbId: DB_TABLES.id, kind: "db" };
  dbGroup.add(dbBody);
  pickables.push(dbBody);

  const dbRoof = new THREE.Mesh(houseRoofGeo, matHouseRoof);
  dbRoof.position.set(0, HOUSE_H + ROOF_H / 2, 0);
  dbRoof.rotation.y = Math.PI / 4;
  dbRoof.userData = { dbId: DB_TABLES.id, kind: "db" };
  dbGroup.add(dbRoof);
  pickables.push(dbRoof);

  const dbHit = new THREE.Mesh(
    new THREE.BoxGeometry(HOUSE_W * 1.6, HOUSE_H + ROOF_H + 0.5, HOUSE_W * 1.6),
    new THREE.MeshBasicMaterial({ visible: false })
  );
  dbHit.position.set(0, (HOUSE_H + ROOF_H) / 2, 0);
  dbHit.userData = { dbId: DB_TABLES.id, kind: "dbHit" };
  dbGroup.add(dbHit);
  pickables.push(dbHit);

  const dbLabel = makeLabel(DB_TABLES.name, new THREE.Vector3(0, HOUSE_H + ROOF_H + 0.5, 0), 40, "#333333", [3, 0.75, 1]);
  dbGroup.add(dbLabel);

  const dbLinks = [];
  const dbCenter = dbBase.clone().add(new THREE.Vector3(0, HOUSE_H / 2, 0));
  DB_TABLES.relatedTrees.forEach((treeId) => {
    const treeData = TREES.find((t) => t.id === treeId);
    if (!treeData) return;
    const treeBase = vec3(treeData.pos);
    const treeCenter = treeBase.clone().add(new THREE.Vector3(0, TRUNK_H * 0.5, 0));
    const dist = dbCenter.distanceTo(treeCenter);
    const mid = dbCenter.clone().add(treeCenter).multiplyScalar(0.5);
    mid.y += Math.min(2, dist * 0.1);
    const curve = new THREE.QuadraticBezierCurve3(dbCenter, mid, treeCenter);
    const pts = curve.getPoints(20);
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const line = new THREE.Line(geo, houseLinkMat);
    line.computeLineDistances();
    line.userData = { kind: "dbLink", dbId: DB_TABLES.id, treeId };
    scene.add(line);
    dbLinks.push(line);
  });

  // Floating particles
  const particleCount = 200;
  const pGeo = new THREE.BufferGeometry();
  const pPositions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i++) {
    pPositions[i * 3] = (Math.random() - 0.5) * 60;
    pPositions[i * 3 + 1] = Math.random() * 6;
    pPositions[i * 3 + 2] = (Math.random() - 0.5) * 60;
  }
  pGeo.setAttribute("position", new THREE.Float32BufferAttribute(pPositions, 3));
  const pMat = new THREE.PointsMaterial({ color: 0xaaaaaa, size: 0.04, transparent: true, opacity: 0.7 });
  const particles = new THREE.Points(pGeo, pMat);
  scene.add(particles);

  return {
    renderer, scene, camera, particles, pickables,
    treeGroups, branchGroups, branchPositions, branchLabels,
    crossLinks, treeLabelSprites, titleSprite, gridGroup,
    houseGroups, houseLinks,
    dbGroup, dbLinks,
  };
}
