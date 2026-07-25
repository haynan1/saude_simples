# -*- coding: utf-8 -*-
"""Confere a extração ANTES de qualquer gravação. Só lê — não toca no banco.

Existe porque carga de cadastro de saúde não se faz no escuro: este relatório é
o que separa "o parser leu 682 pessoas" de "o parser leu as pessoas certas".
Ele expõe o que o caderno tem de errado (CPF que não fecha, data ilegível,
pessoa em duas casas) para a decisão ser de quem conhece o território.

Uso:
    python scripts/importacao_pdf/auditar.py
    python scripts/importacao_pdf/auditar.py --extracao temp/extraido.json
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comum import (  # noqa: E402
    SAIDA_PADRAO,
    cpf_valido,
    data_iso,
    digitos,
    norm,
    stdout_utf8,
)


def titulo(texto):
    print()
    print("=" * 74)
    print(texto)
    print("=" * 74)


def auditar(dados):
    casas = dados["casas"]
    apendice = dados.get("apendice", {"mudou_se": [], "obito": []})
    pacientes = [(c, p) for c in casas for p in c["pacientes"]]

    titulo("1. COBERTURA")
    print("quadras: %d | casas: %d | moradores: %d"
          % (len({c["quadra"] for c in casas}), len(casas), len(pacientes)))
    print("apêndice: %d se mudaram, %d falecidos"
          % (len(apendice["mudou_se"]), len(apendice["obito"])))
    numeros = [c["numero"] for c in casas]
    print("casas numeradas de %d a %d" % (min(numeros), max(numeros)))
    faltando = sorted(set(range(min(numeros), max(numeros) + 1)) - set(numeros))
    print("números ausentes na sequência: %s" % (faltando or "nenhum"))
    repetidos = sorted(n for n, q in collections.Counter(numeros).items() if q > 1)
    print("números repetidos (casas do fundo): %s" % (repetidos or "nenhum"))
    sem_endereco = [c["rotulo"] for c in casas if not c["endereco"]]
    print("casas SEM endereço: %d -> %s" % (len(sem_endereco), sem_endereco[:12]))
    print("casas SEM morador: %d" % sum(1 for c in casas if not c["pacientes"]))

    titulo("2. PREENCHIMENTO DOS MORADORES")
    for campo in ("cpf", "cns", "data_nascimento", "telefone", "sexo",
                  "nome_mae", "nome_pai", "saude", "medicamentos"):
        n = sum(1 for _, p in pacientes if p.get(campo))
        print("  %-16s %4d  (%5.1f%%)   vazio: %d"
              % (campo, n, 100.0 * n / max(len(pacientes), 1), len(pacientes) - n))

    titulo("3. VALIDAÇÃO DE CPF (dígito verificador)")
    validos, invalidos, so_cns, sem_documento = 0, [], [], 0
    for casa, p in pacientes:
        cpf, cns = p.get("cpf", ""), p.get("cns", "")
        if cpf:
            if cpf_valido(cpf):
                validos += 1
            else:
                invalidos.append((casa["rotulo"], p["nome"], cpf, p["pagina"]))
        elif cns:
            so_cns.append((casa["rotulo"], p["nome"], cns))
        else:
            sem_documento += 1
    print("CPF válido ........... %d" % validos)
    print("CPF INVÁLIDO ......... %d" % len(invalidos))
    for r in invalidos:
        print("   %-12s %-42s %-20s pág.%d" % r)
    print("só CNS (sem CPF) ..... %d" % len(so_cns))
    print("sem documento nenhum . %d" % sem_documento)

    titulo("4. VALIDAÇÃO DE DATA DE NASCIMENTO")
    ruins, idades = [], []
    for casa, p in pacientes:
        valor = p.get("data_nascimento", "")
        if not valor:
            continue
        iso = data_iso(valor)
        if not iso:
            ruins.append((casa["rotulo"], p["nome"], valor, p["pagina"]))
        else:
            idades.append((2026 - int(iso[:4]), p["nome"], valor))
    print("datas ilegíveis/absurdas: %d" % len(ruins))
    for r in ruins:
        print("   %-12s %-42s %-24s pág.%d" % r)
    if idades:
        idades.sort()
        print("faixa etária: %d a %d anos" % (idades[0][0], idades[-1][0]))

    titulo("5. DUPLICIDADES DENTRO DO CADERNO")
    por_cpf = collections.defaultdict(list)
    for casa, p in pacientes:
        if len(digitos(p.get("cpf", ""))) == 11:
            por_cpf[digitos(p["cpf"])].append((casa["rotulo"], p["nome"]))
    dups = {k: v for k, v in por_cpf.items() if len(v) > 1}
    print("mesmo CPF em mais de um registro: %d" % len(dups))
    for k, v in list(dups.items())[:15]:
        print("   %s -> %s" % (k, v))

    por_nome = collections.defaultdict(list)
    for casa, p in pacientes:
        por_nome[(norm(p["nome"]), p.get("data_nascimento", ""))].append(casa["rotulo"])
    dupn = {k: v for k, v in por_nome.items() if len(v) > 1}
    print("mesmo nome + nascimento em mais de uma casa: %d" % len(dupn))
    for k, v in list(dupn.items())[:15]:
        print("   %-45s %-12s -> %s" % (k[0][:45], k[1], v))

    titulo("6. TIPO DE IMÓVEL (CONTAGEM da casa)")
    for valor, n in collections.Counter(
        (c["contagem"] or "(vazio)")[:70] for c in casas
    ).most_common():
        print("  %4d  %s" % (n, valor))

    titulo("7. APÊNDICES")
    sem_casa = [p["nome"] for p in apendice["mudou_se"] if not p.get("casa_anterior")]
    print("se mudaram sem casa anterior indicada: %d %s" % (len(sem_casa), sem_casa[:6]))
    print("falecidos:")
    for p in apendice["obito"]:
        print("   %-44s %s" % (p["nome"][:44], p.get("data_nascimento", "")))

    titulo("8. AVISOS DO PARSER (%d)" % len(dados["avisos"]))
    for tipo, n in collections.Counter(a[1] for a in dados["avisos"]).most_common():
        print("  %4d  %s" % (n, tipo))
    soltas = [a for a in dados["avisos"] if a[1] == "linha solta"]
    if soltas:
        print("\n  linhas soltas (não entraram em campo nenhum):")
        for pagina, _, linha in soltas[:20]:
            print("    pág.%-5d %s" % (pagina, linha[:84]))


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracao", default=os.path.join(SAIDA_PADRAO, "extraido.json"))
    args = ap.parse_args()

    if not os.path.exists(args.extracao):
        raise SystemExit(
            "Extração não encontrada: %s\nRode antes: python scripts/importacao_pdf/parser_pdf.py"
            % args.extracao
        )
    auditar(json.load(open(args.extracao, encoding="utf-8")))


if __name__ == "__main__":
    main()
