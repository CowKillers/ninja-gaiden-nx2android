# Tela preta + perda intermitente de imagem — Ninja Gaiden Sigma no nx2android

**Jogo:** Ninja Gaiden Sigma, title `0100E2F014F46000`, versão 1.0.4, pacote `org.nx2a.t0100e2f014f46000`.
**Aparelho:** Samsung Galaxy S23, Snapdragon 8 Gen 2, Adreno 740, Android 16.
**Uso:** pessoal, sem distribuição, sem redistribuir dump, chaves ou arte do jogo.
**Base auditada:** o host REAL dela, versão `v0.1.2`, extraído do `nx2android.zip` (não o clone 9d67ede, usado só para comparação). Caminhos abaixo são relativos a `nx2android/nxnative/` dentro do zip. Não foram abertos `keys/`, RomFS do jogo ou dumps — só estrutura, perfil, logs e fontes do host.
**Regras respeitadas:** sem reescrever o renderizador, sem recriação contínua da swapchain, sem patch OPAQUE (revogado), sem remover o `alpha_fix`, sem APK e sem re-port até um marco verificável. Este documento é a Fase 1 (auditoria). A instrumentação é a Fase 2, em `BLACK_SCREEN_DIAGNOSTICS.md` + `black-screen-diag.patch`.

## 0. Correção de registro: os "logs novos" são reenvios de logs antigos

Dois arquivos chegaram depois do pedido, e ambos foram verificados aqui como duplicados — nenhum é uma corrida nova:

- **`log_84_nyz4.txt` = `log_82_glhl.txt`.** 3.597 linhas, 321.329 bytes nos dois; após remover endereços hex, o diff é zero. É o log_82 reenviado.
- **`log_85_g2wu.txt` = `log_80_llot.txt`.** 4.994 linhas, 433.839 bytes nos dois; após remover endereços hex, o diff é zero. É a corrida **antiga, pré-bundle**: bundle de 20 shaders na linha 80, 95 linhas `not in the bundle`, 1.090.095 draws pulados por falta de programa até o present 8400, corrida até o frame 8614 / 237 s, filmes em 20,7 s e 41,9 s, músicas até 226 s, fim com app em segundo plano.

**O log_85 NÃO pode ser usado como evidência do estado atual.** O estado atual é o do log_82/84 (bundle 114, zero draws pulados). Usar o log_85 para qualquer conclusão sobre o preto atual seria regredir para um problema já resolvido (shaders faltando). O log_85 serve, no máximo, como referência histórica de como era o sintoma quando os shaders faltavam — e como contraste: naquele tempo os draws eram pulados; hoje não são.

Consequências, registradas para não haver dupla contagem de evidência:

- As estatísticas do frame 3000 citadas no pedido (94.813 draws, 13 pipelines, 2.999 presents, nenhuma sem imagem) vêm **deste mesmo log**, não de uma corrida nova.
- O sintoma NOVO — a imagem aparece e depois some (caso B) — **não está registrado neste log**. O log termina com `graphics suspended` (app em segundo plano), sem erro Vulkan, presents 5.999, `no image 0`, `never drawn 0`.
- **O caso B ainda não tem log próprio.** Todas as hipóteses do caso B abaixo são, portanto, hipóteses de código à espera de um log — não conclusões. A seção 8 diz exatamente qual log falta e como capturá-lo.
- Nada do que segue trata o log_84 como evidência independente. Onde este documento cita "log_82", vale para o log_84 também, porque são o mesmo arquivo.

## 1. Mapa do pipeline: da chamada NVN até a tela

Ordem real do caminho da imagem nesta build. "Layout GENERAL" é o estado permanente das imagens do host (versão 1 do `gfx_vk_tex.c`: toda imagem fica em `GENERAL` após o primeiro uso, ordenada por barreiras de pipeline inteiro).

| # | Etapa | Arquivo / função / linha (v0.1.2) | O que faz |
|---|---|---|---|
| 1 | Jogo grava comandos NVN | `dm/gfx/nvn/hle_nvn.c` — `nvnQueueSubmitCommands`, replay assíncrono (`replay_main`, ~linha 1211) | Comandos do jogo viram registros; submit/present rodam numa thread de replay, não na thread do jogo |
| 2 | Render targets e passes | `dm/android/gfx_vk_exec.c` — `begin_pass()` (~445), `clear_color()` (~516), `clear_ds()` (~531), `pass_commit()` | `SetRenderTargets` vira attachments Vulkan; `loadOp` padrão é `LOAD`; clear de attachment inteiro antes de qualquer draw é dobrado para `loadOp CLEAR` (`folded`) |
| 3 | Descritores, pipelines, draws | `dm/android/gfx_vk_exec.c` — `prepare_draw()`, replay por submissão | Draws executam de verdade (0 pulados no log_82); texturas resolvidas por `vk_tex()` |
| 4 | Texturas | `dm/android/gfx_vk_tex.c` — `vk_tex()` (~254), `vk_tex_prepare()` (~156), `vk_tex_sweep()` (~286), `img_drop()` (~231), `vk_tex_drop_pool()` (~319) | Imagem por chave (pool + offset + formato); primeira utilização transita `UNDEFINED → GENERAL` e nunca mais sai; sweep a cada 300 presents; `img_drop` dá `free()` na struct na hora (só a `VkImage` é liberada de forma diferida) |
| 5 | Janela NVN | `dm/gfx/nvn/hle_nvn.c` — `nvnWindowInitialize` (~1320), `nvnWindowAcquireTexture` (~1364), `nvnWindowSetCrop` (~1331), `QueuePresentTexture` (~1786) | Janela: 3 texturas, 1280×720, formato NVN `0x25` (RGBA8_UNORM, mapa em `gfx_vk_tex.c` ~35); crop 0,0 1280×720; intervalo 1, 60 Hz, modo `game` |
| 6 | Present (fila) | `dm/android/gfx_vk_present.c` — `mtl_present()` (~640), `present_enqueue()` (~615), `present_thread()` (~600), fila `PQ_N = 4` | `mtl_present` só enfileira e retorna; a thread de present faz o trabalho. `present_enqueue` **trava a thread do jogo quando 4 frames estão na fila**. `DM_VK_SYNC_PRESENT=1` apresenta na thread do jogo |
| 7 | Blit + composição | `dm/android/gfx_vk_present.c` — `present_window()` (~513) | Espera o fence do slot, `vkAcquireNextImageKHR` com timeout infinito, limpa o swapchain de preto, faz o blit da textura da janela (aspecto mantido, bordas pretas), roda o `alpha_fix`, desenha o overlay com `LOAD`, apresenta em FIFO com pacing |
| 8 | Swapchain | `dm/android/gfx_vk_present.c` — `swap_make()` (~45), `swap_destroy()` (~33) | Formato preferido `R8G8B8A8_UNORM`; alpha preferido **OPAQUE primeiro**, depois INHERIT; tamanho lido da `ANativeWindow` no momento da criação; 3+ imagens; **só recria se o ponteiro da janela mudar ou se der `OUT_OF_DATE`** |
| 9 | Ciclo de vida | `dm/android/front_android.c` — `on_window_created` (~42), `on_window_destroyed` (~43), `on_pause`/`on_resume` (~83–84), `go_background`/`go_foreground` (~81–82); `dm/gfx/nvn/hle_nvn.c` — `dm_gfx_suspend()` (~1156) | Janela: `ANativeWindow_setBuffersGeometry(w, 0, 0, WINDOW_FORMAT_RGBX_8888)` + `ANativeActivity_setWindowFormat(RGBX)` (~514). Pausa: `dm_gfx_suspend(1)` drena as filas e loga `graphics suspended`. Destruição da janela: `vk_window_lost()` destrói o swapchain |
| 10 | Vídeo | `dm/host/hle_movie.c` (~480), `dm/android/movie_avc.c` — `keep_picture()` | Modo 1, saída NV12 em **buffer de CPU**: o decoder entrega NV12, **o jogo converte para RGB e desenha ele mesmo**; a imagem do vídeo passa pelo mesmo caminho dos itens 2–7. Áudio AAC é independente |

Ponto central do mapa: **o blit lê a textura da janela ao vivo, não uma foto dela.** Entre o `mtl_present` (enfileirar) e o blit (thread de present) não há cópia intermediária. Se a thread de present atrasa e o jogo redesenha a mesma textura nesse intervalo, o blit copia o conteúdo novo — ou o conteúdo limpo, se o jogo já limpou o alvo para o próximo frame. Isso é o que torna o caso B mecanicamente possível (seção 5, hipótese B1).

## 2. O que os logs provam — e o que não provam

Evidência do log_82 (= log_84), com linhas:

- Bundle: `shader bundle …/files/shaders.dmsv: 114 shaders, 1.2 MB` (linha 79); arquivo DMSV conferido (1.247.420 bytes). **Shaders resolvidos.**
- Resumo do frame 3000: 94.813 draws acumulados, 13 pipelines, presents `shown 2.999`, `no image 0`, `never drawn 0` (a linha de replay a cada 600 presents, `gfx_vk_present.c` ~640). **Draws executam, targets existem, textura da janela foi desenhada.**
- Swapchain 2340×1080, formato 37 (`R8G8B8A8_UNORM`); janela 1280×720, formato `0x25`; Adreno 740, Vulkan 1.3, BC/ASTC sim.
- Progresso: `load_img.bin` 2,85 s; filmes 50,9 s e 53,7 s; título/pressstart 55,31 s; `bgm_rail` 60,69 s; corrida até 276 s / frame 6.184; fim com `graphics suspended`, sem crash, sem erro Vulkan.
- Áudio: 200 frames iniciais silenciosos e depois não silenciosos — coerente com jogo que chega ao título e toca BGM; não é evidência de imagem.
- **O que NÃO provam:** draws e presents não provam conteúdo correto. Um frame é contado como `shown` se a textura existe e está em `GENERAL` (`mtl_present`, ~640) — não se o RGB dela tem a cena. É exatamente a regra do pedido, e o código a confirma.

Detalhe novo do mesmo log, que precisa de interpretação correta (linhas 2700–2701):

```
[nvn] frame interval up to frame 3000: >16.7ms 300 / 300 frames, p99 90.74 ms
[nvn] on-screen up to frame 3000: 300 frames, dropped 291 (discarded 0), p99 90.79 ms
```

O código que imprime isso (`hle_nvn.c` ~1519–1527) define `dropped` como **frame exibido por mais tempo que 1,5× o seu hold esperado** — ou seja, frame que chegou atrasado à tela e ficou retido — e `discarded` como frame descartado pelo sistema. Portanto: **291/300 frames atrasados, 0 descartados.** Isso é queda de fluidez por pacing/espera, não é prova de tela preta e não é prova de imagem sumindo. Não confundir "dropped" (atrasado) com o caso B (imagem some). O `discarded 0` também diz que o compositor não estava descartando frames.

## 3. Achados da auditoria (código, não hipótese)

### F1. O acquire tem um timeout silencioso de 1 s — e o jogo continua mesmo assim

`mtl_present_wait()` (`gfx_vk_present.c` ~658): espera `g_pq_done >= tk` com `pthread_cond_timedwait` de 1 s. **Se estourar, retorna do mesmo jeito, sem logar nada.** Quem chama é `nvnWindowAcquireTexture` (`hle_nvn.c` ~1387): depois do timeout, o jogo recebe a textura e desenha nela — mesmo que o present anterior dela ainda esteja na fila da thread de present, esperando o blit. A ordem na GPU é segura (mesma fila, blit submetido antes do próximo frame), mas o conteúdo que o blit vai copiar já pode ter sido limpo ou redesenhado. Este é o único ponto do caminho em que "imagem some" tem um mecanismo concreto e silencioso. A instrumentação da Fase 2 loga esse timeout (hoje ele é invisível).

### F2. A fila de present e o `last` não têm contagem de referência

`present_thread` guarda o último frame em `last` para o redesenho do menu de pausa (`dm_overlay_redraw`), e a fila `g_pq` guarda ponteiros `vkimg_t*` — sem contagem de referência, sem validação. Em paralelo, `img_drop()` (`gfx_vk_tex.c` ~231) dá `free(im)` **na hora**; só a `VkImage` é liberada de forma diferida (`vk_defer_free_image`). Dois caminhos podem soltar a imagem que a fila ainda segura:

- `vk_tex_drop_pool()` (~319): solta **todas** as texturas de um pool finalizado, sem checar uso. Se o jogo finaliza e recria o pool que sustenta as texturas da janela (troca de cena, início de vídeo), o `last` e as entradas da fila passam a apontar para memória liberada. O blit seguinte lê `im->img`, `im->w`, `im->h` de uma struct já liberada: resultado indefinido — preto, lixo ou crash, dependendo do que reutilizou a memória.
- `evict_overlaps()` (~235): solta imagens sobre a mesma memória que uma textura nova vai ocupar, mas só as não consultadas nos últimos 60 presents (`EVICT_KEEP = 60`). A textura da janela é consultada a cada present, então está protegida por esse caminho — o caminho perigoso é o do pool, não o do overlap.

### F3. O swapchain não percebe mudança de tamanho na mesma janela

`swap_make()` (~45): se `g_swap` já existe, retorna 1 imediatamente — só recria se o **ponteiro** da janela mudou ou se um acquire/present retornar `OUT_OF_DATE_KHR`. Se o Android entregar a mesma `ANativeWindow` com outro tamanho (rotação, mudança de configuração, janela redimensionada), `g_sext` fica obsoleto: blit, viewport e scissor continuam calculados sobre o tamanho antigo, e o overlay idem. Isso não apaga a imagem sozinho, mas é um candidato para transições visuais em troca de cena/foco — e, combinado com o redesenho do overlay (`overlay_ready` faz `vkDeviceWaitIdle` quando o tamanho do raster muda), pode travar a thread de present por tempo suficiente para o timeout do F1 estourar.

### F4. Frame descartado silenciosamente quando não há janela

Em `present_thread`, se `swap_make()` falha (janela nula — app em segundo plano, superfície destruída), o frame é simplesmente pulado, mas `g_pq_done` avança do mesmo jeito. O jogo segue como se o frame tivesse sido exibido. Na retomada, o `last` pode ser um frame de antes da pausa. Não há log desse descarte hoje.

### F5. O portão "never drawn" congela, não apaga

Em `mtl_present`: textura nula → `no_img++` e enfileira NULL; textura com layout diferente de `GENERAL` → `undrawn++` e enfileira NULL; a thread de present ignora entradas NULL e **não atualiza o `last`**. Efeito: a tela mantém o frame anterior (congelada), não fica preta. No resumo do frame 3000, ambos são zero — então esse mecanismo não explica o log_82, mas é relevante para o caso B: se num log futuro `no_img`/`undrawn` subirem junto com o sumiço, o culpado está antes do present (textura recriada e ainda não desenhada), não no blit.

### F6. Alpha está duplamente refutado — e há uma correção ao relatório anterior

O relatório anterior já refutava o alpha pelo `alpha_fix`. A auditoria desta build acrescenta um segundo fato: `front_android.c` **sim** fixa o formato da janela nativa — `on_window_created` (~42) chama `ANativeWindow_setBuffersGeometry(w, 0, 0, WINDOW_FORMAT_RGBX_8888)` e o `onCreate` (~514) chama `ANativeActivity_setWindowFormat(RGBX)`. RGBX significa que o compositor **ignora o canal alpha** da superfície. A afirmação anterior de que "o host nunca fixa o formato da janela" valia para o clone, não para esta build. Com `alpha_fix` (força alpha 1 a cada frame, `present_window` ~513, pipeline ~332) **e** RGBX na superfície, o alpha não pode esconder o jogo por dois mecanismos independentes. O preto, se confirmado no RGB pelo frame shot, está no conteúdo da textura da janela.

### F7. O caminho de renderização da janela: o que pode produzir RGB preto

Em `begin_pass()` (`gfx_vk_exec.c` ~445): `loadOp` padrão é `LOAD`; o clear só vira `loadOp CLEAR` quando cobre o attachment inteiro antes de qualquer draw (`clear_color` ~526, `clear_ds` ~540). O scissor é clampado ao pass (`scissor_rect` ~506): scissor fora do pass zera a extensão — draws clipados e clears pulados (extensão zero é testada antes de `vkCmdClearAttachments`), o que **mantém o conteúdo anterior**, não produz preto. Logo, RGB preto permanente exige uma destas situações, em ordem de verificação:

1. O alvo foi limpo para preto e os draws seguintes não produziram nada visível (pipeline, profundidade, textura amostrada preta, condição de renderização).
2. O alvo é uma imagem nova (zeros) que nunca recebeu draws — mas aí o portão `never drawn` a barraria, e ele é zero no log_82; portanto, se o frame shot sair preto, o alvo foi desenhado e o conteúdo desenhado é preto.
3. O blit copiou o alvo errado ou um alvo já limpo para o próximo frame (volta ao F1).
4. As texturas amostradas pela cena estão pretas: upload empacotado perdido (o jogo escreve por CPU e o dirty-tracking não vê a escrita), alias de memória (`[alias] stale read`, `gfx_vk_tex.c` ~220) ou descritor reutilizado apontando para imagem solta (o `vk_tex_view_drop_all` em `img_drop` existe justamente para isso, mas a ordem entre drop e reutilização do descritor é o que o pass dump + `DM_VK_TRACE_PASS` precisam mostrar).

Um detalhe Adreno registrado no próprio código: o corte de command buffer (`DM_VK_CB_DRAWS`, padrão 128, `gfx_vk_exec.c` ~488) existe porque o Adreno confia numa cópia de baixa resolução da profundidade (LRZ) dentro de um command buffer; passes que continuam uma profundidade iniciada em outro command buffer já produziram, noutro jogo, **frames escuros isolados** (o comentário cita "lights went out for single frames", 6–23 em 600 frames). É um precedente documentado de "imagem some por um frame" ligado a profundidade, não a swapchain — candidato específico para o caso B, testável com `DM_VK_CB_DRAWS=0`.

### F8. Vídeo: caminho separado, mesmo destino

Modo 1 / NV12 em buffer de CPU (`hle_movie.c` ~480, `movie_avc.c` `keep_picture()`): o decoder funciona (sem `[RED]` de filme no log_82; `movie_avc.c` ~82–93 lista os erros que apareceriam) e o jogo converte e desenha. A imagem do vídeo, portanto, só aparece se o caminho da janela estiver são — vídeo preto com áudio perfeito é o mesmo sintoma, não um segundo bug. A única interação própria do vídeo com o caso B é que o início de um filme aloca slots, texturas e pools novos — o que pode disparar o F2 (pool finalizado) ou mudar o crop da janela (`WindowCrop` é logado; no log_82 é sempre 0,0 1280×720). Se o sumiço coincidir com o início de um vídeo, o log do caso B precisa mostrar `WindowCrop`, `WindowInitialize` e finalizações de pool ao redor do evento.

### F9. Ciclo de vida: pausa e retomada têm drenagem, mas não invalidação do `last`

`go_background` → `dm_gfx_suspend(1)` → `mtl_drain()` (`gfx_vk_core.c` ~856: `mtl_finish()` + salva o cache de pipelines) e o log `graphics suspended`. A drenagem espera o trabalho em voo, mas **não limpa o `last` nem a fila**. Na retomada, `go_foreground` → `dm_gfx_suspend(0)` e a thread de present continua de onde parou — com o `last` de antes da pausa. Se entre a pausa e a retomada o Android destruiu e recriou a superfície, o `swap_make` recria o swapchain (ponteiro novo), mas o conteúdo do `last` continua sendo o de antes. O fim do log_82 é exatamente esse cenário (app em segundo plano), sem erro — o que mostra que a pausa por si só não quebra nada aqui; o risco é a combinação pausa + recriação de pool/superfície + redesenho.

## 4. Caso A — tela preta permanente: hipóteses ranqueadas

"Permanente" = preto desde o boot/título, com overlay visível, draws e presents saudáveis (o quadro do log_82). O frame shot (`DM_VK_SHOTS=5`, sem reinstalar) continua sendo o passo 1: PPM com arte refutaria tudo abaixo de uma vez (o problema estaria depois da textura); PPM preto confirma que o RGB da textura já é preto e aponta para estas hipóteses, nesta ordem:

| # | Hipótese | Teste que confirma ou refuta | Se confirmar, o fix é |
|---|---|---|---|
| A1 | Os draws da cena escrevem preto: texturas amostradas pretas (upload empacotado perdido, alias de memória, descritor com imagem solta) | Pass dump com `DM_VK_PASSDUMP=1` + `DM_VK_PASSDUMP_SIZE=1280x720`: o pass final da janela sai preto mas os passes anteriores têm conteúdo; ou `DM_VK_TRACE_PASS` no pass da janela mostrando as texturas ligadas | Corrigir o caminho de upload/alias/descritor específico, não o present |
| A2 | Os draws da janela são ineficazes: profundidade (LRZ), condição de renderização, scissor/viewport do jogo | Pass dump + relatório de passes (`vk_pass_report`, a cada 600 presents): pass da janela com draws mas bounding box zero, ou com 0 draws apesar de `SetRenderTargets` | Ajuste no replay do pass (ex.: corte de command buffer, `lrz_touch`), conforme o que o relatório mostrar |
| A3 | O alvo da janela é limpo para preto a cada frame e nada o redesenha de forma visível (ex.: a cena renderiza noutro alvo e a cópia para a janela falha ou copia o alvo errado) | Frame shot preto + pass dump: nenhum pass tem a janela como alvo, ou o pass que a tem como alvo só tem clear | Investigar o `SetRenderTargets`/cópia final do jogo para a janela |
| A4 | Formato/sRGB do blit escurece até o preto | Frame shot com arte + PPM do swapchain (ponto C da instrumentação) preto: a perda está entre a textura e o swapchain | Revisar formato do swapchain vs. da textura (hoje ambos `R8G8B8A8_UNORM`, o que torna A4 improvável — fica em último) |

Não estão na lista, por já refutados: bundle/shaders, draws pulados, apresentação quebrada, alpha, OPAQUE, Turnip, pool zero-copy como causa do preto, push falho.

## 5. Caso B — imagem aparece e depois some: hipóteses ranqueadas

**Status: sem log próprio.** O log_82/log_84 termina em `graphics suspended`, sem o evento. Cada hipótese abaixo diz o que procurar no log que falta; nenhuma é conclusão.

| # | Hipótese | Sinal no log que falta | Teste |
|---|---|---|---|
| B1 | **Timeout de 1 s do `mtl_present_wait` (F1):** a thread de present atrasa (fila cheia, acquire bloqueado, `vkDeviceWaitIdle` do overlay), o acquire retorna mesmo assim, o jogo limpa/redesenha a textura, e o blit atrasado copia o conteúdo limpo → frame preto isolado, depois a imagem "volta" | Intervalo em que o present fica >1 s atrás do acquire; hoje invisível — a instrumentação da Fase 2 loga o timeout | Com o log: se timeouts coincidem com os frames pretos, o fix é no atraso da thread de present (ou no timeout), não no renderizador |
| B2 | **Use-after-free do `last`/fila (F2):** pool da janela finalizado em troca de cena ou início de vídeo; o blit lê struct liberada | `[diag] UAF RISK` da instrumentação, ou, sem ela, finalização de pool seguida de frame preto sem `no_img`/`undrawn` | Referência/geração para as imagens da fila (fix de lifetime, não de renderização) |
| B3 | **LRZ do Adreno (F7):** profundidade obsoleta entre command buffers rejeita draws por um frame | Frames pretos isolados, sem padrão de fila; some com `DM_VK_CB_DRAWS=0` | Ajuste do corte/`lrz_touch` para este jogo |
| B4 | **Swapchain obsoleto/tamanho (F3/F4):** superfície recriada ou redimensionada sem o host perceber; frames descartados silenciosamente na retomada | `swapchain destroyed` / `swap_make` ao redor do evento; `WindowCrop` ou tamanho de janela mudando no log | Detectar mudança de tamanho na mesma janela e recriar o swapchain |
| B5 | **Caminho do vídeo:** início de filme muda crop, texturas ou pools e o primeiro frame após a transição sai preto | Sumiço coincidindo com `movie` aberto / `WindowCrop` / `WindowInitialize` novos | Separar o que muda na transição do filme e tratar só aquilo |

O que diferencia B1 de B2 no log: B1 mostra atraso (timeout) sem finalização de pool; B2 mostra finalização de pool sem atraso necessário. A instrumentação registra os dois.

## 6. Desempenho: 73 ms de frame, 0,73 ms de GPU

O quadro do pedido (frame mediano ~73 ms, GPU ~0,73 ms) e o do log_82 (intervalo >16,7 ms em 300/300 frames, p99 ~90 ms, 291/300 "dropped" = atrasados, seção 2) apontam para o mesmo lugar: **o tempo está em espera, não em trabalho.** A cadeia de espera, em ordem de custo provável:

1. `present_enqueue` trava quando a fila de 4 está cheia — a thread do jogo só anda no ritmo da thread de present.
2. A thread de present espera o fence do slot e o `vkAcquireNextImageKHR` (timeout infinito) da FIFO, mais o `pace_desired` (tempo desejado no futuro, `VK_GOOGLE_display_timing`).
3. Cada submissão espera o fence anterior e varre os pools copiados (`mtl_sub_commit`, `gfx_vk_core.c` ~794: `wait_fence` + `vk_pools_sync`, que faz `memcmp` por blocos de 256 KB sobre até 288 MB varridos por sync — custo de CPU, não de GPU; os blocos alterados são 0–3 por sync, então a cópia em si é pequena e o custo é a varredura).
4. A taxa adaptativa (`perf_android.c`, `STEPS` 60/40/30 fps) **não explica 73 ms**: o maior passo é 33,3 ms. Um frame mediano de 73 ms precisa de espera fora da taxa adaptativa (itens 1–2) — e a taxa adaptativa ainda pode piorar o quadro, porque o trabalho medido inclui esperas e pode derrubar o jogo para 40/30 fps por engano (o código tenta excluir isso quando o custo de GPU é <1,5 ms, `adapt_frame`, mas a exclusão depende da medição do custo, que é o `max(replay, GPU)`).

**Não fazer:** desativar fences, remover sincronização, mudar o pacing, desligar o `pace_desired` ou forçar taxa — sem a causa demonstrada. O teste por `env.txt` que separa pacing de resto continua válido e barato: `DM_VK_PACE=0` (relido a cada 30 presents). Se o frame mediano cair para ~16 ms, o pacing é o culpado; se não cair, o waiter é a fila/acquire (itens 1–2), e aí a instrumentação da Fase 2 mostra onde, com os tempos de `acq_fence`/`submit_pres` por present e o timeout do acquire.

## 7. O que NÃO é causa (lista de refutados, atualizada)

| Hipótese | Veredito | Prova |
|---|---|---|
| Bundle/shaders | Resolvido | 114/114, 0 draws pulados |
| Apresentação quebrada | Refutada | Overlay visível sobre o mesmo swapchain |
| Alpha escondendo o jogo | Refutada 2× | `alpha_fix` a cada frame + superfície RGBX (F6) |
| Patch OPAQUE | Revogado | A build já prefere OPAQUE; a superfície não o oferece; forçar quebraria o swapchain |
| Pool zero-copy | Não é causa | `-4` é forçado por `setenv` (`front_android.c` ~528); blocos sujos 0–768 KB por sync |
| Turnip | Não é fix | Skip antes do driver; host sem `DM_VK_DRIVER`; gargalo é espera |
| Push falho | Refutado | log_82 prova o bundle no celular |
| Perfil como causa do preto | Não sustentada | Jogo boota, chega ao título, áudio e presents saudáveis; heap check nunca feito é risco de estabilidade futura, não de preto |
| "Dropped 291" como imagem sumindo | Interpretação errada | `dropped` = frame atrasado (hold >1,5×), `discarded 0` (seção 2) |
| log_84 como corrida nova | Falso | Diff zero contra o log_82 após remover hex (seção 0) |
| log_85 como estado atual | Falso | É o log_80 pré-bundle (20 shaders, 95 `not in the bundle`); o estado atual é o log_82/84 (seção 0) |

## 8. log.txt pendente — o que falta para o caso B

O caso A pode avançar com os testes sem rebuild já existentes (frame shot, pass dump, `DM_VK_PACE=0`). O caso B **não pode ser fechado sem um log da corrida em que a imagem some**, porque o único log existente termina em pausa, sem o evento. O log necessário é o da seção 2 do `BLACK_SCREEN_DIAGNOSTICS.md` (o que ligar, quando copiar antes de relançar), e precisa conter:

1. A janela de tempo do sumiço: o instante aproximado (ou o número do frame, se o contador de FPS estiver visível) em que a imagem some e, se voltar, quando volta.
2. O trecho do log ao redor desse instante: contadores de replay (`shown`/`no_img`/`undrawn`), `swap_make`/`swapchain destroyed`, `WindowCrop`/`WindowInitialize`, finalizações de pool, `[diag] mtl_present_wait TIMEOUT` e `[diag] UAF RISK` (quando a instrumentação estiver aplicada), e os tempos `acq_fence`/`submit_pres`.
3. O contexto de cena: o sumiço acontece no título, em transição de cena, no início de um vídeo, após pausa/retomada, ou sem padrão? Cada resposta aponta para uma hipótese diferente da seção 5.
4. **Como copiar sem perder:** o `log.txt` vira `log.prev.txt` a cada lançamento (`front_android.c` ~519). Depois da corrida em que a imagem sumir, copiar o `log.txt` **antes** de abrir o jogo de novo; se já tiver aberto uma vez, o log da corrida está em `log.prev.txt`; se abriu duas vezes, foi sobrescrito e a corrida precisa ser refeita.

Sem esse log, a ordem de trabalho é a da seção 11. Nenhum patch de renderização deve entrar antes disso.

## 9. Verificação Rea/binário: a build que roda no S23 é mesmo a fonte auditada?

Pergunta da regra do projeto: antes de qualquer patch, conferir se o binário entregue é a fonte auditada — e não chutar patch sobre uma fonte que não é a do aparelho. Ferramenta tentada: Rea via `npx rea-agents@6.8.0` (skill em `~/workspace/custom-skills/rea/SKILL.md`).

**Bloqueio exato do Rea (registrado, sem inventar resultado):** o CLI 6.8.0 funciona, mas a análise nativa exige um provedor indisponível nesta sessão — `provider_unavailable`, candidatos `ghidra` (não configurado: sem `GHIDRA_INSTALL_DIR`, sem Java), `hopper` (launcher ausente em `/opt/hopper/bin/Hopper`), `ida` (sem `REA_IDA_MCP_CONFIG`) e `kuna` (sem `REA_KUNA_COMMAND`). A skill proíbe instalar software alheio para reparar isso, então não houve descompilação via Rea. O que segue foi obtido com ferramentas normais (`readelf`, `nm`, `strings`, `addr2line`) — e foi suficiente, porque o binário **não está stripado** e tem DWARF.

**O que existe no zip (dois links, não um):**

| Artefato | Tamanho | Data (zip) | Estado |
|---|---|---|---|
| `nxnative/dm/android/out/0100E2F014F46000/libdmhost.so` | 6.655.928 bytes | 28/10 21:46:34 | Não stripado, com DWARF, `BuildID e7a0a8799d650114` |
| `game/0100E2F014F46000_build/android/host/libdmhost.so` | 1.561.688 bytes | 28/10 21:49 | Stripado, `BuildID a75b6810faf94532` |
| `game/NinjaGaiden.apk` → `lib/arm64-v8a/libdmhost.so` | 1.561.688 bytes | 28/10 21:49:58 | **Byte-idêntico ao host/ (SHA-256 `d6d0ed…0cf5`)** |

O log `android_host.log` confirma a sequência: "compiled 137 sources, 0 failed; linked …/android/host/libdmhost.so; stripped …: 1525 KB". Ou seja: **o que roda no S23 é o build host/ de 21:49, não o build out/ de 21:46.** Os `.o` de host/ também são todos de 21:49 — o host foi compilado de novo para empacotar, não copiado de out/.

**O build out/ é, provadamente, a fonte auditada:**

- DWARF aponta para `C:/nx2android/nxnative/dm/android/*.c` (os caminhos Windows dela), com `comp_dir C:/nx2android`.
- Funções presentes: `present_window`, `swap_make`, `swap_destroy`, `mtl_present`, `mtl_present_wait`, `present_enqueue`, `present_thread`, `vk_tex`, `img_drop`, `vk_tex_drop_pool`, `vk_window_lost`.
- Linhas DWARF **idênticas** às da fonte extraída: `swap_make` linha 43, `present_window` linha 485, `mtl_present` linha 622, `alpha_fix` chamado na linha 513 dentro de `present_window` (485–584). A fonte auditada e o build out/ são o mesmo arquivo, linha por linha.
- Strings do build out/ trazem o formato de log **exclusivo da v0.1.2** (`swap_make: win %p (%ux%u), min=%u max=%u trans=%#x alpha=%#x fmt=%d`), que o clone não tem, mais `alpha_fix pipeline failed` e `acq_fence=%.2f ms, submit_pres=%.2f ms`.

**E o build do APK, é o mesmo código?** Quase provado, com uma ressalva honesta:

- A favor: `.rodata` **byte-idêntico** entre out/ e APK (mesmo endereço, mesmo tamanho `0x47f44` — todas as strings, formatos de log e constantes); símbolos dinâmicos idênticos (996 = 996, incluindo `ANativeActivity_onCreate`); mesmo endereço e offset de `.text`; e o log_82, que veio do APK, traz os formatos de log da v0.1.2 (`alpha=0x8`, `acq_fence`), que é prova de comportamento, não só de bytes.
- Contra (ressalva): `.text` difere — 435.666 bytes diferentes no intervalo comum, e o `.text` do APK é 16 bytes maior (`0xd7fa0` contra `0xd7f90`), com `BuildID` diferente. Esse padrão (muitas diferenças pequenas espalhadas, seções de dados idênticas) é o esperado de **dois links do mesmo fonte com otimização guiada por perfil (PGO/BOLT/MLGO, citados no `.comment` do binário) ou ordenação LTO diferente** — não de fonte diferente, que mudaria strings e tamanhos de seção de forma maior. Mas sem descompilação (Rea indisponível) não dá para provar instrução por instrução que a ordem blit → `alpha_fix` → overlay é idêntica no APK.
- Conclusão prática: **a auditoria da fonte vale para o APK, com ressalva de link.** Nenhum achado da auditoria depende de uma linha cuja existência no APK não esteja corroborada (o log_82 confirma o caminho de present do APK em comportamento). Se um dia o frame shot ou o RenderDoc contradisser a fonte, a primeira suspeita passa a ser divergência de link — e aí o passo é descompilar o `present_window` do APK (com Ghidra/Hopper/Kuna, quando disponíveis), não chutar outro patch.
- Também confirmado pelo binário: **nenhuma string `DM_VK_DIAG` ou `swapchain destroyed`** no build entregue — o patch de diagnóstico não está no APK, como esperado.

## 10. Projetos de referência — técnica sim, código direto não

Comparado com precisão, sem copiar código redistribuído. Nenhuma técnica abaixo é um patch pronto para o host dela; cada uma diz o que o outro port faz diferente e se a técnica é reutilizável aqui.

### (a) MK8D-Launcher — present, driver e surface

O ref (`~/workspace/mk8d-launcher-ref/`) é **só o launcher** (`LauncherActivity.java` + `mk2apk.py`); o host daquele projeto não está no ref — o que se sabe dele vem dos comentários do próprio launcher (linhas 52–56) e das chaves que ele escreve. O que ele faz diferente:

| Aspecto | Host MK8D (via launcher) | Host Ninja v0.1.2 | Técnica reutilizável? |
|---|---|---|---|
| Driver | Carrega o ICD do driver diretamente, com fallback para o sistema; seleção por `DM_VK_DRIVER`/`DM_VK_DRIVER_DIR` no `env.txt` | Só `dlopen("libvulkan.so")`; `DM_VK_DRIVER` não é lido | Como técnica, sim — mas só depois das frentes 1 e 3, e exige o patch do host (não basta o launcher). Não resolve preto nem loading |
| Apresentação | `DM_VK_PRESENT_STRETCH` / `DM_VK_PRESENT_FILL` / `DM_VK_PRESENT_720P` (Fit/Fill/Stretch, 720p ou nativa) | Sempre Fit com bordas pretas (`present_window` ~529–531); nenhuma chave `DM_VK_PRESENT_*` é lida | Sim, como técnica de launcher futuro. Inerte sem o suporte no host |
| Preservação de `env.txt` | Reescreve preservando chaves desconhecidas (`DM_LANG`, `DM_VK_PROF`, etc.) | `env_file` lê qualquer `CHAVE=VALOR` para o ambiente; reinstalação sobrescreve tudo (só `settings.txt` é preservado) | Sim — e é pré-requisito de qualquer launcher Ninja, para não apagar `DM_VK_*` |
| Surface | (não visível no ref) | RGBX fixo + swapchain recriado só com ponteiro novo ou `OUT_OF_DATE` | — |

### (b) Black-Android — o espelho de desempenho dela (`~/workspace/black-android-ref/`, `native/vulkan.cpp`)

É o port de outro jogo (BLACK, Xbox) para Android, não um host NVN — o código não é reutilizável diretamente, mas quatro técnicas são, e duas delas tocam exatamente os achados desta auditoria:

1. **Recriar o swapchain quando o tamanho muda — não só quando a janela muda** (`AcquireImage`): ele verifica a cada frame se o `surface_epoch` mudou **e** se `w/h` diferem da extensão atual, e recria. O host Ninja só recria com ponteiro novo ou `OUT_OF_DATE` (achado F3). **Técnica reutilizável e diretamente relevante para o caso B (F3/F4).** Detalhe que o Black-Android ensina junto: `SUBOPTIMAL_KHR` é deixado em paz (recriar a cada frame em tela girada já libertou imagens que a GPU ainda desenhava, num Mali) — ou seja, recriar com critério, nunca em loop.
2. **Acquire com timeout limitado** (`kAcquireTimeout = 500 ms`, 2 tentativas; timeout → retorna falso, sem travar): o host Ninja usa `UINT64_MAX` (infinito) no acquire e 1 s de timeout silencioso no `mtl_present_wait`. **Técnica reutilizável:** um acquire limitado + erro explícito transformaria o travamento silencioso do F1 num evento visível no log.
3. **Present mode por configuração** (FIFO com vsync; `MAILBOX`/`IMMEDIATE` sem vsync): o host Ninja é sempre FIFO + pacing por `display_timing`. **Técnica reutilizável para desempenho, não para o preto** — e só depois de provar que o pacing é o gargalo (teste `DM_VK_PACE=0`).
4. **Render scale** (`RenderScale`, `main.cpp` ~242: `output.height × render_percent / guest_height`, piso 0,1): o jogo é renderizado abaixo da resolução da tela e escalado no present — o fill-rate cai quadraticamente, que é o espelho de desempenho dela ("rodar em qualquer batata"). **Técnica reutilizável para desempenho, não para o preto** — no host Ninja, o equivalente seria renderizar a janela NVN menor (o jogo define 1280×720; mudar isso é decisão do perfil/jogo, não do present) ou escalar no blit (o blit já escala; reduzir a resolução do swapchain é o caminho, com custo de nitidez).
5. **Fences por timeline com fallback** (`PollFences` não bloqueante via `vkGetFenceStatus`, `fenced_` como valor): o host Ninja usa fences binárias com espera bloqueante por slot. **Técnica reutilizável como modelo de espera, não como fix do preto** — trocar espera bloqueante por polling não muda conteúdo, só onde o tempo é gasto.
6. **Alpha:** o Black-Android também prefere OPAQUE e cai para INHERIT (`vulkan.cpp` ~1445) — convergente com o host Ninja. Nada a aprender aqui; confirma que OPAQUE-primeiro é o padrão sensato, não uma peculiaridade.

### (c) xbox-ports-ref — fence/wait + vblank e emissor de shaders como oráculo

O ref tem o `XboxXBERecomp` (runtime) e o `takedawn` (port de Burnout 3, com `android/`). Dois modelos, ambos de outro sistema (Xbox, não Switch) — técnica sim, código não:

1. **Fence como acknowledgement honesto** (`takedawn/src/game/main.c` ~1907: `xbox_Nv2aMirrorFence` espelha o fence que o D3D espera; o runtime o avança como confirmação de tudo que foi submetido): o modelo é "o jogo só anda quando o fence diz que a GPU consumiu". O host Ninja já faz o equivalente funcional (fences por submissão + `mtl_present_wait` por ticket) — a diferença é que no Ninja o wait tem timeout silencioso de 1 s (F1). **Técnica reutilizável:** o princípio "fence honesto, sem timeout silencioso" — se o wait expira, isso é um evento a logar e a tratar, não um detalhe a engolir.
2. **Vblank como relógio do jogo** (`RECOMP_VBLANK=1`, `RECOMP_FLIP_PACING=vblank`, `RECOMP_VBLANK_SYNC=display`; `MAILBOX, not FIFO`: "o título é paced pelo vblank travado no display... com FIFO o presenter ficava em `dequeueBuffer` a maior parte do frame e uma corrida 2× tinha 16% de frames lentos contra 1,5%"): o paralelo com o Ninja é direto — o host Ninja usa FIFO + `pace_desired` por `display_timing`, e o log mostra frames atrasados em massa (291/300). **Técnica reutilizável para o desempenho, depois da prova:** se `DM_VK_PACE=0` provar que o pacing é o gargalo, o modelo a copiar é "pacing pelo vblank do display, sem fila FIFO travando o jogo" — não "desligar o vsync e torcer".
3. **Emissor de shaders como oráculo:** o `xboxrecomp` tem um emissor maduro que traduz shaders do jogo para o backend do host, e ports lançados o usam para validar o que o jogo espera desenhar. Para o Ninja, o análogo já existe e já foi usado: o `dmsh_xlate` (Ryujinx) + o bundle DMSV de 114 shaders, provado entregue e com zero draws pulados. **Como oráculo para o preto atual, não reutilizável:** o problema não é mais shader (não falta nenhum), e um segundo emissor não diria por que um draw que executa sai preto — isso é trabalho do pass dump / RenderDoc, não de tradução. O oráculo só voltaria a ser útil se o pass dump mostrasse um shader específico produzindo preto — aí, comparar a saída do `dmsh_xlate` com a de outro emissor maduro seria o teste.

## 11. Próximos passos executáveis — um de cada vez, cada um com seu critério de prova

Nada de patches hipotéticos em paralelo. A ordem é esta, e cada passo só começa quando o anterior entrega sua prova:

| # | Passo | Como executar | Critério de prova (o que decide) |
|---|---|---|---|
| 1 | **Frame shot** — caso A, sem rebuild | No `env.txt` (sem reinstalar), `DM_VK_SHOTS=5`; abrir o jogo, passar do título, fechar; pegar os `frame_*.ppm` na pasta files | PPM com a arte do jogo → o RGB existe e o problema está **depois** da textura (blit/present) — volta-se à seção 4 com A1–A4 invertidos. PPM preto → o RGB da textura já é preto — ir ao passo 2 |
| 2 | **RenderDoc ou pass dump** — localizar o pass preto | RenderDoc: seção 6 do `BLACK_SCREEN_DIAGNOSTICS.md` (captura no S23, frame preto; para o caso B, o primeiro frame em que a imagem some). Alternativa sem RenderDoc: `DM_VK_PASSDUMP=1` + `DM_VK_PASSDUMP_SIZE=1280x720` no `env.txt` | A captura mostra **qual** pass/target sai preto (ou que a textura 1280×720 já entra preta no blit). Sem isso, nenhum patch é escrito — este é o marco verificável que falta |
| 3 | **Log do caso B** (em paralelo com o passo 2, sem bloquear o caso A) | `DM_VK_DIAG=1` + `DM_VK_DIAG_EVERY=1` + `DM_VK_DIAG_SAMPLE=300` no `env.txt`; na corrida em que a imagem sumir, copiar o `log.txt` **antes** de relançar (se já relançou uma vez, está em `log.prev.txt`; duas vezes, perdido) | O log mostra `TIMEOUT`, `UAF RISK` ou `swapchain destroyed` ao redor do sumiço (hipóteses B1/B2/B4), ou mostra nenhum deles — o que aponta para dentro dos passes (B3) |
| 4 | **Teste de pacing** — desempenho, em paralelo | `DM_VK_PACE=0` no `env.txt` | Frame mediano cai para ~16 ms → pacing é o culpado (e aí o modelo a copiar é o vblank do takedawn, seção 10c). Não cai → o waiter é fila/acquire, e a instrumentação do passo 3 diz onde |
| 5 | **UM patch único** — só se os passos 1–2 apontarem a etapa exata | Diff único, mínimo, sobre a etapa provada (ex.: guarda de lifetime da fila, se B2; detecção de tamanho no swapchain, se B4; ajuste de corte/LRZ, se B3; correção de upload/alias, se A1) — com o `alpha_fix` e o OPAQUE-primeiro intactos, sem recriação contínua de swapchain, sem tocar em outros subsistemas | Teste antes/depois na mesma cena: o sintoma some **e** nenhum erro Vulkan, crash ou regressão de memória aparece, **e** a captura (passo 2) refeita mostra o conteúdo correto no ponto que era preto. Sem os três, o patch é revertido |
| 6 | **Só depois** | Patch do host para Turnip (`DM_VK_DRIVER`) + `DM_VK_PRESENT_*` e, então, o launcher no molde MK8D | Launcher e driver não resolvem preto nem loading; entram quando houver algo para jogar |

O que NÃO entra nesta lista: patch OPAQUE (revogado), remoção do `alpha_fix`, recriação contínua da swapchain, desativação de fences, troca de present mode, render scale e qualquer reescrita do renderizador — todos sem causa demonstrada, e todos proibidos pelas regras dela até que um passo acima os justifique.
