(() => {
  const byId = (id) => document.getElementById(id);
  let vtt = "";
  const form = new FormData();
  function download(name, type, text) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  document.addEventListener("DOMContentLoaded", () => {
    const button = byId("generateCaptionsBtn");
    if (!button) return;
    button.addEventListener("click", async () => {
      const result = byId("captionResult");
      button.disabled = true; button.textContent = "Generating…";
      try {
        form.set("text", byId("captionText").value);
        form.set("duration_seconds", byId("captionDuration").value);
        form.set("words_per_caption", byId("captionWords").value);
        const response = await fetch("/api/captions/generate", { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Caption generation failed");
        byId("captionOutput").value = data.srt;
        vtt = data.vtt;
        byId("downloadSrtBtn").disabled = false;
        byId("downloadVttBtn").disabled = false;
        result.textContent = "Created " + data.cue_count + " cues. " + data.timing;
      } catch (error) {
        result.textContent = "Caption error: " + error.message;
      } finally {
        button.disabled = false; button.textContent = "Generate SRT + VTT";
      }
    });
    byId("downloadSrtBtn").addEventListener("click", () => {
      const text = byId("captionOutput").value;
      if (text.trim()) download("mind-of-ak-captions.srt", "application/x-subrip;charset=utf-8", text);
    });
    byId("downloadVttBtn").addEventListener("click", () => {
      if (vtt) download("mind-of-ak-captions.vtt", "text/vtt;charset=utf-8", vtt);
    });
  });
})();
