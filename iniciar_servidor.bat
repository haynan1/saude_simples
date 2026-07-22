@echo off
REM ============================================================
REM  Saude Simples - Sistema de cadastro do ACS
REM  Duplo-clique para iniciar. Na primeira vez, prepara o
REM  ambiente e instala as dependencias automaticamente.
REM ============================================================
title Saude Simples
cd /d "%~dp0"

REM --- 1. Ambiente virtual (cria se nao existir) ---
if not exist "venv\Scripts\python.exe" (
    echo Preparando o ambiente pela primeira vez...
    python -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo.
    echo [ERRO] Nao foi possivel preparar o ambiente virtual.
    echo Instale o Python 3 ^(https://www.python.org/downloads/^) e tente de novo.
    echo.
    pause
    exit /b 1
)

set "PY=venv\Scripts\python.exe"

REM --- 2. Dependencias (instala se faltar alguma) ---
"%PY%" -c "import dotenv, flask, flask_wtf, waitress, cheroot, cryptography, reportlab, PIL" 1>nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias... pode levar alguns minutos ^(so na primeira vez^).
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Falha ao instalar as dependencias.
        echo Verifique a conexao com a internet e tente de novo.
        echo.
        pause
        exit /b 1
    )
)

REM --- 3. Inicia o servidor ---
echo.
echo Iniciando o servidor... Mantenha esta janela aberta enquanto usar o sistema.
echo Para ENCERRAR: feche esta janela ^(ou tecle Ctrl+C^).
echo.
"%PY%" run.py

echo.
echo O servidor foi encerrado. Pode fechar esta janela.
pause
