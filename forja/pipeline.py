"""Orquestra: roteiro → narração → imagens → cenas → vídeo final + thumbnails."""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import align, render, scriptgen, thumbs, tts
from .media import ImageProvider
from .scriptgen import Script
from .util import CancelToken, slugify


@dataclass
class Result:
    folder: Path
    video: Path | None = None
    thumbnails: list[Path] = field(default_factory=list)
    script: Script | None = None
    backgrounds: list[Path] = field(default_factory=list)


def _noop(*a, **k):
    pass


def _pct(rate: str) -> int:
    try:
        return int(str(rate).replace("%", "").replace("+", "").strip() or 0)
    except ValueError:
        return 0


def _combine_rate(user_rate: str, pace_rate: str) -> str:
    return f"{_pct(user_rate) + _pct(pace_rate):+d}%"


def new_project_folder(cfg: dict, topic: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M")
    folder = Path(cfg["output_dir"]) / f"{slugify(topic)}_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def produce(
    topic: str,
    script_text: str,
    cfg: dict,
    log=print,
    progress=_noop,
    cancel: CancelToken | None = None,
) -> Result:
    """Produz o vídeo completo. 'script_text' vazio = gerar o roteiro automaticamente."""
    cancel = cancel or CancelToken()
    minutes = float(cfg.get("minutes", 3))

    # 1) roteiro --------------------------------------------------------------
    progress(0.01, "Preparando roteiro…")
    if script_text.strip():
        script = scriptgen.parse_script(script_text, fallback_title=topic)
    else:
        script = scriptgen.generate_script(topic, minutes, cfg, log, cancel)
    if not script.scenes:
        raise RuntimeError("O roteiro está vazio. Escreva pelo menos um parágrafo.")
    cancel.check()
    folder = new_project_folder(cfg, script.title or topic)
    (folder / "roteiro.txt").write_text(scriptgen.script_to_text(script), encoding="utf-8")
    result = Result(folder=folder, script=script)

    # 2) cenas -----------------------------------------------------------------
    w, h = render.canvas_size(cfg.get("format", "horizontal"), cfg.get("resolution", "720p"))
    work = folder / "temp"
    work.mkdir(exist_ok=True)
    assets = folder / "imagens"
    provider = ImageProvider(cfg, assets, vertical=(h > w), log=log, cancel=cancel)
    shade = work / "shade.png"
    render.make_shade(w, h, shade)

    pace = cfg.get("pace", "dynamic")
    if pace not in render.PACES:
        pace = "dynamic"
    if cfg.get("tts_engine", "edge") == "edge":  # o ritmo também ajusta a velocidade da voz
        cfg = dict(cfg)
        cfg["edge_rate"] = _combine_rate(cfg.get("edge_rate", "+0%"), render.PACES[pace]["rate"])

    n = len(script.scenes)
    scene_files: list[Path] = []
    total_dur = 0.0
    for i, sc in enumerate(script.scenes):
        cancel.check()
        base = 0.04 + 0.86 * i / n
        span = 0.86 / n
        progress(base, f"Cena {i + 1}/{n}: narração…")
        audio, entries = tts.synthesize_timed(sc.text, work / f"voz_{i:03d}", cfg)
        timing = align.analyze(audio, sc.text, entries)
        plan = render.plan_scene(sc.kind, timing, pace)

        images: list[Path] = []
        if sc.kind != "impact":
            progress(base + span * 0.3, f"Cena {i + 1}/{n}: imagens…")
            queries = scriptgen.query_candidates(sc.query, sc.text, script.title or topic)
            images = provider.get_many(queries, plan.shots, seed=i + 1)
            for img in images:
                if not img.name.startswith("bg_") and img not in result.backgrounds:
                    result.backgrounds.append(img)

        progress(base + span * 0.5, f"Cena {i + 1}/{n}: montando…")
        out = work / f"cena_{i:03d}.mp4"
        total_dur += render.render_scene(
            i, sc.text, sc.kind, plan, images, audio, timing, work, w, h, shade, out, pace, cancel
        )
        scene_files.append(out)

    # 3) vídeo final --------------------------------------------------------------
    progress(0.91, "Juntando as cenas…")
    joined = work / "juntado.mp4"
    render.concat_scenes(scene_files, joined, cancel)
    final = folder / f"{slugify(script.title or topic)}.mp4"
    music = cfg.get("music_file", "")
    if music and Path(music).exists():
        progress(0.94, "Misturando a música de fundo…")
        render.add_music(joined, Path(music), float(cfg.get("music_volume", 0.12)), final, cancel)
    else:
        render.finalize_without_music(joined, final, cancel)
    result.video = final

    # 4) thumbnails ---------------------------------------------------------------
    if cfg.get("make_thumbs", True):
        progress(0.97, "Criando thumbnails…")
        text = (cfg.get("thumb_text") or script.thumb_text or scriptgen.default_thumb_text(script.title or topic)).strip()
        result.thumbnails = thumbs.make_thumbnails(
            text, result.backgrounds, folder, vertical=(cfg.get("format") == "vertical")
        )

    # 5) créditos -----------------------------------------------------------------
    credits = list(dict.fromkeys(script.credits + provider.credits))
    if credits:
        (folder / "creditos.txt").write_text(
            "Créditos (cole na descrição do vídeo):\n\n" + "\n".join(credits) + "\n", encoding="utf-8"
        )
    shutil.rmtree(work, ignore_errors=True)
    progress(1.0, f"Pronto! Duração: {int(total_dur // 60)}min{int(total_dur % 60):02d}s")
    return result


def thumbnails_only(
    text: str, backgrounds: list[Path], out_dir: Path, styles: list[str] | None = None, vertical: bool = False
) -> list[Path]:
    return thumbs.make_thumbnails(text, backgrounds, Path(out_dir), styles, vertical=vertical)
