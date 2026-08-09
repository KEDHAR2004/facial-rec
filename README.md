# facial-rec

A small, self-contained face detection toolkit built on OpenCV. It ships with a
CLI and a Flask web UI, and works fully offline: face detection uses the Haar
cascade bundled with `opencv-python-headless`, and a real sample photograph
(from `scikit-image`) is included so the demo needs no network access.

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

Open the page, upload an image (or click **Try the bundled sample image**), and
the annotated result is rendered inline. A JSON health check is available at
`/health`.

## Tests

```bash
pytest
```

## Project layout

```
facial_rec/          # library + CLI package
  detector.py        # FaceDetector (Haar cascade)
  samples.py         # bundled offline sample image
  cli.py             # `python -m facial_rec` entry point
app.py               # Flask web UI
templates/index.html # web UI template
tests/               # pytest suite
```
