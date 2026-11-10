"""GTK widgets for the read-only PC dashboard and liquid-temperature curves."""
import math
import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango, GdkPixbuf, GLib


def label(text='', style=None, xalign=0):
    w = Gtk.Label(label=text, xalign=xalign)
    if style:
        w.get_style_context().add_class(style)
    w.set_ellipsize(Pango.EllipsizeMode.END)
    return w


def size(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def canvas(width, height):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    return surface, cairo.Context(surface)


def canvas_pixbuf(surface):
    surface.flush()
    width, height = surface.get_width(), surface.get_height()
    raw = bytes(surface.get_data())
    # Cairo ARGB32 uses native byte order; this x86_64 machine stores BGRA.
    pixels = bytearray(width*height*4)
    stride = surface.get_stride()
    for y in range(height):
        source = raw[y*stride:y*stride+width*4]
        dest = y*width*4
        pixels[dest:dest+width*4:4] = source[2::4]
        pixels[dest+1:dest+width*4:4] = source[1::4]
        pixels[dest+2:dest+width*4:4] = source[0::4]
        pixels[dest+3:dest+width*4:4] = source[3::4]
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(pixels)), GdkPixbuf.Colorspace.RGB, True, 8, width, height, width*4)


class Gauge(Gtk.Overlay):
    def __init__(self, title='Uso'):
        super().__init__()
        self.value = None
        self.image = Gtk.Image()
        self.image.set_size_request(150, 150)
        self.add(self.image)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        self.text = label('—', 'gauge-value', 0.5)
        box.pack_start(self.text, False, False, 0)
        box.pack_start(label(title, 'sub', 0.5), False, False, 0)
        self.add_overlay(box)
        self.update(None)

    def update(self, value):
        self.value = value
        self.text.set_text(f'{value:.0f}%' if value is not None else '—')
        surface, cr = canvas(150, 150)
        cr.set_source_rgb(.114, .122, .133)
        cr.paint()
        cr.set_line_width(9)
        cr.set_source_rgb(.086, .09, .102)
        cr.arc(75, 75, 60, 0, 2*math.pi)
        cr.stroke()
        if value is not None and value > 0:
            cr.set_source_rgb(.655, .478, .98)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.arc(75, 75, 60, -math.pi/2, -math.pi/2+2*math.pi*min(100, value)/100)
            cr.stroke()
        self.image.set_from_pixbuf(canvas_pixbuf(surface))


class Dashboard(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)
        self.fields = {}
        top = Gtk.Box(spacing=14, homogeneous=True)
        self.pack_start(top, False, False, 0)
        self.gauges = {}
        for key, title in [('cpu', 'CPU'), ('gpu', 'GPU')]:
            card = self.card(title)
            top.pack_start(card, True, True, 0)
            name = label('Detectando dispositivo…', 'sub')
            self.fields[key+'_name'] = name
            card.pack_start(name, False, False, 0)
            body = Gtk.Box(spacing=14)
            card.pack_start(body, True, True, 0)
            gauge = Gauge()
            self.gauges[key] = gauge
            body.pack_start(gauge, False, False, 0)
            stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            body.pack_start(stats, True, True, 0)
            for k, title in [('temp', 'Temperatura'), ('clock', 'Frecuencia'), ('fan' if key == 'gpu' else 'pump', 'Ventilador GPU' if key == 'gpu' else 'Bomba Kraken')]:
                self.stat(stats, key+'_'+k, title)
            if key == 'gpu':
                self.stat(stats, 'vram', 'Memoria gráfica')
        middle = Gtk.Box(spacing=14, homogeneous=True)
        self.pack_start(middle, False, False, 0)
        ram = self.card('RAM')
        middle.pack_start(ram, True, True, 0)
        self.ram_gauge = Gauge()
        ram.pack_start(self.ram_gauge, False, False, 0)
        self.fields['ram'] = label('—', 'sub')
        ram.pack_start(self.fields['ram'], False, False, 0)
        self.fields['ram_temp'] = label('Temperatura: —', 'sub')
        ram.pack_start(self.fields['ram_temp'], False, False, 0)
        network = self.card('Red')
        middle.pack_start(network, True, True, 0)
        self.stat(network, 'download', '↓ Descarga')
        self.stat(network, 'upload', '↑ Subida')
        self.fields['interfaces'] = label('Muestreando…', 'sub')
        network.pack_start(self.fields['interfaces'], False, False, 0)
        disk = self.card('Almacenamiento')
        middle.pack_start(disk, True, True, 0)
        self.disk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        disk.pack_start(self.disk_box, True, True, 0)
        cooling = self.card('Kraken · Lecturas en vivo')
        self.pack_start(cooling, False, False, 0)
        row = Gtk.Box(spacing=20, homogeneous=True)
        cooling.pack_start(row, False, False, 0)
        for key, title in [('liquid', 'Líquido'), ('pump', 'Bomba'), ('fan', 'Ventiladores')]:
            self.stat(row, key, title)
        processes = self.card('Procesos · Mayor uso de CPU')
        self.pack_start(processes, True, True, 0)
        self.store = Gtk.ListStore(str, str, str, str)
        view = Gtk.TreeView(model=self.store)
        view.set_headers_visible(True)
        for i, title in enumerate(('Proceso', 'PID', 'CPU total', 'RAM')):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            column.set_expand(i == 0)
            view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(185)
        scroll.add(view)
        processes.pack_start(scroll, True, True, 0)
        note = label('Actualización cada 3 s · CPU por proceso expresada sobre la capacidad total del equipo', 'sub')
        self.pack_start(note, False, False, 0)

    def card(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class('card')
        box.pack_start(label(title, 'card-title'), False, False, 0)
        return box

    def stat(self, box, key, title):
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        group.pack_start(label(title, 'sub'), False, False, 0)
        value = label('—', 'reading')
        self.fields[key] = value
        group.pack_start(value, False, False, 0)
        box.pack_start(group, True, True, 0)

    def update_sensors(self, values, ram_temps):
        for key, field in [('cpu', 'cpu_temp'), ('liquid', 'liquid'), ('pump', 'pump'), ('pump', 'cpu_pump'), ('fan', 'fan')]:
            value = values.get(key)
            self.fields[field].set_text((f'{value:.1f} °C' if key in ('cpu', 'liquid') else f'{value:.0f} RPM') if value is not None else 'Sin lectura')
        self.fields['ram_temp'].set_text(f'Módulos: {min(ram_temps):.1f}–{max(ram_temps):.1f} °C' if ram_temps else 'Temperatura no disponible')

    def update(self, data):
        self.fields['cpu_name'].set_text(data['cpu_name'])
        self.gauges['cpu'].update(data['cpu_load'])
        self.fields['cpu_clock'].set_text(f"{data['cpu_clock']:.0f} MHz" if data['cpu_clock'] is not None else 'Sin lectura')
        gpu = data['gpu']
        self.fields['gpu_name'].set_text(gpu.get('name') or 'GPU NVIDIA · Sin acceso al controlador')
        self.gauges['gpu'].update(gpu.get('load'))
        for field, key, suffix in [('gpu_temp', 'temperature', '°C'), ('gpu_clock', 'clock', 'MHz'), ('gpu_fan', 'fan', '%')]:
            v = gpu.get(key)
            self.fields[field].set_text(f'{v:.0f} {suffix}' if v is not None else 'Sin lectura')
        used, total = gpu.get('vram_used'), gpu.get('vram_total')
        self.fields['vram'].set_text(f'{used/1024:.1f} / {total/1024:.1f} GiB' if used is not None and total is not None else 'Sin lectura')
        mem = data['memory']
        self.ram_gauge.update(mem['percent'])
        self.fields['ram'].set_text(f"{size(mem['used'])} / {size(mem['total'])}")
        net = data['network']
        for key in ('download', 'upload'):
            self.fields[key].set_text(size(net[key])+'/s' if net[key] is not None else ('Sin lectura' if net.get('unavailable') else 'Muestreando…'))
        self.fields['interfaces'].set_text('Sin acceso a la red' if net.get('unavailable') else (', '.join(net['interfaces']) or 'Sin interfaces activas'))
        for child in self.disk_box.get_children():
            self.disk_box.remove(child)
        for disk in data['storage'][:4]:
            text = label(disk['path'], 'sub')
            text.set_tooltip_text(disk['path'])
            self.disk_box.pack_start(text, False, False, 0)
            bar = Gtk.ProgressBar(show_text=True)
            bar.set_fraction(min(1, disk['percent']/100))
            bar.set_text(f"{size(disk['used'])} / {size(disk['total'])}")
            self.disk_box.pack_start(bar, False, False, 0)
        self.disk_box.show_all()
        self.store.clear()
        for p in data['processes']:
            self.store.append([p['name'], str(p['pid']), f"{p['cpu']:.1f}%" if p['cpu'] is not None else '—', size(p['ram'])])


class CurveGraph(Gtk.EventBox):
    """Editable curve rendered to a pixbuf; no GTK/Cairo bridge required."""
    def __init__(self, get_points, set_point):
        super().__init__()
        self.get_points = get_points
        self.set_point = set_point
        self.selected = None
        self.temperature = None
        self.dimensions = None
        self.image = Gtk.Image()
        self.add(self.image)
        self.set_size_request(560, 220)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect('size-allocate', self.allocated)
        self.connect('button-press-event', self.press)
        self.connect('motion-notify-event', self.motion)
        self.connect('button-release-event', self.release)
        self.set_tooltip_text('Arrastra un punto para ajustar temperatura y velocidad. Después pulsa Aplicar.')

    def xy(self, t, duty):
        w, h = max(560, self.get_allocated_width()), max(220, self.get_allocated_height())
        return 50+(t-20)/40*(w-75), 15+(100-duty)/100*(h-48)

    def allocated(self, _, allocation):
        if self.dimensions != (allocation.width, allocation.height):
            self.dimensions = (allocation.width, allocation.height)
            self.render()

    def queue_draw(self):
        self.render()
        super().queue_draw()

    def render(self):
        w, h = max(560, self.get_allocated_width()), max(220, self.get_allocated_height())
        surface, cr = canvas(w, h)
        cr.set_source_rgb(.114, .122, .133)
        cr.paint()
        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        for duty in (0, 25, 50, 75, 100):
            _, y = self.xy(20, duty)
            cr.set_source_rgb(.19, .20, .23)
            cr.move_to(50, y); cr.line_to(w-25, y); cr.stroke()
            cr.set_source_rgb(.62, .64, .7)
            cr.move_to(5, y+4); cr.show_text(f'{duty}%')
        for t in (20, 30, 40, 50, 60):
            x, _ = self.xy(t, 0)
            cr.move_to(x-12, h-8); cr.show_text(f'{t}°C')
        if self.temperature is not None:
            x, _ = self.xy(max(20, min(60, self.temperature)), 0)
            cr.set_source_rgba(.7, .55, 1, .5)
            cr.set_dash([4, 4]); cr.move_to(x, 15); cr.line_to(x, h-33); cr.stroke(); cr.set_dash([])
        points = self.get_points()
        if points:
            cr.set_source_rgb(.26, .84, .61)
            cr.set_line_width(2.5)
            cr.move_to(*self.xy(20, points[0][1]))
            for t, duty in points:
                cr.line_to(*self.xy(t, duty))
            cr.line_to(*self.xy(60, points[-1][1])); cr.stroke()
            for t, duty in points:
                cr.arc(*self.xy(t, duty), 5, 0, 2*math.pi); cr.fill()
        self.image.set_from_pixbuf(canvas_pixbuf(surface))

    def press(self, area, event):
        if event.button != 1:
            return False
        for i, point in enumerate(self.get_points()):
            x, y = self.xy(*point)
            if (x-event.x)**2+(y-event.y)**2 < 225:
                self.selected = i
                return True
        return False

    def motion(self, area, event):
        if self.selected is None:
            return False
        t = round(20+(event.x-50)/max(1, self.get_allocated_width()-75)*40)
        duty = round(100-(event.y-15)/max(1, self.get_allocated_height()-48)*100)
        self.set_point(self.selected, max(20, min(59, t)), max(0, min(100, duty)))
        self.queue_draw()
        return True

    def release(self, *_):
        self.selected = None
        return True
