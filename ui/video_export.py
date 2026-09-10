"""Encode the displayed timelapse PNGs into an annotated constant-FPS MP4.

Pillow lays out the title, original heatmap, inferno color scale, and each
frame's timestamp line. FFmpeg encodes one frame per image at the requested
rate; temporary files are removed automatically. Numerical arrays are untouched.
"""
import base64
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from matplotlib import colormaps, font_manager


def encode_video(video, fps, labels):
    if not np.isfinite(fps) or not 1 <= fps <= 20:
        raise ValueError("Playback FPS must be between 1 and 20.")
    if len(labels) != len(video['frames']) or any(not isinstance(x, str) or len(x)>1000 for x in labels):
        raise ValueError("Expected one timestamp label per video frame.")
    executable = shutil.which('ffmpeg')
    if not executable and Path('/opt/homebrew/bin/ffmpeg').exists():
        executable = '/opt/homebrew/bin/ffmpeg'
    if not executable:
        raise ValueError("MP4 export requires FFmpeg. Install FFmpeg and restart the app.")
    stage = 'Absorbance after baseline' if video['kind']=='baseline' else 'Absorbance before baseline'
    title = f"{video['wavenumber']} cm⁻¹ · {stage} · Contrast: {video['low']:g}–{video['high']:g} percentiles · FPS: {fps:g}"
    font_path = font_manager.findfont('DejaVu Sans')
    font = ImageFont.truetype(font_path, 20)
    # Wrap long tie lists without expanding the video to an impractical width.
    words = video.get('extrema_label', '').split()
    lines = ['']
    for word in words:
        candidate = (lines[-1] + ' ' + word).strip()
        if font.getlength(candidate) > 1050 and lines[-1]:
            lines.append(word)
        else:
            lines[-1] = candidate
    extra_height = 28 * len(lines)
    width = max(1100, int(font.getlength(title))+48, max(int(font.getlength(x))+48 for x in labels))
    width += width % 2
    first = Image.open(io.BytesIO(base64.b64decode(video['frames'][0]['png'])))
    scale = min((width-190)/first.width, 700/first.height)
    iw, ih = max(1,round(first.width*scale)), max(1,round(first.height*scale))
    height = ih+150+extra_height
    height += height%2
    gradient = colormaps['inferno'](np.linspace(1,0,ih), bytes=True)[:,:3]
    bar = Image.fromarray(np.repeat(gradient[:,None,:],18,axis=1))
    with tempfile.TemporaryDirectory(prefix='qcl-video-') as folder:
        for i, (frame, label) in enumerate(zip(video['frames'], labels)):
            canvas = Image.new('RGB',(width,height),'white')
            draw = ImageDraw.Draw(canvas)
            draw.text((24,18),title,font=font,fill='#213a35')
            for line_index, line in enumerate(lines):
                draw.text((24,46+28*line_index),line,font=font,fill='#213a35')
            image = Image.open(io.BytesIO(base64.b64decode(frame['png']))).convert('RGB')
            canvas.paste(image.resize((iw,ih),Image.Resampling.NEAREST),(24,65+extra_height))
            canvas.paste(bar,(iw+45,65+extra_height))
            for fraction, value in [(0,video['vmax']),(.5,(video['vmin']+video['vmax'])/2),(1,video['vmin'])]:
                draw.text((iw+70,65+extra_height+int(fraction*(ih-24))),f'{value:.4f}',font=font,fill='#213a35')
            draw.text((24,ih+90+extra_height),label,font=font,fill='#213a35')
            canvas.save(Path(folder)/f'{i:06d}.png')
        output = Path(folder)/'timelapse.mp4'
        result = subprocess.run([executable,'-y','-loglevel','error','-framerate',str(fps),'-i',str(Path(folder)/'%06d.png'),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],capture_output=True)
        if result.returncode:
            raise ValueError('Video encoding failed: '+result.stderr.decode(errors='replace')[-1000:])
        return output.read_bytes()
