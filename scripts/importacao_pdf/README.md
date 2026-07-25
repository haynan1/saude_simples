# Importação do caderno de campo (PDF)

Traz para o sistema a **"Lista de todos os dados do pessoal da residência"** —
o caderno da Microárea 13, 181 páginas, escrito pelo próprio agente. O PDF é
digital (tem camada de texto real), então a extração é exata: **não há OCR e
nenhum dígito é adivinhado.**

Estes scripts existem para a carga ser **auditável e reexecutável**. Rodar tudo
de novo sobre o banco atual não muda nada — são idempotentes por construção.

---

## Regra número um

**Nenhum script grava sem `--gravar`.** Sem a flag eles executam tudo dentro de
uma transação e dão `ROLLBACK` no fim, imprimindo exatamente o que fariam.
Confira a simulação, depois grave.

Com `--gravar`, cada script tira um **backup automático** antes de encostar no
banco, pelo mesmo mecanismo do app — o arquivo aparece na tela *Banco*.

---

## Preparo

```bash
pip install -r scripts/importacao_pdf/requirements.txt
```

O PDF é procurado em `temp/LISTA DE TODOS OS DADOS DO PESSOAL DA RESIDENCIA.pdf`.
Outro caminho: `--pdf`.

> **O JSON da extração contém nome, CPF, filiação e condição de saúde de
> centenas de pessoas.** Por isso a saída padrão é `temp/`, que está no
> `.gitignore`. Não mova esse arquivo para dentro do repositório, não anexe em
> issue, não mande por e-mail.

---

## A ordem

```bash
# 1. Extrai o PDF para JSON. Não toca no banco.
python scripts/importacao_pdf/parser_pdf.py

# 2. Confere a extração. Só lê. É aqui que você decide se pode seguir.
python scripts/importacao_pdf/auditar.py

# 3. Carga: casas, quadras e moradores do território.
python scripts/importacao_pdf/aplicar_merge.py            # simula
python scripts/importacao_pdf/aplicar_merge.py --gravar

# 4. Apêndices: quem se mudou e quem faleceu.
python scripts/importacao_pdf/aplicar_apendices.py --gravar

# 5. Reativa quem o caderno confirma morando no território.
python scripts/importacao_pdf/reativar_confirmados.py --gravar
```

O passo 5 é específico do estado em que o banco estava (todos os cadastros
vindos do e-SUS marcados como *fora de área*). Num banco novo ele não faz nada
— e a simulação diz isso antes.

---

## O que cada arquivo faz

| Arquivo | Papel |
|---|---|
| `comum.py` | Normalização, validação de CPF, conversão de data e **a regra única de identidade de paciente**. Os outros scripts importam daqui — foi extraído justamente porque essa regra copiada em três lugares é onde nascem os cadastros duplicados. |
| `parser_pdf.py` | Lê o PDF e devolve JSON. Nunca abre o banco. |
| `auditar.py` | Relatório de conferência. Nunca abre o banco. |
| `aplicar_merge.py` | Casas, quadras e moradores do território. |
| `aplicar_apendices.py` | Quem se mudou (`mudou_se`) e quem faleceu (`obito`). |
| `reativar_confirmados.py` | Devolve para `ativo` quem o caderno confirma no território. |

---

## As decisões que governam a carga

Confirmadas por James em 2026-07-24. Mudá-las é decisão de produto, não de
implementação.

**1. Merge não destrutivo.** Morador que já existe só recebe dado em campo
**vazio**. Nada preenchido é sobrescrito — correção feita à mão depois da
importação do e-SUS vale mais que o documento.

**2. Casa sem endereço não é criada.** As casas 171–180 são só marcador no
caderno: sem endereço, sem contagem, sem morador. O app exige endereço, e
inventar um para satisfazer a validação seria inventar dado.

**3. Condição de saúde só em termo inequívoco.** A marcação sai **apenas** da
observação de saúde escrita pelo agente, nunca do nome do medicamento —
*losartana* não marca hipertensão. E qualquer marca de dúvida no texto
(`CONFIRMAR SE`, `SINTOMAS DE`, `APARENTEMENTE`, `PRÉ-DIABÉTICA`) **cancela a
marcação inteira daquele morador**, inclusive termos certos que estejam na mesma
frase. Isso é deliberado: é melhor faltar marcação para conferir na visita do
que gravar diagnóstico que o agente não afirmou.

**4. Nada do caderno é descartado.** O que o app não tem coluna para guardar —
peso, altura, naturalidade, medicamento de uso contínuo, número da casa
anterior, apelido — vai para `observacao` com rótulo. O texto de saúde original
vai **sempre** inteiro para lá, mesmo quando virou checkbox: assim nenhuma
marcação depende da interpretação da máquina. Etiquetas de trabalho da casa
(`CADASTRO NÃO REALIZADO`, `ABANDONADO`, `LAR VICENTINO`) vão entre colchetes no
fim do `endereco`, já que `casas` não tem campo de observação.

---

## Armadilhas do documento que o parser trata

Cada uma destas corrompia dado antes de ser tratada. Se você mexer no parser,
os testes destas situações estão em `tests/test_scripts_importacao.py` e a
auditoria (`auditar.py`) acusa regressão.

- **Timbre repetido** nas 181 páginas — a linha `Fone: (64) 9244-5685` seria
  lida como um campo.
- **Registros atravessam a quebra de página**; as páginas viram um fluxo único.
- **Valores quebram em várias linhas** — linha sem rótulo é continuação. Mas
  data, CPF, CNS e telefone **nunca** continuam: texto solto depois deles é nota,
  senão `24/07/1949 PREFERIU FICAR NO POSTO DE SAÚDE` virava data de nascimento.
- **`CONTAGEM:` é ambíguo** — dentro de um morador é sexo, fora dele é o tipo do
  imóvel.
- **Rótulos com erro de digitação** (`DATA DE NACIMENTO`, `NOME DA MÂE`), **sem
  os dois-pontos** (`CPF 051.886.521-53`) ou **sem separador nenhum**
  (`DATA DE NASCIMENTO10/03/1993`). Só o tratamento dos dois-pontos recuperou
  53 CPFs: a validação subiu de 91,5% para 99,5%.
- **Rótulo repetido por engano** — o caderno tem `DATA DE NASCIMENTO: 26/07/1972`
  seguido de `DATA DE NASCIMENTO: HIPERTENSO, DIABETICO;`. O segundo não pode
  sobrescrever a data boa.
- **`NOME:` onde era `NOME DA MÃE:`** (casas 83 e 249) — sem tratar, duas mães
  viravam moradoras com a saúde do filho pendurada nelas.
- **Dois apêndices depois da última casa** (`LISTA DE CADA PESSOA QUE SE MUDOU`,
  pág. 168, e `NOMES DOS FALESCIDOS`, pág. 179). Sem reconhecê-los, 72 pessoas
  viravam moradoras ativas do Lar Vicentino. O cabeçalho dos falecidos chegou a
  virar um cadastro chamado *"S dos Falescidos"*, porque o rótulo `NOME` casa
  com o começo da palavra.
- **Casas do fundo** (`CASA-19.5`, `234.5`, `262.5`, `287.5`) entram com o número
  da casa da frente e a marca `(CASA DO FUNDO)` no endereço, para aparecerem
  lado a lado na lista ordenada. O reconhecimento procura `CASA DO FUNDO` sem os
  parênteses justamente para não duplicar a casa se a marca variar.

---

## O que ficou pendente de campo

A carga não resolve, e nem deveria: são perguntas para a visita.

- **2 CPFs com dígito verificador errado** — Sonia Maria de Souza (CASA-282) e
  Benedita de Souza Rodrigues (falecida). Gravados como o caderno traz.
- **2 datas de nascimento inválidas** — Josué Anjos Donato (CASA-166) tem um
  telefone digitado no campo da data; Karlla Cristina (CASA-244) tem `10/06/193`.
  Os dois campos ficaram **vazios**: não se chuta data de nascimento.
- **3 pessoas em duas casas** — Sergio Lisboa (218/219), Delza Celecina (252/272)
  e Jose Carlos da Silva (repetido na 291). Ficou a primeira ocorrência.
- **6 marcações canceladas por dúvida.** Em dois casos —  Jurandir Gonçalves
  (CASA-110) e Benedita Borges Rabelo (CASA-121) — havia certeza misturada com
  suspeita, e a regra cancelou tudo. Hipertensão e asma ficaram sem marcar
  apesar de serem afirmações diretas. **Marcar à mão.**
- **10 casas não criadas** (171–180), à espera dos endereços.

---

## Histórico de execução

| Quando | O quê | Backup gerado |
|---|---|---|
| 2026-07-24 | Carga inicial (casas, quadras, moradores) | `antes_importar_pdf_residencias` |
| 2026-07-24 | Reativação dos 400 confirmados pelo caderno | `antes_reativar_confirmados_pdf` |
| 2026-07-24 | Correção dos apêndices (63 mudanças, 9 óbitos) | `antes_corrigir_apendice_mudou_obito` |
| 2026-07-24 | Normalização da marca das casas do fundo | `antes_normalizar_marca_casa_fundo` |

Estado depois disso: **18 quadras, 285 casas, 702 cadastros** — 604 ativos,
63 mudaram-se, 26 fora de área, 9 óbitos.

Qualquer backup pode ser restaurado pela tela *Banco*.
