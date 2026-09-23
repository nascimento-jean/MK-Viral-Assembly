# MK-Viral-Assembly Windows Launcher

Aplicativo Windows autocontido que instala ou detecta o ambiente da WebTool no WSL, inicia os serviços silenciosamente e abre a interface em uma janela do Microsoft Edge no modo aplicativo.

## Comportamento

- detecta distribuições WSL e procura `~/MK-Viral-Assembly`;
- quando necessário, solicita a instalação do WSL 2 e Ubuntu 22.04;
- baixa a release correspondente e cria ambientes isolados para Nextflow e WebTool;
- localiza ambientes Conda sem depender do nome do usuário;
- inicia `webtool/start-local.sh` sem abrir terminal;
- aguarda a API e a interface responderem;
- abre `http://localhost:3000` no Edge sem barra de endereço;
- permanece na área de notificação para reabrir a interface, consultar o log ou parar o serviço iniciado por ele.

## Compilar

No PowerShell do Windows:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\windows-launcher\build.ps1
```

Os artefatos são gerados em `windows-launcher/output/`.

## Diagnóstico sem abrir a interface

```powershell
.\windows-launcher\output\MK-Viral-Assembly.exe --diagnose "$env:TEMP\mkva-diagnostic.json"
```

## Distribuição

`build.ps1` produz um launcher .NET autocontido e `MK-Viral-Assembly-Setup.exe`. O usuário final não precisa instalar o runtime .NET. O provisionamento inicial usa Conda por compatibilidade; Docker e Singularity/Apptainer são opções avançadas.

O instalador não inclui bancos Kraken2 ou BLAST nem dados de referência grandes. Esses recursos são mantidos fora do instalador para evitar downloads e uso de disco desnecessários.
