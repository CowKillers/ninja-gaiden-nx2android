#!/usr/bin/env python3
r"""Loop de shaders do nx2android (Ninja Gaiden Sigma e qualquer jogo experimental).

O que ele faz, em cada ciclo:
  1. Roda o port COM --install. Isso e o que puxa os shaders capturados do
     celular (pull_captures, em porter/pipeline.py) ANTES de traduzir:
     celular:/sdcard/Android/data/<package>/files/captured_shaders/*.bin
       -> <pasta do jogo>/<title>_build/android/captured_shaders/
     Depois o shader_vk.py --capture traduz esses capturados junto com os
     shaders achados nos arquivos do jogo (shader_split.py) e remonta o
     shaders.dmsv, que vai no DATA PACK (nao no APK: o APK e so o host).
     O port --install instala APK + data pack, entao o bundle novo chega
     ao celular no mesmo comando.
  2. Conta quantos shaders tem no bundle novo (cabecalho DMSV) e quantos
     .bin capturados existem, e compara com o ciclo anterior.
  3. Para quando um ciclo inteiro de jogo nao trouxer nenhum shader novo:
     ai o bundle esta estavel para tudo que ja foi jogado.

O que ele NAO faz (limite honesto, lido no codigo do projeto):
  - Nao inventa shader do zero. Um shader que o jogo gera em runtime so
    existe quando o jogo roda e o desenha: o host o salva em
    captured_shaders/ (gfx_vk_shader.c, vk_shader_missing) e o draw e
    descartado naquela vez. Traduzir "todos do zero" sem jogar so cobre
    os shaders que estao nos arquivos do jogo -- e o shader_split.py ja
    faz varredura completa desses (nao depende de nome de arquivo).
  - Nao usa RenderDoc para recuperar shader faltando: o draw descartado
    retorna ANTES de virar pipeline Vulkan (gfx_vk_exec.c), entao uma
    captura RenderDoc (camada Vulkan) nunca ve esse shader. RenderDoc
    so serve para conferir o que JA esta desenhando, nao para achar o
    que foi descartado. A captura certa e a do proprio host, em
    captured_shaders/.
  - Nao joga sozinho. Entre um ciclo e outro alguem precisa jogar ate
    areas/cenas novas, senao nao ha shader novo para capturar. O script
    pausa e espera voce jogar e apertar Enter.

Uso (PowerShell, na pasta do nx2android):
  python shader_loop.py --game C:\nx2android\game --keys C:\nx2android\keys\prod.keys
  python shader_loop.py --game C:\nx2android\game --keys C:\nx2android\keys\prod.keys --from-scratch --cycles 6
  python shader_loop.py --game C:\nx2android\game --keys C:\nx2android\keys\prod.keys --porter "C:\nx2android\nx2android.exe"

Opcoes:
  --from-scratch  apaga shaders.dmsv.key e shader/pkg.key antes do 1o
                  ciclo, forcando split + traducao completos (do zero),
                  SEM apagar captured_shaders/ (apagar isso perderia
                  tudo que ja foi capturado).
  --cycles N      maximo de ciclos (padrao 6).
  --no-install    NAO recomendado: sem --install o porter nao puxa as
                  capturas do celular e o bundle nao muda. So use para
                  testar a traducao sem celular conectado.
"""
import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

TITLE_ID = "0100E2F014F46000"
PACKAGE = "org.nx2a.t0100e2f014f46000"


def dmsv_count(path: Path) -> int | None:
    """Conta shaders no shaders.dmsv: 'DMSV' + u32 versao + u32 count."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) < 12 or head[:4] != b"DMSV":
            return None
        _ver, count = struct.unpack_from("<II", head, 4)
        return count
    except OSError:
        return None


def captured_count(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.glob("*.bin")
               if re.fullmatch(r"[0-9a-f]{16}\.bin", p.name))


def shaders_log_line(logs: Path) -> str:
    log = logs / "android_shaders.log"
    if not log.is_file():
        return "(sem android_shaders.log)"
    txt = log.read_text(errors="replace")
    m = re.findall(r"^.*of .* shaders.*$", txt, re.M)
    return m[-1].strip() if m else "(linha de contagem nao encontrada)"


def run_port(porter: list[str], game: Path, keys: Path, install: bool,
             log_file: Path) -> int:
    cmd = porter + ["-m", "porter", "port", str(game), "-k", str(keys),
                    "--experimental"]
    if install:
        cmd.append("--install")
    print(f"\n$ {' '.join(cmd)}", flush=True)
    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    print(f"port terminou com codigo {proc.returncode} "
          f"(saida completa em {log_file})", flush=True)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", default=r"C:\nx2android\game")
    ap.add_argument("--keys", default=r"C:\nx2android\keys\prod.keys")
    ap.add_argument("--porter", default="nx2android.exe",
                    help="nx2android.exe do bundle (ou 'python -m porter' do repo)")
    ap.add_argument("--title-id", default=TITLE_ID)
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--from-scratch", action="store_true")
    ap.add_argument("--no-install", action="store_true",
                    help="NAO recomendado: sem --install nao puxa capturas")
    a = ap.parse_args()

    game = Path(a.game)
    keys = Path(a.keys)
    build = game / f"{a.title_id}_build"
    android = build / "android"
    logs = build / "logs"
    if not game.is_dir():
        print(f"ERRO: pasta do jogo nao existe: {game}")
        return 2
    if not keys.is_file():
        print(f"ERRO: prod.keys nao encontrado: {keys}")
        return 2

    porter = a.porter.split() if isinstance(a.porter, str) else a.porter
    if a.from_scratch:
        for kf in (android / "shaders.dmsv.key", build / "shader" / "pkg.key"):
            if kf.is_file():
                kf.unlink()
                print(f"from-scratch: apagado {kf} (rebuild forcado)")

    prev_bundle = dmsv_count(android / "shaders.dmsv")
    prev_cap = captured_count(android / "captured_shaders")
    print(f"Inicio: bundle={prev_bundle} shaders, "
          f"capturados={prev_cap} arquivos")
    print(f"Celular (origem das capturas): "
          f"/sdcard/Android/data/{PACKAGE}/files/captured_shaders/")

    for cycle in range(1, a.cycles + 1):
        print(f"\n===== CICLO {cycle}/{a.cycles} =====")
        rc = run_port(porter, game, keys, install=not a.no_install,
                      log_file=Path(f"shader_loop_ciclo_{cycle}.log"))
        if rc != 0:
            print("Port falhou. Veja o log do ciclo e o log do porter em "
                  f"{logs} antes de rodar de novo.")
            return rc
        bundle = dmsv_count(android / "shaders.dmsv")
        cap = captured_count(android / "captured_shaders")
        print(f"Resultado: bundle={bundle} shaders "
              f"(antes: {prev_bundle}), capturados={cap} arquivos "
              f"(antes: {prev_cap})")
        print(f"Traducao: {shaders_log_line(logs)}")
        new_cap = cap - prev_cap
        if cycle > 1 and new_cap == 0 and bundle == prev_bundle:
            print("\nESTAVEL: nenhum shader novo neste ciclo. O bundle ja "
                  "cobre tudo que foi jogado ate aqui.")
            print("Se uma area nova ainda aparecer sem imagem, jogue ate "
                  "ela e rode mais um ciclo: so ai o shader dela existe "
                  "para ser capturado.")
            return 0
        prev_bundle, prev_cap = bundle, cap
        if cycle == a.cycles:
            break
        print("\nAgora JOGUE no celular ate areas/cenas novas (menu, "
              "dificuldade, fases). O host vai salvar qualquer shader "
              "novo em captured_shaders/ no celular.")
        input("Quando terminar de jogar, aperte Enter para o proximo "
              "ciclo (o port vai puxar as capturas e remontar o bundle)... ")

    print("\nFim dos ciclos. Se ainda faltar imagem em alguma cena, jogue "
          "ate ela e rode o script de novo: cada ciclo so aprende os "
          "shaders das cenas ja jogadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
