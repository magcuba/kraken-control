#!/usr/bin/python3
"""Kraken Control — desktop controls for this machine's NZXT Kraken Z."""
import json
from pathlib import Path
import subprocess
import sys
import threading

from monitor import Monitor

ROOT = Path(__file__).resolve().parent
PREFS = Path.home() / '.config/kraken-control/settings.json'
DEFAULT = dict(fan_enabled=False, pump_enabled=False, fan=60, pump=70,
               fan_mode='fixed', curve=[[30, 40], [35, 60], [40, 80], [45, 100]],
               angle=180, brightness=75, screen='cpu', media='', pump_mode='fixed',
               pump_curve=[[30, 60], [35, 70], [40, 85], [45, 100]])


def sensors():
    data = {}
    for d in Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            name = (d / 'name').read_text().strip()
            fields = {'k10temp': [('cpu', 'temp1_input', 1000)],
                      'coretemp': [('cpu', 'temp1_input', 1000)],
                      'z53': [('liquid', 'temp1_input', 1000), ('pump', 'fan1_input', 1), ('fan', 'fan2_input', 1)]}
            for key, filename, divisor in fields.get(name, []):
                try:
                    data[key] = float((d / filename).read_text()) / divisor
                except (OSError, ValueError):
                    pass
        except OSError:
            pass
    return data


def launch():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib, Gio
    from dashboard import Dashboard, CurveGraph
    from theme_editor import ThemeEditor

    class Window(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title='Kraken Control')
            self.set_default_size(1180, 850)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.busy = False
            self.monitor_reading = False
            self.monitor = Monitor()
            self.monitor_values = None
            self.latest_sensors = {}
            self.controls = []
            self.cfg = DEFAULT.copy()
            try:
                loaded = json.loads(PREFS.read_text())
                from backend import validate
                self.cfg.update(validate(loaded))
            except (OSError, ValueError, KeyError, TypeError):
                pass
            css = Gtk.CssProvider()
            css.load_from_data(b'''
                window { background: #141517; color: #edf0f5; }
                .hero { font-size: 24px; font-weight: bold; color: #f8f8fa; }
                .sub { color: #9698a5; font-size: 12px; }
                .card { background: #1d1f22; border: 1px solid #36383e; border-radius: 8px; padding: 16px; }
                .card-title { font-size: 17px; font-weight: bold; }
                .cooling-panel { background: #1d1f22; border: 2px solid #8b55e5; border-radius: 10px; padding: 16px; }
                .reading { font-size: 16px; color: #eeeef7; }
                .gauge-value { font-size: 29px; font-weight: 300; }
                .sidebar { background: #101113; border-right: 1px solid #2e3036; }
                .sidebar row { padding: 15px 13px; color: #999ba8; border-left: 3px solid transparent; }
                .sidebar row:selected { background: #23202b; color: #d5c3ff; border-left-color: #a980ff; }
                .sidebar list { background: transparent; }
                button { padding: 8px 13px; border-radius: 5px; }
                .suggested-action { background: #774bd1; color: white; border-color: #9065ed; }
                entry, spinbutton, combobox button { color: #edf0f5; background: #303139; }
                treeview { background: #1d1f22; color: #edf0f5; }
                treeview:selected { background: #41325d; }
                progressbar trough { min-height: 12px; background: #111214; border-radius: 3px; }
                progressbar progress { background: #a78bda; border-radius: 3px; }
                .status { color: #b4b6c2; padding: 8px; }
            ''')
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.add(root)
            header = Gtk.Box(spacing=22, margin=18)
            root.pack_start(header, False, False, 0)
            head = Gtk.Label(label='KRAKEN CONTROL', xalign=0)
            head.get_style_context().add_class('hero')
            header.pack_start(head, False, False, 0)
            subtitle = Gtk.Label(label='PC MONITORING  /  UBUNTU', xalign=0)
            subtitle.get_style_context().add_class('sub')
            header.pack_start(subtitle, True, True, 0)
            self.service_label = Gtk.Label(label='Consultando servicio…', xalign=1)
            self.service_label.get_style_context().add_class('sub')
            header.pack_end(self.service_label, False, False, 0)
            body = Gtk.Box()
            root.pack_start(body, True, True, 0)
            tabs = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=160)
            tabs.set_homogeneous(False)
            sidebar = Gtk.StackSidebar(stack=tabs)
            sidebar.set_size_request(185, -1)
            sidebar.get_style_context().add_class('sidebar')
            body.pack_start(sidebar, False, False, 0)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            body.pack_start(outer, True, True, 0)
            outer.pack_start(tabs, True, True, 0)
            dashboard_scroll = Gtk.ScrolledWindow()
            dashboard_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.dashboard = Dashboard()
            dashboard_scroll.add(self.dashboard)
            tabs.add_titled(dashboard_scroll, 'overview', 'Monitor del PC')
            self.cooling_page(tabs)
            self.screen_page(tabs)
            self.service_page(tabs)
            footer = Gtk.Box(spacing=10, margin_start=18, margin_end=18)
            self.spinner = Gtk.Spinner()
            footer.pack_start(self.spinner, False, False, 0)
            save_button = self.button('Guardar perfil al arrancar', self.save, primary=True)
            footer.pack_start(save_button, False, False, 0)
            outer.pack_start(footer, False, False, 0)
            save_button.set_no_show_all(True)
            tabs.connect('notify::visible-child-name', lambda *_: save_button.set_visible(tabs.get_visible_child_name() in ('Refrigeración', 'Pantalla LCD')))
            self.message = Gtk.Label(label='Lecturas en vivo cada 3 s. Los cambios de refrigeración se aplican solo al pulsar Aplicar.', xalign=0)
            self.message.set_line_wrap(True)
            self.message.set_max_width_chars(100)
            self.message.set_selectable(True)
            self.message.get_style_context().add_class('status')
            outer.pack_start(self.message, False, False, 0)
            self.refresh()
            GLib.timeout_add_seconds(3, self.refresh)
            self.refresh_service()
            GLib.timeout_add_seconds(8, self.refresh_service)

        def button(self, title, callback, primary=False):
            b = Gtk.Button(label=title)
            b.connect('clicked', lambda _: callback())
            if primary:
                b.get_style_context().add_class('suggested-action')
            self.controls.append(b)
            return b

        def page(self, tabs, title):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13, margin=18)
            scroll.add(box)
            tabs.add_titled(scroll, title, title)
            return box

        def row(self, box, title, widget):
            row = Gtk.Box(spacing=12)
            label = Gtk.Label(label=title, xalign=0)
            label.set_hexpand(True)
            row.pack_start(label, True, True, 0)
            row.pack_start(widget, False, False, 0)
            box.pack_start(row, False, False, 0)

        def spin(self, low, high, value):
            w = Gtk.SpinButton.new_with_range(low, high, 1)
            w.set_value(value)
            return w

        def combo(self, values, active):
            w = Gtk.ComboBoxText()
            for key, label in values:
                w.append(key, label)
            w.set_active_id(str(active))
            return w

        def note(self, box, text):
            label = Gtk.Label(label=text, xalign=0)
            label.set_line_wrap(True)
            label.set_max_width_chars(85)
            label.get_style_context().add_class('sub')
            box.pack_start(label, False, False, 0)

        def cooling_page(self, tabs):
            box = self.page(tabs, 'Refrigeración')
            box.get_style_context().add_class('cooling-panel')
            self._loading_profile = False
            self.cooling_live = Gtk.Label(label='Leyendo Kraken…', xalign=0)
            self.cooling_live.get_style_context().add_class('reading')
            box.pack_start(self.cooling_live, False, False, 0)
            self.note(box, 'Los perfiles son propuestas de Kraken Control. Comprueba temperaturas y ruido al probarlos. Los valores visibles son ajustes preparados; no se envían hasta pulsar Aplicar.')
            channels = Gtk.Box(spacing=14, homogeneous=True)
            box.pack_start(channels, False, False, 0)
            self.profiles = {}
            for key, title, low in [('fan', 'Ventiladores del Kraken', 0), ('pump', 'Bomba del Kraken', 20)]:
                panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                panel.get_style_context().add_class('card')
                channels.pack_start(panel, True, True, 0)
                enabled = Gtk.CheckButton(label='Modificar ' + ('ventiladores' if key == 'fan' else 'bomba'))
                enabled.set_active(self.cfg[key+'_enabled'])
                setattr(self, key+'_enabled', enabled)
                panel.pack_start(enabled, False, False, 0)
                profile = self.combo([('fixed', 'Fijo'), ('silent', 'Silencioso'), ('performance', 'Rendimiento'), ('custom', 'Personalizado')],
                                     'fixed' if self.cfg[key+'_mode'] == 'fixed' else 'custom')
                self.profiles[key] = profile
                self.row(panel, 'Perfil', profile)
                mode = self.combo([('fixed', 'Velocidad fija'), ('curve', 'Curva por líquido')], self.cfg[key+'_mode'])
                setattr(self, key+'_mode', mode)
                self.row(panel, 'Control', mode)
                spin = self.spin(low, 100, self.cfg[key])
                setattr(self, key, spin)
                self.row(panel, 'Velocidad fija (%)', spin)
            self.graph_channel = self.combo([('fan', 'Ventiladores'), ('pump', 'Bomba')], 'fan')
            self.row(box, 'Editar curva · Fuente: temperatura del líquido', self.graph_channel)
            self.graph = CurveGraph(self.graph_points, self.graph_set_point)
            box.pack_start(self.graph, False, False, 0)
            self.note(box, 'Arrastra los puntos verdes o edita los valores de abajo. La línea violeta marca la temperatura actual del líquido. Los cambios quedan pendientes hasta aplicarlos.')
            for key in ('fan', 'pump'):
                container = Gtk.Box(spacing=10)
                points = []
                values = self.cfg['curve' if key == 'fan' else 'pump_curve']
                for t, d in values:
                    row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    a, b = self.spin(20, 59, t), self.spin(0 if key == 'fan' else 20, 100, d)
                    line = Gtk.Box(spacing=3)
                    for w in (a, Gtk.Label(label='°C')):
                        line.pack_start(w, False, False, 0)
                    row.pack_start(line, False, False, 0)
                    line = Gtk.Box(spacing=3)
                    for w in (b, Gtk.Label(label='%')):
                        line.pack_start(w, False, False, 0)
                    row.pack_start(line, False, False, 0)
                    points.append((a, b))
                    container.pack_start(row, False, False, 0)
                setattr(self, 'points' if key == 'fan' else 'pump_points', points)
                setattr(self, key+'_curve_box', container)
                box.pack_start(container, False, False, 0)
                container.show_all()
                container.set_no_show_all(True)
            for key in ('fan', 'pump'):
                self.profiles[key].connect('changed', lambda _, k=key: self.select_profile(k))
                getattr(self, key+'_mode').connect('changed', lambda _, k=key: self.mode_changed(k))
                getattr(self, key).connect('value-changed', lambda _: self.graph.queue_draw())
                for a, b in (self.points if key == 'fan' else self.pump_points):
                    for spin in (a, b):
                        spin.connect('value-changed', lambda _, k=key: self.curve_changed(k))
            self.graph_channel.connect('changed', lambda _: self.update_mode())
            box.pack_start(self.button('Aplicar refrigeración', lambda: self.action('cooling'), primary=True), False, False, 0)
            self.update_mode()

        def select_profile(self, key):
            if self._loading_profile:
                return
            profile = self.profiles[key].get_active_id()
            self._loading_profile = True
            try:
                getattr(self, key+'_mode').set_active_id('fixed' if profile == 'fixed' else 'curve')
                if profile in ('silent', 'performance'):
                    curves = {
                        ('fan', 'silent'): [[30,30], [35,45], [40,70], [45,100]],
                        ('fan', 'performance'): [[30,60], [35,75], [40,90], [45,100]],
                        ('pump', 'silent'): [[30,55], [35,65], [40,80], [45,100]],
                        ('pump', 'performance'): [[30,80], [35,90], [40,100], [45,100]],
                    }
                    points = self.points if key == 'fan' else self.pump_points
                    for (a, b), (t, duty) in zip(points, curves[key, profile]):
                        a.set_value(t)
                        b.set_value(duty)
                getattr(self, key+'_enabled').set_active(True)
            finally:
                self._loading_profile = False
            self.update_mode()

        def mode_changed(self, key):
            if not self._loading_profile:
                self._loading_profile = True
                self.profiles[key].set_active_id('fixed' if getattr(self, key+'_mode').get_active_id() == 'fixed' else 'custom')
                self._loading_profile = False
            self.update_mode()

        def curve_changed(self, key):
            if not self._loading_profile:
                self._loading_profile = True
                self.profiles[key].set_active_id('custom')
                getattr(self, key+'_mode').set_active_id('curve')
                self._loading_profile = False
            self.update_mode()

        def update_mode(self):
            selected = self.graph_channel.get_active_id()
            for key in ('fan', 'pump'):
                fixed = getattr(self, key+'_mode').get_active_id() == 'fixed'
                getattr(self, key).set_sensitive(fixed)
                container = getattr(self, key+'_curve_box')
                container.set_visible(key == selected)
                container.set_sensitive(not fixed)
            self.graph.queue_draw()

        def graph_points(self):
            key = self.graph_channel.get_active_id()
            if getattr(self, key+'_mode').get_active_id() == 'fixed':
                value = getattr(self, key).get_value_as_int()
                return [(20, value), (59, value)]
            return [(a.get_value_as_int(), b.get_value_as_int()) for a, b in (self.points if key == 'fan' else self.pump_points)]

        def graph_set_point(self, index, t, duty):
            key = self.graph_channel.get_active_id()
            if getattr(self, key+'_mode').get_active_id() == 'fixed':
                return
            points = self.points if key == 'fan' else self.pump_points
            lower = points[index-1][0].get_value_as_int()+1 if index else 20
            upper = points[index+1][0].get_value_as_int()-1 if index < len(points)-1 else 59
            points[index][0].set_value(max(lower, min(upper, t)))
            points[index][1].set_value(max(20 if key == 'pump' else 0, duty))

        def screen_page(self, tabs):
            box = self.page(tabs, 'Pantalla LCD')
            self.screen = self.combo([('cpu', 'Temperatura del CPU en vivo'), ('liquid', 'Temperatura del líquido'),
                                      ('static', 'Imagen fija'), ('gif', 'GIF animado'), ('theme', 'Tema personalizable en vivo')], self.cfg['screen'])
            self.row(box, 'Contenido', self.screen)
            self.angle = self.combo([(str(v), f'{v}°') for v in (0, 90, 180, 270)], self.cfg['angle'])
            self.row(box, 'Orientación', self.angle)
            self.brightness = self.spin(0, 100, self.cfg['brightness'])
            self.row(box, 'Brillo (%)', self.brightness)
            self.media = Gtk.FileChooserButton(title='Seleccionar imagen o GIF', action=Gtk.FileChooserAction.OPEN)
            filt = Gtk.FileFilter()
            filt.set_name('Imágenes y GIF')
            for mime in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'):
                filt.add_mime_type(mime)
            self.media.add_filter(filt)
            if self.cfg['media']:
                self.media.set_filename(self.cfg['media'])
            self.row(box, 'Archivo', self.media)
            self.note(box, 'Elige «Tema personalizable en vivo» para diseñar la pantalla. Guardar un tema lo añade a la galería; «Aplicar pantalla» lo envía al Kraken. «Guardar perfil al arrancar» lo conserva al reiniciar.')
            self.theme_editor = ThemeEditor(self.cfg.get('theme'))
            box.pack_start(self.theme_editor, False, False, 0)
            self.theme_editor.show_all()
            self.theme_editor.set_no_show_all(True)
            box.pack_start(self.button('Aplicar pantalla', lambda: self.action('screen'), primary=True), False, False, 0)
            def screen_changed(*_):
                self.media.set_sensitive(self.screen.get_active_id() in ('static', 'gif'))
                self.theme_editor.set_visible(self.screen.get_active_id() == 'theme')
            self.screen.connect('changed', screen_changed)
            screen_changed()

        def service_page(self, tabs):
            box = self.page(tabs, 'Servicio y diagnóstico')
            self.note(box, 'Servicio: kraken-control.service. Si has guardado un perfil, arrancar o reiniciar reaplica ese perfil. Deshabilitar el inicio automático no detiene el servicio actual.')
            row = Gtk.Box(spacing=7)
            for title, action in [('Arrancar', 'start'), ('Detener', 'stop'), ('Reiniciar', 'restart')]:
                row.pack_start(self.button(title, lambda a=action: self.action(a)), True, True, 0)
            box.pack_start(row, False, False, 0)
            row = Gtk.Box(spacing=7)
            for title, action in [('Habilitar al inicio', 'enable'), ('Deshabilitar al inicio', 'disable')]:
                row.pack_start(self.button(title, lambda a=action: self.action(a)), True, True, 0)
            box.pack_start(row, False, False, 0)
            box.pack_start(self.button('Ver registros recientes', self.logs), False, False, 0)
            box.pack_start(self.button('Abrir instrucciones', lambda: Gio.AppInfo.launch_default_for_uri(
                (ROOT / 'README.md').as_uri(), None)), False, False, 0)
            self.note(box, 'Los errores de liquidctl se muestran aquí. La aplicación no fuerza el acceso USB ni modifica ajustes de BIOS.')

        def values(self):
            from backend import validate
            return validate(dict(fan_enabled=self.fan_enabled.get_active(), pump_enabled=self.pump_enabled.get_active(),
                fan=self.fan.get_value_as_int(), pump=self.pump.get_value_as_int(), fan_mode=self.fan_mode.get_active_id(),
                curve=[[a.get_value_as_int(), b.get_value_as_int()] for a, b in self.points],
                pump_mode=self.pump_mode.get_active_id(),
                pump_curve=[[a.get_value_as_int(), b.get_value_as_int()] for a, b in self.pump_points],
                angle=int(self.angle.get_active_id()), brightness=self.brightness.get_value_as_int(),
                screen=self.screen.get_active_id(), media=self.media.get_filename() or '',
                theme=self.theme_editor.get_theme() if self.screen.get_active_id() == 'theme' else self.cfg.get('theme')))

        def save(self):
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                       buttons=Gtk.ButtonsType.OK_CANCEL, text='¿Aplicar y guardar este perfil para cada arranque?')
            dialog.format_secondary_text('Se guardarán la pantalla y los canales de refrigeración marcados. El servicio original se conserva; se añade una configuración propia de Kraken Control.')
            response = dialog.run()
            dialog.destroy()
            if response == Gtk.ResponseType.OK:
                self.action('save')

        def action(self, action):
            if self.busy:
                return
            try:
                cfg = self.values() if action in ('screen', 'cooling', 'save') else {}
            except Exception as e:
                self.message.set_text(str(e))
                return
            self.busy = True
            for b in self.controls:
                b.set_sensitive(False)
            self.spinner.start()
            self.message.set_text('Esperando autenticación / aplicando cambios…')
            def worker():
                try:
                    p = subprocess.run(['/usr/bin/pkexec', '/usr/bin/python3', '-I', str(ROOT / 'backend.py'), action, json.dumps(cfg)],
                                       capture_output=True, text=True, timeout=240)
                    if p.returncode:
                        msg = p.stderr.strip() or p.stdout.strip() or 'Autenticación cancelada o acceso denegado.'
                        if p.returncode < 0:
                            msg += '\nEl proceso terminó inesperadamente. Revisa los reportes de crash de Ubuntu.'
                    else:
                        msg = p.stdout.strip()
                        if cfg:
                            PREFS.parent.mkdir(parents=True, exist_ok=True)
                            PREFS.write_text(json.dumps(cfg, indent=2))
                    GLib.idle_add(self.done, msg)
                except Exception as e:
                    GLib.idle_add(self.done, str(e))
            threading.Thread(target=worker, daemon=True).start()

        def done(self, msg):
            self.busy = False
            self.spinner.stop()
            for b in self.controls:
                b.set_sensitive(True)
            self.message.set_text(msg)
            self.refresh()
            self.refresh_service()
            return False

        def refresh(self):
            data = sensors()
            self.latest_sensors = data
            self.update_theme_preview()
            temperatures = []
            for d in Path('/sys/class/hwmon').glob('hwmon*'):
                try:
                    if (d / 'name').read_text().strip() == 'jc42':
                        temperatures.append(int((d / 'temp1_input').read_text()) / 1000)
                except (OSError, ValueError):
                    pass
            self.dashboard.update_sensors(data, temperatures)
            self.cooling_live.set_text('Líquido: ' + (f"{data['liquid']:.1f} °C" if 'liquid' in data else '—') +
                                      '   ·   Bomba: ' + (f"{data['pump']:.0f} RPM" if 'pump' in data else '—') +
                                      '   ·   Ventiladores: ' + (f"{data['fan']:.0f} RPM" if 'fan' in data else '—'))
            self.graph.temperature = data.get('liquid')
            self.graph.queue_draw()
            if not self.monitor_reading:
                self.monitor_reading = True
                def worker():
                    try:
                        values = self.monitor.sample()
                        GLib.idle_add(self.update_monitor, values, None)
                    except Exception as e:
                        GLib.idle_add(self.update_monitor, None, str(e))
                threading.Thread(target=worker, daemon=True).start()
            return True

        def update_monitor(self, values, error):
            self.monitor_reading = False
            if error:
                self.dashboard.set_tooltip_text('Monitor: ' + error)
            else:
                self.dashboard.update(values)
                self.monitor_values = values
                self.update_theme_preview()
            return False

        def update_theme_preview(self):
            if self.screen.get_active_id() != 'theme':
                return
            values = dict(self.latest_sensors)
            if self.monitor_values:
                m = self.monitor_values
                values.update(cpu_load=m['cpu_load'], gpu=m['gpu'].get('temperature'), gpu_load=m['gpu'].get('load'), ram=m['memory']['percent'])
            self.theme_editor.update_values(values)

        def refresh_service(self):
            def worker():
                try:
                    p = subprocess.run(['/usr/bin/systemctl', 'show', 'kraken-control.service', '--property=ActiveState,UnitFileState'], capture_output=True, text=True, timeout=5)
                    if p.returncode:
                        text = 'Servicio: estado no accesible desde esta sesión'
                    else:
                        state = dict(line.split('=', 1) for line in p.stdout.splitlines() if '=' in line)
                        text = f"Servicio: {state.get('ActiveState', '?')} · Inicio: {state.get('UnitFileState', '?')}"
                    GLib.idle_add(self.service_label.set_text, text)
                except Exception:
                    pass
            threading.Thread(target=worker, daemon=True).start()
            return True

        def logs(self):
            def worker():
                try:
                    p = subprocess.run(['/usr/bin/journalctl', '-u', 'kraken-control.service', '-n', '65', '--no-pager'], capture_output=True, text=True, timeout=10)
                    text = p.stdout or p.stderr or 'Sin registros disponibles.'
                except Exception as e:
                    text = str(e)
                GLib.idle_add(self.show_logs, text)
            threading.Thread(target=worker, daemon=True).start()

        def show_logs(self, text):
            dialog = Gtk.Dialog(title='Registros del Kraken', transient_for=self, modal=True)
            dialog.set_default_size(780, 440)
            dialog.add_button('Cerrar', Gtk.ResponseType.CLOSE)
            view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            view.get_buffer().set_text(text)
            scroll = Gtk.ScrolledWindow()
            scroll.add(view)
            dialog.get_content_area().pack_start(scroll, True, True, 0)
            dialog.show_all()
            dialog.run()
            dialog.destroy()
            return False

    app = Gtk.Application(application_id='io.github.magcuba.KrakenControl')
    def activate(app):
        if app.get_active_window():
            app.get_active_window().present()
        else:
            Window(app).show_all()
    app.connect('activate', activate)
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(launch())
