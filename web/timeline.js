(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { duration: 0, clips: [], selectedId: null, nextId: 1 };
  const preview = byId("preview");
  const lane = byId("timelineLane");
  const list = byId("timelineClipList");
  const splitButton = byId("splitClipBtn");
  const resetButton = byId("resetTimelineBtn");
  const playheadButton = byId("addPlayheadBtn");
  if (!lane || !preview) return;

  const time = (value) => {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const minutes = Math.floor(seconds / 60);
    return String(minutes).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  };
  const selected = () => state.clips.find((clip) => clip.id === state.selectedId) || null;
  const setStatus = (message) => {
    const status = byId("analysisResult");
    if (status) status.textContent = message;
  };
  const makeClip = (start, end) => ({
    id: state.nextId++,
    start: Number(start.toFixed(2)),
    end: Number(end.toFixed(2)),
    name: "Clip " + (state.nextId - 1)
  });
  function render() {
    byId("timelineDuration").textContent = state.duration ? time(state.duration) + " total" : "Waiting for upload";
    byId("timelineMid").textContent = state.duration ? time(state.duration / 2) : "—";
    byId("timelineEnd").textContent = state.duration ? time(state.duration) : "—";
    splitButton.disabled = !state.duration || !selected();
    resetButton.disabled = !state.duration;
    playheadButton.disabled = !state.duration;
    if (!state.clips.length) {
      lane.innerHTML = '<div class="timeline-empty">No clips in this timeline.</div>';
      list.innerHTML = '<div class="timeline-empty">Split the source at the preview playhead to create editable sections.</div>';
      return;
    }
    lane.replaceChildren();
    state.clips.forEach((clip) => {
      const block = document.createElement("button");
      block.type = "button";
      block.className = "timeline-clip" + (clip.id === state.selectedId ? " selected" : "");
      block.style.flexGrow = String(Math.max(1, clip.end - clip.start));
      block.setAttribute("aria-label", clip.name + ", " + time(clip.start) + " to " + time(clip.end));
      const title = document.createElement("strong");
      title.textContent = clip.name;
      const meta = document.createElement("small");
      meta.textContent = time(clip.start) + " – " + time(clip.end);
      block.append(title, meta);
      block.addEventListener("click", () => {
        state.selectedId = clip.id;
        preview.currentTime = clip.start;
        render();
      });
      lane.append(block);
    });
    list.replaceChildren();
    state.clips.forEach((clip, index) => {
      const row = document.createElement("div");
      row.className = "clip-row" + (clip.id === state.selectedId ? " active" : "");
      const details = document.createElement("div");
      const title = document.createElement("div");
      title.className = "clip-row-title";
      title.textContent = clip.name;
      const meta = document.createElement("div");
      meta.className = "clip-row-meta";
      meta.textContent = time(clip.start) + " → " + time(clip.end) + " · " + (clip.end - clip.start).toFixed(2) + " sec";
      details.append(title, meta);
      const actions = document.createElement("div");
      actions.className = "clip-row-actions";
      const trimIn = document.createElement("input");
      trimIn.type = "number"; trimIn.min = "0"; trimIn.max = String(state.duration); trimIn.step = "0.1";
      trimIn.value = clip.start; trimIn.setAttribute("aria-label", "Clip start seconds");
      trimIn.style.cssText = "width:82px;min-height:38px;background:#111;color:white;border:1px solid #555;border-radius:8px;padding:6px";
      const trimOut = document.createElement("input");
      trimOut.type = "number"; trimOut.min = "0"; trimOut.max = String(state.duration); trimOut.step = "0.1";
      trimOut.value = clip.end; trimOut.setAttribute("aria-label", "Clip end seconds");
      trimOut.style.cssText = trimIn.style.cssText;
      const apply = document.createElement("button");
      apply.type = "button"; apply.className = "btn secondary"; apply.textContent = "Trim";
      apply.addEventListener("click", () => {
        const start = Number(trimIn.value), end = Number(trimOut.value);
        if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > state.duration || end - start < 0.1) {
          setStatus("Timeline trim rejected: enter a valid range within the source, at least 0.1 seconds long."); return;
        }
        clip.start = Number(start.toFixed(2)); clip.end = Number(end.toFixed(2)); render();
      });
      const up = document.createElement("button");
      up.type = "button"; up.className = "btn secondary"; up.textContent = "↑"; up.disabled = index === 0;
      up.setAttribute("aria-label", "Move clip up");
      up.addEventListener("click", () => { [state.clips[index - 1], state.clips[index]] = [state.clips[index], state.clips[index - 1]]; render(); });
      const down = document.createElement("button");
      down.type = "button"; down.className = "btn secondary"; down.textContent = "↓"; down.disabled = index === state.clips.length - 1;
      down.setAttribute("aria-label", "Move clip down");
      down.addEventListener("click", () => { [state.clips[index + 1], state.clips[index]] = [state.clips[index], state.clips[index + 1]]; render(); });
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "btn secondary"; remove.textContent = "×"; remove.setAttribute("aria-label", "Delete clip");
      remove.addEventListener("click", () => { state.clips.splice(index, 1); state.selectedId = state.clips[Math.min(index, state.clips.length - 1)]?.id || null; render(); });
      actions.append(trimIn, trimOut, apply, up, down, remove);
      row.append(details, actions);
      list.append(row);
    });
  }
  splitButton.addEventListener("click", () => {
    const clip = selected();
    const point = Number(preview.currentTime);
    if (!clip || point <= clip.start + 0.05 || point >= clip.end - 0.05) {
      setStatus("Move the video playhead inside the selected clip before splitting it."); return;
    }
    const index = state.clips.findIndex((item) => item.id === clip.id);
    const right = makeClip(point, clip.end);
    clip.end = Number(point.toFixed(2));
    state.clips.splice(index + 1, 0, right);
    state.selectedId = right.id;
    render();
    setStatus("Timeline split created at " + point.toFixed(2) + " seconds. This is currently a local edit plan.");
  });
  resetButton.addEventListener("click", () => {
    state.clips = [makeClip(0, state.duration)];
    state.selectedId = state.clips[0].id;
    preview.currentTime = 0;
    render();
    setStatus("Timeline reset to one full-length source clip.");
  });
  playheadButton.addEventListener("click", () => {
    if (state.duration) preview.currentTime = Math.min(state.duration, Math.max(0, preview.currentTime));
  });
  window.addEventListener("ak:source-ready", (event) => {
    const duration = Number(event.detail?.duration || 0);
    if (!Number.isFinite(duration) || duration <= 0) return;
    state.duration = duration;
    state.clips = [makeClip(0, duration)];
    state.selectedId = state.clips[0].id;
    render();
  });
  preview.addEventListener("timeupdate", () => {
    const clip = selected();
    if (clip && preview.currentTime >= clip.start && preview.currentTime <= clip.end) {
      // Keep the playhead native to the video element; timeline selection remains explicit.
    }
  });
  window.getAkTimelineSegments = () => state.clips.map(({start,end}) => ({start,end}));
  render();
})();