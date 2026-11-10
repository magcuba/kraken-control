"""Validated Kraken actions; invoked through pkexec only for explicit writes."""
import contextlib
import hashlib
import importlib.util
import shutil
import json
import os
from pathlib import Path
import subprocess
import sys
import time

LIQ = ['/usr/bin/liquidctl', '--match', 'NZXT Kraken Z']
SERVICE = 'kraken-control.service'
DROPIN = Path('/etc/systemd/system/kraken-control.service.d/90-profile.conf')
RUNTIME = Path('/run/systemd/system/kraken-control.service.d/95-kraken-screen-preview.conf')
THEME_RENDERER = Path('/usr/local/lib/kraken-control/theme_renderer.py')
THEME_DATA = Path('/var/lib/kraken-control/themes')


def run(args, timeout=45, check=True):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f'Error {p.returncode}: {args[0]}')
    return p


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'Valor fuera de rango ({low}–{high}): {value}')
    return value


def validate(c):
    if not isinstance(c, dict):
        raise ValueError('Configuración inválida')
    for key in ('fan_enabled', 'pump_enabled'):
        if type(c.get(key)) is not bool:
            raise ValueError('Selección inválida')
    integer(c.get('fan'), 0, 100)
    integer(c.get('pump'), 20, 100)
    integer(c.get('brightness'), 0, 100)
    if c.get('angle') not in (0, 90, 180, 270):
        raise ValueError('Orientación inválida')
    if c.get('fan_mode') not in ('fixed', 'curve'):
        raise ValueError('Modo de ventiladores inválido')
    if c.get('screen') not in ('cpu', 'liquid', 'static', 'gif', 'theme'):
        raise ValueError('Modo de pantalla inválido')
    c.setdefault('pump_mode', 'fixed')
    c.setdefault('pump_curve', [[30, 60], [35, 70], [40, 85], [45, 100]])
    if c['pump_mode'] not in ('fixed', 'curve'):
        raise ValueError('Modo de bomba inválido')
    validate_curve(c['pump_curve'], 20)
    validate_curve(c.get('curve'), 0)
    if c['screen'] in ('static', 'gif'):
        p = Path(c.get('media', ''))
        if not p.is_absolute() or not p.is_file() or any(x in str(p) for x in ('\n', '\r', '\0')):
            raise ValueError('Selecciona un archivo de imagen o GIF existente')
    if c['screen'] == 'theme':
        c['theme'] = theme_module().validate_theme(c.get('theme'))
    return c


def validate_curve(curve, minimum):
    if not isinstance(curve, list) or not 2 <= len(curve) <= 9:
        raise ValueError('La curva requiere entre 2 y 9 puntos')
    last = -1
    for point in curve:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('Punto de curva inválido')
        t, duty = point
        integer(t, 0, 59)
        integer(duty, minimum, 100)
        if t <= last:
            raise ValueError('Las temperaturas de la curva deben aumentar')
        last = t


def cooling(c):
    commands = []
    if c['fan_enabled']:
        values = [c['fan']] if c['fan_mode'] == 'fixed' else [v for pair in c['curve'] for v in pair]
        commands.append(LIQ + ['set', 'fan', 'speed'] + list(map(str, values)))
    if c['pump_enabled']:
        values = [c['pump']] if c.get('pump_mode', 'fixed') == 'fixed' else [v for pair in c['pump_curve'] for v in pair]
        commands.append(LIQ + ['set', 'pump', 'speed'] + list(map(str, values)))
    return commands


def display(c):
    return LIQ + ['set', 'lcd', 'screen', c['screen']] + ([c['media']] if c['screen'] in ('static', 'gif') else [])


def setup(c):
    return [LIQ + ['initialize'],
            LIQ + ['set', 'lcd', 'screen', 'orientation', str(c['angle'])],
            LIQ + ['set', 'lcd', 'screen', 'brightness', str(c['brightness'])]] + cooling(c)


def unit_command(args):
    # systemd quoting: no shell; neutralize specifier and environment expansion.
    return ' '.join(json.dumps(str(v).replace('%', '%%').replace('$', '$$'), ensure_ascii=False) for v in args)


def theme_module():
    path = Path(__file__).resolve().with_name('theme_renderer.py')
    spec = importlib.util.spec_from_file_location('kraken_theme_validation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def theme_command(c):
    content = json.dumps(c['theme'], sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(content.encode()).hexdigest()[:24]
    return ['/usr/bin/python3', '-I', str(THEME_RENDERER), '--config', str(THEME_DATA / (digest+'.json'))]


def install_theme(c):
    THEME_RENDERER.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().with_name('theme_renderer.py')
    if source.resolve() != THEME_RENDERER.resolve():
        shutil.copyfile(source, THEME_RENDERER)
    THEME_RENDERER.chmod(0o644)
    THEME_DATA.mkdir(parents=True, exist_ok=True)
    theme = json.loads(json.dumps(c['theme']))
    # Copy an optional background so the service does not depend on a user/temp file.
    if theme.get('background_image'):
        original = Path(theme['background_image'])
        digest = hashlib.sha256(original.read_bytes()).hexdigest()[:24]
        target = THEME_DATA / (digest+'.image')
        shutil.copyfile(original, target)
        target.chmod(0o644)
        theme['background_image'] = str(target)
    target = Path(theme_command(c)[-1])
    target.write_text(json.dumps(theme, ensure_ascii=False))
    target.chmod(0o644)


def runtime_text(c):
    command = theme_command(c) if c['screen'] == 'theme' else ['/usr/bin/python3','-u','/usr/local/lib/kraken-control/cpu_display.py']
    lines = ['[Service]', 'Type=simple', 'Restart=always', 'RemainAfterExit=no', 'ExecStart=',
             'ExecStart='+unit_command(command)]
    # Retain existing startup/cooling settings, then apply the screen controls.
    lines += ['ExecStartPre='+unit_command(a) for a in setup(c)[1:3]]
    return '\n'.join(lines)+'\n'


def unit_text(c):
    lines = ['# Managed by Kraken Control. Remove this drop-in to restore the original service.', '[Service]',
             'ExecStartPre=', 'ExecStart=', 'ExecStartPost=', 'RemainAfterExit=no']
    lines += ['ExecStartPre=' + unit_command(a) for a in setup(c)]
    if c['screen'] in ('cpu','theme'):
        command = theme_command(c) if c['screen'] == 'theme' else ['/usr/bin/python3','-u','/usr/local/lib/kraken-control/cpu_display.py']
        lines += ['Type=simple', 'Restart=always', 'ExecStart='+unit_command(command)]
    else:
        lines += ['Type=oneshot', 'Restart=no', 'RemainAfterExit=yes', 'ExecStart=' + unit_command(display(c))]
    return '\n'.join(lines) + '\n'


@contextlib.contextmanager
def pause_writer():
    result = run(['/usr/bin/systemctl', 'show', SERVICE, '--property=MainPID', '--value'])
    pid = int(result.stdout.strip() or '0')
    if pid:
        # Pause the Python writer, allowing an already running USB child to finish.
        run(['/usr/bin/systemctl', 'kill', '--kill-whom=main', '--signal=SIGSTOP', SERVICE])
    try:
        if pid:
            deadline = time.monotonic() + 25
            children = Path(f'/proc/{pid}/task/{pid}/children')
            while children.exists():
                running = []
                for child in children.read_text().split():
                    try:
                        state = Path(f'/proc/{child}/stat').read_text().rsplit(')', 1)[1].split()[0]
                        if state != 'Z':
                            running.append(child)
                    except FileNotFoundError:
                        pass
                if not running:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('El actualizador USB sigue ocupado; no se modificaron velocidades. Intenta de nuevo.')
                time.sleep(0.2)
        yield
    finally:
        if pid:
            run(['/usr/bin/systemctl', 'kill', '--kill-whom=main', '--signal=SIGCONT', SERVICE], check=False)


def perform(action, c):
    if action in ('start', 'stop', 'restart', 'enable', 'disable'):
        args = ['/usr/bin/systemctl', action]
        if action == 'enable':
            args += ['--now']
        run(args + [SERVICE])
        return 'Servicio actualizado.'
    c = validate(c)
    if action == 'cooling':
        cmds = cooling(c)
        if not cmds:
            raise ValueError('Activa el control de ventiladores o bomba antes de aplicar')
        with pause_writer():
            for cmd in cmds:
                run(cmd)
        return 'Refrigeración aplicada. No se ha guardado para el próximo arranque.'
    if action == 'screen':
        previous = run(['/usr/bin/systemctl', 'is-active', '--quiet', SERVICE], check=False).returncode == 0
        old_runtime = RUNTIME.read_bytes() if RUNTIME.exists() else None
        if c['screen'] == 'theme':
            install_theme(c)
        run(['/usr/bin/systemctl', 'stop', SERVICE])
        try:
            if c['screen'] in ('cpu','theme'):
                RUNTIME.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME.write_text(runtime_text(c))
                RUNTIME.chmod(0o644)
                run(['/usr/bin/systemctl', 'daemon-reload'])
                run(['/usr/bin/systemctl', 'start', SERVICE])
            else:
                RUNTIME.unlink(missing_ok=True)
                run(['/usr/bin/systemctl', 'daemon-reload'])
                for cmd in setup(c)[1:3]:
                    run(cmd)
                run(display(c))
        except Exception:
            if old_runtime is None:
                RUNTIME.unlink(missing_ok=True)
            else:
                RUNTIME.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME.write_bytes(old_runtime)
            run(['/usr/bin/systemctl', 'daemon-reload'], check=False)
            if previous:
                run(['/usr/bin/systemctl', 'start', SERVICE], check=False)
            raise
        return 'Pantalla aplicada. Para conservarla al reiniciar, usa «Guardar perfil al arrancar».'
    if action == 'save':
        if c['screen'] in ('static', 'gif') and (c['media'].startswith('/tmp/') or c['media'].startswith('/var/tmp/')):
            raise ValueError('Para guardar al arrancar, mueve la imagen o GIF a una carpeta permanente de tu usuario.')
        if c['screen'] == 'theme':
            install_theme(c)
        old_runtime = RUNTIME.read_bytes() if RUNTIME.exists() else None
        RUNTIME.unlink(missing_ok=True)
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        old = DROPIN.read_bytes() if DROPIN.exists() else None
        temp = DROPIN.with_suffix('.tmp')
        temp.write_text(unit_text(c))
        temp.chmod(0o644)
        temp.replace(DROPIN)
        try:
            run(['/usr/bin/systemctl', 'daemon-reload'])
            run(['/usr/bin/systemctl', 'enable', SERVICE])
            run(['/usr/bin/systemctl', 'restart', SERVICE])
        except Exception:
            if old_runtime is not None:
                RUNTIME.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME.write_bytes(old_runtime)
            if old is None:
                DROPIN.unlink(missing_ok=True)
            else:
                DROPIN.write_bytes(old)
            run(['/usr/bin/systemctl', 'daemon-reload'], check=False)
            run(['/usr/bin/systemctl', 'restart', SERVICE], check=False)
            raise
        return 'Configuración aplicada y guardada para cada arranque.'
    raise ValueError('Acción desconocida')


if __name__ == '__main__':
    try:
        if os.geteuid() != 0:
            raise RuntimeError('Esta acción requiere autenticación de administrador')
        if len(sys.argv) != 3:
            raise ValueError('Argumentos inválidos')
        print(perform(sys.argv[1], json.loads(sys.argv[2])))
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
