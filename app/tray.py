import threading

from PIL import Image, ImageDraw
import pystray

from . import config


def _make_icon_image(size: int = 64) -> Image.Image:
    """Fallback si icon.png no existe: dibuja un placeholder."""
    img = Image.new("RGBA", (size, size), (30, 30, 30, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=(52, 152, 219, 255))
    d.polygon([(18, 18), (size // 2, size - 18), (size - 18, 18)],
              fill=(255, 255, 255, 255))
    return img


def _load_brand_icon() -> Image.Image:
    """Carga icon.png. Si falla, vuelve al placeholder."""
    try:
        return Image.open(config.ICON_PATH).convert("RGBA")
    except Exception:
        return _make_icon_image()


class TrayIcon:
    """Icono en bandeja con menú Mostrar / Ocultar / Salir.
    Corre pystray en su propio hilo. Las acciones llaman a los callbacks
    proporcionados (que internamente deben usar el hilo de Tk con `after`)."""

    def __init__(self, on_show, on_hide, on_quit, on_log=None):
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_quit = on_quit
        self.on_log = on_log or (lambda m: None)
        self._icon = None
        self._thread = None

    def _build(self):
        image = _load_brand_icon()
        # `default=True` en la primera entrada hace que el doble-click sobre
        # el ícono del tray dispare esa acción (restaurar la ventana).
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar Wisip", self._handle_show, default=True),
            pystray.MenuItem("Ocultar ventana", self._handle_hide),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar Wisip", self._handle_quit),
        )
        return pystray.Icon(
            "wisip",
            icon=image,
            title="Wisip",
            menu=menu,
        )

    def _handle_show(self, icon, item):
        try:
            self.on_show()
        except Exception as e:
            self.on_log(f"[tray] error en 'mostrar': {e}")

    def _handle_hide(self, icon, item):
        try:
            self.on_hide()
        except Exception as e:
            self.on_log(f"[tray] error en 'ocultar': {e}")

    def _handle_quit(self, icon, item):
        try:
            self.on_quit()
        finally:
            try:
                icon.stop()
            except Exception:
                pass

    def start(self):
        if self._icon is not None:
            return
        self._icon = self._build()

        def run():
            try:
                self._icon.run()
            except Exception as e:
                self.on_log(f"[tray] error en run(): {e}")

        self._thread = threading.Thread(target=run, daemon=True, name="tray")
        self._thread.start()
        self.on_log("[tray] icono activo en la bandeja")

    def notify(self, message: str, title: str = "Wisip"):
        """Globo de notificación de Windows desde el icono de la bandeja."""
        try:
            if self._icon is not None:
                self._icon.notify(message, title)
        except Exception as e:
            self.on_log(f"[tray] notify falló: {e}")

    def stop(self):
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            pass
        self._icon = None
