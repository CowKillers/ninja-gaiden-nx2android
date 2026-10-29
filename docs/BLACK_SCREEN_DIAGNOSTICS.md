# Instrumentação de diagnóstico — tela preta + perda intermitente de imagem

**Build-alvo:** host v0.1.2 do `nx2android.zip` (não o clone). **O patch é temporário e desligado por padrão.** Não foi aplicado ao host dela, não foi compilado e não gerou APK — ele existe como diff pronto (`black-screen-diag.patch`, neste diretório) para ser aplicado numa build de diagnóstico quando houver um marco verificável para isso. Nada aqui muda o renderizador, o `alpha_fix`, o swapchain ou o pacing por conta própria.

## 1. Como ligar (sem reinstalar o data pack)

O `env.txt` mora na pasta files do app e é lido a cada lançamento (`front_android.c` ~497, ~527). **Reinstalar o data pack sobrescreve o `env.txt`** (só o `settings.txt` é preservado); por isso, edite o `env.txt` e apenas **relance** o jogo — não reinstale. Linhas de comentário começam com `#`.

```text
# Diagnóstico de tela preta (temporário)
DM_VK_DIAG=1
DM_VK_DIAG_EVERY=1
```

E, conforme o objetivo da corrida:

| Objetivo | Acrescentar | Por quê |
|---|---|---|
| Caçar o sumiço imprevisível (caso B) | nada além das duas linhas acima | As linhas de evento (timeout, UAF, swapchain) já bastam para o primeiro log do caso B, sem custo de captura |
| Amostrar B/C ao longo de uma sessão longa | `DM_VK_DIAG_SAMPLE=300` | Captura B e C em 1 present a cada 300, continuamente — pega preto persistente e dá amostras antes/depois de um sumiço |
| Capturar uma transição conhecida (ex.: sempre ao iniciar um vídeo) | `DM_VK_SHOTS=5` e `DM_VK_DIAG_FRAMES=5` | A = PPM da textura da janela nos 5 primeiros presents; B e C = hashes (e PPM, com `DM_VK_DIAG_PPM=1`) dos mesmos presents |
| Separar pacing do resto | `DM_VK_PACE=0` | Relido a cada 30 presents; se o frame mediano cair para ~16 ms, o pacing é o culpado |
| Achar qual pass sai preto (caso A, após PPM preto) | `DM_VK_PASSDUMP=1` e `DM_VK_PASSDUMP_SIZE=1280x720` | Despeja os alvos dos passes com esse tamanho; `DM_VK_PASSDUMP_SKIP=n` pula os primeiros passes de cada submissão; `DM_VK_PASSDUMP_FRAMES=N` repete por N presents |
| Testar a hipótese LRZ do Adreno (caso B, frames escuros isolados) | `DM_VK_CB_DRAWS=0` | Desliga o corte de command buffer; se os frames escuros isolados sumirem, o corte/LRZ é o culpado |
| Apresentar na thread do jogo (separar thread de present de thread do jogo) | `DM_VK_SYNC_PRESENT=1` | Elimina a fila `PQ_N` e o `mtl_present_wait` da equação; se o sumiço sumir, o culpado está na fila |
| Breakdown por frame dos frames atrasados | `DM_SLOWFRAME=1` | Escreve o breakdown por frame dos frames julgados atrasados (anel dos últimos 16 frames) |

Limitação honesta: o controle remoto `DM_CTL` ("env line" ao vivo, citado nos comentários do código) **não existe nesta build** — `front_android.c` ~532 faz `unsetenv("DM_CTL")` em release. Não há como armar capturas no meio de uma corrida; tudo é por `env.txt` antes do lançamento. Por isso a amostragem (`DM_VK_DIAG_SAMPLE`) existe: é o substituto para o evento imprevisível.

## 2. Os três pontos de captura

| Ponto | O que é | Como é capturado (sem ler enquanto a GPU escreve) | O que significa |
|---|---|---|---|
| **A** — textura da janela | A imagem do jogo antes do blit, 1280×720 | O `shot()` existente (`gfx_vk_present.c` ~553): copia para scratch **na thread de replay, antes de enfileirar**, espera o fence (`mtl_wait`) e só então lê. Com o patch, quando `DM_VK_DIAG=1`, o `shot()` também loga o hash RGB. Ligado por `DM_VK_SHOTS=N` (próximos N presents) e grava `frame_XXXXXX.ppm` | A preto → o problema está na renderização da cena (voltar aos passes). A com arte → o problema está depois da textura |
| **B** — swapchain após blit + `alpha_fix`, antes do overlay | A imagem composta, sem overlay | Novo no patch: dentro do mesmo command buffer do present, após o `alpha_fix`, o rendering termina, a imagem vai para `TRANSFER_SRC`, é copiada para um staging buffer, e o rendering recomeça (`LOAD`) para o overlay. A leitura do staging só acontece no reuso do slot, **depois** do `vkWaitForFences` do slot — nunca enquanto a GPU escreve | A com arte + B preto → o blit ou o `alpha_fix` perdeu o conteúdo. A preto + B preto → o problema já estava em A |
| **C** — swapchain após overlay, antes do present | A imagem final que vai para a tela | Novo no patch: mesmo mecanismo, cópia após o overlay e antes da barreira para `PRESENT_SRC`, lida no reuso do slot | B com arte + C preto → o overlay ou a transição final perdeu o conteúdo. B preto + C preto → o problema já estava em B ou antes |

Regra de leitura, sem exceção: **A ok + B errado → composição (blit/`alpha_fix`); B ok + C errado → overlay/transição final; A preto → retroceder pelo pipeline (pass dump, seção 1).** Os hashes RGB (FNV sobre R,G,B na ordem, ignorando alpha) permitem comparar A, B e C sem abrir os PPMs: hashes iguais = mesmo conteúdo; hash de A diferente de B com A com arte = perda no blit.

Custos, para não ligar tudo sempre: o hash de A varre 1280×720×4 bytes na CPU por frame capturado (só quando `DM_VK_SHOTS` está armado); os stagings de B/C ocupam ~10 MB por slot usado e por ponto (2340×1080×4), até ~160 MB se os 8 slots forem usados — por isso `DM_VK_DIAG_FRAMES` e `DM_VK_DIAG_SAMPLE` existem, e o PPM de B/C só é escrito com `DM_VK_DIAG_PPM=1` (sem ele, só o hash é logado). `DM_VK_DIAG_EVERY=1` loga uma linha por present (~60 linhas/s a 60 fps): use 1 na caçada de uma transição e 60 (o padrão) em sessões longas.

## 3. O que cada linha de log significa

### Linhas novas do patch (prefixo `[diag]`)

| Linha | Significado | Ação |
|---|---|---|
| `[diag] present N tex <serial> 1280x720 layout 6 crop 0,0 1280x720 queue_depth D shown S no_img I undrawn U` | Um present passou, com a textura da janela, seu layout (6 = `GENERAL`), o crop e a profundidade da fila no momento. Amostrada por `DM_VK_DIAG_EVERY` | Se `queue_depth` fica em 4 por muito tempo, a thread de present é o gargalo. Se `no_img`/`undrawn` sobem junto com o sumiço, a textura foi recriada e ainda não desenhada |
| `[diag] A present N rgb-hash=… (1280x720)` | Hash RGB da textura da janela (ponto A), junto com o `frame_NNNNNN.ppm` do `shot()` | Compare com B/C do mesmo N |
| `[diag] present N B rgb-hash=…` / `[diag] present N C rgb-hash=…` | Hash RGB dos pontos B e C, lidos no reuso do slot (portanto, com atraso de até um ciclo de slot) | Aplique a regra de leitura da seção 2 |
| `[diag] mtl_present_wait TIMEOUT after 1 s: ticket T, done D` | **A linha mais importante para o caso B.** A thread de present estava >1 s atrasada; o acquire retornou mesmo assim e o jogo redesenhou uma textura ainda na fila do blit. Só os 20 primeiros timeouts são logados | Se timeouts coincidem com os frames pretos: o fix é no atraso da thread de present (ou no timeout), não no renderizador |
| `[diag] mtl_present_wait slow: X ms for ticket T` | Acquire esperou >100 ms (sem estourar o timeout) | Atraso crônico da thread de present; correlacione com `acq_fence`/`submit_pres` |
| `[diag] UAF RISK: image … dropped while still queued for present or held as last frame` | Uma imagem foi solta (`img_drop`, por finalização de pool ou overlap) enquanto a fila de present ou o `last` ainda a referenciavam | Se aparece junto com o sumiço: o fix é de lifetime (referência/geração), não de renderização |
| `[diag] present N dropped: no swapchain` | Frame descartado porque não havia janela/swapchain (app em segundo plano ou superfície destruída); o ticket avançou do mesmo jeito | Esperado durante pausa; fora dela, indica perda de superfície |
| `swapchain destroyed (<motivo>)` | Motivo: `window changed`, `acquire out of date`, `present out of date` ou `window lost` | Correlacione com o sumiço: `window lost`/`out of date` ao redor do evento aponta para superfície, não para cena |

### Linhas que já existem (e o que significam aqui)

| Linha | Significado |
|---|---|
| `replay up to present N: draws …, skipped (no program …, no target …, no pipeline …); presents shown …, no image …, never drawn …` (a cada 600 presents) | Saúde do replay. `shown` conta textura existente em `GENERAL` — **não** prova conteúdo correto |
| `[present_window] acq_fence=X ms, submit_pres=Y ms` (a cada 120 presents) | Tempo esperando o fence do slot + acquire, e tempo de submit+present. `submit_pres` alto e constante = FIFO/pacing; `acq_fence` alto = slot preso |
| `[pool_sync] wait_fence=X ms, sync=Y ms` (a cada 30 submissões com pools copiados) | Espera do fence anterior + varredura dos pools (`memcmp` por blocos de 256 KB). Custo de CPU, não de GPU |
| `[nvn] frame interval up to frame N: >16.7ms X / Y frames, p99 …` | Intervalo entre frames do jogo. >16,7 ms em todos os frames = o jogo não está sustentando 60 fps |
| `[nvn] on-screen up to frame N: F frames, dropped D (discarded C), p99 …` | **Cuidado:** `dropped` = frame exibido por mais que 1,5× o hold esperado (atrasado), **não** frame que sumiu; `discarded` = descartado pelo sistema. `dropped` alto + `discarded 0` = fluidez ruim por espera, não perda de imagem |
| `[alias] stale read: …` | Duas texturas sobre a mesma memória, uma renderizada depois da outra ter sido amostrada — candidato para textura amostrada preta/velha |
| `[RED] alpha_fix pipeline failed` / `[RED] overlay pipeline failed` / `[RED] swapchain creation failed` / `vkAcquireNextImageKHR: …` | Falhas de pipeline/swapchain/acquire. Ausência delas no log_82 é evidência de que esses passos rodaram |
| `[nvn] WindowCrop …` / `[nvn] WindowInitialize …` | Mudança de crop ou recriação da janela do jogo — correlacione com o sumiço (transição de cena, início de vídeo) |
| `[nvn] graphics suspended` / `[nvn] graphics resumed` | Pausa/retomada com drenagem das filas. O fim do log_82 é um `suspended` normal, não um erro |

## 4. Capturar o log da corrida em que a imagem some (caso B) — passo a passo

O caso B **não tem log próprio**: o log_82/84 termina em pausa, sem o evento, e o log_85 é o log_80 antigo (pré-bundle). Sem este procedimento, a próxima ocorrência do sumiço também chegará sem prova.

### Antes da corrida

1. Sem reinstalar o data pack, edite o `env.txt` na pasta files do app e deixe:
   ```text
   DM_VK_DIAG=1
   DM_VK_DIAG_EVERY=1
   DM_VK_DIAG_SAMPLE=300
   ```
   (`EVERY=1` dá uma linha por present — volume alto, mas é o que permite apontar o frame exato do sumiço. Para sessões longas sem caçada, use `EVERY=60`.)
2. Se o sumiço já tiver um padrão conhecido (ex.: sempre ao iniciar um vídeo, sempre após a pausa), prefira a captura direcionada: `DM_VK_SHOTS=5` + `DM_VK_DIAG_FRAMES=5` + `DM_VK_DIAG_PPM=1` numa corrida que reproduza o padrão — mas lembre que os 5 presents são os **primeiros** da corrida, não os do evento; para o evento em si, a amostragem (`SAMPLE=300`) é o mecanismo certo.
3. Anote a hora aproximada e o que estava na tela (título, cena, vídeo, pausa) quando a imagem sumir e, se voltar, quando voltar. Sem esse marco, o log é um palheiro sem agulha.

### Depois da corrida — copiar ANTES de relançar

O log mora na pasta files do app (o `DM_ROOT` do host):

```text
/sdcard/Android/data/org.nx2a.t0100e2f014f46000/files/log.txt
```

Copie por `adb pull` (ou pelo app Arquivos, se acessível) **antes de abrir o jogo de novo**. O motivo é a rotação (`front_android.c` ~519): **a cada lançamento, o `log.txt` anterior é renomeado para `log.prev.txt`**. Ou seja:

| Situação | Onde está o log da corrida do sumiço |
|---|---|
| Ainda não relançou depois dela | `log.txt` — copie agora |
| Relançou uma vez depois dela | `log.prev.txt` — copie esse |
| Relançou duas vezes depois dela | **Perdido** (o `log.prev.txt` foi sobrescrito pelo `log.txt` da corrida seguinte) — a corrida precisa ser refeita |

Os `frame_*.ppm` (ponto A) e, com `DM_VK_DIAG_PPM=1`, os `diag_B_*.ppm` / `diag_C_*.ppm` ficam na mesma pasta. Envie junto: o log, os PPMs (se houver), o instante do sumiço e o contexto de cena da etapa 3.

### O que o log do caso B precisa conter para fechar o caso

- As linhas `[diag]` ao redor do instante do sumiço, em especial `TIMEOUT`, `UAF RISK` e `swapchain destroyed`.
- Os contadores `shown`/`no_img`/`undrawn` do replay anterior e posterior ao evento.
- `WindowCrop`/`WindowInitialize`, finalizações de pool e abertura de filme (`movie`) ao redor do evento.
- Se nada disso aparecer ao redor do evento, isso também é informação: o sumiço, nesse caso, está dentro do conteúdo dos passes — e o passo seguinte é o pass dump da seção 1, não mais present.

## 5. Como aplicar o patch (quando houver build de diagnóstico)

```sh
cd <pasta do nx2android>   # a que contém nxnative/
patch -p1 < black-screen-diag.patch
```

O patch toca: `nxnative/dm/android/gfx_vk.h` (declarações), `nxnative/dm/android/gfx_vk_present.c` (logs de present, timeout do acquire, stagings B/C, motivo da destruição do swapchain, `last` espelhado), `nxnative/dm/android/gfx_vk_tex.c` (detector de imagem solta ainda referenciada). Ele **não** altera o caminho de renderização, o `alpha_fix`, a escolha de alpha do swapchain, o pacing ou qualquer sincronização — só observa. Com `DM_VK_DIAG` ausente ou `0`, o único comportamento novo é o motivo no log de destruição do swapchain (evento raro) e o log dos 20 primeiros timeouts do `mtl_present_wait` (anomalia que hoje é silenciosa). Para voltar ao comportamento exato anterior, reverta o patch; não há chave de compilação nova nem arquivo novo de build.

## 6. Captura RenderDoc no S23 — passo a passo

**Por que agora é válido (e quando não seria):** o RenderDoc **não** recupera shader faltando — um draw descartado nunca vira pipeline Vulkan e nunca aparece na captura. Aqui não falta shader: o log_82 tem zero draws pulados e o bundle é 114/114, então **todos os draws viram pipelines e aparecem na captura**. A captura é válida para este caso. (Se um dia o log voltar a mostrar draws pulados, o RenderDoc volta a ser inútil para esses draws — e o caminho volta a ser jogar → capturar → re-port.)

**Pré-requisito verificado — leia antes de tentar:** o APK entregue (`NinjaGaiden.apk`) foi conferido no manifesto e é **release, `debuggable=false`** (o `mkapk.py` só marca debuggable quando **não** se passa `--release`). A injeção da camada do RenderDoc via adb só funciona em apps debuggable (ou em aparelho com root). Ou seja: **não adianta tentar capturar o APK release atual esperando que funcione.** São necessários um dos dois, antes de qualquer passo abaixo:

- (a) uma build de diagnóstico com a **única** diferença de `debuggable=true` no manifesto — sem mudança de código, sem mudança de renderer, sem mudança de host. É uma build de diagnóstico, não um patch, e precisa de autorização (a regra dela é não sair APK sem marco verificável — e a captura RenderDoc é o marco que falta); ou
- (b) um S23 com root, caso em que a camada pode ser injetada em qualquer app.

Se nenhum dos dois existir, não perca tempo com o RenderDoc: use o pass dump da seção 1, que funciona no APK atual só com `env.txt`. O `mkapk.py` tem até um `--extra-so` ("outra biblioteca arm64 ao lado da principal, uma camada de validação Vulkan"), mas empacotar a camada junto não dispensa o requisito de debuggable/root — não trate o `--extra-so` como atalho.

**Não há `renderdoccmd` nesta VM** — a captura é feita no aparelho dela, com o RenderDoc instalado no PC e/ou no celular. O passo a passo:

1. No PC: baixe e instale o RenderDoc (renderdoc.org, versão estável atual). No S23: ative as Opções do desenvolvedor e a Depuração USB; conecte por USB e confirme com `adb devices` que o aparelho aparece.
2. Instale o app RenderDoc no S23 (o APK do RenderDoc acompanha a instalação do PC) e abra-o. Nele, selecione o app do jogo (`org.nx2a.t0100e2f014f46000`) e toque em Launch — o RenderDoc lança o jogo com a camada de captura ativa. (Se o lançamento falhar ou a captura vier vazia, volte ao pré-requisito acima: quase certamente é o APK release sem root.)
3. No jogo, chegue ao estado a capturar:
   - **Caso A (tela preta permanente):** qualquer frame com a tela preta e o overlay visível serve — a captura de um frame preto já decide.
   - **Caso B (imagem some):** capture **dois** frames seguidos — o último frame bom e o **primeiro** frame em que a imagem some. A comparação entre os dois é a prova; um único frame preto, sem o anterior bom, não diz o que mudou.
4. No app RenderDoc (ou no RenderDoc do PC conectado ao aparelho), dispare a captura no frame certo e salve o arquivo `.rdc`. Envie o `.rdc` junto com o instante e o contexto de cena (título, transição, vídeo, pausa).
5. Atenção: capturar serializa o trabalho da GPU e muda o timing — um sumiço que depende de atraso (hipótese B1, timeout de 1 s) pode **não reproduzir** sob captura. Se o sumiço sumir quando o RenderDoc está ativo, isso também é informação (aponta para timing), e o caminho volta a ser o log de eventos da seção 4 + pass dump.

### O que procurar dentro da captura (checklist, na ordem)

1. **A textura da janela antes do blit.** No Event Browser, localize o `vkCmdBlitImage` que copia para a imagem do swapchain. No Texture Viewer, veja o conteúdo da textura **origem** naquele ponto (1280×720, `R8G8B8A8_UNORM`):
   - Origem com a cena → a renderização está sã e a perda está **depois** do blit (vá ao item 3).
   - Origem preta → a perda está **antes** do blit, na renderização (vá ao item 2). É o resultado esperado pelo resto da auditoria.
2. **Qual pass produz a textura da janela.** Volte pelos eventos até o último render pass que tem a textura 1280×720 como alvo de cor. Verifique, nessa ordem:
   - O pass tem draws? Quantos? (Compare com os ~30–160 draws/frame do log.)
   - O alvo entra limpo para preto (clear) e os draws seguintes produzem o quê? Veja a saída de cor do pass no Texture Viewer.
   - As texturas amostradas pelos draws do pass estão com conteúdo ou pretas/vazias? Uma textura amostrada preta (upload perdido, alias) produz cena preta com draws saudáveis.
   - O depth/stencil do pass está plausível? (Um depth obsoleto do Adreno/LRZ rejeita draws inteiros — hipótese B3.)
   - O scissor/viewport do pass cobre a textura? (Scissor zerado clipa tudo sem erro.)
3. **O blit, o `alpha_fix` e o overlay.** Na mesma captura, depois do blit:
   - O blit copia a textura certa (origem = a textura da janela do item 1, não outra imagem) e com o crop 0,0 1280×720?
   - O draw do `alpha_fix` (triângulo fullscreen) tem máscara de escrita **só no canal alpha**? (Se ele tocasse no RGB, estaria apagando a cena — o código diz que não, mas a captura prova.)
   - Os draws do overlay usam `LOAD` (preservam o que o blit escreveu) e o overlay aparece por cima? (Overlay visível + jogo preto = blit/overlay sãos, problema na origem.)
4. **O present.** Localize o `vkQueuePresentKHR`: a imagem apresentada é a que recebeu o blit? O swapchain é 2340×1080? Se a imagem do present é a mesma do blit e o overlay aparece nela, a apresentação está exonerada por completo.
5. **Para o caso B (dois frames):** compare bom × primeiro preto e responda: o pass que produz a janela mudou? A textura origem do blit é outro `VkImage` (janela recriada)? O blit sumiu? Algum alvo mudou de tamanho? A diferença entre os dois frames **é** a hipótese — registre qual foi, não apenas "sumiu".

### Como a captura decide

| Resultado da captura | Decisão |
|---|---|
| Textura da janela com a cena, swapchain preto após o blit | Perda na apresentação (blit/`alpha_fix`/overlay/present) — o patch, se houver, é ali |
| Textura da janela preta, passes anteriores com conteúdo | A cena se perde no pass final da janela — o patch, se houver, é no replay/pass desse alvo |
| Textura da janela preta e todos os passes pretos, com texturas amostradas pretas | Upload/alias/descritor de textura — o patch, se houver, é no caminho de textura |
| Textura da janela preta, passes com draws mas saída preta e texturas sãs | Draws ineficazes (profundidade, condição, scissor, pipeline) — o patch, se houver, é no replay do pass |
| Captura vazia ou sem o blit | A captura não pegou o trabalho do present (thread separada) ou o app não estava com a camada ativa — refazer; não concluir nada a partir de captura vazia |

## 7. Limites do que esta instrumentação prova

- Hashes iguais entre A, B e C provam que o conteúdo sobreviveu ao present; não provam que o conteúdo é a cena certa (um RGB preto idêntico nos três pontos continua preto nos três).
- A amostragem (`SAMPLE=300`) pode perder um sumiço de um único frame; ela serve para sumiços persistentes ou recorrentes, não para um frame isolado — para esse, o timeout/UAF do log de eventos é o sinal, não a captura.
- O detector `UAF RISK` é best-effort: ele verifica a fila e o `last` no momento do drop, sob mutex da fila, mas o `last` é espelhado sem lock total — um positivo é evidência forte, um negativo não exclui lifetime como causa.
- Nenhuma linha de log substitui o frame shot para o caso A nem o pass dump para localizar o pass preto. A instrumentação diz **onde** a imagem se perde; o pass dump diz **por quê** a cena sai preta.
