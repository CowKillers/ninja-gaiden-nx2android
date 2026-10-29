# Ninja Gaiden Sigma no nx2android — diagnóstico de tela preta

Repositório **privado** de diagnóstico do port de Ninja Gaiden Sigma
(title `0100E2F014F46000`, versão 1.0.4) para Android via nx2android,
testado num Galaxy S23 (Snapdragon 8 Gen 2, Adreno 740, Android 16).

Contém **somente** documentação de investigação, instrumentação de
diagnóstico, arquivos `env.txt` prontos e ferramentas. **Não contém**
o jogo, o dump, as chaves do console, a chave de assinatura do porter,
o APK, o data pack, os shaders do jogo (`shaders.dmsv`,
`captured_shaders/`), logs com conteúdo do jogo, capturas de tela do
jogo nem frames de vídeo. Quem for reproduzir precisa do seu próprio
dump, das suas próprias chaves e do seu próprio port feito pelo porter
do nx2android. O código do host do nx2android em si **não** está aqui;
este repositório é só a camada de diagnóstico por cima dele.

## O que não funciona (resumo, provado até 29/10/2026)

- **Tela preta permanente.** A textura da janela já nasce preta desde o
  primeiro present; só o overlay de toque aparece. O frame do vídeo de
  abertura existe dentro do pipeline (passes 2–4 do pass dump), mas
  nunca chega à janela — o pass final (5) sai preto. Ainda não se sabe
  se é clear sem desenho, quad amostrando a textura errada, draws
  ineficazes ou a janela nunca escrita. Ver
  `docs/WINDOW_PASS_ANALYSIS.md`.
- **Imagem que aparece e some (intermitente).** Sem diagnóstico e sem
  log próprio até agora. Hipóteses: timeout silencioso do present,
  uso de textura liberada, LRZ do Adreno. Ver
  `docs/BLACK_SCREEN_ROOT_CAUSE.md` (caso B).
- **Loading lento.** Frame mediano de 50–73 ms com GPU em ~0,7 ms: o
  tempo vai para espera em submissão, apresentação e pacing.
- **RenderDoc no APK atual: impossível.** O APK é release e não
  debuggable, sem root no aparelho. Precisa de uma build só com
  `debuggable=true`, sem mudança de código.
- **Trace mirando um frame do filme: impossível a partir do
  lançamento.** O trace só pega o primeiro pass 5 da corrida; não há
  controle remoto nesta build release.
- **Turnip:** o host ignora seleção de driver e só abre o Vulkan do
  sistema.
- **Shader em runtime:** não existe no nx2android. Shader novo só
  entra com re-port no PC (ver `tools/shader_loop.py`).
- **Launcher próprio:** não existe ainda; o APK atual é só a activity
  nativa, sem importação de data pack nem opções de modo/resolução/
  driver.

O que **já funciona** e não entra na lista: bundle de shaders 114/114,
zero draws pulados, áudio, decodificação de vídeo e a apresentação em
si (o overlay aparece).

## Como usar os arquivos `env.txt` (o ritual)

O `env.txt` mora na pasta `files` do app e é lido a cada lançamento.
**Reinstalar o data pack sobrescreve o `env.txt`** (só o
`settings.txt` é preservado). Por isso, em todos os passos abaixo:
troque o `env.txt` na pasta, **só relance o jogo, não reinstale**.

1. **Frame shot** — `env/env-shots.txt` (`DM_VK_SHOTS=5`): grava
   `frame_*.ppm` da textura da janela nos 5 primeiros presents.
   PPM preto = o RGB da textura já é preto (problema na renderização
   para a janela, não no blit nem na apresentação).
2. **Pass dump** — `env/env-passdump.txt` (`DM_VK_PASSDUMP=1`,
   `DM_VK_PASSDUMP_SIZE=1280x720`, `DM_VK_PASSDUMP_FRAMES=5`): despeja
   `pass_*.ppm`, o primeiro alvo de cor de cada pass. Funciona no APK
   atual, só com `env.txt`.
3. **Pass dump no título/filme** — `env/env-passdump-title.txt`
   (`DM_VK_PASSDUMP=1000`, ...): o `=N` espera N−1 presents antes de
   despejar. Ajuste N pelo log se os dumps caírem antes da cena alvo
   (o título chega por volta de 51–54 s, ~19 presents/s).
4. **Trace do pass 5** — `env/env-trace-pass5.txt`
   (`DM_VK_TRACE_PASS=5` + pass dump, **sem** `SIZE` para pegar o
   pass 1 também): loga por draw shaders, alvos, view, scissor,
   viewport e texturas amostradas do pass 5. Leitura: zero draws =
   clear sem desenho; viewport/scissor zerados = draws ineficazes;
   textura amostrada errada = quad errado; draws normais com pass 5
   preto = problema de identidade (passa para o RenderDoc).

Depois de cada corrida, **copie o `log.txt` e os `*.ppm` antes de
abrir o jogo de novo**: a cada lançamento, o log anterior é renomeado
para `log.prev.txt`, e dois lançamentos perdem o log.

## Documentos

- `docs/BLACK_SCREEN_ROOT_CAUSE.md` — auditoria completa: mapa do
  pipeline (NVN → replay → passes → janela → present), achados,
  hipóteses ranqueadas para a tela preta permanente (caso A) e para a
  perda intermitente (caso B), e o que foi refutado.
- `docs/BLACK_SCREEN_DIAGNOSTICS.md` — desenho da instrumentação,
  significado de cada linha de log, capturas nos pontos A/B/C e o
  procedimento RenderDoc no aparelho (com o pré-requisito de build
  debuggable).
- `docs/WINDOW_PASS_ANALYSIS.md` — análise direcionada do pass que
  deveria escrever a janela durante o vídeo, com os mecanismos M1–M4
  e o teste exato de cada um.

## Instrumentação (patch, não aplicado por padrão)

`black-screen-diag.patch` é o diff da instrumentação temporária de
diagnóstico para o host v0.1.2: logs de criação/destruição de
swapchain, índices de imagem adquirida/apresentada, resultados de
acquire/submit/present, layouts, draws/clears/cópias por frame, hashes
RGB dos pontos A/B/C e sinais de timeout, UAF e recriação. É
**desligado por padrão** (só age com `DM_VK_DIAG=1` no `env.txt`) e
não muda renderização, sincronização, pacing, escolha de swapchain
nem o `alpha_fix`. Não foi aplicado ao host, não foi compilado e não
gerou APK: é só o diff pronto, verificado por `patch --dry-run`.

Regras que valem para qualquer mudança futura, aprendidas nesta
investigação: sem reescrever o renderizador, sem recriação contínua
de swapchain, sem forçar OPAQUE (a superfície do S23 não o oferece e
a build atual já o prefere), sem remover o `alpha_fix`, sem APK
repetido sem marco verificável, um patch único por vez com prova
antes/depois.

## Ferramentas

- `tools/shader_loop.py` — automatiza ciclos de port `--install`
  (puxa os shaders capturados do celular antes de traduzir) e para
  quando o bundle para de crescer. Não inventa shader: um shader que
  o jogo gera em runtime só entra depois de jogado e capturado.

## O que nunca deve entrar neste repositório

Dump do jogo, `prod.keys`, `title.keys`, chave de assinatura do
porter, APK, data pack, `shaders.dmsv`, `captured_shaders/`, RomFS,
saves, logs do jogo, screenshots ou frames do jogo. O `.gitignore`
bloqueia todos esses padrões; se um deles aparecer no `git status`,
não faça commit.
