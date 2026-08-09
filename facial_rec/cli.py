"""Command-line interface for the facial-rec toolkit.

Examples
--------
Detect faces in an image and write an annotated copy::

    python -m facial_rec detect path/to/photo.jpg -o annotated.jpg

Run the bundled offline demo (no input image required)::

    python -m facial_rec demo -o demo_out.jpg
"""

from __future__ import annotations

import argparse
import sys

import cv2

from .detector import FaceDetector
from .samples import astronaut_bgr


def _run_detection(image, output_path: str | None) -> int:
    detector = FaceDetector()
    faces = detector.detect(image)

    print(f"Detected {len(faces)} face(s).")
    for i, face in enumerate(faces, start=1):
        print(f"  face {i}: x={face.x} y={face.y} w={face.width} h={face.height}")

    if output_path:
        annotated = detector.annotate(image, faces)
        if not cv2.imwrite(output_path, annotated):
            print(f"error: failed to write {output_path!r}", file=sys.stderr)
            return 2
        print(f"Wrote annotated image to {output_path}")

    return 0 if faces else 1


def _cmd_detect(args: argparse.Namespace) -> int:
    image = cv2.imread(args.image)
    if image is None:
        print(f"error: could not read image {args.image!r}", file=sys.stderr)
        return 2
    return _run_detection(image, args.output)


def _cmd_demo(args: argparse.Namespace) -> int:
    print("Running offline demo on the bundled astronaut sample image.")
    return _run_detection(astronaut_bgr(), args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="facial_rec", description="Detect faces in images using OpenCV."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="detect faces in an image file")
    p_detect.add_argument("image", help="path to an input image")
    p_detect.add_argument(
        "-o", "--output", help="path to write an annotated copy of the image"
    )
    p_detect.set_defaults(func=_cmd_detect)

    p_demo = sub.add_parser("demo", help="run the bundled offline demo")
    p_demo.add_argument(
        "-o", "--output", default="demo_output.jpg", help="path to write the annotated demo image"
    )
    p_demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
