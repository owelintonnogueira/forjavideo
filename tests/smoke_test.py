"""Teste offline: voz silenciosa, imagens locais. Roda: python tests/smoke_test.py"""
import sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from forja import config, pipeline

tmp = Path(tempfile.mkdtemp(prefix="forja_test_"))
imgs = tmp / "imgs"; imgs.mkdir()
import random
for i in range(3):
    im = Image.new("RGB", (2400, 1500))
    d = ImageDraw.Draw(im)
    for y in range(1500):
        d.line([(0, y), (2400, y)], fill=(40 + i * 60, 80 + y // 20, 160 - y // 15))
    for _ in range(25):
        x, y = random.randint(0, 2300), random.randint(0, 1400)
        d.ellipse([x, y, x + 150, y + 150], fill=(255, 150 + i * 20, 30))
    im.save(imgs / f"t{i}.jpg")

cfg = config.load()
cfg.update(output_dir=str(tmp / "out"), tts_engine="none", image_source="folder", image_folder=str(imgs),
           resolution=sys.argv[1] if len(sys.argv) > 1 else "720p", format=sys.argv[2] if len(sys.argv) > 2 else "horizontal",
           thumb_text="")
script = """#titulo: Como o Japão se reergueu
#thumb: JAPÃO RENASCEU

O Japão saiu da Segunda Guerra Mundial com cidades destruídas, indústria em ruínas e milhões de pessoas sem casa.

@ tokyo reconstruction
Mesmo assim, em poucas décadas, o país se tornou a segunda maior economia do planeta.

! De ruínas a potência mundial

O segredo não foi um milagre, e sim uma combinação de educação, disciplina e investimento em tecnologia.
"""
t = time.time()
logs = []
res = pipeline.produce("Como o Japão se reergueu", script, cfg, log=logs.append,
                       progress=lambda f, m: print(f"{f*100:5.1f}% {m}"))
print("tempo:", round(time.time() - t, 1), "s")
print("video:", res.video, res.video.stat().st_size // 1024, "KB")
print("thumbs:", [p.name for p in res.thumbnails])
print("logs:", logs)
print("FOLDER", res.folder)
