"use strict";

// Tab switching
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("panel-" + tab.dataset.tab).classList.add("active");
  });
});

// Live camera face detection
const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const scratch = document.getElementById("scratch");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const captureBtn = document.getElementById("captureBtn");
const liveBadge = document.getElementById("liveBadge");
const liveHint = document.getElementById("liveHint");
const captureNote = document.getElementById("captureNote");

const octx = overlay.getContext("2d");
const CAPTURE_WIDTH = 480; // width of frames sent to the server for detection
let stream = null;
let running = false;
let inFlight = false;
let lastFaces = [];
let lastFrameSize = { w: CAPTURE_WIDTH, h: CAPTURE_WIDTH };

function frameToDataURL(quality) {
  const vw = video.videoWidth || 640;
  const vh = video.videoHeight || 480;
  const w = CAPTURE_WIDTH;
  const h = Math.round((vh / vw) * w);
  scratch.width = w;
  scratch.height = h;
  scratch.getContext("2d").drawImage(video, 0, 0, w, h);
  lastFrameSize = { w, h };
  return scratch.toDataURL("image/jpeg", quality || 0.7);
}

function drawOverlay(faces, frameW, frameH) {
  overlay.width = overlay.clientWidth;
  overlay.height = overlay.clientHeight;
  octx.clearRect(0, 0, overlay.width, overlay.height);
  const sx = overlay.width / frameW;
  const sy = overlay.height / frameH;
  octx.lineWidth = 3;
  octx.strokeStyle = "#22d3ee";
  octx.fillStyle = "#22d3ee";
  octx.font = "16px sans-serif";
  faces.forEach((f, i) => {
    const x = f.x * sx, y = f.y * sy, w = f.w * sx, h = f.h * sy;
    octx.strokeRect(x, y, w, h);
    octx.fillText("face " + (i + 1), x, Math.max(y - 6, 14));
  });
}

async function detectLoop() {
  if (!running) return;
  if (!inFlight && video.readyState >= 2) {
    inFlight = true;
    try {
      const dataUrl = frameToDataURL(0.6);
      const res = await fetch("/api/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: dataUrl }),
      });
      if (res.ok) {
        const data = await res.json();
        lastFaces = data.faces || [];
        drawOverlay(lastFaces, data.width || lastFrameSize.w, data.height || lastFrameSize.h);
        liveBadge.textContent = data.count + " face(s)";
      }
    } catch (e) {
      // transient network error; keep looping
    } finally {
      inFlight = false;
    }
  }
  setTimeout(detectLoop, 250);
}

async function startCamera() {
  captureNote.textContent = "";
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    video.srcObject = stream;
    await video.play();
    running = true;
    startBtn.disabled = true;
    stopBtn.disabled = false;
    captureBtn.disabled = false;
    liveBadge.textContent = "detecting…";
    liveHint.textContent = "Live detection running. Detected faces are boxed in cyan.";
    detectLoop();
  } catch (err) {
    liveBadge.textContent = "no camera";
    liveHint.textContent =
      "Could not access a camera (" + (err && err.name ? err.name : "error") +
      "). Use the Upload or Sample tabs instead.";
  }
}

function stopCamera() {
  running = false;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  video.srcObject = null;
  octx.clearRect(0, 0, overlay.width, overlay.height);
  startBtn.disabled = false;
  stopBtn.disabled = true;
  captureBtn.disabled = true;
  liveBadge.textContent = "camera off";
}

async function captureAndSave() {
  if (!running) return;
  captureBtn.disabled = true;
  captureNote.textContent = "Saving…";
  try {
    const dataUrl = frameToDataURL(0.85);
    const res = await fetch("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl }),
    });
    const data = await res.json();
    if (res.ok) {
      captureNote.innerHTML =
        "Saved <strong>" + data.filename + "</strong> (" + data.count +
        ' face(s)). <a href="/gallery" style="color:#67e8f9">Open gallery</a>';
    } else {
      captureNote.textContent = "Capture failed: " + (data.error || res.status);
    }
  } catch (e) {
    captureNote.textContent = "Capture failed: " + e;
  } finally {
    captureBtn.disabled = !running;
  }
}

startBtn.addEventListener("click", startCamera);
stopBtn.addEventListener("click", stopCamera);
captureBtn.addEventListener("click", captureAndSave);

// Auto-start the camera when the page loads so the live view is immediately active.
window.addEventListener("DOMContentLoaded", () => {
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    startCamera();
  } else {
    liveHint.textContent = "getUserMedia is not supported in this browser.";
  }
});
