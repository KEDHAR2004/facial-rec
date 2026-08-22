/* FaceSense front-end: live webcam analysis + image upload + enrollment. */

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");
const statusEl = document.getElementById("status");
const facesEl = document.getElementById("faces");
const personsEl = document.getElementById("persons");
const placeholder = document.getElementById("camera-placeholder");

const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const btnEnroll = document.getElementById("btn-enroll");
const enrollName = document.getElementById("enroll-name");
const autoEnroll = document.getElementById("auto-enroll");

const tabLive = document.getElementById("tab-live");
const tabUpload = document.getElementById("tab-upload");
const liveView = document.getElementById("live-view");
const uploadView = document.getElementById("upload-view");
const fileInput = document.getElementById("file-input");
const fileLabel = document.getElementById("file-label");
const btnAnalyzeFile = document.getElementById("btn-analyze-file");
const btnEnrollFile = document.getElementById("btn-enroll-file");
const enrollNameFile = document.getElementById("enroll-name-file");
const resultImage = document.getElementById("result-image");

const EMOTION_COLORS = {
  happiness: "#3ddc84",
  neutral: "#8f9bb8",
  surprise: "#ffc24b",
  sadness: "#5ba8ff",
  anger: "#ff5d73",
  disgust: "#9bd356",
  fear: "#c084fc",
  contempt: "#ff9d5c",
};

let stream = null;
let loopTimer = null;
let busy = false;
let failStreak = 0;

const grabCanvas = document.createElement("canvas");

btnStop.disabled = true;
btnEnroll.disabled = true;

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.style.color = isError ? "#ff5d73" : "";
}

function fmtPct(p) {
  const v = p * 100;
  return (v >= 10 ? Math.round(v) : v.toFixed(1)) + "%";
}

/* ---------------- tabs ---------------- */
tabLive.onclick = () => switchTab(true);
tabUpload.onclick = () => switchTab(false);
function switchTab(live) {
  tabLive.classList.toggle("active", live);
  tabUpload.classList.toggle("active", !live);
  liveView.hidden = !live;
  uploadView.hidden = live;
}

/* ---------------- camera ---------------- */
btnStart.onclick = async () => {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus(
      "Camera API unavailable. Browsers only allow camera access on " +
        "localhost or over HTTPS — start the server with `python app.py --ssl` " +
        "and open the https:// URL.",
      true
    );
    return;
  }
  setStatus("Requesting camera…");
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 960 }, height: { ideal: 540 } },
    });
  } catch (e) {
    setStatus("Camera access denied or unavailable: " + e.message, true);
    return;
  }
  video.srcObject = stream;
  try {
    await video.play();
  } catch (_) {
    /* some browsers reject play() spuriously; the stream still renders */
  }
  // Wait until real frames exist — starting earlier causes a black
  // 0x0 canvas and failed analysis on slower cameras.
  if (!video.videoWidth) {
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 4000);
      video.addEventListener(
        "loadedmetadata",
        () => { clearTimeout(t); resolve(); },
        { once: true }
      );
    });
  }
  if (!video.videoWidth) {
    setStatus(
      "The camera started but is not sending frames. Close other apps " +
        "using the camera and try again.",
      true
    );
    stopCamera();
    return;
  }
  syncOverlaySize();
  placeholder.hidden = true;
  btnStart.disabled = true;
  btnStop.disabled = false;
  btnEnroll.disabled = false;
  failStreak = 0;
  setStatus("Analyzing…");
  loopTimer = setInterval(analyzeFrame, 450);
};

function stopCamera() {
  clearInterval(loopTimer);
  loopTimer = null;
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  video.srcObject = null;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  placeholder.hidden = false;
  btnStart.disabled = false;
  btnStop.disabled = true;
  btnEnroll.disabled = true;
  smoothTracks = [];
}

btnStop.onclick = () => {
  stopCamera();
  setStatus("Stopped.");
};

function syncOverlaySize() {
  if (
    video.videoWidth &&
    (overlay.width !== video.videoWidth || overlay.height !== video.videoHeight)
  ) {
    overlay.width = video.videoWidth;
    overlay.height = video.videoHeight;
  }
}

function grabFrame() {
  if (!video.videoWidth) return null;
  grabCanvas.width = video.videoWidth;
  grabCanvas.height = video.videoHeight;
  grabCanvas.getContext("2d").drawImage(video, 0, 0);
  return grabCanvas.toDataURL("image/jpeg", 0.8);
}

/* ---------------- expression smoothing ----------------
   Blend each face's scores with its previous frame (matched by box
   center) so the mood readout is steady instead of flickering. */
let smoothTracks = [];

function smoothFaces(faces) {
  const next = [];
  for (const f of faces) {
    const [x, y, w, h] = f.box;
    const cx = x + w / 2;
    const cy = y + h / 2;
    let prev = null;
    let bestD = Infinity;
    for (const t of smoothTracks) {
      const d = (t.cx - cx) ** 2 + (t.cy - cy) ** 2;
      if (d < bestD) { bestD = d; prev = t; }
    }
    let scores = { ...f.expression_scores };
    if (prev && bestD < w * w) {
      for (const k in scores) {
        scores[k] = 0.45 * scores[k] + 0.55 * (prev.scores[k] || 0);
      }
    }
    next.push({ cx, cy, scores });
    f.expression_scores = scores;
    f.expression = Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
  }
  smoothTracks = next;
  return faces;
}

/* ---------------- live analysis loop ---------------- */
async function analyzeFrame() {
  if (busy || !stream) return;
  const frame = grabFrame();
  if (!frame) return;
  busy = true;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frame }),
    });
    if (!res.ok) throw new Error(`server responded ${res.status}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    failStreak = 0;
    syncOverlaySize();
    const faces = smoothFaces(data.faces);
    drawOverlay(faces);
    renderFaces(faces);
    renderPersons(data.persons);
    setStatus(`${faces.length} face(s) detected`);
  } catch (e) {
    // Hosted servers can briefly return errors while waking/restarting;
    // keep retrying quietly and only surface persistent failures.
    failStreak += 1;
    if (failStreak >= 5) {
      setStatus("Analysis error: " + e.message, true);
    } else if (failStreak >= 2) {
      setStatus("Reconnecting…");
    }
  } finally {
    busy = false;
  }
}

/* The video preview is mirrored (selfie style), so overlay X coordinates
   must be flipped to stay aligned with what the user sees. */
const MIRROR = true;

function drawOverlay(faces) {
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  ctx.lineWidth = 2;
  ctx.font = "15px 'Inter', 'Segoe UI', sans-serif";
  const W = overlay.width;
  for (const f of faces) {
    let [x, y, w, h] = f.box;
    if (MIRROR) x = W - x - w;
    const known = f.name !== "Unknown";
    const color = known ? "#3ddc84" : "#ff5d73";
    ctx.strokeStyle = color;
    ctx.strokeRect(x, y, w, h);

    const conf = f.expression_scores[f.expression] || 0;
    const label = `${f.name} | ${f.expression} ${fmtPct(conf)}`;
    const tw = ctx.measureText(label).width + 10;
    const ty = y > 24 ? y - 24 : y + h + 4;
    ctx.fillStyle = color;
    ctx.fillRect(x, ty, tw, 20);
    ctx.fillStyle = "#0b0e1a";
    ctx.fillText(label, x + 5, ty + 15);

    ctx.fillStyle = "#ffc800";
    for (const [px, py] of f.landmarks) {
      ctx.beginPath();
      ctx.arc(MIRROR ? W - px : px, py, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

/* ---------------- side panel ---------------- */
function renderFaces(faces) {
  if (!faces.length) {
    facesEl.innerHTML = '<p class="empty">No faces detected.</p>';
    return;
  }
  facesEl.innerHTML = faces
    .map((f) => {
      const known = f.name !== "Unknown";
      const bars = Object.entries(f.expression_scores)
        .sort((a, b) => b[1] - a[1])
        .map(
          ([label, p]) => `
            <div class="bar-row">
              <span class="label">${label}</span>
              <div class="bar"><div style="width:${Math.max(p * 100, 1.5).toFixed(1)}%;
                background:${EMOTION_COLORS[label] || "#6d8dff"}"></div></div>
              <span class="pct">${fmtPct(p)}</span>
            </div>`
        )
        .join("");
      return `
        <div class="face-card">
          <span class="who ${known ? "known" : "unknown"}">${f.name}</span>
          ${known ? `<span class="expr"> · match ${fmtPct(f.similarity)}</span>` : ""}
          <div class="expr">${f.expression}</div>
          ${bars}
        </div>`;
    })
    .join("");
}

function renderPersons(persons) {
  const names = Object.keys(persons || {});
  if (!names.length) {
    personsEl.innerHTML = '<li class="empty">Nobody enrolled yet.</li>';
    return;
  }
  personsEl.innerHTML = names
    .map(
      (n) =>
        `<li><span>${n} <small>(${persons[n]} sample${persons[n] > 1 ? "s" : ""})</small></span>
         <button data-name="${n}">remove</button></li>`
    )
    .join("");
  personsEl.querySelectorAll("button").forEach((b) => {
    b.onclick = async () => {
      const res = await fetch(`/api/persons/${encodeURIComponent(b.dataset.name)}`, {
        method: "DELETE",
      });
      const data = await res.json();
      renderPersons(data.persons || {});
    };
  });
}

/* ---------------- enrollment ---------------- */
btnEnroll.onclick = async () => {
  if (!stream) return;
  const frame = grabFrame();
  if (!frame) return;
  const res = await fetch("/api/enroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: frame, name: enrollName.value }),
  });
  const data = await res.json();
  if (data.error) return setStatus(data.error, true);
  enrollName.value = "";
  renderPersons(data.persons);
  setStatus(`Enrolled as "${data.enrolled}".`);
};

autoEnroll.onchange = async () => {
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_enroll: autoEnroll.checked }),
  });
};

document.getElementById("btn-reset").onclick = async () => {
  if (!confirm("Remove all enrolled people?")) return;
  const res = await fetch("/api/reset", { method: "POST" });
  const data = await res.json();
  renderPersons(data.persons);
};

/* ---------------- upload ---------------- */
fileInput.onchange = () => {
  const has = fileInput.files.length > 0;
  btnAnalyzeFile.disabled = !has;
  btnEnrollFile.disabled = !has;
  if (has) fileLabel.textContent = fileInput.files[0].name;
};

function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

btnAnalyzeFile.onclick = async () => {
  const image = await fileToDataURL(fileInput.files[0]);
  setStatus("Analyzing image…");
  const res = await fetch("/api/analyze?annotated=1", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image }),
  });
  const data = await res.json();
  if (data.error) return setStatus(data.error, true);
  if (data.annotated) {
    resultImage.src = data.annotated;
    resultImage.hidden = false;
  }
  renderFaces(data.faces);
  renderPersons(data.persons);
  setStatus(`${data.faces.length} face(s) detected`);
};

btnEnrollFile.onclick = async () => {
  const image = await fileToDataURL(fileInput.files[0]);
  const res = await fetch("/api/enroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image, name: enrollNameFile.value }),
  });
  const data = await res.json();
  if (data.error) return setStatus(data.error, true);
  enrollNameFile.value = "";
  renderPersons(data.persons);
  setStatus(`Enrolled as "${data.enrolled}".`);
};

/* initial state */
fetch("/api/persons")
  .then((r) => r.json())
  .then((d) => {
    renderPersons(d.persons);
    autoEnroll.checked = !!d.auto_enroll;
  })
  .catch(() => {});
