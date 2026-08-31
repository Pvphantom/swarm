// UI panels — upload, blueprint preview, and the live status HUD.
const $ = (id) => document.getElementById(id);

const BLOCK_HEX = { small_cube: "#4488ff", large_slab: "#ff6633", medium_brick: "#44ff88" };
const BLOCK_LABEL = { small_cube: "Small cube", large_slab: "Large slab", medium_brick: "Medium brick" };
const ROLE_LABEL = { small: "Small spec.", large: "Large spec.", generalist: "Generalist" };
const ROLE_HEX = { small: "#8cbcff", large: "#ffa680", generalist: "#d8d8ff" };

export function initUI(handlers) {
  let currentBlueprint = null;
  let started = false;

  const dropzone = $("dropzone");
  const fileInput = $("file-input");
  const cvStatus = $("cv-status");

  // ---- upload interactions ----
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault(); dropzone.classList.remove("drag");
    if (e.dataTransfer.files[0]) uploadImage(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", (e) => { if (e.target.files[0]) uploadImage(e.target.files[0]); });
  $("demo-btn").addEventListener("click", loadDemo);

  async function uploadImage(file) {
    cvStatus.textContent = "◇ Running CV pipeline (GPT-4o Vision)…";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: fd });
      const bp = await res.json();
      setBlueprint(bp);
      cvStatus.textContent = bp.source === "gpt-4o"
        ? "✓ Voxelized via GPT-4o Vision"
        : "✓ Voxelized (fallback demo — no OpenAI key)";
    } catch (e) {
      cvStatus.textContent = "✗ Upload failed: " + e.message;
    }
  }

  async function loadDemo() {
    cvStatus.textContent = "◇ Loading demo blueprint…";
    try {
      const res = await fetch("/api/demo", { method: "POST" });
      setBlueprint(await res.json());
      cvStatus.textContent = "✓ Demo blueprint loaded";
    } catch (e) {
      cvStatus.textContent = "✗ " + e.message;
    }
  }

  function setBlueprint(bp) {
    currentBlueprint = bp;
    $("blueprint-card").hidden = false;
    $("bp-name").textContent = bp.object_name || "object";
    $("bp-source").textContent = bp.source || "";
    renderBlueprintCanvas(bp);
    renderLegend(bp);
    const m = bp.metrics || {};
    $("bp-meta").innerHTML =
      `${bp.voxels.length} voxels · ${bp.dimensions.x}×${bp.dimensions.y}×${bp.dimensions.z} grid<br>` +
      `complexity ${(bp.complexity_score ?? 0).toFixed(2)} · ` +
      `spread ${(m.spread ?? 0).toFixed(2)} · ${m.occupied_quadrants ?? "?"} quadrant(s)`;
    $("start-btn").disabled = false;
    if (handlers.onBlueprint) handlers.onBlueprint(bp);
  }

  function renderBlueprintCanvas(bp) {
    const cv = $("bp-canvas");
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    const dx = bp.dimensions.x, dy = bp.dimensions.y;
    const cell = Math.max(4, Math.min(Math.floor(cv.width / (dx + 1)), Math.floor(cv.height / (dy + 1))));
    const ox = (cv.width - dx * cell) / 2;
    const oy = (cv.height - dy * cell) / 2;
    // Front projection (x, y); draw far-z first so near-z overpaints.
    const sorted = [...bp.voxels].sort((a, b) => b.z - a.z);
    for (const v of sorted) {
      const shade = 1 - Math.min(0.5, v.z * 0.08);
      ctx.fillStyle = BLOCK_HEX[v.block_type] || "#888";
      ctx.globalAlpha = shade;
      const px = ox + v.x * cell;
      const py = oy + (dy - 1 - v.y) * cell;
      ctx.fillRect(px, py, cell - 1, cell - 1);
    }
    ctx.globalAlpha = 1;
  }

  function renderLegend(bp) {
    const counts = bp.counts || {};
    $("bp-legend").innerHTML = Object.keys(BLOCK_LABEL)
      .filter((t) => counts[t])
      .map((t) => `<span class="lg"><span class="sw" style="background:${BLOCK_HEX[t]}"></span>${BLOCK_LABEL[t]} ×${counts[t]}</span>`)
      .join("");
  }

  // ---- start / reset ----
  $("start-btn").addEventListener("click", async () => {
    $("start-btn").disabled = true;
    $("start-btn").textContent = "◇ Deploying swarm…";
    try {
      const res = await fetch("/api/start", { method: "POST" });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      started = true;
      $("start-btn").hidden = true;
      $("reset-btn").hidden = false;
      $("overlay-hint").textContent = "Swarm building — orbit with mouse drag";
      if (handlers.onStart) handlers.onStart(data);
    } catch (e) {
      $("start-btn").disabled = false;
      $("start-btn").textContent = "▶ Start build";
      cvStatus.textContent = "✗ Start failed: " + e.message;
    }
  });

  $("reset-btn").addEventListener("click", async () => {
    await fetch("/api/reset", { method: "POST" });
    started = false;
    $("reset-btn").hidden = true;
    $("start-btn").hidden = false;
    $("start-btn").disabled = false;
    $("start-btn").textContent = "▶ Start build";
    $("done-banner").hidden = true;
    $("overlay-hint").textContent = "Load a blueprint, then start the build ↖";
    resetHUD();
    if (handlers.onReset) handlers.onReset();
  });

  function resetHUD() {
    $("progress-bar").firstElementChild.style.width = "0%";
    $("progress-label").textContent = "idle";
    $("s-placed").textContent = "0";
    $("s-dropped").textContent = "0";
    $("s-coll").textContent = "0";
    $("s-time").textContent = "0.0s";
    $("drone-count").textContent = "0";
    $("drone-list").innerHTML = "";
    $("event-log").innerHTML = "";
    lastEventCount = 0;
  }

  // ---- HUD ----
  let lastEventCount = 0;
  function updateHUD(state) {
    if (!state || !state.build_progress) return;
    const bp = state.build_progress;
    const pct = bp.total_tasks ? Math.round((bp.completed / bp.total_tasks) * 100) : 0;
    $("progress-bar").firstElementChild.style.width = pct + "%";
    $("progress-label").textContent = `${bp.completed}/${bp.total_tasks}`;

    const st = state.stats || {};
    $("s-placed").textContent = st.placed ?? 0;
    $("s-dropped").textContent = st.dropped ?? 0;
    $("s-coll").textContent = st.collisions ?? 0;
    $("s-time").textContent = (st.elapsed ?? 0).toFixed(1) + "s";

    // Robot reasoning.
    const r = state.robot_reasoning || {};
    if (r.chosen) {
      $("robot-reasoning").innerHTML =
        `<b>${r.chosen}</b> drones chosen — ` +
        `spatial ${r.spatial_quadrants}q · time ${r.time_factor} · ${r.distinct_block_types} block types`;
    }

    // Drone list.
    $("drone-count").textContent = state.drones.length;
    $("drone-list").innerHTML = state.drones.map((d) => {
      const carry = d.carrying
        ? `<span class="carry-dot" style="background:${BLOCK_HEX[d.carrying]}"></span>`
        : `<span class="carry-none">·</span>`;
      const reassigned = d.reassigned ? `<span class="tag-reassigned">helper</span>` : "";
      return `<div class="drone-row ${d.collision_flash ? "flash" : ""}">
        <span class="id" style="background:${ROLE_HEX[d.specialist_type]}">${d.id}</span>
        <span class="drone-meta">
          <span class="role">${ROLE_LABEL[d.specialist_type]} ${reassigned}</span>
          <span class="state">${d.state.replace(/_/g, " ").toLowerCase()}</span>
        </span>
        ${carry}
      </div>`;
    }).join("");

    // Event log (only re-render when it grew).
    if (state.events && state.events.length !== lastEventCount) {
      lastEventCount = state.events.length;
      $("event-log").innerHTML = state.events.slice().reverse().map((ev) => {
        let cls = "";
        if (/collided/i.test(ev)) cls = "collision";
        else if (/placed/i.test(ev)) cls = "place";
        else if (/recovery|recover/i.test(ev)) cls = "recover";
        else if (/reassigned/i.test(ev)) cls = "reassign";
        else if (/dropped/i.test(ev)) cls = "drop";
        return `<div class="ev ${cls}">${ev}</div>`;
      }).join("");
    }

    // Done banner.
    $("done-banner").hidden = !state.finished;
  }

  return { updateHUD };
}
