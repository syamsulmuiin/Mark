"""Render a bounded declarative design; never execute model-supplied code."""
from __future__ import annotations

import hashlib
import io
import re
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Design integer outside allowed range')
    return value


def _color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ValueError('Design colors must be hexadecimal RGB')
    return value


def render_design(plan, base_dir):
    if not isinstance(plan,dict) or plan.get('supported') is not True:
        raise ValueError('Unsupported design request')
    width, height = _integer(plan.get('width'),256,2048), _integer(plan.get('height'),256,2048)
    elements = plan.get('elements')
    if not isinstance(elements,list) or not 1 <= len(elements) <= 80:
        raise ValueError('Design requires 1-80 elements')
    image = Image.new('RGB',(width,height),_color(plan.get('background')))
    draw = ImageDraw.Draw(image)
    for item in elements:
        if not isinstance(item,dict):
            raise ValueError('Invalid design element')
        kind, color = item.get('type'), _color(item.get('color'))
        x,y = _integer(item.get('x'),0,width-1), _integer(item.get('y'),0,height-1)
        if kind == 'text':
            text = item.get('text')
            if not isinstance(text,str) or not text.strip() or len(text)>1000:
                raise ValueError('Invalid design text')
            size = _integer(item.get('size'),10,200)
            try:
                font = ImageFont.truetype('DejaVuSans.ttf',size)
            except OSError:
                font = ImageFont.load_default(size=size)
            # Fail instead of clipping text. The model must lay out explicit lines.
            left,top,right,bottom = draw.multiline_textbbox((x,y),text,font=font,spacing=6)
            if left < 0 or top < 0 or right > width or bottom > height:
                raise ValueError('Design text would be clipped')
            draw.multiline_text((x,y),text,fill=color,font=font,spacing=6)
        elif kind in {'rectangle','ellipse','line'}:
            x2,y2 = _integer(item.get('x2'),x,width-1),_integer(item.get('y2'),y,height-1)
            if kind == 'line':
                draw.line((x,y,x2,y2),fill=color,width=_integer(item.get('stroke',3),1,40))
            else:
                getattr(draw,kind)((x,y,x2,y2),fill=color)
        else:
            raise ValueError('Only text, rectangle, ellipse and line are allowed')
    output = io.BytesIO()
    image.save(output,format='PNG')
    data = output.getvalue()
    root = Path(base_dir).resolve()/'storage/artifacts/images'
    if root.resolve()!=root:
        raise ValueError('Unsafe image output directory')
    root.mkdir(parents=True,exist_ok=True)
    path = root/('image-'+uuid.uuid4().hex+'.png')
    with path.open('xb') as target:
        target.write(data)
    return {'file_path':str(path),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'image_verified':True}
