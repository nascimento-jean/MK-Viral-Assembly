# Instalação da WebTool do MK-Viral-Assembly

A WebTool é a opção recomendada para profissionais de laboratório e saúde pública com pouca ou nenhuma experiência em Bioinformática. Ela oferece uma interface gráfica para executar localmente o pipeline MK-Viral-Assembly. FASTQs, referências, bancos e resultados permanecem no computador.

Escolha o seu sistema:

- [Windows 10/11](#windows-1011)
- [Ubuntu 2204-ou-2404](#ubuntu-2204-ou-2404)

A instalação por linha de comando para servidores e HPC continua disponível no [README principal](../README.md#requirements).

## Antes de instalar

Recursos recomendados:

- computador x86 de 64 bits;
- 16 GB de RAM ou mais (8 GB é o mínimo para análises pequenas);
- internet durante a preparação inicial e a primeira análise;
- pelo menos 30 GB livres para o aplicativo, ambientes isolados e arquivos de trabalho;
- espaço adicional para FASTQs, resultados e bancos opcionais.

A primeira abertura pode demorar vários minutos, pois o aplicativo baixa a versão correspondente do MK-Viral-Assembly e prepara ambientes isolados com Nextflow, Java, Node.js e Conda.

## Windows 10/11

É necessário Windows 10 versão 2004 ou mais recente, ou Windows 11.

### Instalar

1. Abra a [versão mais recente do MK-Viral-Assembly](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest).
2. Baixe `MK-Viral-Assembly-Setup.exe` e `MK-Viral-Assembly-Setup.exe.sha256`.
3. Opcionalmente, confira o download no PowerShell:

   ```powershell
   cd $HOME\Downloads
   (Get-FileHash .\MK-Viral-Assembly-Setup.exe -Algorithm SHA256).Hash.ToLower()
   Get-Content .\MK-Viral-Assembly-Setup.exe.sha256
   ```

   Os dois códigos devem ser idênticos.

4. Dê duplo clique em `MK-Viral-Assembly-Setup.exe` e conclua a instalação.
5. Mantenha marcada a opção **Open MK-Viral-Assembly**.
6. Na primeira abertura, aprove a solicitação de administrador somente se for necessário ativar o WSL 2 e o Ubuntu.
7. Se o Windows solicitar reinicialização, reinicie o computador e abra **MK-Viral-Assembly** pelo menu Iniciar. A preparação continuará automaticamente.
8. Aguarde o término da janela de preparação. Em seguida, a WebTool será aberta como um aplicativo.

O instalador ainda não possui assinatura digital. O Windows SmartScreen pode mostrar **Editor desconhecido**. Confira o SHA-256, selecione **Mais informações** e depois **Executar assim mesmo**.

O inicializador do Windows instala WSL 2 e Ubuntu somente quando necessário. Ele cria o projeto e ambientes isolados dentro do Ubuntu e não substitui uma instalação Conda já existente.

### Diagnóstico no Windows

O log fica em:

```text
%LOCALAPPDATA%\MK-Viral-Assembly\launcher.log
```

Use o ícone da bandeja para reabrir a interface ou visualizar o log.

## Ubuntu 22.04 ou 24.04

O pacote gráfico é compatível com Ubuntu 22.04 e 24.04 em computadores x86-64/AMD64.

### Instalar pela Central de Aplicativos

1. Abra a [versão mais recente do MK-Viral-Assembly](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest).
2. Baixe `MK-Viral-Assembly-WebTool_1.2.0_amd64.deb` e o arquivo `.sha256` correspondente.
3. Abra o arquivo `.deb` com a **Central de Aplicativos** ou **Instalação de software**.
4. Clique em **Instalar** e informe a senha do Ubuntu.
5. Abra o menu de aplicativos, procure **MK-Viral-Assembly** e execute-o.
6. Clique em **Continuar** na janela da primeira instalação e aguarde a preparação.

### Instalar pelo terminal

Se a Central de Aplicativos não abrir o pacote, execute:

```bash
cd ~/Downloads
sha256sum -c MK-Viral-Assembly-WebTool_1.2.0_amd64.deb.sha256
sudo apt install ./MK-Viral-Assembly-WebTool_1.2.0_amd64.deb
```

Depois, abra **MK-Viral-Assembly** pelo menu de aplicativos. O comando `apt install ./...` também instala as pequenas dependências de sistema necessárias ao inicializador.

O pacote instala somente o inicializador, o ícone e o script de preparação nos diretórios do sistema. Na primeira abertura, o aplicativo cria o ambiente isolado dentro da pasta pessoal:

```text
~/.local/share/mk-viral-assembly/
├── source/
├── miniforge3/
└── envs/
```

Os logs ficam em:

```text
~/.local/state/mk-viral-assembly/
```

### Diagnóstico no Ubuntu

Execute no terminal:

```bash
mk-viral-assembly --diagnose
mk-viral-assembly --stop
```

O primeiro comando mostra os caminhos instalados e informa se os serviços locais estão prontos. O segundo encerra o serviço local da WebTool.

## Executar uma análise

1. Abra **MK-Viral-Assembly**.
2. Use **Single Analysis** para um vírus/referência ou **Mixed Virus Analysis** para um samplesheet com vários vírus.
3. Use os botões de pasta e arquivo para selecionar FASTQs, referência FASTA, arquivos opcionais GFF3/BED de primers e a pasta de resultados.
4. Marque as análises opcionais desejadas.
5. Clique em **Iniciar análise** e mantenha o computador e o aplicativo ligados até a conclusão.
6. Abra o dashboard e o relatório MultiQC gerados na pasta de resultados.

## Bancos Kraken2, BLAST e Nextclade

- **Kraken2:** o banco não é baixado automaticamente. Baixe ou prepare separadamente um banco compatível com Kraken2 e indique essa pasta na WebTool.
- **BLAST:** ao ativar **Identificação por BLAST**, o pipeline baixa e monta automaticamente o banco RefSeq Viral na primeira utilização. Ele fica salvo dentro do projeto instalado e é reutilizado nas análises seguintes. Por padrão, a idade do banco é verificada a cada execução e ele é reconstruído após sete dias.
- **Nextclade:** os datasets necessários são obtidos conforme o dataset/vírus selecionado.

A primeira análise com BLAST ou Nextclade pode demorar mais e precisa de internet.

## Dados, privacidade e desinstalação

A WebTool escuta somente em `127.0.0.1`. Ela repassa caminhos locais ao Nextflow e não envia FASTQs, referências ou resultados para a internet.

A desinstalação do inicializador do Windows ou do pacote Ubuntu preserva os dados do aplicativo, o histórico, bancos baixados e resultados para evitar perda acidental de dados científicos. Faça backup dos resultados importantes e apague essas pastas manualmente somente quando tiver certeza de que não precisa mais delas.

Para remover o inicializador no Ubuntu:

```bash
sudo apt remove mk-viral-assembly-webtool
```

## Solução de problemas

- **O Windows pede reinicialização:** reinicie e abra o aplicativo novamente.
- **A preparação inicial falha:** confirme a internet e o espaço livre e reabra o aplicativo. As etapas concluídas são reaproveitadas.
- **Proxy ou firewall institucional:** libere GitHub, conda-forge, Bioconda, NCBI e os registros usados pelo perfil escolhido.
- **A janela de seleção aparece atrás do aplicativo:** atualize para a versão mais recente. Os inicializadores atuais solicitam que os diálogos nativos sejam exibidos em primeiro plano.
- **O Ubuntu informa arquitetura incompatível:** o pacote atual é para AMD64/x86-64, não ARM64.
- **A WebTool não abre no Ubuntu:** execute `mk-viral-assembly --diagnose` e consulte `~/.local/state/mk-viral-assembly/launcher.log` e `webtool-service.log`.
- **Falta de espaço:** FASTQs, diretórios de trabalho do Nextflow e bancos geralmente ocupam a maior parte do disco.
