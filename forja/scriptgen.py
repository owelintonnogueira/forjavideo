"""Geração e interpretação do roteiro.

Formato do texto do roteiro (editável na interface):

    #titulo: Como o Japão se reergueu
    #thumb: JAPÃO RENASCEU

    @ Tokyo skyline night
    O Japão saiu da Segunda Guerra com as cidades destruídas...

    ! De ruínas a potência mundial

Cenas são separadas por linha em branco.
  - "@ termo" na primeira linha da cena define a busca da imagem.
  - "!" no começo marca um cartão de impacto (texto grande, também narrado).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

import requests

from .util import USER_AGENT, CancelToken, split_sentences

WORDS_PER_MIN = 150
HEADERS = {"User-Agent": USER_AGENT}


@dataclass
class Scene:
    text: str
    query: str = ""
    kind: str = "image"  # image | impact


@dataclass
class Script:
    title: str = ""
    thumb_text: str = ""
    scenes: list[Scene] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- texto <-> Script
def script_to_text(s: Script) -> str:
    out = []
    if s.title:
        out.append(f"#titulo: {s.title}")
    if s.thumb_text:
        out.append(f"#thumb: {s.thumb_text}")
    if out:
        out.append("")
    blocks = []
    for sc in s.scenes:
        lines = []
        if sc.kind == "impact":
            lines.append("! " + sc.text)
        else:
            if sc.query:
                lines.append("@ " + sc.query)
            lines.append(sc.text)
        blocks.append("\n".join(lines))
    return "\n".join(out) + "\n\n".join(blocks) + "\n"


def parse_script(text: str, fallback_title: str = "") -> Script:
    s = Script(title=fallback_title)
    blocks = re.split(r"\n\s*\n", text.strip())
    for blk in blocks:
        lines = [ln.rstrip() for ln in blk.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        # cabeçalhos
        rest = []
        for ln in lines:
            low = ln.lower()
            if low.startswith("#titulo:") or low.startswith("#título:"):
                s.title = ln.split(":", 1)[1].strip()
            elif low.startswith("#thumb:"):
                s.thumb_text = ln.split(":", 1)[1].strip()
            else:
                rest.append(ln)
        if not rest:
            continue
        query = ""
        kind = "image"
        if rest[0].startswith("@"):
            query = rest[0][1:].strip()
            rest = rest[1:]
        body = " ".join(rest).strip()
        if body.startswith("!"):
            kind = "impact"
            body = body[1:].strip()
        if body:
            s.scenes.append(Scene(text=body, query=query, kind=kind))
    return s


# --------------------------------------------------------------------------- utilidades
def _chunk_sentences(sentences: list[str], target_words: int = 26) -> list[str]:
    scenes, cur, n = [], [], 0
    for sen in sentences:
        w = len(sen.split())
        if cur and n + w > target_words * 1.4:
            scenes.append(" ".join(cur))
            cur, n = [], 0
        cur.append(sen)
        n += w
        if n >= target_words:
            scenes.append(" ".join(cur))
            cur, n = [], 0
    if cur:
        scenes.append(" ".join(cur))
    return scenes


def default_thumb_text(topic: str) -> str:
    t = re.sub(r"\s+", " ", topic.strip().rstrip("?!.")).upper()
    words = t.split()
    if len(words) > 6:
        words = words[:6]
    return " ".join(words)


def proper_noun_runs(sentence: str) -> list[str]:
    """Nomes próprios no meio da frase (ex.: 'Segunda Guerra Mundial'), na ordem em que aparecem."""
    runs: list[str] = []
    run: list[str] = []
    for idx, tok in enumerate(sentence.split()):
        core = tok.strip(".,;:!?\"“”()")
        if idx > 0 and core[:1].isupper() and core.isalpha() and len(core) > 2 and len(run) < 3:
            run.append(core)
        else:
            if run:
                runs.append(" ".join(run))
            run = [core] if (idx > 0 and core[:1].isupper() and core.isalpha() and len(core) > 2) else []
    if run:
        runs.append(" ".join(run))
    return runs


def _query_from_sentence(sentence: str, topic: str) -> str:
    runs = proper_noun_runs(sentence)
    return runs[0] if runs else topic


def query_candidates(scene_query: str, text: str, topic: str) -> list[str]:
    """Buscas de imagem para uma cena, da mais específica para a mais geral (sem repetir)."""
    qs = [scene_query] if scene_query else []
    qs += proper_noun_runs(text)
    qs.append(topic)
    seen, out = set(), []
    for q in qs:
        k = q.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(q.strip())
    return out


# --------------------------------------------------------------------------- Wikipédia (grátis, sem chave)
def wikipedia_script(topic: str, minutes: float, log=print, cancel: CancelToken | None = None) -> Script:
    target_words = int(minutes * WORDS_PER_MIN)
    api = "https://pt.wikipedia.org/w/api.php"
    r = requests.get(
        api,
        params={"action": "query", "list": "search", "srsearch": topic, "format": "json", "srlimit": 5},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    if not hits:
        raise RuntimeError(f"A Wikipédia não achou nada sobre “{topic}”. Tente outro tema ou cole seu roteiro.")
    script = Script(title=topic, thumb_text=default_thumb_text(topic))
    words = 0
    for h in hits:
        if cancel:
            cancel.check()
        if words >= target_words:
            break
        title = h["title"]
        log(f"Lendo a Wikipédia: {title}")
        r = requests.get(
            api,
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "exsectionformat": "plain",
                "titles": title,
                "format": "json",
                "redirects": 1,
            },
            headers=HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        extract = next(iter(pages.values())).get("extract", "")
        paras = []
        for line in extract.split("\n"):
            line = re.sub(r"\[[^\]]*\]", "", line)
            for _ in range(4):  # remove (...) mesmo aninhados ou longos (pronúncia, datas, etc.)
                line = re.sub(r"\s*\([^()]*\)", "", line)
            line = re.sub(r"[()]", "", line)
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) > 60 and line[-1] in ".!?":
                paras.append(line)
        sentences = []
        for p in paras:
            sentences.extend(split_sentences(p))
        for sc_text in _chunk_sentences(sentences):
            if words >= target_words:
                break
            words += len(sc_text.split())
            script.scenes.append(Scene(text=sc_text, query=_query_from_sentence(sc_text, title)))
        script.credits.append(
            f"Texto base: Wikipédia, artigo “{title}” (https://pt.wikipedia.org/wiki/{title.replace(' ', '_')}), licença CC BY-SA 4.0."
        )
    if not script.scenes:
        raise RuntimeError("Não consegui montar um roteiro a partir da Wikipédia. Cole seu próprio roteiro.")
    return script


# --------------------------------------------------------------------------- Ollama (IA local, grátis)
def ollama_available(url: str) -> bool:
    try:
        r = requests.get(url.rstrip("/") + "/api/tags", timeout=2)
        return r.ok
    except Exception:
        return False


def ollama_models(url: str) -> list[str]:
    try:
        r = requests.get(url.rstrip("/") + "/api/tags", timeout=3)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def _ollama(url: str, model: str, prompt: str, json_mode: bool = False) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.7}}
    if json_mode:
        payload["format"] = "json"
    r = requests.post(url.rstrip("/") + "/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def ollama_script(
    topic: str, minutes: float, url: str, model: str, log=print, cancel: CancelToken | None = None
) -> Script:
    target_words = int(minutes * WORDS_PER_MIN)
    n_sections = max(3, math.ceil(minutes * 60 / 40))  # ~40 s por seção
    words_per_section = max(60, target_words // n_sections)

    log("IA local: montando a estrutura do vídeo…")
    outline_prompt = (
        "Você é roteirista de vídeos para YouTube em português do Brasil. "
        f'Tema: "{topic}". Crie a estrutura de um vídeo de {minutes:g} minutos com {n_sections} seções. '
        "Responda SOMENTE com JSON válido neste formato: "
        '{"titulo": "título chamativo", "thumb": "texto curtíssimo para thumbnail (até 4 palavras, MAIÚSCULAS)", '
        '"secoes": [{"titulo": "nome da seção", "busca": "termo de busca de imagem em inglês, 2-3 palavras"}]}'
    )
    raw = _ollama(url, model, outline_prompt, json_mode=True)
    try:
        outline = json.loads(raw)
        secoes = outline["secoes"]
    except Exception:
        raise RuntimeError("O modelo local não devolveu uma estrutura válida. Tente outro modelo ou a opção Wikipédia.")
    script = Script(title=outline.get("titulo") or topic, thumb_text=(outline.get("thumb") or default_thumb_text(topic)))
    for i, sec in enumerate(secoes, 1):
        if cancel:
            cancel.check()
        log(f"IA local: escrevendo seção {i}/{len(secoes)}…")
        prompt = (
            "Escreva a narração falada de uma seção de vídeo de YouTube em português do Brasil, tom envolvente e claro. "
            f'Tema geral: "{topic}". Seção {i} de {len(secoes)}: "{sec.get("titulo", "")}". '
            f"Use cerca de {words_per_section} palavras, frases curtas, sem listas, sem emojis, sem títulos, "
            "sem indicações de cena. Não invente números ou datas que você não tenha certeza. "
            "Responda apenas com o texto da narração."
        )
        text = _ollama(url, model, prompt)
        text = re.sub(r"[*_#>`]+", "", text)
        sentences = split_sentences(text)
        busca = sec.get("busca") or topic
        for sc_text in _chunk_sentences(sentences):
            script.scenes.append(Scene(text=sc_text, query=busca))
    if not script.scenes:
        raise RuntimeError("O modelo local não escreveu nada. Verifique se o Ollama está rodando.")
    return script


# --------------------------------------------------------------------------- orquestração
def generate_script(topic: str, minutes: float, cfg: dict, log=print, cancel: CancelToken | None = None) -> Script:
    src = cfg.get("script_source", "auto")
    url, model = cfg.get("ollama_url", ""), cfg.get("ollama_model", "")
    if src == "ollama" or (src == "auto" and ollama_available(url) and ollama_models(url)):
        models = ollama_models(url)
        if models and model not in models:
            model = models[0]
            log(f"Modelo configurado não encontrado, usando {model}.")
        return ollama_script(topic, minutes, url, model, log, cancel)
    if src in ("auto", "wikipedia"):
        if src == "auto":
            log("Ollama não encontrado; usando a Wikipédia como base do roteiro.")
        return wikipedia_script(topic, minutes, log, cancel)
    raise RuntimeError("Modo manual: escreva ou cole o roteiro na caixa de texto.")
