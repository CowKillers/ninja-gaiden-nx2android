# Qual pass deveria escrever a janela — e por que ela sai preta

**Jogo:** Ninja Gaiden Sigma (`0100E2F014F46000`), host real dela **v0.1.2** (não o clone).
**Base de código:** `nx2android/nxnative/dm/` dentro do `nx2android.zip`. Caminhos abaixo são relativos a ela.
**Dados:** pass dumps dos presents 1000–1004 durante o filme `ninja_vi`
(`workspace/nx2a-black-screen/pass-dump-title/`, log junto), frame shots do ponto A
(pretos puros, `workspace/nx2a-black-screen/frame-shots/`).
**Uso:** pessoal, sem distribuição. Nada aqui abre `keys/`, RomFS ou dumps do jogo.
**Regras mantidas:** sem APK, sem re-port, sem alterar o host. Este documento é análise;
o único teste proposto na seção 7 usa chaves de `env.txt` já existentes no APK atual.

## 0. O que já está provado, e o que este documento acrescenta

Provado antes (não reaberto aqui):

- O frame do vídeo **existe** dentro do pipeline: passes 2, 3 e 4 dos presents
  1002–1004 contêm o frame completo do `ninja_vi` (mar tempestuoso com chuva,
  conferido visualmente em `pass_07_preview.png`), byte-idênticos entre si dentro
  de cada present e avançando levemente entre presents.
- A textura da janela (ponto A, frame shot) é **preto puro** — 0 de 921.600 pixels
  diferentes de zero nos 5 PPMs.
- Logo, **A1 (texturas pretas) e A2 (draws ineficazes) estão refutados para este
  conteúdo**: draws executam e produzem imagem. Resta a família **A3**: o conteúdo
  não chega à textura da janela.
- O preto é **permanente em todo conteúdo** (título, filme, jogo), não específico
  do vídeo. O filme é só o caso em que dá para *ver* o conteúdo intermediário.
  Consequência: o defeito está no passo final (último pass e/ou seleção do que é
  apresentado), não na decodificação nem na conversão do vídeo.

O que este documento faz: mapear nominalmente os passes 0–5, dizer qual deles
deveria escrever a janela, e ranquear os mecanismos A3 com o teste exato de cada um.

## 1. Como um "pass" é definido nesta build (leitura obrigatória antes do mapa)

- Um pass **não** é um frame nem um `SetRenderTargets` isolado. Ele é um segmento
  da submissão: abre preguiçosamente no primeiro draw ou clear após
  `SetRenderTargets` e fecha antes de qualquer coisa que não seja desenho
  (`dm/android/gfx_vk_exec.c`, comentário da linha 4; `begin_pass()` ~445;
  `pass_commit()` ~239–265, que incrementa `g_sub_pass`).
- Um **novo** pass começa quando `SetRenderTargets` muda o conjunto de alvos
  (`set_rt()`, ~1426: se o conjunto é idêntico ao do pass aberto, o pass
  *continua* — contador `same targets kept` — e só muda de número se algo mudar),
  em trechos com rasterizer discard (~1016), e no fim da submissão.
- O pass dump captura **só o primeiro alvo de cor** do pass (`S.rt_col[0]`), no
  `vk_end_pass()` (~437 → `pass_dump()` ~293–307), copiado para buffer após
  barreira. Ele **não registra a identidade** do alvo (pool+offset, serial).
  Dois dumps byte-idênticos podem ser o mesmo `VkImage` ou duas cópias — o dump
  sozinho não distingue. Esta limitação é central para a seção 5.
- O filtro usado foi `DM_VK_PASSDUMP_SIZE=1280x720`: só passes cujo primeiro alvo
  de cor tem esse tamanho aparecem. Um pass ausente do dump não é um pass
  inexistente — é um pass cujo primeiro alvo tem outro tamanho, outro formato
  fora da lista do dump, ou nenhum alvo de cor.

## 2. O caminho do vídeo até a janela (cadeia completa, com linhas)

1. **Decodificação** — `dm/android/movie_avc.c`, `keep_picture()` (~107): o
   MediaCodec (`c2.qti.avc.decoder`) entrega quadros NV12 compactos. No log do
   título: decoder tipo 1, saída 4 (NV12), modo 1; buffer de saída de 1.382.400
   bytes = NV12 de 1280×720. Sem `[RED]` de filme: o decoder funciona.
2. **Entrega ao jogo** — `dm/host/hle_movie.c`, modo 1 (~480–499): o host copia o
   NV12 para um **buffer de CPU do jogo** (`GetOutputBuffer`). O host **não**
   compõe o vídeo. O jogo converte NV12→RGB e desenha ele mesmo (quad com shader
   próprio, amostrando as texturas Y/UV que ele mesmo sobe).
   - O modo 2 (textura nativa, RGBA direto na textura NVN via
     `nvn_host_write_texture()`, ~743) **não** está em uso aqui.
3. **Conversão e composição (jogo)** — os draws do jogo, replayados por
   `dm/android/gfx_vk_exec.c` (`prepare_draw()` ~992 em diante), escrevem o frame
   convertido em alvos 1280×720. São os passes 2–4 da seção 3.
4. **Aquisição da janela** — `dm/gfx/nvn/hle_nvn.c`:
   `nvnWindowInitialize` (~1320) cria a janela com **3 texturas** 1280×720,
   formato NVN `0x25` (RGBA8); `nvnWindowAcquireTexture` (~1364) devolve os
   índices em round-robin (`*idx = o->next++ % o->ntex`) e espera o present
   anterior daquela textura (`mtl_present_wait`, ~1387).
5. **Vínculo como render target** — o jogo liga a textura adquirida via
   `nvnCommandBufferSetRenderTargets` (`hle_nvn.c` ~898) → `set_rt()`
   (`gfx_vk_exec.c` ~1426), que fecha o pass anterior e abre o novo com aquela
   textura como `S.rt_col[i]`. É **neste** pass que a textura da janela deveria
   receber o conteúdo final.
6. **Present** — `nvnQueuePresentTexture` (`hle_nvn.c` ~1757) apresenta
   `o->tex[idx]` via `mtl_present()` (`dm/android/gfx_vk_present.c` ~622):
   `im = vk_tex(t)`; se `im->layout == GENERAL`, conta `shown` e enfileira;
   o `shot()` (~563) copia **essa mesma** `im` para o PPM do ponto A.
   A thread de present (`present_window()` ~485) faz o blit dessa `im` para o
   swapchain, roda o `alpha_fix` e o overlay, e apresenta.
   - Conclusão estrutural: **o ponto A preto significa que a textura que o jogo
     apresentou já estava preta quando `mtl_present` a enfileirou**. Nada entre
     o present e a tela (blit, `alpha_fix`, overlay, swapchain) pode ser o
     culpado — o que falta aconteceu antes, nos passes da submissão.

## 3. Mapa pass → alvo nos presents 1000–1004 (do log + dumps)

Leitura do log (`pass dump NN is the submission's pass P (present Q)`):

| Present | Pass 0 | Pass 1 | Pass 2 | Pass 3 | Pass 4 | Pass 5 |
|---|---|---|---|---|---|---|
| 1000 | preto | — (sem dump) | preto | preto | — | — |
| 1001 | preto | — (sem dump) | preto | preto | — | — |
| 1002 | preto | — (sem dump) | **vídeo completo** | **vídeo completo (idêntico)** | **vídeo completo (idêntico)** | preto |
| 1003 | preto | — (sem dump) | **vídeo completo** | **vídeo completo (idêntico)** | **vídeo completo (idêntico)** | preto |
| 1004 | preto | — (sem dump) | **vídeo completo** | **vídeo completo (idêntico)** | **vídeo completo (idêntico)** | preto |

Todos os dumps são 1280×720, formato 37 (`R8G8B8A8_UNORM`). Verificação própria
(hash dos arquivos): pass 0 sempre com o mesmo hash de preto total; passes 2, 3
e 4 com o mesmo hash entre si dentro de cada present e hashes diferentes entre
presents (o vídeo avança); pass 5 sempre com o hash de preto total.
Presents 1000–1001 todos pretos = vídeo recém-iniciando (decoder aquecendo,
primeiros quadros ainda não fluindo); frames 1001–1002 do log estão em 48,45 s e
48,52 s, dentro do `ninja_vi` (aberto em 47,91 s), com buffers NV12 de
1.382.400 bytes fluindo.

### 3.1 Pass 0 — sempre preto

É o **primeiro** conjunto de alvos da submissão. Duas leituras possíveis, ainda
indistinguíveis pelos dumps:

- (a) Um intermediário que o jogo limpa no início do frame e nunca mais escreve
  com conteúdo (ou escreve e o conteúdo é descartado por um pass posterior).
- (b) A própria textura da janela, limpa no início do frame (prática comum:
  limpar o backbuffer antes de desenhar a cena) e nunca reescrita com a cena.

O que decide entre (a) e (b) é a identidade do alvo (seção 6). O que já se sabe:
se (b) for verdade, o defeito é "a janela é limpa e a composição final nunca
volta para ela" — e isso explicaria o preto permanente em **todo** conteúdo, não
só no filme.

### 3.2 Pass 1 — o ausente (não é o elo perdido deste conteúdo)

Não aparece em nenhum dump porque seu primeiro alvo de cor não tem 1280×720
(ou tem formato fora da lista do dump, ou não tem alvo de cor). Candidatos:
alvo menor (ex.: plano UV, downscale, mip de outra textura), pass só de
profundidade, ou pass cujo primeiro alvo usa formato fora da lista
(`pass_dump()` ~303). **Não pode ser o elo perdido do conteúdo do filme**,
porque o conteúdo chega inteiro aos passes 2–4 *depois* dele: o que quer que o
pass 1 faça, a cadeia passa por ele sem perder o frame. O teste que o nomeia
está na seção 7 (dump sem filtro de tamanho).

### 3.3 Passes 2, 3 e 4 — o frame do vídeo, três vezes

São três segmentos distintos (o contador `same targets kept` é 0 até o present
1200, então não é um único pass continuado). Conteúdo byte-idêntico admite
exatamente duas estruturas, e o dump não distingue:

- (i) **Mesma imagem** como `rt_col[0]` nos três passes, com outros slots
  (profundidade, segundo alvo, view) diferentes — o conteúdo persiste por
  `loadOp LOAD` (`begin_pass()` ~455: `loadOp` padrão é `LOAD`). Neste caso,
  os passes 3 e 4 não acrescentam nenhum pixel visível ao alvo 0 (ou redesenham
  exatamente o mesmo quadro).
- (ii) **Três imagens distintas**, cada uma recebendo uma cópia do frame
  (cadeia de cópias/quads: conversão → cópia → composição).

Nos dois casos, a conclusão é a mesma e é a que importa: **um frame de vídeo
completo existe em alvo(s) 1280×720 durante a submissão**. A quebra está no
último elo (pass 4 → pass 5 → present), não antes dele.

### 3.4 Pass 5 — o último pass, preto, e o ponto central

Aparece **só** a partir do present 1002, isto é, só quando o quadro de vídeo
está fluindo — ele faz parte da cadeia do frame de vídeo, não é um pass genérico
de fim de frame (nos presents 1000–1001, sem vídeo fluindo, ele não existe).
É o **último** segmento da submissão do frame de vídeo. Estruturalmente, o
último segmento de um frame de jogo é onde se espera a composição final na
textura da janela. Há, portanto, duas leituras — e só a identidade do alvo as
separa (seção 6):

- **Leitura A — pass 5 é a textura da janela.** Então o jogo liga a janela por
  último, e o que ele faz nela resulta em preto: ou só limpa (clear dobrado
  para `loadOp CLEAR` preto, `clear_color()` ~517–529), ou desenha um quad
  final que amostra a textura errada, ou desenha com estado ineficaz
  (viewport/scissor zerados, depth rejeitando tudo, cull, rasterizer discard,
  condição de renderização falsa).
- **Leitura B — pass 5 é outro intermediário.** Então a textura da janela é
  outro pass (o mais plausível seria o pass 0, limpo no início e nunca
  reescrito) ou **nenhum** pass da submissão — isto é, o jogo apresenta uma
  textura que ele não desenhou nesta submissão. Neste caso, o elo perdido é a
  cópia/composição final em si: ela não existe na submissão, ou o host a
  desvia para o alvo errado.

Em ambas as leituras, o próximo teste é o mesmo (seção 7): ver os draws do
pass 5. A diferença entre elas só se fecha com identidade (RenderDoc, seção 6).

## 4. O remap de swizzle, avaliado (não presumido)

O log traz, uma vez, na inicialização:
`TextureViewSetSwizzle not identity (4 3 2 5): remapped with a Metal view when sampling`
(`hle_nvn.c` ~2103, `ONCE_LOG`).

- Enum NVN (`gfx_vk_tex.c` ~379): 0=zero, 1=um, 2=R, 3=G, 4=B, 5=A. Logo
  (4 3 2 5) = **(B, G, R, A)**: troca R com B, G e A intactos.
- No Vulkan, o swizzle **é aplicado**: `vk_tex_view()` (~429) compõe o
  `componentMapping` da view amostrada a partir do swizzle da view — o texto
  "Metal view" é herança de nomenclatura do backend Metal, não ausência de
  suporte. Para alvos de renderização, o swizzle é identidade (`~438`).
- **Veredito: o swizzle não explica preto.** Uma troca R↔B sobre um frame
  colorido produz um frame com cores trocadas, não preto. Para produzir preto,
  o swizzle precisaria conter ZERO/UM nos canais — o que não é o caso do único
  swizzle não-identidade logado. Variantes exóticas sobrevivem apenas como
  resíduo: uma view com nível/camada errada (ex.: nível de mip vazio) ou um
  swizzle diferente no quad final, ambos verificáveis no trace do pass 5
  (linhas `texture handle`, com tamanho/formato/níveis da textura amostrada).
  O swizzle, sozinho, está rebaixado — não é o mecanismo principal.

## 5. Mecanismos candidatos (família A3), ranqueados

Ordem = probabilidade × testabilidade, não ordem de preferência de patch.
Cada mecanismo tem **um** teste e **um** patch que se seguiria — nunca vários
patches em paralelo.

### M1 — O pass 5 desenha na janela, mas o desenho resulta em preto (primeiro)

Subvariantes, todas dentro do pass 5:

- **M1a — clear sem desenho posterior.** O pass 5 só limpa a janela para preto
  (clear de attachment inteiro dobrado para `loadOp CLEAR`, `clear_color()`
  ~526–529, ou `vkCmdClearAttachments` após o commit) e nenhum draw escreve
  depois. O dump preto + 0 draws no trace confirma.
- **M1b — quad final amostra a textura errada.** O draw final existe, mas o
  descritor aponta para outra textura (slot de pool desatualizado, handle
  obsoleto, textura cuja subida foi perdida) — amostra preto/zeros. O trace do
  pass 5 mostra a textura amostrada (pool+offset, tamanho, formato): se não
  for 1280×720 formato 37 com o conteúdo do vídeo, confirma.
- **M1c — draws ineficazes.** Draws existem, mas com viewport ou scissor
  zerados (`scissor_rect()` ~506 zera a extensão fora do pass; extensão zero
  pula clears e clipa draws), profundidade rejeitando tudo (LRZ do Adreno com
  profundidade de outro command buffer — o precedente documentado em
  `begin_pass()` ~493–500), cull invertido, rasterizer discard, ou bloco de
  condição de renderização avaliado falso (o perfil não define `render_cond`,
  mas o jogo pode usar `SetRenderEnableConditional` — o host avalia no replay,
  `gfx_vk_exec.c` ~121–130). O trace mostra viewport/scissor/shaders por draw;
  o estado de profundidade/cull não sai no trace — RenderDoc o mostra.
- **Teste exato (sem rebuild):** `DM_VK_TRACE_PASS=5` no `env.txt` (seção 7).
  O trace loga, por draw do pass 5: shaders, alvos (pool+offset, serial),
  view, scissor, viewport, faixa de profundidade e texturas amostradas
  (`trace_draw()` ~1216; linhas `texture handle` ~797). Zero linhas `draw:` =
  M1a. Draws com viewport/scissor zerados = M1c (parcial; profundidade/cull
  ficam para o RenderDoc). Draws amostrando textura que não é o alvo do vídeo
  = M1b.
- **Patch único se confirmado:** conforme a subvariante — M1a: nenhum patch de
  host inventa desenho; o passo passa a ser investigar por que o jogo não
  desenha (e, se o host descarta o desenho — linha `colour target: not a
  texture object: left out` no trace — corrigir **essa** validação, só ela).
  M1b: corrigir a resolução do descritor/textura daquele binding, só ele.
  M1c: corrigir o estado de replay identificado (viewport/scissor, corte
  LRZ/`lrz_touch`, cull/front-face ou avaliação da condição), só ele.

### M2 — A janela nunca é escrita nesta submissão (segundo)

- O jogo limpa a janela no pass 0 e renderiza o vídeo em intermediários, mas a
  composição final de volta para a janela **não acontece** nesta submissão —
  ou acontece para o alvo errado. O apresentado é então a janela limpa (pass 0)
  ou uma textura nunca escrita (zeros de alocação).
- Por que é plausível apesar de soar como "bug do jogo": no Switch o mesmo
  jogo funciona, então a composição existe no código do jogo; se ela não chega
  à janela aqui, o desvio é do host — ex.: o `SetRenderTargets` final é
  descartado (`rt_bad`: objeto sem o magic `TEX`, `set_rt()` ~1430–1441), ou
  o índice apresentado não é o índice desenhado (ver M2b abaixo).
- **M2b (variante de índice):** `nvnWindowAcquireTexture` devolve índices em
  round-robin e `nvnQueuePresentTexture` apresenta `o->tex[idx]`. Se o host
  apresentar um índice diferente do que o jogo desenhou (por exemplo, por
  divergência entre o índice adquirido e o apresentado na fila assíncrona),
  o apresentado seria uma textura velha/zerada. Não há evidência disso hoje;
  é a variante mais fraca de M2.
- **Teste exato:** o trace do pass 5 **não** decide M2 sozinho (ele mostra o
  pass 5, não a janela). Decidem: (i) o trace mostrar `rt_bad` / alvo
  descartado no pass final; ou (ii) RenderDoc, que mostra por handle qual
  imagem o blit lê e quais imagens cada pass escreveu — se nenhuma pass
  escreveu a imagem do blit, M2 está confirmado.
- **Patch único se confirmado:** corrigir o desvio específico — validação de
  alvo (`rt_bad`) ou bookkeeping de índice acquire/present — só ele. Se
  nenhum desvio do host for encontrado, **não há patch de host**: o passo
  passa a ser reexaminar a submissão inteira no RenderDoc, não inventar uma
  cópia final.

### M3 — Pass 5 limpa a mesma imagem que o pass 4 encheu (terceiro)

- Se passes 4 e 5 têm como `rt_col[0]` a **mesma** imagem (outros slots
  diferentes), então o pass 5 pode estar limpando/sobrescrevendo o vídeo que
  o pass 4 acabou de escrever — por exemplo, um clear de "preparar para o
  próximo uso" emitido dentro da mesma submissão, ou um quad preto de
  letterbox/fade. O dump final seria preto e o frame shot, preto — exatamente
  o observado — mesmo com a cadeia 2–4 perfeita.
- **Teste exato:** identidade — o trace do pass 5 dá o alvo dele
  (pool+offset); o alvo do pass 4 **não** está nos dados atuais. Decidem:
  RenderDoc (handles por pass), ou um segundo trace (`DM_VK_TRACE_PASS=4`)
  comparado com o do pass 5 **na mesma corrida** — inviável com as chaves
  atuais (cada chave traça um pass de uma submissão; comparar entre corridas
  é frágil porque endereços de pool variam). Logo, o teste de M3 é o
  RenderDoc; o trace do pass 5 é necessário mas não suficiente para M3.
- **Patch único se confirmado:** impedir a sobrescrita — conforme a causa
  exata (ordem clear/draw do jogo mal replayada, ou `loadOp` dobrado
  incorretamente para CLEAR num pass que deveria dar LOAD). Só o que o
  RenderDoc apontar.

### M4 — View/nível/camada errada no quad final (resíduo)

- O quad final amostra o alvo certo, mas através de uma view com nível de mip
  vazio, camada errada ou formato incompatível — amostra zeros. É o resíduo
  do swizzle (seção 4): o mecanismo de view existe e é testável, mas não há
  nenhuma linha de log apontando para ele hoje.
- **Teste exato:** linhas `texture handle` do trace do pass 5 (níveis, camadas,
  formato da view) + RenderDoc (view efetiva do descritor).
- **Patch único se confirmado:** corrigir a composição da view em
  `vk_tex_view()` para aquele caso, só ela.

### Rebaixados (não lideram, ficam registrados)

- **Pass 1 como elo perdido:** refutado como causa deste conteúdo — o frame
  chega inteiro aos passes 2–4 depois dele. Resta apenas nomeá-lo (dump sem
  filtro, seção 7).
- **F1 (timeout silencioso de 1 s) / F2 (UAF de pool):** mecanismos do caso B
  (perda intermitente), não do preto estável do pass 5 em três presents
  seguidos com estrutura idêntica.
- **Formato/sRGB do blit:** ambos os lados são formato 37; o blit de um alvo
  colorido produziria swapchain colorido. O ponto A preto já exclui o blit.
- **Swizzle (B,G,R,A):** seção 4 — troca de canais, não apagamento.

## 6. O que ainda NÃO dá para saber (limites honestos)

1. **Identidade dos alvos.** O dump não registra pool+offset/serial. Não dá
   para afirmar, só com os dumps, se pass 5 = janela, se pass 5 = mesma imagem
   do pass 4, ou se a janela = pass 0. Afirmar qualquer uma dessas três sem o
   trace/RenderDoc seria chute — e é exatamente o que esta análise se recusa
   a fazer.
2. **Draws do pass 5.** O dump não registra draws, viewport, scissor,
   texturas amostradas nem valores de clear. Tudo isso vem do trace (seção 7).
3. **Estado de profundidade/cull do pass 5.** O trace não imprime func de
   profundidade nem cull por draw; só o RenderDoc (build debuggable) mostra o
   estado completo do pipeline.
4. **Pass 1.** Sem dump sem filtro, seu tamanho/formato/conteúdo são
   desconhecidos — mas, pela seção 3.2, isso não bloqueia a conclusão principal.

## 7. Próximo passo executável único (sem rebuild, sem reinstalar)

**Uma corrida, um `env.txt`, dois instrumentos que já existem no APK atual.**
Trocar o `env.txt` na pasta files do app pelo arquivo
`workspace/nx2a-black-screen/env-trace-pass5.txt` (conteúdo abaixo), **só
relançar** (não reinstalar — reinstalar sobrescreve o `env.txt`), jogar até o
filme `ninja_vi`, e mandar o `log.txt` + os `pass_*.ppm` dessa corrida antes
de relançar de novo.

```text
DM_LANG=en-US
DM_VK_NO_ZEROCOPY=1
DM_FS=1
DM_MOVIE=1
DM_VK_SHOTS=5
DM_VK_TRACE_PASS=5
DM_VK_PASSDUMP=1000
DM_VK_PASSDUMP_FRAMES=5
```

Sem `DM_VK_PASSDUMP_SIZE` desta vez, de propósito: o dump sem filtro captura
também o pass 1 (tamanho/formato/conteúdo) e confirma que o pass 5 dos presents
1000–1004 é o mesmo fenômeno do dump anterior.

### Como ler o resultado (regras de decisão, sem ambiguidade)

1. Localizar no log o bloco `=== traced pass 5` e verificar em que contexto
   ele caiu: se houver linhas de filme (buffers NV12 de 1.382.400 bytes) ao
   redor, é um frame de vídeo — o caso que interessa. Se cair antes do filme
   (presents baixos, sem fluxo de vídeo), o trace é de outro tipo de frame:
   ainda informa a estrutura do pass 5, mas o passo seguinte passa a ser o
   RenderDoc (o trace não consegue mirar um frame de filme a partir do
   lançamento — `DM_CTL` não existe nesta build release).
2. **Zero linhas `draw:` sob o pass 5** → M1a (pass 5 só limpa). Próximo passo:
   RenderDoc para confirmar a identidade do alvo antes de qualquer patch.
3. **Draws com viewport ou scissor zerados, ou com `colour target: not a
   texture object: left out`** → M1c / descarte de alvo. O patch segue a
   causa exata mostrada, só ela.
4. **Draws amostrando textura que não é 1280×720 formato 37** → M1b. Comparar
   a textura amostrada com o alvo do vídeo; o patch corrige aquele binding.
5. **Draws normais, viewport/scissor sãos, amostrando o alvo do vídeo, e o
   pass 5 mesmo assim preto no dump** → o problema não está nos draws do
   pass 5: passa a ser identidade (M2/M3) e o passo seguinte é o RenderDoc
   com build debuggable, mirando um frame do filme (último bom = pass 4 com
   vídeo, primeiro preto = pass 5).
6. **Dump sem filtro mostra o pass 1** → registra-se o que ele é
   (tamanho/formato/conteúdo); se for um alvo com conteúdo, avalia-se se ele
   participa da cadeia — sem reabrir a conclusão principal, que não depende
   dele.

### O que NÃO fazer nesta corrida

Não mudar mais nenhuma chave, não reinstalar, não trocar o `env.txt` no meio
da corrida, não abrir o jogo duas vezes antes de copiar o `log.txt` (a segunda
abertura sobrescreve o `log.prev.txt`).

## 8. Resumo da cadeia (uma linha por elo)

Decodificação NV12 funciona → jogo converte e desenha → passes 2–4 contêm o
frame completo → **pass 5, o último elo, sai preto** → a textura apresentada
(ponto A) é preta → blit/`alpha_fix`/overlay/swapchain apenas reproduzem o
preto. A quebra está entre o pass 4 e o present. O trace do pass 5 diz *como*
o último elo falha; o RenderDoc diz *em qual imagem* ele falha, se o trace
não bastar.
