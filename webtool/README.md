# MK-Viral-Assembly Webtool

Interface web local para configurar, iniciar e acompanhar o pipeline MK-Viral-Assembly sem precisar montar manualmente o comando Nextflow.

Para instalar como aplicativo, use o [guia completo para Windows e Ubuntu](../docs/WEBTOOL_INSTALLATION.md) ou o [tutorial em português](../docs/INSTALACAO_WEBTOOL_PT_BR.md). Os instaladores publicados em cada [release](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest) criam automaticamente os ambientes isolados necessários.

## O que esta versão inicial oferece

- seleção entre `Single Analysis` (pasta FASTQ + referência global) e `Mixed Virus Analysis` (samplesheet CSV existente ou criada pela própria WebTool);
- formulário de caminhos para dados brutos, samplesheet, referência, Primer BED, GFF3, metadados, resultados e banco Kraken2;
- presets de vírus para SARS-CoV-2, Dengue, CHIKV, VSR, Oropouche e outros;
- seleção do perfil de execução (Singularity/Apptainer, Docker ou Conda);
- controles para Nextclade, BLAST, Kraken2 e depleção do hospedeiro;
- parâmetros de consenso, qualidade, CPUs e memória;
- prévia do comando Nextflow;
- API restrita ao computador local para iniciar, enfileirar, listar, cancelar e consultar logs das execuções;
- fila FIFO persistente com uma única execução Nextflow ativa por vez e início automático da próxima análise;
- telas iniciais de visão geral, execuções, amostras e resultados.

## Modos de entrada

- **Single Analysis:** informe uma pasta com FASTQs pareados e uma referência FASTA global. Se o Nextclade estiver ativado, o dataset é obrigatório e pode ser informado por um alias do pipeline (por exemplo, `denv4`) ou pelo caminho completo do catálogo. Opcionalmente, informe um Primer BED e uma anotação GFF3. A webtool envia `--input`, `--reference`, `--virus`, `--nextclade_dataset` e, quando preenchidos, `--primer_bed` e `--gff` ao pipeline.
- **Mixed Virus Analysis:** use um samplesheet CSV existente ou crie-o na própria WebTool. Para criar, selecione a pasta-pai que contém as subpastas nomeadas conforme os vírus do catálogo e escolha onde salvar o CSV. O serviço executa `bin/make_samplesheet.py`, usa automaticamente `assets/virus_catalog.tsv` e preenche o campo de entrada com o arquivo gerado. Vírus, referência, GFF3, Primer BED e dataset Nextclade são definidos individualmente pelas colunas `virus`, `reference`, `gff`, `bed_file` e `nextclade_dataset` de cada amostra.

Os arquivos FASTQ não são enviados pelo navegador. A webtool recebe apenas caminhos locais e o serviço executa o Nextflow dentro da instalação local no Windows/WSL ou Ubuntu. Se já houver uma análise em execução, novas submissões ficam em uma fila FIFO persistente e começam automaticamente, uma por vez, quando a anterior termina, falha ou é cancelada.

## Iniciar

Em uma instalação manual no Linux/WSL:

```bash
cd ~/MK-Viral-Assembly/webtool
./start-local.sh
```

Depois, abra `http://localhost:3000` no navegador. Use `Ctrl+C` no terminal para encerrar.

## Instalação do ambiente da interface

Os instaladores Windows e Ubuntu criam automaticamente o ambiente `mkva-webtool`. Em uma instalação manual, recrie-o com:

```bash
conda create -n mkva-webtool -c conda-forge nodejs=22
conda run -n mkva-webtool npm ci
```

O serviço detecta Nextflow pelo `PATH`. Para usar um executável específico:

```bash
MKVA_NEXTFLOW=/caminho/para/nextflow ./start-local.sh
```

## Segurança e limitações desta versão

- API vinculada somente a `127.0.0.1:8787`;
- execução por lista de argumentos, sem interpolação em shell;
- validação de perfis, números e existência dos arquivos de entrada;
- histórico e logs locais em `.local-data/` (não versionados);
- a máquina e o serviço local precisam permanecer ligados durante a análise;
- não há autenticação multiusuário nem envio para nuvem nesta versão local.
