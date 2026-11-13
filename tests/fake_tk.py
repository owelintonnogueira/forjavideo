"""Simulador mínimo do tkinter: valida opções/métodos usados pela interface (sem abrir janela)."""
import sys, types

COMMON = {"bg","background","bd","borderwidth","highlightbackground","highlightcolor","highlightthickness","relief","cursor","width","height","padx","pady","takefocus"}
OPTS = {
 "Tk": COMMON,
 "Frame": COMMON,
 "Label": COMMON | {"text","font","fg","foreground","anchor","justify","textvariable","image","activebackground","activeforeground","wraplength"},
 "Entry": COMMON | {"textvariable","font","fg","foreground","show","insertbackground","selectbackground","selectforeground","disabledbackground","disabledforeground","state"},
 "Button": COMMON | {"text","command","font","fg","foreground","anchor","activebackground","activeforeground","state","disabledforeground"},
 "Checkbutton": COMMON | {"text","variable","font","fg","foreground","anchor","activebackground","activeforeground","selectcolor","command","state","justify"},
 "Radiobutton": COMMON | {"text","variable","value","font","fg","foreground","anchor","activebackground","activeforeground","selectcolor","command","state"},
 "Canvas": COMMON | {"yscrollcommand","scrollregion"},
 "Text": COMMON | {"wrap","font","fg","foreground","insertbackground","selectbackground","selectforeground","undo","state","padx","pady"},
 "Combobox": {"textvariable","values","width","state","style","font"},
 "Progressbar": {"variable","maximum","style","orient","length","mode"},
 "Scrollbar": {"orient","command","style"},
}
METHODS = {"configure","config","cget","grid","pack","place","grid_propagate","pack_propagate","columnconfigure","rowconfigure","bind","bind_all","unbind_all","after","winfo_children","winfo_exists","destroy","tkraise","insert","delete","get","see","create_window","itemconfigure","bbox","yview","yview_scroll","set","title","geometry","minsize","protocol","mainloop","grid_remove","focus_set","update_idletasks","update","winfo_screenwidth","winfo_screenheight"}

class TclError(Exception): pass

class _TkCall:
    def call(self, *a): return ""
    def eval(self, *a): return ""

class Widget:
    def __init__(self, parent=None, **kw):
        self._o = {"state": "normal"}
        self._children = []
        self._text = ""
        self.tk = _TkCall()
        self._check(kw)
        self._o.update(kw)
        if parent is not None and hasattr(parent, "_children"):
            parent._children.append(self)
    def _check(self, kw):
        allowed = next(OPTS[c.__name__] for c in type(self).__mro__ if c.__name__ in OPTS)
        for k in kw:
            if k not in allowed:
                raise TclError(f'unknown option "-{k}" for {type(self).__mro__[0].__name__}')
    def configure(self, **kw):
        self._check(kw); self._o.update(kw)
    config = configure
    def cget(self, k): return self._o.get(k, "")
    def __getitem__(self, k): return self.cget(k)
    def __getattr__(self, n):
        if n.startswith("_"): raise AttributeError(n)
        if n in METHODS: return lambda *a, **k: None
        raise AttributeError(f"{type(self).__name__} has no method {n}")
    def winfo_children(self): return list(self._children)
    def winfo_exists(self): return 1
    def destroy(self):
        self._o["_dead"] = True
    def insert(self, idx, txt): self._text += txt
    def delete(self, a, b=None): self._text = ""
    def get(self, a=None, b=None): return self._text + "\n"
    def after(self, ms, fn=None, *a): return "after#1"
    def __str__(self): return f".{type(self).__name__.lower()}{id(self)%9999}"

def _mk(name):
    return type(name, (Widget,), {})
Tk = _mk("Tk"); Frame=_mk("Frame"); Label=_mk("Label"); Entry=_mk("Entry"); Button=_mk("Button")
Checkbutton=_mk("Checkbutton"); Radiobutton=_mk("Radiobutton"); Canvas=_mk("Canvas"); Text=_mk("Text")
Combobox=_mk("Combobox"); Progressbar=_mk("Progressbar"); Scrollbar=_mk("Scrollbar")

class Var:
    def __init__(self, value=None): self._v = value if value is not None else ("" if type(self) is StringVar else 0)
    def get(self): return self._v
    def set(self, v): self._v = v
class StringVar(Var): pass
class BooleanVar(Var): pass
class DoubleVar(Var): pass

class Style:
    def __init__(self, *a): self.log = []
    def theme_use(self, n): pass
    def configure(self, name, **kw): self.log.append(name)
    def map(self, name, **kw): pass

class Misc: pass

def install():
    tk = types.ModuleType("tkinter")
    for n in ("Tk","Frame","Label","Entry","Button","Checkbutton","Radiobutton","Canvas","Text","StringVar","BooleanVar","DoubleVar","TclError","Misc"):
        setattr(tk, n, globals()[n])
    ttk = types.ModuleType("tkinter.ttk")
    for n in ("Combobox","Progressbar","Scrollbar","Style"):
        setattr(ttk, n, globals()[n])
    fd = types.ModuleType("tkinter.filedialog")
    for n in ("askopenfilename","askdirectory"): setattr(fd, n, lambda **k: "")
    mb = types.ModuleType("tkinter.messagebox")
    mb.calls = []
    for n in ("showinfo","showerror"): setattr(mb, n, lambda t, m, _n=n: mb.calls.append((_n, t, m)))
    tk.ttk, tk.filedialog, tk.messagebox = ttk, fd, mb
    sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": fd, "tkinter.messagebox": mb})
    imtk = types.ModuleType("PIL.ImageTk")
    imtk.PhotoImage = lambda im=None, **k: object()
    sys.modules["PIL.ImageTk"] = imtk
    import PIL; PIL.ImageTk = imtk
    return mb
