import os
from typing import Tuple
from PIL import Image, ImageDraw, ImageOps

def make_simple_hat_mockup(design_rgba: Image.Image, *, size: Tuple[int,int]=(1400,1400)) -> Image.Image:
    """
    Creates a simple, generic, copyright-safe hat mockup image (flat illustration),
    and places the design in the front panel area.

    This is NOT a branded mockup and does not imitate any specific manufacturer's product photography.
    """
    w, h = size
    bg = Image.new("RGB", (w,h), (245,245,245))
    draw = ImageDraw.Draw(bg)

    # Hat body
    body_bbox = (int(w*0.18), int(h*0.22), int(w*0.82), int(h*0.78))
    draw.ellipse(body_bbox, fill=(230,230,230), outline=(200,200,200), width=6)

    # Mask lower half to make it look like a cap
    mask = Image.new("L", (w,h), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.ellipse(body_bbox, fill=255)
    # cut bottom of ellipse
    cut_y = int(h*0.62)
    mdraw.rectangle((0, cut_y, w, h), fill=0)
    body = Image.new("RGB", (w,h), (0,0,0))
    body.paste(bg, mask=mask)
    bg = Image.composite(body, bg, mask)

    draw = ImageDraw.Draw(bg)
    # Brim
    brim_bbox = (int(w*0.18), int(h*0.56), int(w*0.82), int(h*0.80))
    draw.ellipse(brim_bbox, fill=(220,220,220), outline=(200,200,200), width=6)
    # Inner brim shading line
    draw.arc(brim_bbox, start=200, end=340, fill=(190,190,190), width=6)

    # Stitch line
    draw.arc((int(w*0.22), int(h*0.28), int(w*0.78), int(h*0.74)), start=200, end=340, fill=(190,190,190), width=4)

    # Place design on front panel
    d = design_rgba.convert("RGBA")
    # remove transparent padding by trimming
    bbox = d.getbbox()
    if bbox:
        d = d.crop(bbox)
    max_dw = int(w*0.28)
    max_dh = int(h*0.22)
    d.thumbnail((max_dw, max_dh), Image.Resampling.LANCZOS)
    x = int(w*0.5 - d.size[0]/2)
    y = int(h*0.40 - d.size[1]/2)
    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(d, (x,y))
    return bg_rgba
