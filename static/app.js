/* FaceSense front-end: live webcam analysis + image upload + enrollment. */

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");
const statusEl = document.getElementById("status");
const facesEl = document.getElementById("faces");
const personsEl = document.getElementById("persons");

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
const btnAnalyzeFile = document.getElementById("btn-analyze-file");
const btnEnrollFile = document.getElementById("btn-enroll-file");
const enrollNameFile = document.getElementById("enroll-name-file");
const resultImage = document.getElementById("result-image");

let stream = null;
let loopTimer = null;
let busy = false;

const grabCanvas = document.createElement("canvas");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.style.color = isError ? "#ff5d73" : "";
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
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 960 }, height: { ideal: 540 } },
    });
  } catch (e) {
    setStatus("Camera access denied or unavailable: " + e.message, true);
    return;
  }
  video.srcObject = stream;
  await video.play();
  overlay.width = video.videoWidth;
  overlay.height = video.videoHeight;
  btnStart.disabled = true;
  btnStop.disabled = false;
  btnEnroll.disabled = false;
  setStatus("Analyzing…");
  loopTimer = setInterval(analyzeFrame, 450);
};

btnStop.onclick = () => {
  clearInterval(loopTimer);
  loopTimer = null;
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  video.srcObject = null;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  btnStart.disabled = false;
  btnStop.disabled = true;
  btnEnroll.disabled = true;
  setStatus("Stopped.");
};

function grabFrame() {
  grabCanvas.width = video.videoWidth;
  grabCanvas.height = video.videoHeight;
  grabCanvas.getContext("2d").drawImage(video, 0, 0);
  return grabCanvas.toDataURL("image/jpeg", 0.8);
}

async function analyzeFrame() {
  if (busy || !stream) return;
  busy = true;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: grabFrame() }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    drawOverlay(data.faces);
    renderFaces(data.faces);
    renderPersons(data.persons);
    setStatus(`${data.faces.length} face(s) detected`);
  } catch (e) {
    setStatus("Analysis error: " + e.message, true);
  } finally {
    busy = false;
  }
}

function drawOverlay(faces) {
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  ctx.lineWidth = 2;
  ctx.font = "15px 'Segoe UI', sans-serif";
  for (const f of faces) {
    const [x, y, w, h] = f.box;
    const known = f.name !== "Unknown";
    const color = known ? "#3ddc84" : "#ff5d73";
    ctx.strokeStyle = color;
    ctx.strokeRect(x, y, w, h);

    const conf = f.expression_scores[f.expression] || 0;
    const label = `${f.name} | ${f.expression} ${(conf * 100).toFixed(0)}%`;
    const tw = ctx.measureText(label).width + 10;
    const ty = y > 24 ? y - 24 : y + h + 4;
    ctx.fillStyle = color;
    ctx.fillRect(x, ty, tw, 20);
    ctx.fillStyle = "#0f1220";
    ctx.fillText(label, x + 5, ty + 15);

    ctx.fillStyle = "#ffc800";
    for (const [px, py] of f.landmarks) {
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
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
        .slice(0, 4)
        .map(
          ([label, p]) => `
            <div class="bar-row">
              <span class="label">${label}</span>
              <div class="bar"><div style="width:${(p * 100).toFixed(1)}%"></div></div>
              <span>${(p * 100).toFixed(0)}%</span>
            </div>`
        )
        .join("");
      return `
        <div class="face-card">
          <span class="who ${known ? "known" : "unknown"}">${f.name}</span>
          ${known ? `<span class="expr"> · match ${(f.similarity * 100).toFixed(0)}%</span>` : ""}
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
  const res = await fetch("/api/enroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: grabFrame(), name: enrollName.value }),
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
  });
