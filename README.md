# Saúde Simples

Sistema local de cadastro de quadras, casas e pacientes para uma unidade de saúde, com exportação de relatórios em PDF. Não depende de internet nem de serviços externos — roda inteiramente na máquina onde é instalado.

Interface: **Tailwind CSS 3 + Alpine.js (build CSP)**, tudo vendorizado — zero CDN. Tema claro/escuro, sidebar colapsável e painel de acessibilidade (tamanho de fonte, realce em negrito) persistidos por dispositivo.

## Requisitos

- Python 3.9 ou superior
- Windows, Linux ou macOS

## Instalação (primeira vez nessa máquina)

```bash
# 1. Criar e ativar o ambiente virtual
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/macOS

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. Criar o arquivo de configuração
copy .env.example .env         # Windows
cp .env.example .env           # Linux/macOS
```

Abra o `.env` e defina a `SAUDE_SIMPLES_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Cole o valor gerado em `SAUDE_SIMPLES_SECRET_KEY=` no `.env`. Esse valor não precisa (e não deve) ser o mesmo em outra instalação.

## Rodar o sistema

```bash
python run.py
```

(`python app.py` continua funcionando — delega para o `run.py`. No Windows, o duplo-clique em `iniciar_servidor.bat` prepara o ambiente sozinho e inicia.)

Por padrão abre em `http://127.0.0.1:5001`, **apenas neste computador**. O banco de dados é criado automaticamente no primeiro boot e o terminal mostra os endereços de acesso.

## Rede WiFi local

O padrão é privado (localhost). Para acessar de celulares/computadores na **mesma rede WiFi**:

1. No `.env`, descomente `SAUDE_SIMPLES_COMPARTILHAR_REDE=true`
2. Reinicie o servidor — o IP da máquina é detectado automaticamente e aparece no banner:

```
  Neste computador:      http://localhost:5001
  Outros dispositivos:   http://192.168.1.42:5001
```

Na primeira execução em rede, o Windows pergunta se libera o Python — aceite para **redes privadas**. Se outros dispositivos não acessarem, libere a porta manualmente:

```
netsh advfirewall firewall add rule name="Saude Simples" dir=in action=allow protocol=TCP localport=5001
```

> Este modelo é para **rede local fechada**. Não exponha a porta na internet (sem port-forward no roteador).

## HTTPS na rede local (opcional)

```bash
python gerar_certificado.py
```

Gera um certificado self-signed em `instance/certs/` que inclui `localhost`, `127.0.0.1` e o IP atual da máquina. Com o certificado presente, o `run.py` sobe **automaticamente em HTTPS** (servidor cheroot) e liga cookie `Secure` + HSTS sozinho.

- Se o IP da máquina mudar (DHCP), o certificado é **regenerado automaticamente** no próximo start — o endereço nunca fica "chumbado".
- Endereços extras: `python gerar_certificado.py 192.168.1.50 recepcao.local`
- Self-signed: cada dispositivo aceita o aviso de segurança uma única vez.
- Para voltar ao HTTP, apague `instance/certs/`.

### Primeiro acesso

Na primeira execução (sem senha configurada), o terminal exibe um **código de segurança**:

```
==============================================================
  PRIMEIRO ACESSO — nenhuma senha configurada ainda.

  Código de segurança:  AB7K-3XM2
  ...
==============================================================
```

Abra o sistema no navegador — ele leva direto à tela de configuração inicial. Informe o código e defina a senha de acesso (mínimo 10 caracteres). O código:

- Prova posse da máquina: só quem lê o terminal (ou `instance/setup_token`) consegue definir a senha — estar na mesma rede não basta.
- É de uso único: depois da senha definida, a tela `/setup` é desativada para sempre e o arquivo do código é destruído.
- É comparado em tempo constante e protegido por rate limit (5 tentativas/minuto).

## Esqueci a senha / vou usar numa máquina nova

Mesmo comando dos dois casos:

```bash
python resetar_senha.py
```

Não é preciso saber a senha atual — quem roda esse comando já tem acesso direto à máquina onde os dados ficam, então esse já é o nível de confiança necessário (o mesmo de quem poderia abrir o arquivo `.env`). O script:

1. Pede confirmação antes de qualquer mudança.
2. Pede a nova senha duas vezes, validando o tamanho mínimo.
3. Cria um backup do banco de dados antes de aplicar a mudança.
4. Grava a nova senha.

Depois disso é só fazer login normalmente com a nova senha.

## Trocar a senha já logado

Dentro do sistema, use **Alterar senha** na barra lateral (seção "Conta"). Pede a senha atual + a nova senha — diferente do `resetar_senha.py`, que é pra quando você **não** sabe a senha atual.

## Banco de dados — backup, exportação e importação

Na barra lateral, **Banco de dados** concentra a gestão dos dados:

- **Exportar banco (.db)** — baixa um snapshot consistente de todos os dados (via API de backup do SQLite, seguro mesmo com o servidor em uso). Ideal para levar a outra máquina ou guardar fora do computador.
- **Importar banco** — substitui os dados atuais pelo arquivo .db enviado. O arquivo é validado (assinatura SQLite, integridade, esquema do Saúde Simples), um backup do estado atual é criado antes, e a **senha de acesso atual é mantida** — importar dados de outra máquina nunca tranca você para fora.
- **Criar backup agora** — backup manual sob demanda.
- **Restaurar** — volta o sistema ao estado de qualquer backup listado (com backup do estado atual criado antes; a senha atual também é mantida).

### Backups automáticos

Cópias de segurança em `backups/`, criadas automaticamente:

- Toda vez que o servidor inicia.
- Antes de excluir uma quadra, casa ou paciente.
- Antes de importar ou restaurar um banco.
- Antes de redefinir a senha pelo `resetar_senha.py`.

São mantidos os 50 backups mais recentes; os mais antigos são removidos automaticamente. A restauração também pode ser feita pela tela **Banco de dados**, sem mexer em arquivos.

O banco fica em `instance/database.db`. Instalações antigas (banco na raiz do projeto) são migradas automaticamente no primeiro boot.

## Variáveis de ambiente (`.env`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SAUDE_SIMPLES_SECRET_KEY` | Sim | Chave de sessão. Gere uma por instalação, nunca reaproveite. |
| `SAUDE_SIMPLES_PASSWORD_HASH` | Não | Só para setups automatizados que preferem definir a senha via `.env` em vez de `resetar_senha.py`. Na maioria dos casos, ignore esta variável. |
| `SAUDE_SIMPLES_DEBUG` | Não | `true` usa o servidor de desenvolvimento do Flask; `false` (padrão) usa waitress, recomendado mesmo em uso local. |
| `SAUDE_SIMPLES_COMPARTILHAR_REDE` | Não | `true` abre o acesso para a rede WiFi local (bind `0.0.0.0`). Padrão: só localhost. |
| `SAUDE_SIMPLES_HOST` | Não | Bind explícito (casos avançados). Diferente de localhost também liga o compartilhamento. |
| `SAUDE_SIMPLES_PORT` | Não | Padrão `5001`. |
| `SAUDE_SIMPLES_FORCE_HTTPS` | Não | Gerenciada pelo `run.py` quando há certificado TLS (cookie `Secure` + HSTS). Só defina manualmente com TLS externo. |

O `.env` nunca deve ser commitado — já está no `.gitignore`.

## Estrutura

```
run.py               # entrada do servidor: rede WiFi local + TLS automático
app.py               # rotas, regras de negócio, geração de PDF, CSP/headers
db.py                # banco de dados, senha e backups (sem depender do Flask)
rede_tls.py          # descoberta de IP na LAN + certificado self-signed
gerar_certificado.py # gera/renova o certificado TLS local
iniciar_servidor.bat # bootstrap de duplo-clique no Windows
resetar_senha.py     # ferramenta de recuperação/definição de senha
templates/           # páginas HTML (base.html é o layout mestre)
static/css/          # app.css (componentes/tema escuro) + tailwind.css compilado
static/js/           # alpine-components, csp-events, masks, app, smooth-navigation
static/vendor/       # Alpine.js (build CSP) vendorizado
static/src/          # fonte do Tailwind (para rebuild)
tailwind.config.js   # config do build de CSS
tests/               # suíte de testes (segurança + fluxos) — pytest tests
instance/database.db # banco SQLite (gerado automaticamente, não commitado)
backups/             # cópias de segurança automáticas (não commitado)
```

### Testes

```bash
pip install -r requirements-dev.txt
pytest tests
```

A maior parte da suíte usa o `test_client` do Flask (rápido, sem navegador). Os
testes end-to-end (`tests/test_navegacao_e2e.py`) sobem o servidor de verdade e
dirigem um Chromium real via Playwright — é o que prova a navegação sem recarregar
a página e o diálogo de confirmação. Eles rodam junto com `pytest tests`, mas
precisam do navegador baixado uma vez:

```bash
python -m playwright install chromium
```

Sem o Chromium, esses testes se **pulam** sozinhos (não quebram a suíte). Para
rodar só eles, ou pular todos: `pytest -m e2e` / `pytest -m "not e2e"`.

### Rebuild do CSS (apenas se criar classes novas nos templates)

O `static/css/tailwind.css` já vem compilado — o sistema funciona sem Node. Se você
criar classes Tailwind novas nos templates:

```bash
npm install
npm run build:css
```

## Segurança

- A senha de acesso fica como hash (nunca em texto plano) no banco de dados.
- Login tem limite de 5 tentativas por minuto por IP.
- Sessão expira em 8 horas.
- Todas as rotas, exceto login, exigem autenticação.
- Content-Security-Policy com nonce por resposta: nenhum script/estilo inline
  roda sem autorização do servidor; Alpine.js usa o build CSP (sem `eval`).
- Nenhum recurso externo (CDN, fontes, ícones) — tudo servido localmente.
- `instance/`, `backups/` e `.env` ficam fora do controle de versão.

### Dado sensível em repouso — criptografe o disco

O banco (`instance/database.db`), os backups (`backups/`) e o `.db` exportado
guardam dado pessoal de saúde (CPF, filiação, condições de saúde) **em texto
claro** — como qualquer SQLite. O sistema é uma ferramenta local: a fronteira de
confiança é a própria máquina do agente. Quem tem acesso ao disco tem acesso aos
dados.

Por isso, **habilite a criptografia de disco do sistema operacional** na máquina
onde o Saúde Simples roda:

- **Windows** — BitLocker (Painel de Controle → Criptografia de Unidade de Disco BitLocker).
- **macOS** — FileVault (Ajustes → Privacidade e Segurança → FileVault).
- **Linux** — LUKS (normalmente uma opção na instalação da distribuição).

Sem isso, copiar o arquivo do banco ou uma pasta de backup vaza o território
inteiro. É o único controle que fecha esse risco num deploy local — e é
recomendação de conformidade com a LGPD para dado de saúde.
