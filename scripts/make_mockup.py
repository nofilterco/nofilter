import os
import argparse
from PIL import Image
from mockup_factory import make_simple_hat_mockup

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True, help="Path to the transparent design PNG")
    ap.add_argument("--out", required=True, help="Output mockup PNG path")
    ap.add_argument("--size", default="1400x1400", help="e.g. 1400x1400")
    args = ap.parse_args()

    w,h = [int(x) for x in args.size.lower().split("x")]
    img = Image.open(args.design).convert("RGBA")
    mock = make_simple_hat_mockup(img, size=(w,h))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    mock.save(args.out, "PNG")
    print(f"✅ Wrote mockup: {args.out}")

if __name__ == "__main__":
    main()
