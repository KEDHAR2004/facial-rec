"""Command-line interface for the face engine.

Examples:
  python cli.py enroll photos/alice.jpg --name "Alice"
  python cli.py enroll photos/someone.jpg              # auto-named "Person N"
  python cli.py analyze group.jpg -o annotated.jpg
  python cli.py video --source 0 --auto-enroll         # live webcam window
  python cli.py video --source clip.mp4 -o out.mp4
  python cli.py persons
  python cli.py remove "Person 1"
"""

from __future__ import annotations

import argparse
import json
import sys

import cv2

from facerec import FaceEngine


def cmd_enroll(engine: FaceEngine, args) -> int:
    img = cv2.imread(args.image)
    if img is None:
        print(f"error: cannot read image: {args.image}", file=sys.stderr)
        return 1
    name = engine.enroll(img, args.name)
    print(f'Enrolled face as "{name}".')
    return 0


def cmd_analyze(engine: FaceEngine, args) -> int:
    img = cv2.imread(args.image)
    if img is None:
        print(f"error: cannot read image: {args.image}", file=sys.stderr)
        return 1
    results = engine.analyze(img)
    print(json.dumps([r.to_dict() for r in results], indent=2))
    if args.output:
        cv2.imwrite(args.output, FaceEngine.annotate(img, results))
        print(f"Annotated image written to {args.output}", file=sys.stderr)
    return 0


def cmd_video(engine: FaceEngine, args) -> int:
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"error: cannot open video source: {args.source}", file=sys.stderr)
        return 1

    writer = None
    if args.output:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(
            args.output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)
        )

    show = not args.no_window
    print("Processing... press q in the window to quit." if show else "Processing...")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            annotated = FaceEngine.annotate(frame, engine.analyze(frame))
            if writer is not None:
                writer.write(annotated)
            if show:
                try:
                    cv2.imshow("FaceSense", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error:
                    show = False  # headless environment; keep processing
    finally:
        cap.release()
        if writer is not None:
            writer.release()
            print(f"Annotated video written to {args.output}")
        cv2.destroyAllWindows()
    return 0


def cmd_persons(engine: FaceEngine, _args) -> int:
    persons = engine.persons
    if not persons:
        print("No persons enrolled.")
        return 0
    for name, count in persons.items():
        print(f"{name}: {count} sample(s)")
    return 0


def cmd_remove(engine: FaceEngine, args) -> int:
    if engine.remove_person(args.name):
        print(f'Removed "{args.name}".')
        return 0
    print(f'error: no such person: "{args.name}"', file=sys.stderr)
    return 1


def cmd_reset(engine: FaceEngine, _args) -> int:
    engine.reset()
    print("Database cleared.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Face recognition & expression analysis CLI."
    )
    parser.add_argument(
        "--db", default="data/faces_db.json", help="Path to the person database."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Cosine similarity threshold for a person match (default 0.363).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("enroll", help="Enroll a face from an image.")
    p.add_argument("image")
    p.add_argument("--name", help='Person name (default: auto "Person N").')
    p.set_defaults(func=cmd_enroll)

    p = sub.add_parser("analyze", help="Analyze faces in an image.")
    p.add_argument("image")
    p.add_argument("-o", "--output", help="Write an annotated copy here.")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("video", help="Analyze a video file or webcam stream.")
    p.add_argument(
        "--source", default="0", help="Webcam index (e.g. 0) or video file path."
    )
    p.add_argument("-o", "--output", help="Write the annotated video here (mp4).")
    p.add_argument(
        "--auto-enroll",
        action="store_true",
        help='Automatically enroll unknown faces as "Person N".',
    )
    p.add_argument(
        "--no-window", action="store_true", help="Do not open a preview window."
    )
    p.set_defaults(func=cmd_video)

    sub.add_parser("persons", help="List enrolled persons.").set_defaults(
        func=cmd_persons
    )

    p = sub.add_parser("remove", help="Remove an enrolled person.")
    p.add_argument("name")
    p.set_defaults(func=cmd_remove)

    sub.add_parser("reset", help="Clear the person database.").set_defaults(
        func=cmd_reset
    )

    args = parser.parse_args()
    kwargs = {"db_path": args.db, "auto_enroll": getattr(args, "auto_enroll", False)}
    if args.threshold is not None:
        kwargs["match_threshold"] = args.threshold
    engine = FaceEngine(**kwargs)
    return args.func(engine, args)


if __name__ == "__main__":
    sys.exit(main())
