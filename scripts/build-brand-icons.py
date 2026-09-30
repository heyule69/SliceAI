"""Rasterize the same vector geometry used by the sidebar into native icon sizes."""
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];svg=ET.fromstring((root/'public/sliceai.svg').read_text(encoding='utf-8'))
group=svg[0];scale=32;canvas=Image.new('RGBA',(32*scale,32*scale));draw=ImageDraw.Draw(canvas)
for element in group:
    attr=element.attrib
    if element.tag.endswith('rect'):
        x,y,w,h=(float(attr[k])*scale for k in ('x','y','width','height'))
        draw.rounded_rectangle((x,y,x+w,y+h),radius=float(attr['rx'])*scale,fill=attr['fill'])
    else:draw.polygon([tuple(float(n)*scale for n in pair.split(',')) for pair in attr['points'].split()],fill=attr['fill'])
canvas=canvas.rotate(5,resample=Image.Resampling.BICUBIC)
folder=root/'src-tauri/icons';folder.mkdir(exist_ok=True)
image=canvas.resize((256,256),Image.Resampling.LANCZOS)
image.save(folder/'icon.png')
image.save(folder/'icon.ico',sizes=[(s,s) for s in (16,20,24,32,40,48,64,128,256)])
for size in (32,128):canvas.resize((size,size),Image.Resampling.LANCZOS).save(folder/f'{size}x{size}.png')
print('Sidebar SVG and Windows ICO share the same vector geometry.')
