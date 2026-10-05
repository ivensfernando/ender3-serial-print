# Como o Claude controla a impressora a partir do PC

Documento escrito em 2026-10-05, depois de uma semana imprimindo peças do dispensador (corpo, tambor,
tampa, boné, bigodes, pinos) em uma Ender-3 V3 SE ligada por USB. Explica como funciona, o que deu errado
e se dá para fazer um programa de desktop. O passo a passo curto continua no `README.md`.

## 1. A ideia em uma frase

A impressora não é "controlada por um programa mágico": o cabo USB-C dela aparece no Linux como uma **porta
serial** (`/dev/ttyUSB0`), e o firmware Marlin dentro dela entende **G-code em texto**. Quem manda uma linha
de texto e espera a resposta `ok` está, na prática, operando a impressora.

## 2. O caminho completo, do desenho à peça

```
OpenSCAD (.scad)  ->  STL  ->  CuraEngine (slice_cura.py)  ->  G-code  ->  send_gcode.py  ->  porta serial  ->  Marlin
```

| Etapa | Ferramenta | O que faz |
|---|---|---|
| Modelar | OpenSCAD, `hardware/lollipop-cat-drum/*.scad` | Peças paramétricas, uma por `part="..."`, já na posição de impressão |
| Conferir | `check_overhang.py` | Soma a área que ficaria no ar (precisaria de suporte) |
| Fatiar | `slice_cura.py` (usa o CuraEngine 4.13) | Troca o STL por G-code, com o início/fim certos para esta impressora |
| Enviar | `send_gcode.py` | Manda o G-code linha por linha pela serial |
| Executar | Marlin 1.0.6 na impressora | Aquece, move, extruda |

## 3. A conexão serial

- A porta USB-C da impressora é uma ponte CH340 (`1a86:7523`), **115200 baud**. Ela não é armazenamento:
  `M20`/`M21` respondem "No SD card".
- Abrir a porta não reinicia a placa, então os eixos continuam "homeados".
- O usuário precisa estar no grupo `dialout`. Numa sessão nova, rodo tudo com `sg dialout -c '...'`.
- O protocolo é simples: escrevo uma linha, a impressora responde `ok` quando coloca o comando na fila.
  Enquanto aquece, ela manda `busy` ou `T:...` para dizer que está viva.

### Comandos que uso só para ler (não movem nada)

| Comando | Resposta |
|---|---|
| `M115` | Versão do firmware e modelo |
| `M105` | Temperatura do bico e da mesa, e os alvos |
| `M114` | Posição X Y Z E atual |
| `M27` | "Not SD printing" quando está parada |
| `M119` | Estado dos sensores de fim de curso e da sonda |
| `M401` + `M119` + `M402` + `M119` | Teste da sonda: aberta com o pino abaixado, acionada recolhida |
| `M420 V`, `M851` | Malha de nivelamento e offset Z (-1,36) |

## 4. Imprimir: `send_gcode.py`

Faz um laço simples: lê a linha, escreve, espera `ok`. Regras que ele já tem:

- **Parar**: criar o arquivo `/tmp/print.stop`. Ele desliga bico, mesa e ventilador e sai.
- **Qualquer linha com `error`, `kill` ou `halt`** na resposta também desliga tudo e sai.
- **Comando ao vivo**: escrever em `/tmp/print.cmd`; as linhas são enviadas entre duas linhas da peça.
  É assim que mudo a temperatura no meio da impressão, ou faço uma **pausa**.
- **Progresso**: `/tmp/print.log` mostra `linhas feitas / total`; `/tmp/print.idx` guarda a linha atual.
- **Timeout**: 15 minutos sem receber nada da impressora aborta (ela pode estar aquecendo, por isso é longo).

Comando padrão (em segundo plano, para não prender o terminal):

```bash
sg dialout -c "nohup python3 hardware/tools/ender3_serial_print/send_gcode.py ARQUIVO.gcode >/tmp/print.out 2>&1 &"
tail /tmp/print.log
```

### Pausar por 1 minuto (o que fiz no boné)

Escrevo isto em `/tmp/print.cmd`. O `G91` liga o modo relativo, então não preciso saber onde a cabeça está:

```
G91
G1 E-3 F1800     ; retrai o filamento para não pingar
G1 Z20 F600      ; sobe o bico 20 mm
M400
G4 S60           ; espera 60 s
G1 Z-20 F600     ; desce
G1 E3 F1800      ; devolve o filamento
G90              ; volta ao modo absoluto
```

O `G90` só pode vir **depois** de descer e devolver o filamento. Se vier antes, a impressão continua 20 mm
no ar.

### Mover à mão (a lubrificação)

`lube.py` (na pasta temporária da sessão) manda movimentos soltos, esperando `ok` e depois `M400` (que só
responde quando o movimento acabou). Passos: subir o bico, `G28 X Y`, idas e voltas em X e em Y, diagonais, Z devagar,
estacionar. Eu rehomeio X e Y primeiro, porque você mexeu nos eixos com os motores soltos.

## 5. O que deu errado, para não repetir

1. **Nunca abrir a porta enquanto a impressão roda.** Eu consultei `M105` durante a fatia de teste. As duas
   leituras se bateram, o `send_gcode.py` caiu com `multiple access on port` aos 39%. Para ver o andamento,
   só ler `/tmp/print.log`.
2. **`G28` completo com peça no prato.** A sonda CR-Touch mede o Z no centro do prato. Com peça lá,
   o bico bate. Uso `G28 X Y` e retomo a peça sem sonda.
3. **Motores soltos no fim.** O G-code termina com `M84 X Y E`; a cabeça desliza. Retomar uma impressão
   exige `G28 X Y` e subir antes.
4. **`pkill -f send_gcode` mata o próprio shell** (o padrão está na linha de comando). Usar o PID ou o arquivo de parada.
5. **Contar processos com `grep` conta o próprio comando.** Usar `grep -v "bash -c" | grep -v "sg dialout"`.
6. **Disco cheio.** O log da sessão gráfica (`/tmp/tmp.*`) chegou a 81 GB porque o cliente do PIA VPN repete
   um erro de IPC sem parar. Com o disco cheio, o log da impressão não grava e o envio cai.
7. **Material errado.** ABS fecha furos e encaixes uns 1 mm; PLA fecha pouco. O encaixe do rabo e o furo do
   corpo mostraram isso. Teste de encaixe com o **mesmo** material da peça final.
8. **Tempo estimado.** O `;TIME:` no começo do G-code não vale; o certo é o último `;TIME_ELAPSED:`.

## 6. O que eu não faço (e você precisa fazer)

- Eu **não vejo** o prato nem escuto a impressora. Só sei o que ela responde pela serial.
- Eu não tiro a peça, não limpo o prato, não troco filamento. Por isso peço "prato limpo" antes de cada
  impressão. Sem isso a próxima peça cai em cima da anterior.
- Eu não decido sozinho parar uma impressão boa. Parei uma vez sem perguntar e você reclamou com razão.

## 7. Dá para fazer um programa de desktop? Sim.

Nada do que eu faço é exclusivo: é só uma porta serial, G-code e disciplina. Há dois caminhos.

### A) Usar um programa que já existe (mais rápido)

- **OctoPrint** (servidor web, roda no próprio PC): upload do G-code, temperaturas, controle, pausa,
  histórico. É o mais próximo do que eu faço, e aguenta bem o Marlin 1.0.6.
- **Pronterface / Printrun**, **Cura** com impressão USB: mais simples, mas só uma janela.

Para o dia a dia, eu usaria o OctoPrint. Não precisa escrever nada.

### B) Escrever um programa próprio (Python)

É viável. Um desenho que funciona:

```
[ janela / navegador ]  <-->  [ servidor Python ]  <-->  [ UM só dono da porta serial ]  <-->  Marlin
   botões, gráficos             fila de comandos          thread que escreve e espera "ok"
```

Peças principais:

1. **Um único dono da porta serial**. É a lição nº 1 acima. Tudo (G-code, `M105`, jog) entra numa fila e é
   enviado em ordem; nunca um segundo processo.
2. **Fila com `ok`**. Enviar uma linha, esperar `ok`, tratar `busy`, `T:` e `error`.
3. **Temperatura**: mandar `M105` na mesma fila a cada 2 s e mostrar num gráfico.
4. **Controles**: eixos (jog em passos de 0,1 / 1 / 10 / 50 mm), home X Y, temperatura, ventilador, extrusão.
5. **Imprimir**: abrir `.gcode`, barra de progresso por linhas (e tempo restante pelo `;TIME_ELAPSED`),
   pausa e retomada como a da seção 4, botão de parada que desliga aquecedores.
6. **Fatiar dentro do programa**: chamar o `slice_cura.py` (ABS/PLA, topo concêntrico, suporte) e mostrar o resultado.
7. **Verificações antes de começar**: disco livre, impressora parada, temperatura, "prato limpo? janela aberta?".
8. **Registro**: guardar o log por impressão, e apagar os antigos.

Bibliotecas: `pyserial` (serial), `FastAPI` ou `Flask` (servidor), uma página HTML simples ou `PySide6` (janela).
Um MVP (conectar, jog, temperatura, imprimir, parar) é um trabalho de poucos dias; pausa, retomada e fatiador
integrado acrescentam mais.

Limites a considerar:
- Imprimir pelo PC exige o PC **ligado e sem suspender** durante toda a peça. Em impressões de 3 h isso importa.
- A segurança contra superaquecimento está no firmware da impressora. O programa não substitui isso.
- Sem câmera, o programa também não vê o prato. Uma câmera USB com visualização ao vivo seria o próximo passo útil.

Se quiser, eu começo pelo caminho B com um servidor mínimo que aproveite o `send_gcode.py` e o `slice_cura.py`
que já existem.
