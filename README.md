# facial-rec

A small, self-contained face detection toolkit built on OpenCV. It ships with a
CLI and a Flask web UI, and works fully offline: face detection uses the Haar
cascade bundled with `opencv-python-headless`, and a real sample photograph
(from `scikit-image`) is included so the demo needs no network access.

Features:

- **Live camera detection** — the browser streams your webcam and faces are
  boxed live (via the `/api/detect` endpoint).
- **Capture gallery** — save annotated snapshots from the live camera; they are
  written to `captures/` and listed on the `/gallery` page.
- **Image upload / sample** — detect faces in an uploaded image or the bundled
  sample photo.
- **CLI** — detect faces in image files from the terminal.

## Requirements

- Python 3.10+
- Dependencies pinned in [`requirements.txt`](requirements.txt)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### CLI

Run the bundled offline demo (annotates the sample image):

```bash
python -m facial_rec demo -o demo_output.jpg
```

Detect faces in your own image:

```bash
python -m facial_rec detect path/to/photo.jpg -o annotated.jpg
```

The command prints the number of faces found and their bounding boxes, and
writes an annotated copy when `-o/--output` is given. Exit code is `0` when at
least one face is found, `1` when none are found, and `2` on I/O errors.

### Web app

```bash
python app.py          # dev server on http://localhost:5000
# or, for production-style serving:
gunicorn --bind 0.0.0.0:5000 app:app
```

Then open the page:

- **Live camera** tab: click **Start camera**, allow access, and detected faces
  are boxed live. Click **Capture & save** to store an annotated snapshot.
- **Upload image** / **Sample** tabs: run server-side detection on your own
  image or the bundled sample; the annotated result renders inline.
- **Capture gallery** (`/gallery`): browse saved live-camera captures.

### HTTP API

- `POST /api/detect` — JSON `{"image": "<data-url or base64>"}` (or multipart
  `image`); returns `{count, width, height, faces:[{x,y,w,h}]}`.
- `POST /api/capture` — JSON `{"image": ...}`; saves an annotated capture and
  returns its filename and URL.
- `GET /health` — JSON health check.

## Tests

```bash
pytest
```

## Project layout

```
facial_rec/            # library + CLI package
  detector.py          # FaceDetector (Haar cascade)
  samples.py           # bundled offline sample image
  cli.py               # `python -m facial_rec` entry point
app.py                 # Flask web UI + JSON detection/capture API
templates/index.html   # web UI (live camera / upload / sample)
templates/gallery.html # capture gallery page
static/app.js          # live camera capture + detection loop
static/style.css        # styles
captures/              # saved live-camera captures (created at runtime)
tests/                 # pytest suite
```
