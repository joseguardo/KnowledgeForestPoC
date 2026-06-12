/**
 * Directed camera for the Forest Creation demo.
 *
 * Ambient mode: slow auto-orbit around an "overview" goal that widens as the
 * forest grows. Featured events request shots (push-in on a forming branch /
 * tree); goals are reached with exponential damping. User drag/zoom takes
 * over instantly and the director eases back ~5s after the last interaction.
 */
import * as THREE from "three";

const DAMP = 2.6; // goal-chasing stiffness
const USER_COOLDOWN = 5; // seconds after last interaction before re-directing

export function createCameraDirector(camera) {
  const target = new THREE.Vector3(0, 1.5, 0);
  const targetGoal = new THREE.Vector3(0, 1.5, 0);
  const overviewTarget = new THREE.Vector3(0, 1.5, 0);

  const state = {
    radius: 34,
    radiusGoal: 34,
    overviewRadius: 34,
    phi: Math.PI / 3.2,
    phiGoal: Math.PI / 3.2,
    theta: 0.8,
    orbitSpeed: 0.07,
    shotUntil: -1,
    userUntil: -1,
    dragging: false,
    now: 0,
  };

  function setOverview({ radius, height }) {
    state.overviewRadius = radius;
    overviewTarget.y = height;
  }

  /** Push-in shot on a world position. Ignored while the user is in control. */
  function setShot(worldPos, radius, hold) {
    if (state.now < state.userUntil) return;
    targetGoal.set(worldPos[0], worldPos[1] * 0.6 + 1, worldPos[2]);
    state.radiusGoal = radius;
    state.phiGoal = Math.PI / 3.0;
    state.shotUntil = state.now + hold;
  }

  function userDrag(dx, dy) {
    state.userUntil = state.now + USER_COOLDOWN;
    state.theta -= dx * 0.005;
    state.phi = Math.max(0.15, Math.min(Math.PI / 2 - 0.05, state.phi - dy * 0.005));
  }

  function userZoom(deltaY) {
    state.userUntil = state.now + USER_COOLDOWN;
    state.radius = Math.max(12, Math.min(120, state.radius * Math.exp(deltaY * 0.001)));
  }

  function setDragging(d) {
    state.dragging = d;
    if (d) state.userUntil = state.now + USER_COOLDOWN;
  }

  /** Snap back to overview instantly (used on scrub). */
  function resetToOverview() {
    state.shotUntil = -1;
    state.userUntil = -1;
    targetGoal.copy(overviewTarget);
    state.radiusGoal = state.overviewRadius;
    target.copy(overviewTarget);
    state.radius = state.overviewRadius;
  }

  function update(dt, now) {
    state.now = now;
    const userActive = now < state.userUntil;

    if (!state.dragging) {
      state.theta += state.orbitSpeed * dt;
    }

    if (!userActive) {
      if (now > state.shotUntil) {
        targetGoal.copy(overviewTarget);
        state.radiusGoal = state.overviewRadius;
        state.phiGoal = Math.PI / 3.2;
      }
      const k = 1 - Math.exp(-DAMP * dt);
      target.lerp(targetGoal, k);
      state.radius += (state.radiusGoal - state.radius) * k;
      state.phi += (state.phiGoal - state.phi) * k;
    }

    const offset = new THREE.Vector3().setFromSpherical(
      new THREE.Spherical(state.radius, state.phi, state.theta)
    );
    camera.position.copy(target).add(offset);
    camera.lookAt(target);
  }

  return { setOverview, setShot, userDrag, userZoom, setDragging, resetToOverview, update };
}
