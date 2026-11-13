"""Alinhamento de palavras: áudio sintético com tempos conhecidos + conversão de marcas do Edge/ElevenLabs."""
import math, struct, sys, tempfile, wave, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from forja import align

RATE = 16000
text = "Em 1923, Hitler organizou um golpe de Estado em Munique para tentar tomar o poder. O golpe fracassou."
words = text.split()
rnd = random.Random(3)

# monta o áudio: fala (burst com envelope) por palavra, pausas curtas entre palavras, longas após vírgula/ponto
samples, t, truth = [], 0.0, []
def silence(sec):
    global t
    samples.extend([0] * int(RATE * sec)); t += sec
silence(0.45)
for w in words:
    d = 0.06 * len(align.letters(w)) + 0.10
    n = int(RATE * d)
    f = rnd.choice([180, 220, 260])
    truth.append((w, t, t + d))
    for i in range(n):
        env = min(1, i / 400, (n - i) / 400)
        samples.append(int(9000 * env * (math.sin(2 * math.pi * f * i / RATE) + 0.4 * math.sin(2 * math.pi * 3 * f * i / RATE))))
    t += d
    silence(0.35 if w[-1] in ",." else 0.04)
silence(0.5)
tmp = Path(tempfile.mkdtemp())
wav = tmp / "fala.wav"
with wave.open(str(wav), "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(RATE)
    wf.writeframes(struct.pack("<%dh" % len(samples), *samples))

def err(tm):
    e = [abs(a[1] - b[1]) for a, b in zip(tm.words, truth)]
    return sum(e) / len(e), max(e)

tm = align.analyze(wav, text)
mean, mx = err(tm)
print(f"energia: fonte={tm.source} | erro médio início={mean*1000:.0f} ms, máx={mx*1000:.0f} ms | corte útil {tm.start:.2f}–{tm.end:.2f}s (real {truth[0][1]:.2f}–{truth[-1][2]:.2f})")
assert tm.source == "energia" and mean < 0.22 and tm.start <= truth[0][1] and tm.end >= truth[-1][2]

# marcas por palavra (Edge WordBoundary): palavras partidas diferente do texto (pontuação separada)
entries = []
for w, a, b in truth:
    core = w.rstrip(",.")
    entries.append((core, a, b - a))
    if core != w:
        entries.append((w[-1], b, 0.01))      # pontuação como entrada própria
tv = align.analyze(wav, text, entries)
mean, mx = err(tv)
print(f"voz (palavras): fonte={tv.source} | erro médio={mean*1000:.0f} ms, máx={mx*1000:.0f} ms")
assert tv.source == "voz" and mean < 0.02

# marcas por FRASE (SentenceBoundary): interpola letra a letra
sents = [("Em 1923, Hitler organizou um golpe de Estado em Munique para tentar tomar o poder.", truth[0][1], truth[14][2] - truth[0][1]),
         ("O golpe fracassou.", truth[15][1], truth[-1][2] - truth[15][1])]
ts = align.analyze(wav, text, sents)
mean, mx = err(ts)
print(f"voz (frases): fonte={ts.source} | erro médio={mean*1000:.0f} ms, máx={mx*1000:.0f} ms")
assert ts.source == "voz" and mean < 0.30

# marcas incompatíveis com o texto -> cai para energia
bad = align.analyze(wav, text, [("outra coisa totalmente diferente", 0.0, 2.0)])
print("incompatível ->", bad.source); assert bad.source == "energia"

# ElevenLabs por caractere
chars = list(text); st, en, tt = [], [], 0.0
for ch in chars:
    st.append(tt); tt += 0.05; en.append(tt)
ent = align.entries_from_chars(text, chars, st, en)
assert len(ent) == len(words), (len(ent), len(words))
te = align.from_boundaries(words, ent)
print("eleven por caractere ->", te.source, f"{te.words[0]} ... {te.words[-1]}")

# silêncio digital -> proporcional
sil = tmp / "sil.wav"
with wave.open(str(sil), "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(RATE); wf.writeframes(b"\x00\x00" * RATE * 4)
tp = align.analyze(sil, text)
print("silêncio ->", tp.source, round(tp.end, 2)); assert tp.source == "proporcional"
print("OK")
