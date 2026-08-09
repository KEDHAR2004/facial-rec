# FaceSense — container image for hosting a live demo
# (works on Render, Hugging Face Spaces, Fly.io, Railway, etc.)
FROM python:3.12-slim

WORKDIR /app

# OpenCV runtime libraries
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Bake the pretrained models into the image (one-time ~90 MB download)
RUN python scripts/download_models.py

# Writable dir for the person database (JSON of face embeddings)
RUN mkdir -p data && chmod 777 data

# Hugging Face Spaces uses port 7860; Render/Fly inject $PORT at runtime.
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "gunicorn --workers 2 --timeout 120 --bind 0.0.0.0:${PORT} app:app"]
