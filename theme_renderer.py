#!/usr/bin/python3
"""Standalone, validated 320x320 theme renderer and Kraken screen updater."""
import argparse
import copy
import csv
import datetime
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
import psutil

SOURCES = {'text':'Texto libre', 'clock':'Reloj', 'cpu':'Temperatura CPU', 'gpu':'Temperatura GPU',
           'liquid':'Temperatura líquido', 'cpu_load':'Uso CPU', 'gpu_load':'Uso GPU',
           'ram':'Uso RAM', 'pump':'RPM bomba', 'fan':'RPM ventiladores'}
PERCENT = {'cpu_load', 'gpu_load', 'ram'}
FONT = '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf'
BOLD = '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf'


def text(source, x, y, size, color, title='', **extra):
    return dict(kind='text', source=source, x=x, y=y, size=size, color=color, title=title, visible=True, **extra)


def ring(source, radius, color):
    return dict(kind='ring', source=source, x=160, y=160, radius=radius, width=10, color=color, visible=True)


THEMES = {
    'Nebula': dict(version=1, name='Nebula', background='#07090f', background_image='', elements=[
        ring('cpu_load', 148, '#b35cff'), ring('gpu_load', 132, '#42d5ed'),
        text('clock',160,102,44,'#ffffff'), text('text',160,139,12,'#bca9d5','KRAKEN CONTROL'),
        text('cpu',160,179,32,'#ffffff','CPU'), text('gpu',160,217,27,'#55d4e7','GPU'),
        text('liquid',160,252,15,'#bca9d5','LÍQUIDO')]),
    'Minimal': dict(version=1, name='Minimal', background='#080e18', background_image='', elements=[
        ring('cpu_load',146,'#61dafb'), text('text',160,90,27,'#ffffff','CPU'),
        text('cpu',160,157,65,'#61dafb'), text('liquid',160,219,19,'#aab6ca','LÍQUIDO'),
        text('clock',160,254,15,'#ffffff')]),
    'Aurora': dict(version=1, name='Aurora', background='#08110e', background_image='', elements=[
        ring('ram',148,'#46e3a7'), ring('cpu_load',132,'#f3b95f'),
        text('clock',160,100,43,'#ffffff'), text('cpu',160,161,29,'#46e3a7','CPU'),
        text('gpu',160,202,26,'#f3b95f','GPU'), text('ram',160,246,18,'#b5d4c6','RAM')]),
}


def validate_theme(theme):
    if not isinstance(theme, dict) or theme.get('version') != 1:
        raise ValueError('Tema incompatible: se requiere formato versión 1')
    c = copy.deepcopy(theme)
    if not isinstance(c.get('name'), str) or not 1 <= len(c['name']) <= 60:
        raise ValueError('El nombre del tema debe tener entre 1 y 60 caracteres')
    def color(value):
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('Color inválido; usa #RRGGBB')
    def integer(v, low, high):
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f'Valor de tema fuera de rango ({low}–{high})')
    color(c.get('background'))
    bg = c.setdefault('background_image', '')
    if not isinstance(bg, str) or len(bg) > 2048 or any(v in bg for v in ('\n','\r','\0')):
        raise ValueError('Ruta de fondo inválida')
    if bg and (not Path(bg).is_absolute() or not Path(bg).is_file()):
        raise ValueError('La imagen de fondo no existe; selecciónala otra vez o quítala')
    elements = c.get('elements')
    if not isinstance(elements,list) or not 1 <= len(elements) <= 16:
        raise ValueError('Un tema debe tener entre 1 y 16 elementos')
    for e in elements:
        if not isinstance(e,dict) or e.get('kind') not in ('text','ring') or e.get('source') not in SOURCES:
            raise ValueError('Elemento de tema inválido')
        if type(e.get('visible')) is not bool:
            raise ValueError('Visibilidad inválida')
        integer(e.get('x'),0,320); integer(e.get('y'),0,320)
        color(e.get('color'))
        if e['kind'] == 'text':
            integer(e.get('size'),8,80)
            if not isinstance(e.get('title'),str) or len(e['title']) > 80 or any(v in e['title'] for v in ('\n','\r','\0')):
                raise ValueError('Texto inválido; máximo 80 caracteres en una línea')
        else:
            if e['source'] not in PERCENT:
                raise ValueError('Los anillos usan CPU, GPU o RAM en porcentaje')
            integer(e.get('radius'),10,155); integer(e.get('width'),2,24)
    return c


def value_label(source, values):
    if source == 'clock':
        return str(values.get('clock') or datetime.datetime.now().strftime('%H:%M'))
    value = values.get(source)
    if value is None:
        return '—'
    if source in ('cpu','gpu','liquid'):
        return f'{value:.1f} °C'
    if source in PERCENT:
        return f'{value:.0f}%'
    return f'{value:.0f} RPM'


def render(theme, values, resolution=320):
    """Same render function for the desktop preview, PNG exports and physical LCD."""
    c = validate_theme(theme)
    scale = 2
    image = Image.new('RGB',(320*scale,320*scale),c['background'])
    if c['background_image']:
        from PIL import ImageOps
        with Image.open(c['background_image']) as bg:
            image = ImageOps.fit(bg.convert('RGB'), image.size)
    draw = ImageDraw.Draw(image)
    for e in c['elements']:
        if not e['visible']:
            continue
        x,y=e['x']*scale,e['y']*scale
        if e['kind']=='ring':
            r=e['radius']*scale
            bounds=(x-r,y-r,x+r,y+r)
            draw.arc(bounds,130,410,fill='#292b32',width=e['width']*scale)
            value=values.get(e['source'])
            if isinstance(value,(int,float)) and math.isfinite(value) and value>0:
                draw.arc(bounds,130,130+280*min(100,value)/100,fill=e['color'],width=e['width']*scale)
        else:
            title=e['title']
            content=title if e['source']=='text' else value_label(e['source'],values)
            font=ImageFont.truetype(BOLD if e['size']>=24 else FONT,e['size']*scale)
            if e['source']!='text' and title:
                titlefont=ImageFont.truetype(FONT,max(9,e['size']//3)*scale)
                draw.text((x,y-(e['size']*.7)*scale),title,font=titlefont,fill=e['color'],anchor='mm')
            draw.text((x,y),content,font=font,fill=e['color'],anchor='mm')
    return image.resize((resolution,resolution),Image.Resampling.LANCZOS)


class LiveData:
    def __init__(self):
        self.last_cpu=None

    def sample(self):
        data={'clock':datetime.datetime.now().strftime('%H:%M')}
        for d in Path('/sys/class/hwmon').glob('hwmon*'):
            try:
                name=(d/'name').read_text().strip()
                fields={'k10temp':[('cpu','temp1_input',1000)],'coretemp':[('cpu','temp1_input',1000)],'z53':[('liquid','temp1_input',1000),('pump','fan1_input',1),('fan','fan2_input',1)]}
                for key,filename,div in fields.get(name,[]):
                    data[key]=float((d/filename).read_text())/div
            except (OSError,ValueError):
                pass
        t=psutil.cpu_times()
        current=(sum(t)-getattr(t,'guest',0)-getattr(t,'guest_nice',0),t.idle+getattr(t,'iowait',0))
        if self.last_cpu:
            total=current[0]-self.last_cpu[0]
            if total>0: data['cpu_load']=max(0,min(100,100*(1-(current[1]-self.last_cpu[1])/total)))
        self.last_cpu=current
        mem=psutil.virtual_memory()
        data['ram']=100*(1-mem.available/mem.total)
        try:
            p=subprocess.run(['/usr/bin/nvidia-smi','--id=0','--query-gpu=temperature.gpu,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2)
            if not p.returncode:
                row=next(csv.reader([p.stdout.strip()]))
                for key,value in zip(('gpu','gpu_load'),row):
                    try:
                        v=float(value)
                        if math.isfinite(v) and v>=0: data[key]=v
                    except ValueError:
                        pass
        except (OSError,subprocess.TimeoutExpired,StopIteration,csv.Error):
            pass
        return data


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--export',help='Exportar PNG y salir sin acceder al Kraken')
    args=parser.parse_args()
    theme=validate_theme(json.loads(Path(args.config).read_text()))
    live=LiveData()
    if args.export:
        render(theme,live.sample()).save(args.export)
        return
    with tempfile.TemporaryDirectory(prefix='kraken-theme-') as directory:
        frame=Path(directory)/'frame.png'
        while True:
            render(theme,live.sample()).save(frame)
            subprocess.run(['/usr/bin/liquidctl','--match','NZXT Kraken Z','set','lcd','screen','static',str(frame)],check=True,timeout=25)
            time.sleep(3)


if __name__=='__main__':
    main()
