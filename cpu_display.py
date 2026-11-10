#!/usr/bin/python3
"""Show CPU temperature on the NZXT Kraken Z LCD."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont


def cpu_temperature():
    for hwmon in Path('/sys/class/hwmon').glob('hwmon*'):
        if (hwmon / 'name').read_text().strip() in ('k10temp','coretemp'):
            for label in hwmon.glob('temp*_label'):
                if label.read_text().strip() in ('Tctl','Package id 0'):
                    return int(label.with_name(label.name.replace('_label', '_input')).read_text()) / 1000
    raise RuntimeError('No se encontró un sensor de temperatura del CPU compatible.')


def render(temperature, destination):
    image = Image.new('RGB', (320, 320), '#080e18')
    draw = ImageDraw.Draw(image)
    font_path = '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf'
    color = '#61dafb' if temperature < 80 else '#ffab57'
    draw.ellipse((12, 12, 308, 308), outline=color, width=5)
    for text, y, size, fill in [('CPU', 94, 36, '#ffffff'),
                                (f'{temperature:.0f} °C', 170, 72, color),
                                ('CPU', 240, 20, '#aab6ca')]:
        font = ImageFont.truetype(font_path, size)
        draw.text((160, y), text, font=font, fill=fill, anchor='mm')
    image.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', metavar='PNG', help='Crear una imagen sin acceder al Kraken')
    args = parser.parse_args()
    if args.preview:
        temperature = cpu_temperature()
        render(temperature, args.preview)
        print(f'CPU: {temperature:.1f} °C. Vista previa: {args.preview}')
        return
    with tempfile.TemporaryDirectory(prefix='kraken-cpu-') as directory:
        frame = Path(directory) / 'cpu.png'
        print('Mostrando temperatura del CPU cada 3 segundos. Ctrl+C para detener.', flush=True)
        try:
            while True:
                render(cpu_temperature(), frame)
                subprocess.run(['/usr/bin/liquidctl', '--match', 'NZXT Kraken Z',
                                'set', 'lcd', 'screen', 'static', str(frame)],
                               check=True, timeout=20)
                time.sleep(3)
        except KeyboardInterrupt:
            print('\nActualización detenida.')


if __name__ == '__main__':
    main()
