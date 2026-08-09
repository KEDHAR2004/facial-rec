#!/usr/bin/env bash
# Idempotent Cloud Agent setup for facial-rec.
# Installs system libraries required by OpenCV/scikit-image, creates a virtual
# environment, and installs pinned Python dependencies.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends \
  python3-venv \
  libglib2.0-0

echo "==> Creating virtual environment (.venv)"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

echo "==> Installing Python dependencies"
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "==> Verifying import"
./.venv/bin/python -c "import cv2, skimage, flask; from facial_rec import FaceDetector; FaceDetector(); print('facial-rec deps OK')"

echo "==> Setup complete"
