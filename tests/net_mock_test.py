"""Testa Wikipédia/Commons/Ollama com respostas simuladas (formato real das APIs)."""
import io, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from PIL import Image
from forja import scriptgen, media

class R:
    def __init__(self, js=None, content=b"", ok=True, status=200):
        self._js, self.content, self.ok, self.status_code = js, content, ok, status
        self.headers = {}
    def json(self): return self._js
    def raise_for_status(self): pass

buf = io.BytesIO(); Image.new("RGB", (2000, 1200), (200, 100, 50)).save(buf, "JPEG"); JPG = buf.getvalue()
EXTRACT = ("O Japão é um país insular da Ásia Oriental.\n\nHistória\n\n"
  "Após a Segunda Guerra Mundial, o Japão ficou devastado, com cidades destruídas e a economia em colapso. "
  "A ocupação aliada, liderada pelos Estados Unidos, promoveu reformas políticas e econômicas profundas (1945–1952). "
  "O país investiu pesadamente em educação e em indústria, e a economia cresceu a taxas muito altas durante os anos 1960. "
  "Empresas como a Toyota e a Sony se tornaram conhecidas no mundo inteiro por sua qualidade e inovação. "
  "Na década de 1980, o Japão já era a segunda maior economia do planeta, atrás apenas dos Estados Unidos.[3]\n")

def fake_get(url, params=None, **kw):
    if "wikipedia.org" in url:
        if params.get("list") == "search":
            return R({"query": {"search": [{"title": "Milagre econômico japonês"}, {"title": "Japão"}]}})
        return R({"query": {"pages": {"1": {"title": params["titles"], "extract": EXTRACT}}}})
    if "commons.wikimedia.org" in url:
        return R({"query": {"pages": {
          "9": {"title": "File:Tokyo.jpg", "index": 1, "imageinfo": [{"mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "https://upload.x/t.jpg", "descriptionurl": "https://commons/File:Tokyo.jpg", "extmetadata": {"Artist": {"value": "<a href='#'>Fulano</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]},
          "8": {"title": "File:Vertical.jpg", "index": 2, "imageinfo": [{"mime": "image/jpeg", "width": 900, "height": 1600, "thumburl": "https://upload.x/v.jpg"}]},
        }}})
    if url.startswith("https://upload.x"):
        return R(content=JPG)
    if "/api/tags" in url:
        return R({"models": [{"name": "llama3.1:latest"}]})
    raise requests.exceptions.ConnectionError("offline")

def fake_post(url, json=None, **kw):
    if "/api/generate" in url:
        if json.get("format") == "json":
            return R({"response": '{"titulo":"Como o Japão Renasceu","thumb":"JAPÃO RENASCEU","secoes":[{"titulo":"Ruínas","busca":"hiroshima ruins"},{"titulo":"Milagre","busca":"tokyo 1964"},{"titulo":"Hoje","busca":"tokyo skyline"}]}'})
        return R({"response": "O Japão estava em ruínas. As cidades precisavam ser reconstruídas. Milhões de pessoas não tinham casa. A fome era um risco real. Mesmo assim, o povo se uniu. A reconstrução começou pelas fábricas. Era preciso reerguer a economia."})
    raise requests.exceptions.ConnectionError("offline")

requests.get, requests.post = fake_get, fake_post
scriptgen.requests.get, scriptgen.requests.post = fake_get, fake_post
media.requests.get = fake_get

# Wikipédia
s = scriptgen.wikipedia_script("Como o Japão se reergueu", 1, log=lambda m: None)
print("wiki:", len(s.scenes), "cenas |", s.thumb_text, "|", s.scenes[0].query, "|", s.scenes[0].text[:70])
assert "[3]" not in "".join(sc.text for sc in s.scenes) and "(1945" not in "".join(sc.text for sc in s.scenes)
# round-trip do texto
t = scriptgen.script_to_text(s); s2 = scriptgen.parse_script(t)
assert len(s2.scenes) == len(s.scenes) and s2.thumb_text == s.thumb_text
# Ollama
cfg = {"script_source": "auto", "ollama_url": "http://localhost:11434", "ollama_model": "llama3.1"}
o = scriptgen.generate_script("Japão", 2, cfg, log=lambda m: None)
print("ollama:", o.title, "|", len(o.scenes), "cenas |", o.scenes[0].query, "| modelo ajustado")
# Commons
tmp = Path(tempfile.mkdtemp())
for vertical in (False, True):
    p = media.ImageProvider({"image_source": "commons"}, tmp / ("v" if vertical else "h"), vertical=vertical, log=print)
    img = p.get("tokyo skyline")
    print("commons", "vertical" if vertical else "horizontal", "->", img.name, "|", p.credits[:1])
# offline cai para fundo gerado
media.requests.get = lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("x"))
p = media.ImageProvider({"image_source": "commons"}, tmp / "off", vertical=False, log=print)
print("offline ->", p.get("x").name)
print("OK")
