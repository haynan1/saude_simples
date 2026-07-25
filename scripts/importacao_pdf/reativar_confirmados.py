# -*- coding: utf-8 -*-
"""Reativa quem o caderno confirma morando numa casa do território.

Contexto: a importação do CSV do e-SUS trouxe a lista da unidade inteira, e
todos entraram marcados como "fora de área" — não dava para saber quem era da
microárea 13 antes de conferir. O caderno responde exatamente isso.

Escopo deliberadamente estreito: a lista de alvos sai da extração do PDF,
pessoa por pessoa, e NÃO de "todo mundo que tem casa_id". Assim o que muda é
exatamente o que o documento afirma.

ATENÇÃO — este script empurra para 'ativo'. Se você marcou alguém à mão como
mudou-se/óbito DEPOIS da carga, rodar de novo desfaz essa marcação para quem o
caderno lista como morador. Confira a simulação antes de gravar. As pessoas dos
apêndices não são tocadas: elas não estão em `casas` na extração.

Uso:
    python scripts/importacao_pdf/reativar_confirmados.py            # simulação
    python scripts/importacao_pdf/reativar_confirmados.py --gravar   # efetiva
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comum import (  # noqa: E402
    BANCO,
    SAIDA_PADRAO,
    backup,
    conectar,
    confirmar_gravacao,
    encontrar_paciente,
    indexar_pacientes,
    stdout_utf8,
)


def aplicar(conn, dados):
    _, por_documento, por_nome = indexar_pacientes(conn)

    alvos, nao_encontrados = {}, []
    for casa in dados["casas"]:
        for pessoa in casa["pacientes"]:
            nome, linha = encontrar_paciente(pessoa, por_documento, por_nome)
            if not nome:
                continue
            if linha is None:
                nao_encontrados.append((casa["rotulo"], nome))
                continue
            alvos[linha["id"]] = (linha, casa["rotulo"])

    por_status = {}
    for pid, (linha, rotulo) in alvos.items():
        atual = (linha["status"] or "ativo").strip() or "ativo"
        por_status.setdefault(atual, []).append((pid, linha["nome"], rotulo))

    mudar = [pid for status, itens in por_status.items() if status != "ativo"
             for pid, _, _ in itens]
    if mudar:
        conn.executemany(
            "UPDATE pacientes SET status = 'ativo' WHERE id = ?"
            " AND COALESCE(status,'ativo') <> 'ativo'",
            [(pid,) for pid in mudar],
        )
    return alvos, nao_encontrados, por_status, mudar


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracao", default=os.path.join(SAIDA_PADRAO, "extraido.json"))
    ap.add_argument("--banco", default=BANCO)
    ap.add_argument("--gravar", action="store_true", help="efetiva (sem isto, simula)")
    args = ap.parse_args()

    if not os.path.exists(args.extracao):
        raise SystemExit("Extração não encontrada: %s — rode parser_pdf.py antes."
                         % args.extracao)

    dados = json.load(open(args.extracao, encoding="utf-8"))
    if args.gravar:
        backup("antes_reativar_confirmados_pdf", args.banco)

    conn = conectar(args.banco)
    try:
        alvos, nao_encontrados, por_status, mudar = aplicar(conn, dados)

        print("moradores do caderno resolvidos no banco : %d" % len(alvos))
        print("não encontrados (serão criados pela carga): %d" % len(nao_encontrados))
        print()
        for status, itens in sorted(por_status.items()):
            marca = "(sem mudança)" if status == "ativo" else "-> vira ATIVO"
            print("  status atual %-14s %4d %s" % (status, len(itens), marca))
        print()
        print("registros a reativar: %d" % len(mudar))

        confirmar_gravacao(conn, args.gravar)

        print()
        for r in conn.execute("SELECT COALESCE(status,'ativo') s, COUNT(*) n "
                              "FROM pacientes GROUP BY 1 ORDER BY n DESC"):
            print("   %-14s %d" % (r["s"], r["n"]))
        print("   ainda fora de área e sem casa: %d" % conn.execute(
            "SELECT COUNT(*) FROM pacientes WHERE casa_id IS NULL"
            " AND COALESCE(status,'ativo') <> 'ativo'"
        ).fetchone()[0])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
