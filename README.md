# FaceSense — Face Recognition & Expression Analysis

FaceSense detects faces, recognizes **who** each person is (with automatic
"Person 1", "Person 2", … labeling or custom names), and classifies their
**facial expression** — all running locally on CPU with no cloud services.

## Features

- **Face detection** — [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
  deep-learning detector: bounding boxes + 5 facial landmarks, robust to pose
  and scale, works with multiple faces per frame.
- **Person identification** — [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
  128-d face embeddings with cosine-similarity matching. People can be enrolled
  with a custom name or auto-labeled `Person 1`, `Person 2`, … An optional
  *auto-enroll* mode labels every new unknown face automatically.
- **Expression recognition** — an **ensemble of two models** classifying
  **8 expressions**: neutral, happiness, surprise, sadness, anger, disgust,
  fear, contempt — with per-class confidence scores.
  [HSEmotion](https://github.com/av-savchenko/face-emotion-recognition)
  (EfficientNet-B0 trained on AffectNet) provides high sensitivity to
  non-neutral expressions, and
  [FER+](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus)
  stabilizes neutral/happiness; on a labeled test set the ensemble scored
  significantly higher than either model alone.
- **Web app** — live browser-webcam analysis with real-time overlays, image
  upload, one-click enrollment, and a person-database manager.
- **CLI** — batch analysis of images, video files, or a webcam stream, with
  annotated output files.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download the pretrained models (~90 MB total, one time)
python scripts/download_models.py

# 3a. Run the web app, then open http://localhost:5000
python app.py

# 3b. ...or use the CLI
python cli.py analyze photo.jpg -o annotated.jpg
```

## Web app

Start `python app.py` and open <http://localhost:5000>:

> **Opening the app from another device?** Browsers only allow camera access
> on `localhost` or over HTTPS. Start the server with `python app.py --ssl`
> and open the `https://` URL (accept the self-signed certificate warning)
> so the live camera works across the network.

- **Live camera** tab — click *Start camera*; every face gets a live overlay
  showing its identity and dominant expression. Type a name (or leave blank
  for auto `Person N`) and click *Enroll this face* to register the most
  prominent face. Toggle *Auto-enroll unknown faces* to label every new
  person automatically.
- **Upload image** tab — analyze a photo (works with group photos) and get an
  annotated result, or enroll a person from a picture.
- The sidebar lists every detected face with its expression confidence bars,
  plus the enrolled-person database (remove individuals or reset it).

## CLI

```bash
# Enroll people (name is optional — defaults to "Person N")
python cli.py enroll alice.jpg --name "Alice"
python cli.py enroll someone.jpg                 # -> "Person 1"

# Analyze an image; prints JSON and optionally writes an annotated copy
python cli.py analyze group_photo.jpg -o annotated.jpg

# Analyze a video file or webcam (press q to quit the preview window)
python cli.py video --source 0 --auto-enroll
python cli.py video --source clip.mp4 -o annotated.mp4 --no-window

# Manage the person database
python cli.py persons
python cli.py remove "Person 1"
python cli.py reset
```

Useful flags:

- `--db PATH` — use an alternative person-database file (default `data/faces_db.json`).
- `--threshold X` — adjust the match strictness (default `0.363` cosine
  similarity; raise it to reduce false matches, lower it to match more easily).

## Hosting a live demo (working link)

The repo includes a `Dockerfile`, so you can host a public demo with a real
URL in a few clicks. Visitors' webcams work because hosting platforms serve
over HTTPS, and all analysis still happens on the server — no cloud AI APIs.

**Render (simplest):**

1. Sign up at [render.com](https://render.com) with your GitHub account.
2. Click **New → Web Service**, pick this repository.
3. Render auto-detects the `Dockerfile` — choose the **Free** instance type
   and click **Deploy**. You'll get a link like
   `https://facesense.onrender.com`.

Notes for a public demo: the free tier sleeps when idle (first visit takes
~1 minute to wake), and the enrolled-person database is shared by all
visitors and resets on redeploy — fine for a portfolio demo, but say so in
your post.

## How it works

1. **Detect** — YuNet finds every face and its 5 landmarks in the frame.
2. **Identify** — each face is aligned via its landmarks and embedded into a
   128-d vector by SFace; the vector is compared (cosine similarity) against
   all enrolled samples, and the best match above the threshold wins,
   otherwise the face is `Unknown` (or auto-enrolled as the next `Person N`).
3. **Classify expression** — the face crop is scored by two models —
   HSEmotion (224×224 RGB) and FER+ (64×64 grayscale) — and their softmax
   probabilities are blended (0.6 / 0.4) into the final 8-class result.

The person database is a simple JSON file of embeddings (`data/faces_db.json`)
— no face images are stored, and everything runs offline.

## Project layout

```
facerec/engine.py          # FaceEngine: detection + recognition + expression
app.py                     # Flask web app (REST API + UI)
cli.py                     # command-line interface
scripts/download_models.py # one-time model downloader
templates/, static/        # web front-end
models/                    # downloaded ONNX models (git-ignored)
data/                      # person database (git-ignored)
```

## License & credits

This project's code is released under the [MIT License](LICENSE) — free to
use, modify, and share.

It uses three publicly available pretrained models, all under permissive
open-source licenses that allow free (including commercial) use. The models
are **not** bundled in this repository — they are downloaded from their
official sources by `scripts/download_models.py`:

| Model | Purpose | Source | License |
|---|---|---|---|
| YuNet | Face detection | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT |
| SFace | Face recognition | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 |
| FER+ | Expression recognition | [ONNX Model Zoo](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus) | MIT |
| HSEmotion (EfficientNet-B0) | Expression recognition | [av-savchenko/face-emotion-recognition](https://github.com/av-savchenko/face-emotion-recognition) | Apache-2.0 |

## Responsible use

Facial recognition involves biometric data. Only enroll and analyze people
who have given their consent, and comply with the biometric-privacy laws that
apply in your jurisdiction (e.g. GDPR, BIPA).
