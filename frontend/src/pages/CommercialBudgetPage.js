import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, Trash2, FileText, Paperclip, Send, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const TAB_OPTIONS = [
  { id: "ped", label: "Pedidos" },
  { id: "orc", label: "Orçamentos" },
  { id: "cad", label: "Cadastros pendentes" },
  { id: "docs", label: "Documentos e histórico" },
];

const COMMERCIAL_STAGES = ["cotacao", "orcamento_completo", "em_negociacao", "pedido_aprovado"];

function today() {
  return new Date().toISOString().slice(0, 10);
}

function addDays(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function money(value) {
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function parseNumber(value) {
  if (value === null || value === undefined || value === "") return 0;
  const normalized = String(value).replace(/\./g, "").replace(",", ".");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeCondicaoPagamento(value) {
  const raw = String(value || "").trim();
  if (/^\d{3}\/\d{3}\/\d{3}$/.test(raw)) return raw;
  const digits = raw.replace(/\D/g, "");
  if (!digits) return "000/000/000";
  return `${digits.slice(0, 3).padStart(3, "0")}/000/000`;
}

function clientName(client) {
  return client?.nome_empresa || client?.razao_social || client?.nome || "Cliente sem nome";
}

function clientContact(client) {
  return client?.contato_principal || {};
}

function skuLabel(sku) {
  return [sku?.codigo_interno, sku?.nome_produto || sku?.produto_pai_nome].filter(Boolean).join(" — ");
}

function stageLabel(stage) {
  const labels = {
    cotacao: "Cotação",
    orcamento_completo: "Orçamento completo",
    em_negociacao: "Em negociação",
    pedido_aprovado: "Pedido aprovado",
  };
  return labels[stage] || stage || "Sem fase";
}

function emptyPedidoItem() {
  return { skuId: "", qtd: "", valor: "", desconto: "" };
}

function emptyOrcamentoItem() {
  return { descricao: "", qtd: "", valor: "", desconto: "", especificacao: "" };
}

function defaultPedidoForm() {
  return {
    clienteId: "",
    dataPedido: today(),
    po: "",
    previsao: "",
    contato: "",
    telefone: "",
    email: "",
    nf: "100",
    frete: "FOB",
    prazoFrete: "",
    pagamento: "",
    entrega: "",
    faturamento: "",
    obs: "",
  };
}

function defaultOrcamentoForm() {
  return {
    projetoId: "",
    clienteId: "",
    cliente: "",
    cnpj: "",
    contato: "",
    email: "",
    validade: addDays(30),
    pagamento: "",
    frete: "FOB",
    evidencia: "",
    obs: "",
  };
}

export default function CommercialBudgetPage() {
  const [tab, setTab] = useState("ped");
  const [loading, setLoading] = useState(true);
  const [savingPedido, setSavingPedido] = useState(false);
  const [savingOrcamento, setSavingOrcamento] = useState(false);
  const [alert, setAlert] = useState(null);
  const [clients, setClients] = useState([]);
  const [skus, setSkus] = useState([]);
  const [orders, setOrders] = useState([]);
  const [projects, setProjects] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [pedidoForm, setPedidoForm] = useState(defaultPedidoForm);
  const [pedidoItems, setPedidoItems] = useState([emptyPedidoItem()]);
  const [orcamentoForm, setOrcamentoForm] = useState(defaultOrcamentoForm);
  const [orcamentoItems, setOrcamentoItems] = useState([emptyOrcamentoItem()]);
  const [docOrderId, setDocOrderId] = useState("");
  const [docFile, setDocFile] = useState(null);
  const [docMotivo, setDocMotivo] = useState("");
  const alertTimerRef = useRef(null);

  const showAlert = useCallback((message, error = false) => {
    setAlert({ message, error });
    window.clearTimeout(alertTimerRef.current);
    alertTimerRef.current = window.setTimeout(() => setAlert(null), 6000);
  }, []);

  useEffect(() => () => window.clearTimeout(alertTimerRef.current), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: clientData }, { data: skuData }, { data: orderData }, { data: projectData }] = await Promise.all([
        api.get("/crm/clients"),
        api.get("/crm/skus", { params: { status: "ativo" } }),
        api.get("/orders"),
        api.get("/crm/projects"),
      ]);

      const normalizedProjects = (Array.isArray(projectData) ? projectData : []).map((project) => ({
        ...project,
        stage: project.stage === "amostras" ? "amostra_solicitada" : project.stage,
      }));
      const commercialProjects = normalizedProjects.filter((project) => COMMERCIAL_STAGES.includes(project.stage));
      const loadedProposals = await Promise.allSettled(
        commercialProjects.slice(0, 60).map(async (project) => {
          const { data } = await api.get(`/crm/projects/${project.id}/proposta`);
          return { project, proposal: data?.projeto_id ? data : null };
        })
      );

      setClients(Array.isArray(clientData) ? clientData : []);
      setSkus(Array.isArray(skuData) ? skuData : []);
      setOrders(Array.isArray(orderData) ? orderData : []);
      setProjects(normalizedProjects);
      setProposals(loadedProposals.filter((result) => result.status === "fulfilled").map((result) => result.value));
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const sortedClients = useMemo(() => (
    [...clients].sort((a, b) => clientName(a).localeCompare(clientName(b), "pt-BR"))
  ), [clients]);

  const selectedPedidoClient = useMemo(
    () => clients.find((client) => client.id === pedidoForm.clienteId),
    [clients, pedidoForm.clienteId]
  );

  const selectedDocOrder = useMemo(
    () => orders.find((order) => order.id === docOrderId),
    [orders, docOrderId]
  );

  const availablePedidoSkus = useMemo(() => {
    if (!pedidoForm.clienteId) return [];
    return skus.filter((sku) => sku.cliente_id === pedidoForm.clienteId && sku.status === "ativo");
  }, [skus, pedidoForm.clienteId]);

  const commercialProjects = useMemo(() => (
    projects.filter((project) => COMMERCIAL_STAGES.includes(project.stage))
  ), [projects]);

  const proposalRows = useMemo(() => (
    proposals
      .map(({ project, proposal }) => ({ project, proposal }))
      .sort((a, b) => String(b.proposal?.updated_at || b.project.updated_at || "").localeCompare(String(a.proposal?.updated_at || a.project.updated_at || "")))
  ), [proposals]);

  const pendingCadastroRows = useMemo(() => (
    proposalRows.flatMap(({ project, proposal }) => (
      (proposal?.items_pedido || [])
        .filter((item) => !item.sku_id && !item.codigo_kuryos)
        .map((item, index) => ({ id: `${project.id}-${index}`, project, item, proposal }))
    ))
  ), [proposalRows]);

  const pedidoTotals = useMemo(() => {
    return pedidoItems.reduce((acc, item) => {
      const qtd = parseNumber(item.qtd);
      const valor = parseNumber(item.valor);
      const desconto = parseNumber(item.desconto);
      return { qtd: acc.qtd + qtd, total: acc.total + Math.max(0, qtd * valor - desconto) };
    }, { qtd: 0, total: 0 });
  }, [pedidoItems]);

  const orcamentoTotals = useMemo(() => {
    return orcamentoItems.reduce((acc, item) => {
      const qtd = parseNumber(item.qtd);
      const valor = parseNumber(item.valor);
      const desconto = parseNumber(item.desconto);
      return { qtd: acc.qtd + qtd, total: acc.total + Math.max(0, qtd * valor - desconto) };
    }, { qtd: 0, total: 0 });
  }, [orcamentoItems]);

  const pedidoKpis = useMemo(() => ({
    total: orders.length,
    pcp: orders.filter((order) => ["confirmado", "em_producao", "concluido"].includes(order.status)).length,
    parcial: orders.filter((order) => order.entrega_parcial || order.partial_delivery || order.fulfillment?.partial).length,
    valor: orders.reduce((sum, order) => sum + Number(order.total_pedido || order.totalValor || 0), 0),
  }), [orders]);

  const orcamentoKpis = useMemo(() => ({
    total: proposalRows.length,
    abertos: proposalRows.filter(({ proposal }) => !proposal || ["rascunho", "em_desenvolvimento"].includes(proposal.status)).length,
    enviados: proposalRows.filter(({ proposal }) => proposal?.status === "enviado").length,
    aceitos: proposalRows.filter(({ proposal, project }) => proposal?.negociacao_status === "aprovado" || project.stage === "pedido_aprovado").length,
  }), [proposalRows]);

  const applyPedidoClient = (clientId) => {
    const client = clients.find((item) => item.id === clientId);
    const contact = clientContact(client);
    setPedidoForm((current) => ({
      ...current,
      clienteId: clientId,
      contato: contact.nome || "",
      telefone: contact.whatsapp || "",
      email: contact.email || "",
      pagamento: client?.condicao_pagamento || "",
      faturamento: [client?.cidade, client?.uf || client?.estado].filter(Boolean).join(" / "),
      entrega: [client?.cidade, client?.uf || client?.estado].filter(Boolean).join(" / "),
    }));
    setPedidoItems([emptyPedidoItem()]);
  };

  const applyOrcamentoProject = (projectId) => {
    const project = projects.find((item) => item.id === projectId);
    const client = clients.find((item) => item.id === project?.cliente_id);
    const contact = clientContact(client);
    const proposalEntry = proposalRows.find((row) => row.project.id === projectId);
    const proposal = proposalEntry?.proposal;

    setOrcamentoForm((current) => ({
      ...current,
      projetoId: projectId,
      clienteId: project?.cliente_id || "",
      cliente: project?.cliente_nome || clientName(client),
      cnpj: client?.cnpj || "",
      contato: contact.nome || "",
      email: contact.email || "",
      pagamento: proposal?.condicoes_pagamento || client?.condicao_pagamento || "",
      evidencia: proposal?.observacoes_proposta || "",
      obs: proposal?.rodape_observacoes || "",
    }));
    setOrcamentoItems(
      (proposal?.items_pedido || []).length
        ? proposal.items_pedido.map((item) => ({
            descricao: item.item || "",
            qtd: item.qtd ?? "",
            valor: item.valor_unitario ?? item.preco_negociado ?? "",
            desconto: "",
            especificacao: [item.codigo_kuryos, item.codigo_cliente, item.prazo_entrega].filter(Boolean).join(" | "),
          }))
        : [emptyOrcamentoItem()]
    );
  };

  const applyOrcamentoClient = (clientId) => {
    const client = clients.find((item) => item.id === clientId);
    const contact = clientContact(client);
    setOrcamentoForm((current) => ({
      ...current,
      clienteId: clientId,
      cliente: clientId ? clientName(client) : current.cliente,
      cnpj: clientId ? client?.cnpj || "" : current.cnpj,
      contato: clientId ? contact.nome || "" : current.contato,
      email: clientId ? contact.email || "" : current.email,
      pagamento: clientId ? client?.condicao_pagamento || "" : current.pagamento,
    }));
  };

  const setPedidoItem = (index, field, value) => {
    setPedidoItems((current) => current.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const next = { ...item, [field]: value };
      if (field === "skuId") {
        const sku = skus.find((entry) => entry.id === value);
        if (sku?.preco_unitario && !next.valor) next.valor = String(sku.preco_unitario);
      }
      return next;
    }));
  };

  const setOrcamentoItem = (index, field, value) => {
    setOrcamentoItems((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, [field]: value } : item
    )));
  };

  const removePedidoItem = (index) => {
    setPedidoItems((current) => current.length > 1 ? current.filter((_, itemIndex) => itemIndex !== index) : [emptyPedidoItem()]);
  };

  const removeOrcamentoItem = (index) => {
    setOrcamentoItems((current) => current.length > 1 ? current.filter((_, itemIndex) => itemIndex !== index) : [emptyOrcamentoItem()]);
  };

  const savePedido = async () => {
    const client = selectedPedidoClient;
    const nf = parseNumber(pedidoForm.nf);
    const items = pedidoItems.map((item) => {
      const sku = skus.find((entry) => entry.id === item.skuId);
      const qtd = parseNumber(item.qtd);
      const valor = parseNumber(item.valor);
      const desconto = parseNumber(item.desconto);
      const bruto = qtd * valor;
      return {
        sku_id: sku?.id || "",
        codigo_kuryos: sku?.codigo_interno || "",
        codigo_cliente: sku?.codigo_cliente || "",
        item: sku?.nome_produto || sku?.produto_pai_nome || "",
        prazo_entrega: pedidoForm.previsao || "",
        qtd,
        valor_unitario: valor,
        valor_unitario_currency: sku?.preco_unitario_currency || "BRL",
        desconto_percentual: bruto > 0 ? Math.min(100, Math.max(0, (desconto / bruto) * 100)) : 0,
        valor_total: Math.max(0, bruto - desconto),
        tipo_servico: "producao",
      };
    });

    if (!client) return showAlert("Selecione o cliente cadastrado.", true);
    if (!Number.isFinite(nf) || nf < 0 || nf > 100) return showAlert("Informe um percentual de NF entre 0 e 100.", true);
    if (items.some((item) => !item.sku_id || item.qtd <= 0)) return showAlert("Cada linha precisa de produto cadastrado e quantidade positiva.", true);
    if (new Set(items.map((item) => item.sku_id)).size !== items.length) return showAlert("Cada SKU deve aparecer uma única vez. Consolide a quantidade para impedir duplicidade no PCP.", true);

    setSavingPedido(true);
    try {
      const contact = clientContact(client);
      await api.post("/orders/generator", {
        cliente_id: client.id,
        data_pedido: pedidoForm.dataPedido,
        pedido_cliente_ref: pedidoForm.po,
        tipo_servico: "producao",
        nivel_formalizacao: 1,
        cliente: {
          nome: clientName(client),
          razao_social: client?.razao_social || clientName(client),
          cnpj: client?.cnpj || "",
          cidade_uf: [client?.cidade, client?.uf || client?.estado].filter(Boolean).join("/"),
          responsavel: pedidoForm.contato || contact.nome || "",
          telefone: pedidoForm.telefone || contact.whatsapp || "",
          email: pedidoForm.email || contact.email || "",
        },
        frete: {
          tipo: pedidoForm.frete,
          endereco: pedidoForm.entrega,
          cidade_uf: pedidoForm.entrega,
          prazo_coleta: pedidoForm.prazoFrete,
        },
        condicoes: {
          prazo: pedidoForm.prazoFrete,
          forma_pgto: pedidoForm.pagamento,
          condicao_pagamento: normalizeCondicaoPagamento(pedidoForm.pagamento),
        },
        items,
        observacoes: [
          pedidoForm.obs,
          `Snapshot comercial: NF ${nf}%, frete ${pedidoForm.frete}, faturamento: ${pedidoForm.faturamento || "nao informado"}`,
        ].filter(Boolean).join("\n"),
      });
      showAlert("Pedido confirmado e liberado para o fluxo operacional do PCP.");
      setPedidoForm(defaultPedidoForm());
      setPedidoItems([emptyPedidoItem()]);
      await load();
    } catch (error) {
      showAlert(formatApiError(error), true);
    } finally {
      setSavingPedido(false);
    }
  };

  const saveOrcamento = async (status = "rascunho") => {
    const project = projects.find((item) => item.id === orcamentoForm.projetoId);
    const items = orcamentoItems.map((item) => {
      const qtd = parseNumber(item.qtd);
      const valor = parseNumber(item.valor);
      const desconto = parseNumber(item.desconto);
      return {
        item: item.descricao.trim(),
        qtd,
        valor_unitario: valor,
        valor_total: Math.max(0, qtd * valor - desconto),
        prazo_entrega: orcamentoForm.validade,
        codigo_kuryos: "",
        codigo_cliente: "",
      };
    });

    if (!project) return showAlert("Selecione o projeto CRM2 do orçamento.", true);
    if (!orcamentoForm.cliente.trim() || !orcamentoForm.validade) return showAlert("Informe cliente/prospecto e validade.", true);
    if (items.some((item) => !item.item || item.qtd <= 0)) return showAlert("Cada item precisa de descrição e quantidade positiva.", true);

    setSavingOrcamento(true);
    try {
      await api.post(`/crm/projects/${project.id}/proposta`, {
        tipo_produto: items[0]?.item || project.nome_projeto || "",
        variacao_produto: items.map((item) => item.item).filter(Boolean).join(", "),
        preco_unitario: items[0]?.valor_unitario || null,
        insumos_inclusos: [],
        observacoes_proposta: [
          orcamentoForm.evidencia,
          `Cliente/prospecto: ${orcamentoForm.cliente}`,
          orcamentoForm.cnpj ? `CNPJ: ${orcamentoForm.cnpj}` : "",
          orcamentoForm.contato ? `Contato: ${orcamentoForm.contato}` : "",
          orcamentoForm.email ? `E-mail: ${orcamentoForm.email}` : "",
          `Frete proposto: ${orcamentoForm.frete}`,
        ].filter(Boolean).join("\n"),
        items_pedido: items,
        condicoes_pagamento: orcamentoForm.pagamento,
        insumos_fabricacao: [],
        rodape_observacoes: orcamentoForm.obs,
        status,
        negociacao_status: status === "enviado" ? "em_negociacao" : "rascunho",
      });
      showAlert(status === "enviado" ? "Envio registrado; nenhuma demanda foi criada no PCP." : "Orçamento salvo. Nenhuma demanda foi criada no PCP.");
      setOrcamentoForm(defaultOrcamentoForm());
      setOrcamentoItems([emptyOrcamentoItem()]);
      await load();
    } catch (error) {
      showAlert(formatApiError(error), true);
    } finally {
      setSavingOrcamento(false);
    }
  };

  const markProposalSent = async (projectId) => {
    const proposalEntry = proposalRows.find((row) => row.project.id === projectId);
    if (!proposalEntry?.proposal) {
      applyOrcamentoProject(projectId);
      setTab("orc");
      showAlert("Preencha e salve o orçamento antes de marcar como enviado.", true);
      return;
    }
    try {
      await api.patch(`/crm/projects/${projectId}/proposta`, { status: "enviado", negociacao_status: "em_negociacao" });
      showAlert("Envio registrado; a negociação segue no CRM2.");
      await load();
    } catch (error) {
      showAlert(formatApiError(error), true);
    }
  };

  const editProposal = (projectId) => {
    applyOrcamentoProject(projectId);
    setTab("orc");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const markProposalAccepted = async (projectId) => {
    try {
      await api.patch(`/crm/projects/${projectId}/proposta`, { negociacao_status: "aprovado" });
      showAlert("Aceite registrado. O avanço para pedido aprovado continua pelo CRM2.");
      await load();
    } catch (error) {
      showAlert(formatApiError(error), true);
    }
  };

  const uploadDoc = async () => {
    if (!docOrderId || !docFile) return showAlert("Selecione pedido e arquivo.", true);
    const data = new FormData();
    data.append("file", docFile);
    try {
      await api.post(`/orders/${docOrderId}/attachments`, data, { headers: { "Content-Type": "multipart/form-data" } });
      setDocFile(null);
      showAlert("Anexo salvo com segurança.");
      await load();
    } catch (error) {
      showAlert(formatApiError(error), true);
    }
  };

  const openOrderPdf = () => {
    if (!docOrderId) return showAlert("Selecione um pedido.", true);
    const baseUrl = api.defaults.baseURL.replace(/\/api$/, "");
    window.open(`${baseUrl}/api/orders/${docOrderId}/pdf`, "_blank", "noopener,noreferrer");
  };

  return (
    <main className="min-h-screen p-4 md:p-6" data-testid="commercial-budget-page">
      <div className="mx-auto max-w-[1280px] space-y-5 pb-12">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground md:text-3xl">Comercial</h1>
            <p className="mt-1 text-sm text-muted-foreground">Orçamentos comerciais e pedidos liberados para PCP</p>
          </div>
          <Button variant="outline" className="gap-2" onClick={() => { setTab("ped"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
            <Plus className="h-4 w-4" /> Novo documento
          </Button>
        </div>

        {alert && (
          <div className={`rounded-lg border px-3 py-2 text-sm ${alert.error ? "border-destructive/20 bg-destructive/10 text-destructive" : "border-green-200 bg-green-50 text-green-700 dark:border-green-900/60 dark:bg-green-950/30 dark:text-green-300"}`}>
            {alert.message}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {TAB_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setTab(option.id)}
              className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${tab === option.id ? "bg-primary text-primary-foreground shadow-sm" : "bg-secondary text-secondary-foreground hover:bg-muted"}`}
            >
              {option.label}
            </button>
          ))}
        </div>

        {tab === "ped" && (
          <section>
            <Stats>
              <Stat value={pedidoKpis.total} label="Pedidos" />
              <Stat value={pedidoKpis.pcp} label="No PCP" />
              <Stat value={pedidoKpis.parcial} label="Entrega parcial" />
              <Stat value={money(pedidoKpis.valor)} label="Valor contratado" />
            </Stats>
            <TwoColumn>
              <Panel>
                <h2 className="text-xl font-heading font-semibold text-foreground">Novo pedido comercial</h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Pedido aceita somente produtos cadastrados e, ao confirmar, entra no backlog do PCP. O orçamento não é obrigatório.</p>
                <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm leading-relaxed text-blue-900 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200">
                  <b>Frete de venda:</b> FOB = cliente coleta/contrata frete. CIF = Kuryos entrega/contrata frete. A condição, endereço e prazo ficam disponíveis para a logística quando o produto estiver pronto.
                </div>

                <SectionTitle>Cliente e compromisso</SectionTitle>
                <FieldGrid>
                  <Field label="Cliente cadastrado *" className="md:col-span-3">
                    <NativeSelect value={pedidoForm.clienteId} onChange={(event) => applyPedidoClient(event.target.value)}>
                      <option value="">Selecione o cliente...</option>
                      {sortedClients.map((client) => <option key={client.id} value={client.id}>{clientName(client)}</option>)}
                    </NativeSelect>
                    <p className="mt-1 text-xs text-muted-foreground">Contato, e-mail, endereços e pagamento vêm do cadastro. Ajustes abaixo valem apenas para este pedido.</p>
                  </Field>
                  <Field label="Data do pedido *"><InlineInput type="date" value={pedidoForm.dataPedido} onChange={(event) => setPedidoForm({ ...pedidoForm, dataPedido: event.target.value })} /></Field>
                  <Field label="Pedido do cliente / PO"><InlineInput value={pedidoForm.po} onChange={(event) => setPedidoForm({ ...pedidoForm, po: event.target.value })} placeholder="Referência do cliente" /></Field>
                  <Field label="Previsão comercial de entrega"><InlineInput type="date" value={pedidoForm.previsao} onChange={(event) => setPedidoForm({ ...pedidoForm, previsao: event.target.value })} /></Field>
                  <Field label="Contato"><InlineInput value={pedidoForm.contato} onChange={(event) => setPedidoForm({ ...pedidoForm, contato: event.target.value })} placeholder="Nome do contato comercial" /></Field>
                  <Field label="Telefone do contato"><InlineInput type="tel" value={pedidoForm.telefone} onChange={(event) => setPedidoForm({ ...pedidoForm, telefone: event.target.value })} /></Field>
                  <Field label="E-mail de confirmação" className="md:col-span-2"><InlineInput type="email" value={pedidoForm.email} onChange={(event) => setPedidoForm({ ...pedidoForm, email: event.target.value })} placeholder="Registro do contato; envio externo será confirmado manualmente" /></Field>
                  <Field label="% da venda com NF *"><InlineInput type="number" min="0" max="100" value={pedidoForm.nf} onChange={(event) => setPedidoForm({ ...pedidoForm, nf: event.target.value })} /></Field>
                </FieldGrid>

                <SectionTitle>Entrega, faturamento e condições</SectionTitle>
                <FieldGrid>
                  <Field label="Frete *"><NativeSelect value={pedidoForm.frete} onChange={(event) => setPedidoForm({ ...pedidoForm, frete: event.target.value })}><option value="FOB">FOB — cliente coleta</option><option value="CIF">CIF — Kuryos entrega</option></NativeSelect></Field>
                  <Field label="Prazo / condição de frete"><InlineInput value={pedidoForm.prazoFrete} onChange={(event) => setPedidoForm({ ...pedidoForm, prazoFrete: event.target.value })} placeholder="Ex.: retirada após liberação" /></Field>
                  <Field label="Pagamento"><InlineInput value={pedidoForm.pagamento} onChange={(event) => setPedidoForm({ ...pedidoForm, pagamento: event.target.value })} placeholder="Ex.: 028/000/000" /></Field>
                  <Field label="Endereço de entrega" className="md:col-span-2"><InlineInput value={pedidoForm.entrega} onChange={(event) => setPedidoForm({ ...pedidoForm, entrega: event.target.value })} placeholder="Rua, cidade, UF, CEP" /></Field>
                  <Field label="Endereço de faturamento"><InlineInput value={pedidoForm.faturamento} onChange={(event) => setPedidoForm({ ...pedidoForm, faturamento: event.target.value })} placeholder="Endereço completo de faturamento" /></Field>
                  <Field label="Observações e instruções logísticas" className="md:col-span-3"><InlineTextarea rows={2} value={pedidoForm.obs} onChange={(event) => setPedidoForm({ ...pedidoForm, obs: event.target.value })} placeholder="Janelas de coleta, exigências do cliente, faturamento/entrega parcial..." /></Field>
                </FieldGrid>

                <SectionTitle>Produtos cadastrados</SectionTitle>
                <div className="space-y-2">
                  {pedidoItems.map((item, index) => (
                    <ItemRow key={index}>
                      <Field label="Produto *" className="md:col-span-2">
                        <NativeSelect value={item.skuId} onChange={(event) => setPedidoItem(index, "skuId", event.target.value)}>
                          <option value="">Produto cadastrado...</option>
                          {availablePedidoSkus.map((sku) => <option key={sku.id} value={sku.id}>{skuLabel(sku)}</option>)}
                        </NativeSelect>
                      </Field>
                      <Field label="Qtd. *"><InlineInput type="number" min="1" value={item.qtd} onChange={(event) => setPedidoItem(index, "qtd", event.target.value)} /></Field>
                      <Field label="Valor un."><InlineInput type="number" min="0" step=".01" value={item.valor} onChange={(event) => setPedidoItem(index, "valor", event.target.value)} /></Field>
                      <Field label="Desconto R$"><InlineInput type="number" min="0" step=".01" value={item.desconto} onChange={(event) => setPedidoItem(index, "desconto", event.target.value)} /></Field>
                      <Button type="button" variant="ghost" className="self-end px-2 text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => removePedidoItem(index)}><Trash2 className="h-4 w-4" /></Button>
                    </ItemRow>
                  ))}
                </div>
                <Button type="button" variant="outline" className="mt-2 gap-2" onClick={() => setPedidoItems([...pedidoItems, emptyPedidoItem()])}><Plus className="h-4 w-4" /> Adicionar produto</Button>
                <TotalBar qty={pedidoTotals.qtd} total={pedidoTotals.total} qtyLabel="Produtos" />
                <div className="mt-4 flex justify-end">
                  <Button className="gap-2" disabled={savingPedido || loading} onClick={savePedido}>
                    <CheckCircle2 className="h-4 w-4" /> Confirmar e liberar ao PCP
                  </Button>
                </div>
              </Panel>
              <Panel>
                <h2 className="text-xl font-heading font-semibold text-foreground">Pedidos recentes</h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">A produção e a emissão de OP permanecem sob controle do PCP.</p>
                <RecentOrders orders={orders} />
              </Panel>
            </TwoColumn>
          </section>
        )}

        {tab === "orc" && (
          <section>
            <Stats>
              <Stat value={orcamentoKpis.total} label="Orçamentos" />
              <Stat value={orcamentoKpis.abertos} label="Em elaboração" />
              <Stat value={orcamentoKpis.enviados} label="Enviados" />
              <Stat value={orcamentoKpis.aceitos} label="Aceitos" />
            </Stats>
            <TwoColumn>
              <Panel>
                <h2 className="text-xl font-heading font-semibold text-foreground">Novo orçamento</h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Pode atender prospecto ou cliente existente e conter produto ainda não cadastrado. Não cria demanda, compra ou OP.</p>
                <SectionTitle>Cliente / prospecto</SectionTitle>
                <FieldGrid>
                  <Field label="Projeto CRM2 *" className="md:col-span-3">
                    <NativeSelect value={orcamentoForm.projetoId} onChange={(event) => applyOrcamentoProject(event.target.value)}>
                      <option value="">Selecione o projeto em cotação/orçamento...</option>
                      {commercialProjects.map((project) => <option key={project.id} value={project.id}>{project.nome_projeto} — {project.cliente_nome || "sem cliente"} — {stageLabel(project.stage)}</option>)}
                    </NativeSelect>
                  </Field>
                  <Field label="Cliente cadastrado (opcional)" className="md:col-span-3">
                    <NativeSelect value={orcamentoForm.clienteId} onChange={(event) => applyOrcamentoClient(event.target.value)}>
                      <option value="">Prospecto / preenchimento manual</option>
                      {sortedClients.map((client) => <option key={client.id} value={client.id}>{clientName(client)}</option>)}
                    </NativeSelect>
                  </Field>
                  <Field label="Razão social / nome *" className="md:col-span-2"><InlineInput value={orcamentoForm.cliente} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, cliente: event.target.value })} placeholder="Cliente ou prospecto" /></Field>
                  <Field label="CNPJ"><InlineInput value={orcamentoForm.cnpj} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, cnpj: event.target.value })} placeholder="Somente números" /></Field>
                  <Field label="Contato"><InlineInput value={orcamentoForm.contato} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, contato: event.target.value })} /></Field>
                  <Field label="E-mail" className="md:col-span-2"><InlineInput type="email" value={orcamentoForm.email} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, email: event.target.value })} /></Field>
                  <Field label="Validade *"><InlineInput type="date" value={orcamentoForm.validade} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, validade: event.target.value })} /></Field>
                  <Field label="Pagamento" className="md:col-span-2"><InlineInput value={orcamentoForm.pagamento} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, pagamento: event.target.value })} placeholder="Condição proposta" /></Field>
                  <Field label="Frete proposto"><NativeSelect value={orcamentoForm.frete} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, frete: event.target.value })}><option value="FOB">FOB — cliente coleta</option><option value="CIF">CIF — Kuryos entrega</option></NativeSelect></Field>
                </FieldGrid>

                <SectionTitle>Itens e especificação comercial</SectionTitle>
                <div className="space-y-2">
                  {orcamentoItems.map((item, index) => (
                    <ItemRow key={index}>
                      <Field label="Produto / serviço *" className="md:col-span-2"><InlineInput value={item.descricao} onChange={(event) => setOrcamentoItem(index, "descricao", event.target.value)} placeholder="Nome comercial" /></Field>
                      <Field label="Qtd."><InlineInput type="number" min="1" value={item.qtd} onChange={(event) => setOrcamentoItem(index, "qtd", event.target.value)} /></Field>
                      <Field label="Valor un."><InlineInput type="number" min="0" step=".01" value={item.valor} onChange={(event) => setOrcamentoItem(index, "valor", event.target.value)} /></Field>
                      <Field label="Desconto R$"><InlineInput type="number" min="0" step=".01" value={item.desconto} onChange={(event) => setOrcamentoItem(index, "desconto", event.target.value)} /></Field>
                      <Button type="button" variant="ghost" className="self-end px-2 text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => removeOrcamentoItem(index)}><Trash2 className="h-4 w-4" /></Button>
                      <Field label="Especificação técnica/comercial" className="md:col-span-6"><InlineInput value={item.especificacao} onChange={(event) => setOrcamentoItem(index, "especificacao", event.target.value)} placeholder="Volume, embalagem, arte, materiais, MOQ, requisitos..." /></Field>
                    </ItemRow>
                  ))}
                </div>
                <Button type="button" variant="outline" className="mt-2 gap-2" onClick={() => setOrcamentoItems([...orcamentoItems, emptyOrcamentoItem()])}><Plus className="h-4 w-4" /> Adicionar item</Button>
                <TotalBar qty={orcamentoTotals.qtd} total={orcamentoTotals.total} qtyLabel="Itens" />

                <SectionTitle>Evidência e observações</SectionTitle>
                <FieldGrid>
                  <Field label="Pedido, briefing, arte ou aceite do cliente" className="md:col-span-3"><InlineTextarea rows={2} value={orcamentoForm.evidencia} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, evidencia: event.target.value })} placeholder="Referência/descrição do documento e como foi recebido" /></Field>
                  <Field label="Observações" className="md:col-span-3"><InlineTextarea rows={2} value={orcamentoForm.obs} onChange={(event) => setOrcamentoForm({ ...orcamentoForm, obs: event.target.value })} /></Field>
                </FieldGrid>
                <div className="mt-4 flex justify-end gap-2">
                  <Button className="gap-2" disabled={savingOrcamento || loading} onClick={() => saveOrcamento("rascunho")}><FileText className="h-4 w-4" /> Salvar rascunho</Button>
                  <Button variant="outline" className="gap-2" disabled={savingOrcamento || loading} onClick={() => saveOrcamento("enviado")}><Send className="h-4 w-4" /> Marcar enviado</Button>
                </div>
              </Panel>
              <Panel>
                <h2 className="text-xl font-heading font-semibold text-foreground">Orçamentos recentes</h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">O envio e o aceite ficam registrados. Produto novo aceito abre tarefa para cadastro; nunca entra no PCP.</p>
                <RecentProposals rows={proposalRows} onEdit={editProposal} onSend={markProposalSent} onAccept={markProposalAccepted} />
              </Panel>
            </TwoColumn>
          </section>
        )}

        {tab === "cad" && (
          <Panel>
            <h2 className="text-xl font-heading font-semibold text-foreground">Solicitações de cadastro de produto</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Nascem apenas de orçamento aceito com item ainda não cadastrado. A anamnese e o kick-off ocorrerão no fluxo de cadastro; não há impacto no PCP antes do produto existir.</p>
            <PendingCadastro rows={pendingCadastroRows} />
          </Panel>
        )}

        {tab === "docs" && (
          <TwoColumn>
            <Panel>
              <h2 className="text-xl font-heading font-semibold text-foreground">Documentos, aditivos e cancelamento</h2>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">O pedido original é preservado. Anexe o pedido do cliente agora; use o mesmo fluxo para o aceite posterior.</p>
              <FieldGrid>
                <Field label="Pedido comercial" className="md:col-span-3">
                  <NativeSelect value={docOrderId} onChange={(event) => setDocOrderId(event.target.value)}>
                    <option value="">Selecione...</option>
                    {orders.map((order) => <option key={order.id} value={order.id}>{order.numero_pedido || order.id} — {order.cliente?.nome || order.cliente?.razao_social || "cliente"}</option>)}
                  </NativeSelect>
                </Field>
                <Field label="Tipo de anexo"><NativeSelect><option>Pedido do cliente</option><option>Aceite do cliente</option><option>Briefing</option><option>Arte</option></NativeSelect></Field>
                <Field label="Arquivo" className="md:col-span-2"><Input type="file" accept="application/pdf,image/*,.doc,.docx" className="text-sm" onChange={(event) => setDocFile(event.target.files?.[0] || null)} /></Field>
                <Field label="Motivo" className="md:col-span-3"><InlineTextarea rows={2} value={docMotivo} onChange={(event) => setDocMotivo(event.target.value)} placeholder="Obrigatório para aditivo e cancelamento" /></Field>
              </FieldGrid>
              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <Button variant="outline" className="gap-2" onClick={openOrderPdf}><FileText className="h-4 w-4" /> Imprimir / salvar PDF</Button>
                <Button variant="outline" className="gap-2" onClick={uploadDoc}><Paperclip className="h-4 w-4" /> Anexar</Button>
                <Button variant="outline" className="border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300 dark:hover:bg-amber-950/50">Registrar aditivo</Button>
                <Button variant="outline" className="gap-2 border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive"><XCircle className="h-4 w-4" /> Cancelar saldo</Button>
              </div>
            </Panel>
            <Panel>
              <h2 className="text-xl font-heading font-semibold text-foreground">Linha do tempo</h2>
              <Timeline order={selectedDocOrder} />
            </Panel>
          </TwoColumn>
        )}
      </div>
    </main>
  );
}

function Stats({ children }) {
  return <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>;
}

function Stat({ value, label }) {
  return (
    <div className="rounded-lg border border-border/70 bg-card/90 p-4 text-card-foreground shadow-sm backdrop-blur">
      <b className="block text-2xl font-semibold text-primary">{value}</b>
      <span className="text-xs font-medium uppercase text-muted-foreground">{label}</span>
    </div>
  );
}

function TwoColumn({ children }) {
  return <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.8fr)]">{children}</div>;
}

function Panel({ children }) {
  return <div className="rounded-lg border border-border/70 bg-card/90 p-4 text-card-foreground shadow-sm backdrop-blur sm:p-5">{children}</div>;
}

function SectionTitle({ children }) {
  return <div className="mb-3 mt-5 border-b border-border pb-2 text-xs font-semibold uppercase text-muted-foreground">{children}</div>;
}

function FieldGrid({ children }) {
  return <div className="grid gap-3 md:grid-cols-3">{children}</div>;
}

function Field({ label, className = "", children }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function InlineInput(props) {
  return <Input {...props} className={`text-sm ${props.className || ""}`} />;
}

function InlineTextarea(props) {
  return <Textarea {...props} className={`text-sm ${props.className || ""}`} />;
}

function NativeSelect({ className = "", children, ...props }) {
  return (
    <select {...props} className={`h-10 w-full rounded-lg border border-input bg-background/75 px-3 py-2 text-sm text-foreground shadow-sm outline-none transition-all focus:border-ring focus:ring-2 focus:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}>
      {children}
    </select>
  );
}

function ItemRow({ children }) {
  return <div className="grid items-end gap-2 rounded-lg border border-border bg-muted/20 p-3 md:grid-cols-[minmax(0,2fr)_80px_105px_105px_35px]">{children}</div>;
}

function TotalBar({ qtyLabel, qty, total }) {
  return (
    <div className="mt-3 flex justify-end gap-6 border-t border-border pt-3 text-sm text-muted-foreground">
      <span>{qtyLabel} <b className="text-base text-primary">{Number(qty || 0).toLocaleString("pt-BR")}</b></span>
      <span>Total <b className="text-base text-primary">{money(total)}</b></span>
    </div>
  );
}

function RecentOrders({ orders }) {
  if (!orders.length) return <div className="p-6 text-center text-sm text-muted-foreground">Nenhum pedido comercial.</div>;
  return (
    <table className="mt-5 w-full border-collapse text-sm">
      <thead>
        <tr>{["Pedido", "Cliente", "Status"].map((header) => <th key={header} className="border-b border-border px-2 py-2 text-left text-xs font-semibold uppercase text-muted-foreground">{header}</th>)}</tr>
      </thead>
      <tbody>
        {orders.slice(0, 12).map((order) => (
          <tr key={order.id} className="hover:bg-muted/30">
            <td className="border-b border-border px-2 py-3 align-top"><b>{order.numero_pedido || order.id}</b><br /><small className="text-muted-foreground">{String(order.data_pedido || order.created_at || "").slice(0, 10)}</small></td>
            <td className="border-b border-border px-2 py-3 align-top">{order.cliente?.nome || order.cliente?.razao_social || "—"}</td>
            <td className="border-b border-border px-2 py-3 align-top"><StatusBadge status={order.status} /><br /><small className="text-muted-foreground">{order.frete?.tipo || ""}</small></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecentProposals({ rows, onEdit, onSend, onAccept }) {
  if (!rows.length) return <div className="p-6 text-center text-sm text-muted-foreground">Nenhum orçamento.</div>;
  return (
    <table className="mt-5 w-full border-collapse text-sm">
      <thead>
        <tr>{["Orçamento", "Cliente", "Situação", ""].map((header) => <th key={header} className="border-b border-border px-2 py-2 text-left text-xs font-semibold uppercase text-muted-foreground">{header}</th>)}</tr>
      </thead>
      <tbody>
        {rows.slice(0, 12).map(({ project, proposal }) => (
          <tr key={project.id} className="hover:bg-muted/30">
            <td className="border-b border-border px-2 py-3 align-top"><b>{proposal?.id || project.id}</b><br /><small className="text-muted-foreground">{stageLabel(project.stage)}</small></td>
            <td className="border-b border-border px-2 py-3 align-top">{project.cliente_nome || proposal?.cliente_nome || "—"}</td>
            <td className="border-b border-border px-2 py-3 align-top"><StatusBadge status={proposal?.negociacao_status === "aprovado" ? "ACEITO" : proposal?.status || "EM_ELABORACAO"} /></td>
            <td className="border-b border-border px-2 py-3 align-top">
              {!proposal && <Button size="sm" variant="outline" onClick={() => onEdit(project.id)}>Abrir</Button>}
              {proposal && proposal.status !== "enviado" && <Button size="sm" variant="outline" onClick={() => onSend(project.id)}>Marcar enviado</Button>}
              {proposal?.status === "enviado" && proposal?.negociacao_status !== "aprovado" && <Button size="sm" variant="outline" className="border-green-300 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-900/60 dark:bg-green-950/30 dark:text-green-300 dark:hover:bg-green-950/50" onClick={() => onAccept(project.id)}>Registrar aceite</Button>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PendingCadastro({ rows }) {
  if (!rows.length) return <div className="mt-5 p-6 text-center text-sm text-muted-foreground">Nenhuma solicitação pendente.</div>;
  return (
    <table className="mt-5 w-full border-collapse text-sm">
      <thead>
        <tr>{["Solicitação", "Cliente", "Item", "Status"].map((header) => <th key={header} className="border-b border-border px-2 py-2 text-left text-xs font-semibold uppercase text-muted-foreground">{header}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map(({ id, project, item, proposal }) => (
          <tr key={id} className="hover:bg-muted/30">
            <td className="border-b border-border px-2 py-3"><b>{proposal?.id || project.id}</b></td>
            <td className="border-b border-border px-2 py-3">{project.cliente_nome || "—"}</td>
            <td className="border-b border-border px-2 py-3">{item.item || "—"}</td>
            <td className="border-b border-border px-2 py-3"><StatusBadge status="PENDENTE_CADASTRO" /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Timeline({ order }) {
  if (!order) return <p className="mt-5 border-l-2 border-border pl-4 text-sm text-muted-foreground">Selecione um pedido para consultar o histórico.</p>;
  const events = [
    { tipo: "CRIADO", texto: `Pedido ${order.numero_pedido || order.id}`, em: order.created_at, por: order.created_by_name },
    ...(order.attachments || []).map((attachment) => ({ tipo: "DOCUMENTO", texto: attachment.original_filename, em: attachment.uploaded_at, por: attachment.uploaded_by_name })),
    ...(order.updated_at ? [{ tipo: "ATUALIZADO", texto: order.status || "", em: order.updated_at, por: order.updated_by_name }] : []),
  ].filter((event) => event.em || event.texto);
  return (
    <div className="mt-5 border-l-2 border-border pl-4">
      {events.map((event, index) => (
        <div key={`${event.tipo}-${index}`} className="relative mb-3 text-sm before:absolute before:left-[-21px] before:top-[3px] before:h-2 before:w-2 before:rounded-full before:bg-primary">
          <b>{event.tipo}</b><br />{event.texto}<small className="block text-muted-foreground">{String(event.em || "").slice(0, 19)} {event.por ? `· ${event.por}` : ""}</small>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }) {
  const normalized = String(status || "—").replaceAll("_", " ").toUpperCase();
  const cls = normalized.includes("ACEITO") || normalized.includes("CONFIRMADO") || normalized.includes("CONCLUIDO")
    ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-300"
    : normalized.includes("ENVIADO") || normalized.includes("ELABORACAO") || normalized.includes("RASCUNHO")
      ? "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
      : "bg-muted text-muted-foreground";
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{normalized}</span>;
}
