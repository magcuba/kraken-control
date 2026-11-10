"""Local theme gallery, element editor and circular live preview."""
import copy
import hashlib
import json
from pathlib import Path
import re

import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
from PIL import Image, ImageDraw
from theme_renderer import THEMES, SOURCES, PERCENT, validate_theme, render

LIBRARY=Path.home()/'.config/kraken-control/themes'


def save_theme(theme, directory=LIBRARY):
    theme=validate_theme(theme)
    directory.mkdir(parents=True,exist_ok=True)
    slug=re.sub(r'[^a-z0-9_-]+','-',theme['name'].lower()).strip('-') or 'tema'
    digest=hashlib.sha256(theme['name'].encode()).hexdigest()[:8]
    path=directory/(slug+'-'+digest+'.json')
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(theme,indent=2,ensure_ascii=False))
    temp.replace(path)
    return path


class ThemeEditor(Gtk.Box):
    def __init__(self, theme=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        self.theme=copy.deepcopy(theme or THEMES['Nebula'])
        self.loading=False
        self.values={}
        self.selected=0
        self.drag=None
        self.catalog={}
        self.notice=Gtk.Label(xalign=0)
        self.notice.set_line_wrap(True)
        gallery=Gtk.Box(spacing=8)
        gallery.pack_start(Gtk.Label(label='Galería de temas'),False,False,0)
        self.gallery=Gtk.ComboBoxText()
        self.gallery.set_hexpand(True)
        self.populate_gallery()
        self.gallery.set_active_id(self.theme['name'])
        gallery.pack_start(self.gallery,True,True,0)
        self.pack_start(gallery,False,False,0)
        body=Gtk.Box(spacing=18)
        self.pack_start(body,False,False,0)
        left=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        body.pack_start(left,False,False,0)
        self.preview=Gtk.Image()
        self.stage=Gtk.EventBox()
        self.stage.set_halign(Gtk.Align.CENTER)
        self.stage.set_valign(Gtk.Align.START)
        self.stage.add(self.preview)
        self.stage.set_size_request(360,360)
        self.stage.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK)
        self.stage.connect('button-press-event',self.press)
        self.stage.connect('motion-notify-event',self.motion)
        self.stage.connect('button-release-event',self.release)
        left.pack_start(self.stage,False,False,0)
        hint=Gtk.Label(label='Vista previa en vivo · LCD 320 × 320\nSelecciona un elemento y arrástralo para moverlo.')
        hint.get_style_context().add_class('sub')
        left.pack_start(hint,False,False,0)
        self.element_list=Gtk.ComboBoxText()
        self.element_list.connect('changed',self.select_element)
        left.pack_start(self.element_list,False,False,0)
        controls=Gtk.Box(spacing=5,homogeneous=True)
        for title,callback in [('＋ Texto',lambda:self.add_element('text')),('＋ Anillo',lambda:self.add_element('ring')),('Eliminar',self.delete_element)]:
            b=Gtk.Button(label=title)
            b.connect('clicked',lambda _,fn=callback:fn())
            controls.pack_start(b,True,True,0)
        left.pack_start(controls,False,False,0)
        right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        right.set_hexpand(True)
        right.get_style_context().add_class('card')
        body.pack_start(right,True,True,0)
        self.name=Gtk.Entry(max_length=60)
        self.row(right,'Nombre del tema',self.name)
        self.background=Gtk.ColorButton()
        self.row(right,'Color de fondo',self.background)
        bgrow=Gtk.Box(spacing=5)
        self.bgfile=Gtk.FileChooserButton(title='Imagen de fondo',action=Gtk.FileChooserAction.OPEN)
        filt=Gtk.FileFilter();filt.set_name('Fondos');filt.add_mime_type('image/png');filt.add_mime_type('image/jpeg');filt.add_mime_type('image/webp')
        self.bgfile.add_filter(filt)
        bgrow.pack_start(self.bgfile,True,True,0)
        clear=Gtk.Button(label='Quitar')
        clear.connect('clicked',lambda _:self.clear_background())
        bgrow.pack_start(clear,False,False,0)
        self.row(right,'Imagen de fondo',bgrow)
        self.visible=Gtk.CheckButton(label='Mostrar elemento seleccionado')
        right.pack_start(self.visible,False,False,0)
        self.source=Gtk.ComboBoxText()
        self.row(right,'Dato / contenido',self.source)
        self.title=Gtk.Entry(max_length=80)
        self.title.set_placeholder_text('Texto libre o etiqueta del dato')
        self.row(right,'Texto / etiqueta',self.title)
        self.color=Gtk.ColorButton()
        self.row(right,'Color del elemento',self.color)
        self.fontsize=self.spin(8,80)
        self.row(right,'Tamaño del texto',self.fontsize)
        positions=Gtk.Box(spacing=6)
        self.x,self.y=self.spin(0,320),self.spin(0,320)
        positions.pack_start(Gtk.Label(label='X'),False,False,0);positions.pack_start(self.x,True,True,0)
        positions.pack_start(Gtk.Label(label='Y'),False,False,0);positions.pack_start(self.y,True,True,0)
        self.row(right,'Posición',positions)
        self.radius,self.width=self.spin(10,155),self.spin(2,24)
        self.row(right,'Radio del anillo',self.radius)
        self.row(right,'Grosor del anillo',self.width)
        self.name.connect('changed',self.change_theme)
        self.background.connect('color-set',self.change_theme)
        self.bgfile.connect('file-set',self.change_theme)
        for widget,signal in [(self.visible,'toggled'),(self.source,'changed'),(self.title,'changed'),(self.color,'color-set'),
                              (self.fontsize,'value-changed'),(self.x,'value-changed'),(self.y,'value-changed'),
                              (self.radius,'value-changed'),(self.width,'value-changed')]:
            widget.connect(signal,self.change_element)
        self.gallery.connect('changed',self.load_gallery)
        buttons=Gtk.Box(spacing=7)
        for title,callback in [('Guardar tema',self.save),('Importar tema…',self.import_theme),('Exportar tema…',self.export_theme),('Exportar PNG…',self.export_png)]:
            b=Gtk.Button(label=title);b.connect('clicked',lambda _,fn=callback:fn())
            buttons.pack_start(b,True,True,0)
        self.pack_start(buttons,False,False,0)
        self.pack_start(self.notice,False,False,0)
        self.load_controls()

    def row(self,box,title,widget):
        row=Gtk.Box(spacing=8)
        label=Gtk.Label(label=title,xalign=0)
        row.pack_start(label,True,True,0)
        row.pack_start(widget,False,False,0)
        box.pack_start(row,False,False,0)

    def spin(self,low,high):
        return Gtk.SpinButton.new_with_range(low,high,1)

    def hex(self,button):
        c=button.get_rgba()
        return '#'+''.join(f'{round(v*255):02x}' for v in (c.red,c.green,c.blue))

    def set_color(self,button,color):
        c=Gdk.RGBA();c.parse(color);button.set_rgba(c)

    def populate_gallery(self):
        self.catalog=copy.deepcopy(THEMES)
        if LIBRARY.exists():
            for path in sorted(LIBRARY.glob('*.json')):
                try:
                    theme=validate_theme(json.loads(path.read_text()))
                    self.catalog[theme['name']]=theme
                except (OSError,ValueError,TypeError):
                    pass
        self.gallery.remove_all()
        for name in self.catalog:self.gallery.append(name,name)

    def load_gallery(self,*_):
        if self.loading:return
        name=self.gallery.get_active_id()
        if name in self.catalog:
            self.theme=copy.deepcopy(self.catalog[name]);self.selected=0
            self.load_controls()
            self.notice.set_text('Tema cargado para editar. Todavía no se ha aplicado al Kraken.')

    def load_controls(self):
        self.loading=True
        self.name.set_text(self.theme['name'])
        self.set_color(self.background,self.theme['background'])
        if self.theme.get('background_image'):self.bgfile.set_filename(self.theme['background_image'])
        else:self.bgfile.unselect_all()
        self.populate_elements()
        self.loading=False
        self.load_element()
        self.update_preview()

    def populate_elements(self):
        self.element_list.remove_all()
        for i,e in enumerate(self.theme['elements']):
            self.element_list.append(str(i),f"{i+1}. {'Anillo' if e['kind']=='ring' else 'Texto'} · {SOURCES[e['source']]}")
        self.selected=min(self.selected,len(self.theme['elements'])-1)
        self.element_list.set_active_id(str(self.selected))

    def select_element(self,*_):
        if self.loading:return
        value=self.element_list.get_active_id()
        if value is not None:self.selected=int(value);self.load_element();self.update_preview()

    def load_element(self):
        self.loading=True
        e=self.theme['elements'][self.selected]
        self.visible.set_active(e['visible'])
        self.source.remove_all()
        for key,name in SOURCES.items():
            if e['kind']=='text' or key in PERCENT:self.source.append(key,name)
        self.source.set_active_id(e['source'])
        self.title.set_text(e.get('title',''))
        self.set_color(self.color,e['color'])
        self.fontsize.set_value(e.get('size',24))
        self.x.set_value(e['x']);self.y.set_value(e['y'])
        self.radius.set_value(e.get('radius',140));self.width.set_value(e.get('width',10))
        self.fontsize.set_sensitive(e['kind']=='text');self.title.set_sensitive(e['kind']=='text')
        self.radius.set_sensitive(e['kind']=='ring');self.width.set_sensitive(e['kind']=='ring')
        self.loading=False

    def change_theme(self,*_):
        if self.loading:return
        self.theme.update(name=self.name.get_text(),background=self.hex(self.background),background_image=self.bgfile.get_filename() or '')
        self.update_preview()

    def change_element(self,*_):
        if self.loading:return
        e=self.theme['elements'][self.selected]
        e.update(visible=self.visible.get_active(),source=self.source.get_active_id(),x=self.x.get_value_as_int(),y=self.y.get_value_as_int(),color=self.hex(self.color))
        if e['kind']=='text':e.update(size=self.fontsize.get_value_as_int(),title=self.title.get_text())
        else:e.update(radius=self.radius.get_value_as_int(),width=self.width.get_value_as_int())
        self.update_preview()

    def clear_background(self):
        self.bgfile.unselect_all();self.theme['background_image']='';self.update_preview()

    def add_element(self,kind):
        if len(self.theme['elements'])>=16:
            self.notice.set_text('Máximo 16 elementos por tema.');return
        from theme_renderer import text,ring
        self.theme['elements'].append(text('text',160,160,24,'#ffffff','Texto') if kind=='text' else ring('cpu_load',120,'#b35cff'))
        self.selected=len(self.theme['elements'])-1
        self.loading=True;self.populate_elements();self.loading=False
        self.load_element();self.update_preview()

    def delete_element(self):
        if len(self.theme['elements'])<=1:
            self.notice.set_text('Conserva al menos un elemento.');return
        del self.theme['elements'][self.selected]
        self.loading=True;self.populate_elements();self.loading=False
        self.load_element();self.update_preview()

    def get_theme(self):
        return validate_theme(self.theme)

    def update_values(self,values):
        self.values=values
        self.update_preview()

    def update_preview(self):
        try:
            image=render(self.theme,self.values,resolution=360).convert('RGBA')
            mask=Image.new('L',(360,360),0);ImageDraw.Draw(mask).ellipse((1,1,359,359),fill=255)
            image.putalpha(mask)
            pixbuf=GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(image.tobytes()),GdkPixbuf.Colorspace.RGB,True,8,360,360,360*4)
            self.preview.set_from_pixbuf(pixbuf)
            self.preview.set_tooltip_text('Diseño en edición; el Kraken solo cambia al aplicar. Datos sin lectura se muestran como —.')
        except Exception as e:
            self.notice.set_text(str(e))

    def press(self,widget,event):
        if event.button!=1:return False
        self.drag=(event.x,event.y,self.theme['elements'][self.selected]['x'],self.theme['elements'][self.selected]['y'])
        return True

    def motion(self,widget,event):
        if not self.drag:return False
        x,y,origin_x,origin_y=self.drag
        self.x.set_value(max(0,min(320,origin_x+(event.x-x)*320/360)))
        self.y.set_value(max(0,min(320,origin_y+(event.y-y)*320/360)))
        return True

    def release(self,*_):
        self.drag=None;return True

    def save(self):
        try:
            path=save_theme(self.get_theme())
            self.loading=True;self.populate_gallery();self.gallery.set_active_id(self.theme['name']);self.loading=False
            self.notice.set_text('Tema guardado en la galería. No se ha aplicado al dispositivo.')
        except Exception as e:self.loading=False;self.notice.set_text(str(e))

    def choose(self,title,save=False,name='tema.json'):
        dialog=Gtk.FileChooserDialog(title=title,transient_for=self.get_toplevel(),action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancelar',Gtk.ResponseType.CANCEL,'Guardar' if save else 'Abrir',Gtk.ResponseType.OK)
        if save:dialog.set_current_name(name);dialog.set_do_overwrite_confirmation(True)
        result=dialog.get_filename() if dialog.run()==Gtk.ResponseType.OK else None
        dialog.destroy();return result

    def import_theme(self):
        path=self.choose('Importar tema JSON')
        if not path:return
        try:
            self.theme=validate_theme(json.loads(Path(path).read_text()));self.selected=0;self.load_controls()
            self.notice.set_text('Tema importado para editar. Guarda una copia en la galería si quieres conservarlo.')
        except Exception as e:self.notice.set_text(str(e))

    def export_theme(self):
        try:
            theme=self.get_theme()
            path=self.choose('Exportar tema JSON',True)
            if path:Path(path).write_text(json.dumps(theme,indent=2,ensure_ascii=False));self.notice.set_text('Tema exportado. Una imagen de fondo externa debe acompañar al JSON.')
        except Exception as e:self.notice.set_text(str(e))

    def export_png(self):
        try:
            theme=self.get_theme();path=self.choose('Exportar imagen para LCD',True,'kraken-tema.png')
            if path:render(theme,self.values).save(path,format='PNG');self.notice.set_text('PNG de 320 × 320 exportado.')
        except Exception as e:self.notice.set_text(str(e))
