# Gecko — Roteiro do Pitch (3 min)

**Formato:** otimizado para leitura no celular.
**Alinhado a:** `Gecko_Pitchdeck_Jun-2026.pdf` (10 slides, PT-BR).
**Última atualização:** 2026-06-01.

---

## 1. One-liner

> **Gecko é o oracle que diz que não.**

Alternativas para sala diferente:
- **Técnica:** *Gecko é a camada de julgamento acima de qualquer agente de trading na Solana.*
- **Mercado:** *Execução virou commodity. Julgamento é escasso. A gente constrói o julgamento.*

---

## 2. Pitch de 30 segundos (~88 palavras)

> Todo agente de trading diz que está ganhando.
> O nosso te diz quando ele está errado.
>
> Gecko é a camada de julgamento que fica acima de qualquer agente — Eliza, SendAI, OKX, o seu próprio. Default é dizer **não**. Só dispara quando o gráfico e o corpus concordam. E cita a fonte em todo veredicto.
>
> Sete especialistas debatem cada tese. As vozes discordantes sobrevivem no resultado — citadas, assinadas, auditáveis.
>
> Vantagem de performance: **+0,6% · N=78 · validada estatisticamente**.
>
> Fundamentado em Howard Marks, Buffett, Damodaran e Mauboussin.

---

## 3. Pitch de 3 minutos com demo

> **Premissa do roteiro:** os 10 slides do deck servem como suporte visual. Você fala; o slide reforça. Não leia o slide — abra o slide ao mesmo tempo em que diz a linha-chave.

---

### 00:00 → 00:10 — Abertura (Slide 1, contato visual)

> "Execução virou commodity."
>
> "Julgamento é escasso."
>
> "IAs já atuam de forma autônoma com dinheiro real. Gecko é a camada de julgamento acima delas."

---

### 00:10 → 00:40 — Problema (Slide 2)

> "Você já tem capital exposto. Ninguém te diz quando parar."
>
> "Pagamentos: já tem. Descoberta: já tem. Execução: já tem. **Julgamento: não tem.**"
>
> "O usuário-alvo não está procurando uma tese. Ele está copiando uma — e já foi prejudicado pelo menos uma vez."
>
> "Quinhentos dólares desperdiçados em uma posição que o agente nunca testou sob pressão. Zero comprovantes de por que o agente errou. Uma única voz no resultado — o modelo que confirmou o viés do usuário."
>
> "Essa é a camada que ninguém construiu. Até agora."

---

### 00:40 → 01:20 — Solução em 4 camadas (Slide 3)

> "Gecko é o oracle que diz que não. Quatro camadas, qualquer trilho de execução."
>
> "**Camada 1 — Coach.** Constrói a estratégia do agente em conversa. A cada decisão importante, aciona o oracle."
>
> "**Camada 2 — Oracle, o Gecko Core.** Sete especialistas debatem cada tese. As vozes contrárias **sobrevivem no veredicto**. Porque decisão sem dissidência é decisão sem rigor. Matamos as nossas próprias estratégias antes que cheguem ao dinheiro do usuário. **$0,25 por veredicto. $0,75 painel pro. Pay-as-you-go.**"
>
> "**Camada 3 — Agente local.** Roda na máquina do usuário. Identifica oportunidades. **Nunca age sem aprovação.**"
>
> "**Camada 4 — Trilho de execução.** Qualquer wallet, qualquer plataforma. Solana, frameworks de agentes de IA, execução on-chain. Você escolhe."
>
> "Fundamentado em Howard Marks, Buffett, Damodaran, Mauboussin. Cânone testado em décadas, não em três meses de backtest."

---

### 01:20 → 02:00 — Demo (Slides 4 + 5)

**Cue de demo:** abrir terminal AO VIVO ou mostrar o slide 4.

Digite ou aponte para a linha:

```
$ gecko_trade_research --idea "deposit USDC into Kamino" \
    --protocol kamino --vertical dex --tier pro
```

> "Uma pergunta. Sete especialistas."

Aponte para a sequência:

> "Quatrocentos e dois, payment required. Desafio x402 na Solana. Setenta e cinco centavos. **Transação confirmada em 1,6 segundos.**"

Aponte para o JSON:

> "Veredicto: pass. Confiança: 0,75. Três drivers — utilização do reserve a 78%, JLP melhor risk-ajusted no janelado de 30 dias, headroom abaixo de $2M antes de throttle."
>
> "E aqui — **a parte que ninguém te dá:**"

Aponte para `surviving_dissent`:

> "A discordância que sobreviveu. Um especialista alertou que a curva de utilização cruza o kink em 80% e há spike de volatilidade de APR provável em 48 horas. **Citado. Assinado. Auditável.**"
>
> "Três citações. Marks. Kamino. JLP."

Avance para o Slide 5:

> "Vantagens são medidas. Não alegadas."
>
> "Vantagem de performance: **+0,6%**. O delta de filtragem — a diferença entre o agente seguir tudo e o agente seguir só o que o oracle aprova."
>
> "**N=78. Validado estatisticamente. Consistente entre condições de mercado. Mais forte em tendências de alta.**"
>
> "Isso é antes de pedir que qualquer um arriscasse um centavo."

---

### 02:00 → 02:30 — Momento (Slide 6)

> "Trinta dias de desenvolvimento."
>
> "Judgment oracle live. Waitlist aberta. Pagamentos autônomos on-chain. Quatro rotas de pagamento. Avaliação de qualidade 1.0 em três domínios."
>
> "E o melhor dogfood que existe: **a gente perguntou para o nosso próprio oracle se devíamos seguir com a estratégia. As sete vozes responderam: postergar.** A gente seguiu o veredicto."
>
> "Apesar de: ainda não cobrar usuários, nenhum pagante, primeira integração externa em testes — o produto já produz o tipo de output que o usuário precisa para parar de perder dinheiro."

---

### 02:30 → 02:45 — Tração + mercado (Slides 7 + 8)

> "Como os primeiros cem usuários chegam: comunidades de devs de agentes de IA, marketplace de skills, campanhas de bounties, waitlist no site. Dois canais já ativos, um confirmado."
>
> "Mercado endereçável: **$380 milhões.** A camada de execução já existe — nós somos a camada acima."
>
> "Pricing: $0,25 por veredicto. $0,75 painel pro. **Sem subscrição.** A gente só ganha se o oracle for útil. Veredicto já respondido — grátis."

---

### 02:45 → 03:00 — Fechamento (Slides 9 + 10)

> "Construímos porque precisávamos. Eu uso Gecko nas minhas decisões de trading todo dia."
>
> "Leticia veio do design e da Liga Ventures — ela viu centenas de fundadores vencerem ou fracassarem. Eu venho do Itaú e do Santander — engenharia em dados financeiros."
>
> "Construímos a camada de julgamento porque ela não existia, e a gente precisava dela."

Pausa. Contato visual. Slide 10 no fundo.

> "Seu próximo agente não precisa agir sem julgamento."
>
> "**app.geckovision.tech**"
>
> "Obrigado."

---

## 4. Demo failure modes (memorize)

| Se… | Pivote para… |
|---|---|
| Terminal não conecta / timeout | "O resultado típico já está no slide — vou guiar pelo JSON." |
| Slide quebra / projeção falha | Tire o iPad / celular do bolso. Mostre o deck direto. |
| **"Qual a sua moat?"** | "Três coisas compondo. Um — as nulls validadas, oito até hoje, crescendo toda semana. Dois — a infra de rigor CPCV+PBO+DSR que produz elas. Três — o formato de veredicto citado que o comprador pode auditar. Não vendemos alpha. Vendemos **disciplina de rejeição**." |
| **"Por que um painel em vez de um modelo?"** | "Modelo único ancora ao próprio prompt. Painel com dissidência explícita expõe discordância. **A gente quer ver** quando o chart_voice e o memory_voice discordam. Isso É o produto." |
| **"E latência?"** | "Veredicto em menos de três segundos com classificador cacheado. O custo de latência é real. O custo de uma operação ruim é maior." |
| **"$0,25 é caro?"** | "Comparado ao quê? A perda média de quem copia tese sem julgamento é $500. Por vinte e cinco centavos você compra o veto antes da operação." |
| **"Vocês competem com X?"** | "Não competimos com seu agente. Somos a camada que ele chama **antes** de operar." |
| **"Cadê os usuários?"** | "Trinta dias de produto. Waitlist aberta. Primeiro usuário externo em testes. Quando alguém topa pagar pelo veto antes de ter o veto, ainda é fé. Pagar depois — é evidência. Estamos no momento de evidência." |
| **"Não é só Reddit + RAG?"** | "RAG retorna texto. Nós retornamos um **veredicto com dissidência sobrevivente**. O Reddit não tem CPCV+PBO+DSR. E nem cita Marks." |

---

## 5. Números para decorar

| Número | O quê | Quando usar |
|---|---|---|
| **+0,6%** | vantagem de performance medida | resposta padrão para "funciona?" |
| **N=78** | trades na validação estatística | quando alguém duvidar do +0,6% |
| **7** | especialistas no painel | arquitetura |
| **4** | camadas (Coach · Oracle · Agente · Execução) | stack |
| **$0,25** | preço por veredicto | pricing |
| **$0,75** | painel pro | pricing tier |
| **1,0** | avaliação de qualidade em três domínios | rigor |
| **30 dias** | tempo de desenvolvimento | momentum |
| **$380M** | SAM | mercado |
| **1,6s** | settlement do x402 | demo flex |

---

## 6. O que NÃO falar

- **"AI trading agent"** — é a categoria que a gente bate, não somos isso
- **"Bater o mercado"** — promessa de PnL que a gente não faz
- **"Cinco vozes" ou "seis vozes"** sem checar — o deck diz **sete**; mantenha sete
- **"Solo founder"** — são dois fundadores (Ernani + Leticia)
- **"Nosso backtest mostra"** — mostre o +0,6% N=78 validado, não backtest cru
- **"Smarter than ChatGPT"** — claim que não medimos e não precisamos
- **"Beta privada"** ou **"em breve"** — está live. Diga: live, waitlist aberta.
- **"Vamos cobrar"** — diga: o pricing **já está definido**. Cobrança ativa quando integração externa estiver validada.

---

## 7. Versão de bolso (se só tiver 60 segundos)

Use os 30s acima + uma das duas pontes:

**Se for VC:** "Mercado endereçável $380M. Pricing pay-per-call, sem assinatura. Vantagem de performance validada estatisticamente em N=78. Posso te mostrar um veredicto rodando em 1,6 segundos."

**Se for builder:** "MCP call, x402 settled na Solana, veredicto com dissidência sobrevivente. Plug em qualquer agente. $0,25 por chamada. Quer ver um exemplo agora?"

---

**Arquivo:** `docs/marketing/pitch-script-3min.md` — empurra no `git pull` e abre no celular pelo GitHub.
