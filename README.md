<div align="center">

<img src="docs/logo.png" width="180" alt="Logo do ERP Kuryos Beauty"/>

# ERP Kuryos Beauty

### Plataforma ERP Empresarial para a Indústria de Cosméticos e Perfumaria

*Um ERP Full Stack moderno, desenvolvido para digitalizar, automatizar e otimizar todo o ciclo de vida de produtos — desde Pesquisa e Desenvolvimento até Produção, Controle de Qualidade, Logística e Faturamento.*

<p>

![React](https://img.shields.io/badge/React-19-61DAFB?logo=react\&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi\&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python\&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-Database-47A248?logo=mongodb\&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3-38B2AC?logo=tailwindcss\&logoColor=white)
![JWT](https://img.shields.io/badge/Auth-JWT-black)
![AWS](https://img.shields.io/badge/AWS-S3-FF9900?logo=amazonaws\&logoColor=white)
![Stripe](https://img.shields.io/badge/Stripe-Payments-635BFF?logo=stripe\&logoColor=white)

</p>

> **Desenvolvido com foco em escalabilidade, modularidade e fluxos empresariais complexos.**

</div>

---

# 📖 Visão Geral

O **ERP Kuryos Beauty** é uma plataforma SaaS completa, desenvolvida para indústrias de cosméticos e perfumaria, cobrindo todas as etapas do processo empresarial por meio de módulos especializados.

Em vez de utilizar sistemas desconectados, a plataforma centraliza as operações em um único ecossistema, proporcionando maior **rastreabilidade, automação, controle de qualidade, gestão de workflows e apoio à tomada de decisões estratégicas**.

O projeto foi desenvolvido com uma arquitetura modular e utiliza práticas modernas de desenvolvimento Full Stack, permitindo escalabilidade, facilidade de manutenção e expansão contínua.

---

# ✨ Principais Diferenciais

* 🏭 ERP completo voltado para a indústria de cosméticos
* 📦 Gestão de ponta a ponta do ciclo de vida do produto
* 🧪 Pesquisa e Desenvolvimento
* 📋 Planejamento e Controle da Produção
* 📊 CRM e pipeline comercial
* 📦 Controle de estoque e armazenagem
* 🚚 Expedição e logística
* 💰 Faturamento e operações financeiras
* ✅ Controle de Qualidade
* 🔒 Autenticação JWT e controle de acesso por perfil
* 📈 Dashboards interativos
* 🤖 Estrutura preparada para integrações com Inteligência Artificial
* 📄 Geração de relatórios em PDF e Excel
* ☁ Arquitetura preparada para ambientes em nuvem

---

# 🏗 Arquitetura do Sistema

```text
                    Navegador
                        │
                React 19 + Tailwind
                        │
                API REST / WebSocket
                        │
                  Backend FastAPI
                        │
          Módulos de Negócio e Workflow Engine
                        │
                    MongoDB
                        │
 ┌──────────────┬──────────────┬──────────────┐
 │              │              │              │
AWS S3        Stripe       Google AI      ReportLab
```

A aplicação segue uma **arquitetura modular orientada por domínios**, na qual cada área de negócio é organizada em módulos independentes.

Essa abordagem melhora a manutenção, a escalabilidade, a separação de responsabilidades e a evolução do sistema a longo prazo.

---

# 🚀 Tecnologias Utilizadas

| Camada                      | Tecnologias                                                 |
| --------------------------- | ----------------------------------------------------------- |
| **Frontend**                | React 19, React Router 7, Tailwind CSS, Radix UI, shadcn/ui |
| **Backend**                 | FastAPI, Python, Uvicorn, Pydantic                          |
| **Banco de Dados**          | MongoDB com Motor assíncrono                                |
| **Autenticação**            | JWT e bcrypt                                                |
| **Formulários e Validação** | React Hook Form e Zod                                       |
| **Gráficos e Dashboards**   | Recharts                                                    |
| **Comunicação HTTP**        | Axios                                                       |
| **Relatórios**              | ReportLab e OpenPyXL                                        |
| **Armazenamento**           | AWS S3                                                      |
| **Pagamentos**              | Stripe                                                      |
| **Integrações com IA**      | OpenAI, Google Generative AI e LiteLLM                      |
| **Testes**                  | Pytest e pytest-asyncio                                     |

---

# 📦 Módulos de Negócio

| Módulo                            | Descrição                                                                          |
| --------------------------------- | ---------------------------------------------------------------------------------- |
| 🧪 **Pesquisa e Desenvolvimento** | Formulações, estudos de estabilidade, aprovação de produtos e documentação técnica |
| 🤝 **CRM Comercial**              | Gestão de clientes, projetos, amostras e pipeline de vendas                        |
| 📋 **PCP**                        | Planejamento e Controle da Produção                                                |
| 🏭 **Produção**                   | Gestão e acompanhamento dos processos produtivos                                   |
| 📦 **Estoque**                    | Controle de lotes, movimentações e rastreabilidade                                 |
| 🛒 **Compras**                    | Fornecedores, cotações, ordens de compra e planejamento de materiais               |
| ✅ **Controle de Qualidade**       | Registros de análise, inspeções, retenções e não conformidades                     |
| 📑 **Contratos**                  | Gestão de contratos comerciais                                                     |
| 🚚 **Expedição**                  | Fluxo de despacho, notas de saída e logística                                      |
| 💰 **Faturamento**                | Controle financeiro, cobranças e emissão de documentos                             |
| 📥 **Recebimento**                | Controle de materiais e notas fiscais de entrada                                   |
| 🔄 **Workflow Engine**            | Automação de tarefas, aprovações, notificações e auditoria                         |
| 📊 **Dashboards**                 | Indicadores operacionais, estratégicos e gerenciais                                |

---

# 🔄 Ciclo de Vida do Produto

```text
CRM
│
├── Cliente
├── Projeto
└── Amostra
      │
      ▼
Pesquisa e Desenvolvimento
│
├── Formulação
├── Estudo de Estabilidade
├── Ficha Técnica
└── Aprovação
      │
      ▼
Geração Automática de SKU
      │
      ▼
Ordem de Produção
      │
      ▼
PCP
      │
      ▼
Produção
      │
      ▼
Controle de Qualidade
      │
      ▼
Estoque
      │
      ▼
Expedição
      │
      ▼
Faturamento
```

Esse fluxo permite acompanhar o produto desde sua concepção inicial até sua entrega e faturamento, mantendo histórico, rastreabilidade e integração entre os departamentos.

---

# 🧪 Fluxo de Pesquisa e Desenvolvimento

```text
PENDENTE
   │
   ▼
EM ANDAMENTO
   │
   ▼
EM TESTES
   │
   ▼
EM APROVAÇÃO
   │
   ├── APROVADO
   │
   └── REPROVADO
```

As formulações podem possuir controle de versões, estudos de estabilidade, itens de composição e documentação técnica relacionada.

Ao avançar para determinadas etapas, algumas informações podem ser protegidas contra alterações indevidas, garantindo a integridade do processo.

---

# 📋 Fluxo de Pedidos

```text
RASCUNHO
   │
   ▼
CONFIRMADO
   │
   ▼
EM PRODUÇÃO
   │
   ▼
CONCLUÍDO
```

O pedido também pode ser cancelado conforme as regras de negócio e permissões do usuário.

---

# 🛡 Princípios Arquiteturais

* Arquitetura modular
* Separação por domínios de negócio
* APIs RESTful
* Autenticação JWT
* Controle de acesso baseado em funções
* Estrutura preparada para múltiplos clientes
* Logs de auditoria
* Registros imutáveis no Controle de Qualidade
* Automação de workflows
* Integração com serviços em nuvem
* Escalabilidade de módulos
* Estrutura preparada para Inteligência Artificial
* Separação entre frontend e backend
* Validação de dados no cliente e no servidor

---

# 🏢 Arquitetura Multiempresa

A plataforma foi estruturada para permitir a separação dos dados por organização por meio de identificadores específicos.

```text
Empresa A
├── Usuários
├── Clientes
├── Produtos
├── Pedidos
└── Operações

Empresa B
├── Usuários
├── Clientes
├── Produtos
├── Pedidos
└── Operações
```

Essa estratégia permite que diferentes empresas utilizem a mesma aplicação, mantendo seus dados e operações isolados.

---

# 👥 Perfis de Usuário

A plataforma utiliza um sistema de **controle de acesso baseado em funções**, permitindo restringir telas, ações e operações conforme o perfil do usuário.

Entre os perfis suportados estão:

* Administrador
* Formulador
* Vendedor
* Líder de P&D
* Engenharia de Produto
* Compras
* Qualidade
* Operações Comerciais
* Produção
* Sucesso do Cliente

Cada perfil pode possuir permissões específicas para visualizar, criar, editar, aprovar ou acompanhar informações dentro do sistema.

---

# 🔄 Workflow Engine

O sistema possui uma estrutura de workflows voltada à automação de processos empresariais.

Entre as possibilidades estão:

* Criação automática de tarefas
* Tarefas obrigatórias antes de mudanças de status
* Aprovações por área responsável
* Notificações internas
* Escalação de tarefas
* Registro de auditoria
* Bloqueio de transições inválidas
* Histórico de movimentações
* Acompanhamento de pendências

Essa estrutura permite que os processos avancem apenas quando os requisitos necessários forem atendidos.

---

# 🔔 Notificações em Tempo Real

A arquitetura possui suporte a comunicação em tempo real por meio de WebSocket.

Esse recurso pode ser utilizado para:

* Atualização de tarefas
* Novas notificações
* Alteração de status
* Atualização de dashboards
* Avisos de aprovação
* Alertas de processo
* Atualizações de produção

---

# 📄 Relatórios e Documentos

A plataforma permite a geração de documentos empresariais em diferentes formatos.

## Documentos em PDF

* Ordens de Produção
* Fichas Técnicas
* Certificados de Análise
* Documentos de Qualidade
* Relatórios operacionais
* Documentação de produtos

## Planilhas Excel

* Relatórios de estoque
* Listagens de produtos
* Dados de compras
* Indicadores gerenciais
* Exportações operacionais
* Dados para auditoria

---

# 📁 Estrutura do Projeto

```text
KURYOS/
│
├── backend/
│   ├── server.py
│   ├── rbac.py
│   ├── workflow_engine.py
│   ├── authentication/
│   ├── routes/
│   ├── services/
│   ├── reports/
│   ├── integrations/
│   ├── migrations/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.js
│   │   ├── pages/
│   │   ├── components/
│   │   ├── contexts/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── utils/
│   ├── tailwind.config.js
│   └── package.json
│
├── tests/
├── uploads/
├── docs/
└── conftest.py
```

---

# 🎨 Design System

A interface foi construída utilizando um design system moderno, com foco em legibilidade, organização visual e experiência do usuário.

## Características visuais

* Suporte aos modos claro e escuro
* Componentes baseados em shadcn/ui e Radix UI
* Layouts responsivos
* Cards para indicadores
* Tabelas operacionais
* Quadros Kanban
* Modais laterais
* Feedback visual de status
* Cores semânticas para etapas de processo
* Componentes reutilizáveis
* Formulários padronizados

## Tipografia

* **Outfit:** títulos e destaques
* **Manrope:** textos e conteúdos
* **JetBrains Mono:** códigos, identificadores e valores numéricos

---

# 🗃 Principais Coleções do Banco de Dados

| Módulo                    | Coleções                                                                                                              |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **P&D**                   | `pd_requests`, `pd_formulas`, `pd_formula_items`, `pd_stability_studies`, `pd_stability_readings`, `pd_ficha_tecnica` |
| **CRM**                   | `crm_clients`, `crm_projects`, `crm_samples`, `cards`, `stages`                                                       |
| **Controle de Qualidade** | `cq_registros_analise`, `cq_checklists`, `cq_rncs`, `cq_retencoes`, `cq_instrumentos`                                 |
| **Compras**               | `compras_fornecedores`, `compras_itens`, `compras_pos`, `compras_mrp_rodadas`                                         |
| **Operacional**           | `orders`, `estoque_lotes`, `recebimento_notas`, `expedicao_notas`, `faturamento_notas`, `faturamento_duplicatas`      |
| **Sistema**               | `users`, `tenants`, `workflow_tasks`, `audit_logs`                                                                    |

---

# 🔐 Segurança

A aplicação foi desenvolvida seguindo práticas de segurança voltadas a sistemas empresariais.

* Autenticação baseada em JWT
* Hash de senhas com bcrypt
* Rotas protegidas no backend
* Controle de acesso por perfil
* Separação de dados por empresa
* Variáveis de ambiente
* Registro de auditoria
* Validação de entrada de dados
* Registros imutáveis no módulo de Qualidade
* Tratamento seguro de arquivos
* Controle de permissões no frontend e backend
* Proteção de informações confidenciais

> Credenciais, segredos, regras comerciais sensíveis, informações privadas e ativos proprietários não devem ser publicados no repositório.

---

# ⚙ Pré-requisitos

Antes de executar o projeto, certifique-se de possuir:

* Python 3.11 ou superior
* Node.js 20 ou superior
* Yarn 1.22 ou superior
* MongoDB 6 ou superior
* Git instalado
* Ambiente virtual Python, recomendado

---

# ⚙ Instalação

## 1. Clonar o repositório

```bash
git clone https://github.com/DEVMarlosGomes/ERPKuryosBeauty.git

cd ERPKuryosBeauty
```

---

## 2. Configurar o Backend

```bash
cd backend

python -m venv venv
```

### Ativar o ambiente virtual no Windows

```bash
venv\Scripts\activate
```

### Ativar o ambiente virtual no Linux ou macOS

```bash
source venv/bin/activate
```

### Instalar as dependências

```bash
pip install -r requirements.txt
```

---

## 3. Configurar as Variáveis de Ambiente

Crie um arquivo `.env` dentro da pasta do backend.

```env
MONGO_URL=mongodb://127.0.0.1:27017
DB_NAME=kuryos_crm
JWT_SECRET=adicione-uma-chave-segura
# NF-e via Focus NFe. Comece sempre em homologacao.
FOCUS_NFE_ENV=homologacao
FOCUS_NFE_TOKEN=token-da-empresa-no-provedor
```

Sem `FOCUS_NFE_TOKEN`, o sistema mantém a nota em rascunho e bloqueia a falsa emissão manual. Use `FOCUS_NFE_ENV=producao` somente depois da homologação fiscal, cadastro do emitente e validação do certificado no provedor.

> Nunca publique arquivos `.env`, chaves privadas, senhas, tokens ou credenciais de serviços externos.

---

## 4. Executar o Backend

```bash
python server.py
```

Também é possível executar utilizando Uvicorn:

```bash
uvicorn server:app --reload --port 8000
```

A API ficará disponível em:

```text
http://localhost:8000
```

A documentação interativa da API poderá estar disponível em:

```text
http://localhost:8000/docs
```

---

## 5. Configurar o Frontend

```bash
cd frontend

npm install
```

Crie um arquivo `.env` dentro da pasta do frontend.

```env
VITE_BACKEND_URL=http://localhost:8000
```

---

## 6. Executar o Frontend

```bash
npm start
```

A aplicação ficará disponível em:

```text
http://localhost:3000
```

---

# 🧪 Testes

Para executar a suíte unitária:

```bash
python -m pytest backend/tests -q
```

Para executar a homologação HTTP obrigatória no Windows, com API e banco de
teste isolados iniciados e encerrados automaticamente:

```powershell
.\scripts\run_backend_tests.ps1
```

O reset destrutivo usado pela suíte HTTP só é liberado no processo de teste e
exige a confirmação do tenant autenticado. Ele permanece bloqueado nos demais
ambientes.

Para executar um módulo específico:

```bash
pytest tests/cq_test.py -v
```

```bash
pytest tests/backend_test.py -v
```

```bash
pytest backend/tests/test_compras.py -v
```

Os testes utilizam configurações próprias para evitar interferência nos dados do ambiente principal.

---

# 📊 Competências Demonstradas

O ERP Kuryos Beauty representa a construção de uma aplicação empresarial completa, envolvendo diferentes áreas de negócio dentro de um único ecossistema.

O projeto demonstra experiência prática em:

* Desenvolvimento Full Stack
* Desenvolvimento de sistemas empresariais
* Arquitetura modular
* Arquitetura de software
* Desenvolvimento de APIs REST
* Integração entre frontend e backend
* Modelagem de banco de dados
* Autenticação e autorização
* Controle de acesso baseado em funções
* Desenvolvimento de dashboards
* Automação de processos
* Gestão de workflows
* Geração de relatórios
* Integrações com serviços em nuvem
* Integrações com Inteligência Artificial
* Desenvolvimento de interfaces responsivas
* Testes automatizados
* Gestão de estados e formulários
* Boas práticas de segurança
* Organização e manutenção de código

---

# 💡 Por que este projeto é relevante?

O ERP Kuryos Beauty não representa apenas um sistema de cadastro ou um conjunto de telas isoladas.

A aplicação reúne processos reais de uma indústria em um ecossistema integrado, conectando áreas comerciais, técnicas, produtivas, logísticas e financeiras.

Entre os desafios técnicos presentes no projeto estão:

* Gerenciamento de processos com múltiplas etapas
* Controle de acesso para diferentes departamentos
* Rastreabilidade de informações
* Integração entre módulos
* Automação de tarefas
* Geração de documentos
* Persistência de dados assíncrona
* Controle de versões
* Auditoria de ações
* Fluxos de aprovação
* Segurança de informações
* Escalabilidade da aplicação

---

# 📈 Próximas Evoluções

* Containerização com Docker
* Orquestração com Kubernetes
* Pipeline de integração e entrega contínua
* Ampliação dos testes automatizados
* Testes end-to-end
* Monitoramento de aplicação
* Observabilidade e logs centralizados
* Melhorias na responsividade mobile e tablet
* Assinatura digital de documentos
* Alertas automáticos para estudos de estabilidade
* Scheduler para tarefas recorrentes
* Notificações em tempo real
* Documentos com controle automático de versão
* Homologação obrigatória de fornecedores
* Otimizações de desempenho
* Cache de dados
* Deploy em múltiplas regiões
* Arquitetura orientada a eventos
* Evolução gradual para microsserviços

---

# 👨‍💻 Autor

## Marlos Gomes

**Desenvolvedor Full Stack**

Desenvolvedor focado na construção de aplicações modernas, soluções empresariais, automações e sistemas escaláveis.

### Principais tecnologias

* Python
* FastAPI
* React
* JavaScript
* MongoDB
* SQL
* Cloud Computing
* APIs REST
* Arquitetura de Software
* UI/UX
* Automação de Processos

---

# 📄 Licença e Confidencialidade

Este repositório é destinado à apresentação de portfólio, demonstração técnica e evolução do projeto.

Regras de negócio confidenciais, credenciais, ativos proprietários, documentos internos, dados de clientes e informações operacionais sensíveis foram omitidos ou abstraídos.

O código, as marcas, os documentos e os recursos visuais do projeto não devem ser utilizados comercialmente sem autorização prévia.

---

<div align="center">

### Desenvolvido por Marlos Gomes

**Tecnologia aplicada à transformação de processos empresariais.**

</div>
