# ForjaVideo

Programa de desktop (Windows) que transforma um **tema** em um **vídeo pronto** — roteiro, narração, imagens, legendas,
música — e já gera **3 thumbnails** em laranja e preto. Interface com tema **escuro** (laranja + preto) e **claro** (laranja + branco).

## Baixar (Windows)

Vá em **[Releases](../../releases/latest)** e baixe `ForjaVideo.exe` (ou `ForjaVideo-pasta.zip`, se o `.exe` não abrir).
Detalhes sobre o aviso do SmartScreen estão na própria página da release. Se algo falhar, o programa mostra o erro
e salva os detalhes em `C:\Users\SEU_USUARIO\.forjavideo\erro.log`.

## Começar pelo código (sem gastar nada)

1. Instale o Python 3.10+ (python.org, marque *Add to PATH*).
2. No terminal, dentro desta pasta:
   ```
   pip install -r requirements.txt
   python main.py
   ```
3. Digite o tema, clique em **Gerar roteiro**, revise o texto e clique em **PRODUZIR VÍDEO**.

Para gerar o programa você mesmo: dê duplo clique em `build_exe.bat` (gera `dist\ForjaVideo\ForjaVideo.exe`) ou rode o workflow
**Gerar ForjaVideo (Windows)** na aba *Actions* do GitHub — ele também testa o programa abrindo a janela de verdade.

## O que é grátis e o que é opcional

| Etapa | Grátis (padrão) | Opcional |
|---|---|---|
| Roteiro | **Wikipédia** (básico) · **Ollama** (IA local, melhor) · ou cole o seu | — |
| Narração | **Edge TTS** (vozes pt-BR neurais, sem chave, precisa de internet) · **Voz do Windows** (offline) · **Piper** (IA local offline) | **ElevenLabs** (chave da sua conta, em Configurações) |
| Imagens | **Wikimedia Commons** (sem chave, com licença livre) · sua pasta · fundos gerados | **Pexels** (chave grátis) |
| Vídeo | ffmpeg embutido (via imageio-ffmpeg) | — |

**Roteiro melhor:** instale o [Ollama](https://ollama.com), rode `ollama pull llama3.1` e deixe o roteiro em *Automático*.
Ou escreva/cole seu próprio roteiro na caixa — é o que dá o melhor resultado.

## Formato do roteiro

Cenas separadas por linha em branco. Cada cena vira uma imagem + legenda + trecho de narração.

```
#titulo: Como o Japão se reergueu
#thumb: JAPÃO RENASCEU

@ tokyo skyline night
O Japão saiu da guerra com as cidades destruídas...

! De ruínas a potência mundial
```

* `@ termo` (1ª linha da cena): o que buscar de imagem (em inglês costuma achar mais).
* `!` no começo: cartão de impacto (texto grande em laranja, também narrado).

## O que sai na pasta do projeto

`<titulo>.mp4` · `thumbnail_1_impacto.jpg`, `thumbnail_2_centro.jpg`, `thumbnail_3_dividido.jpg` (1280×720) ·
`roteiro.txt` · `imagens/` · `creditos.txt` (**cole na descrição**: autores e licenças das imagens/textos usados).

## Cuidados

* **Direitos:** imagens do Commons são livres, mas muitas exigem crédito (CC BY / CC BY-SA) — use o `creditos.txt`.
  O texto da Wikipédia é CC BY-SA 4.0.
* **YouTube:** conteúdo produzido em massa, sem revisão e sem valor próprio pode ser desmonetizado
  (“conteúdo inautêntico/repetitivo”). Revise o roteiro e confira fatos, números e datas antes de publicar.
* **Edge TTS** usa o serviço de voz do Microsoft Edge de forma não oficial; pode mudar ou parar de funcionar.
  Se isso acontecer, use Piper, Voz do Windows ou ElevenLabs.

## Estrutura

```
main.py                 ponto de entrada
forja/gui.py            interface (tkinter) e temas
forja/pipeline.py       roteiro → voz → imagens → cenas → vídeo + thumbs
forja/scriptgen.py      roteiro (Wikipédia, Ollama, manual)
forja/tts.py            narração (Edge, Windows, Piper, ElevenLabs)
forja/media.py          imagens (Commons, Pexels, pasta, fundos gerados)
forja/render.py         ffmpeg: zoom, legendas, cartões, música
forja/thumbs.py         thumbnails
tests/                  testes (smoke_test.py roda offline)
```

Fonte Poppins: SIL Open Font License 1.1.
