import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { formatApiError } from "@/lib/formatError";
import {
  ArrowLeft, Building2, CheckCircle2, ClipboardList, FileText,
  Loader2, Mail, PackagePlus, Paperclip, Plus, ReceiptText, Search, Send,
  ShieldCheck, Sparkles, Trash2, Truck,
} from "lucide-react";
import { toast } from "sonner";

const blankItem = () => ({
  item: "",
  item_origem: "cadastrado",
  sku_id: "",
  pd_request_id: "",
  pd_concluido: false,
  codigo_kuryos: "",
  codigo_cliente: "NA",
  prazo_entrega: "",
  valor_unitario: "",
  valor_unitario_currency: "BRL",
  qtd: "",
});

const blankInsumo = () => ({
  item: "",
  especificacoes: "",
  quantidade: "",
  responsavel: "Kuryos",
});

const initialForm = () => ({
  modo_teste: false,
  cliente_id: "",
  cliente: "",
  data: new Date().toISOString().slice(0, 10),
  resumo: "",
  gerado_por: "",
  cnpj: "",
  razao_social: "",
  pedido_num_cliente: "",
  cidade_uf: "",
  responsavel: "",
  telefone: "",
  email: "",
  tipo_frete: "FOB",
  cidade_uf_frete: "",
  endereco: "",
  prazo_coleta: "",
  prazo_pgto_texto: "",
  pct_nf: "",
  pedido_cliente_file_name: "",
  enviar_email: false,
  email_destinatario: "",
  observacoes: "",
});

function brl(value) {
  const n = Number(value || 0);
  return `R$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function numberValue(value) {
  const n = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

function maskCnpj(value) {
  const digits = String(value || "").replace(/\D/g, "").slice(0, 14);
  if (digits.length <= 2) return digits;
  if (digits.length <= 5) return `${digits.slice(0, 2)}.${digits.slice(2)}`;
  if (digits.length <= 8) return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5)}`;
  if (digits.length <= 12) return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8)}`;
  return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12)}`;
}

function clientName(client) {
  return client.nome_empresa || client.nome || client.razao_social || "";
}

function clientKey(client) {
  const cnpj = String(client.cnpj || client.cnpj_normalized || "").replace(/\D/g, "");
  return cnpj || clientName(client).trim().toLowerCase();
}

function cityUfFromClient(client) {
  if (client.cidade_uf) return client.cidade_uf;
  const cidade = client.cidade || client.city || client.endereco?.cidade || "";
  const uf = client.uf || client.estado || client.endereco?.uf || "";
  return cidade && uf ? `${cidade}/${uf}` : (cidade || uf || "");
}

function addressFromClient(client) {
  if (client.endereco_completo) return client.endereco_completo;
  if (typeof client.endereco === "string") return client.endereco;
  const e = client.endereco || {};
  return [e.logradouro, e.numero, e.bairro, e.cidade, e.uf, e.cep].filter(Boolean).join(", ");
}

function Section({ number, title, icon: Icon, children, description }) {
  return (
    <Card className="overflow-hidden border-border/70 shadow-sm">
      <CardHeader className="border-b bg-muted/20 px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">{number}</span>
          <div className="min-w-0 flex-1">
            <CardTitle className="flex items-center gap-2 text-base">
              {Icon && <Icon className="h-4 w-4 text-primary" />}
              {title}
            </CardTitle>
            {description && <CardDescription className="mt-1 text-xs">{description}</CardDescription>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-5">{children}</CardContent>
    </Card>
  );
}

function Field({ label, children, hint, className = "" }) {
  return (
    <div className={className}>
      <Label className="text-xs font-semibold text-muted-foreground">{label}</Label>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function OrderGeneratorPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [form, setForm] = useState(() => ({ ...initialForm(), gerado_por: user?.name || "" }));
  const [items, setItems] = useState([blankItem()]);
  const [insumos, setInsumos] = useState([]);
  const [clients, setClients] = useState([]);
  const [skus, setSkus] = useState([]);
  const [skuSource, setSkuSource] = useState("pd");
  const [loadingRefs, setLoadingRefs] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [pedidoClienteFile, setPedidoClienteFile] = useState(null);
  const [downloadAfterCreate, setDownloadAfterCreate] = useState(true);

  const loadRefs = useCallback(async () => {
    setLoadingRefs(true);
    try {
      const [clientsRes, skusRes] = await Promise.all([
        api.get("/crm/clients").catch(() => ({ data: [] })),
        api.get("/crm/skus", { params: { status: "ativo", pd_concluidos: true } }).catch(() => ({ data: [] })),
      ]);
      setClients(Array.isArray(clientsRes.data) ? clientsRes.data : []);
      let skuData = Array.isArray(skusRes.data) ? skusRes.data : [];
      if (!skuData.length) {
        const fallback = await api.get("/crm/skus", { params: { status: "ativo" } }).catch(() => ({ data: [] }));
        skuData = Array.isArray(fallback.data) ? fallback.data : [];
        setSkuSource("all");
      } else {
        setSkuSource("pd");
      }
      setSkus(skuData);
    } finally {
      setLoadingRefs(false);
    }
  }, []);

  useEffect(() => { loadRefs(); }, [loadRefs]);

  const total = useMemo(() => items.reduce((sum, item) => (
    sum + numberValue(item.qtd) * numberValue(item.valor_unitario)
  ), 0), [items]);

  const validItems = useMemo(() => items.filter((item) => item.item.trim()), [items]);

  const uniqueClients = useMemo(() => {
    const map = new Map();
    for (const client of clients) {
      const key = clientKey(client);
      if (!key) continue;
      const current = map.get(key);
      if (!current || (client.cli4 && !current.cli4) || (client.cnpj && !current.cnpj)) {
        map.set(key, client);
      }
    }
    return Array.from(map.values()).sort((a, b) => clientName(a).localeCompare(clientName(b)));
  }, [clients]);
  const clientOptions = useMemo(() => Array.from(new Set(uniqueClients.map(clientName).filter(Boolean))).sort(), [uniqueClients]);
  const skuOptions = useMemo(() => skus
    .filter((sku) => sku.status === "ativo")
    .filter((sku) => String(sku.codigo_interno || "").trim())
    .filter((sku) => !form.cliente_id || sku.cliente_id === form.cliente_id)
    .sort((a, b) => Number(!!b.pd_concluido) - Number(!!a.pd_concluido) || String(a.nome_produto || "").localeCompare(String(b.nome_produto || ""))),
    [skus, form.cliente_id]
  );

  const setField = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const updateItem = (index, field, value) => setItems((prev) => prev.map((item, idx) => idx === index ? { ...item, [field]: value } : item));
  const updateInsumo = (index, field, value) => setInsumos((prev) => prev.map((item, idx) => idx === index ? { ...item, [field]: value } : item));

  const applyClient = (name) => {
    setField("cliente", name);
    const found = uniqueClients.find((client) => clientName(client).toLowerCase() === name.toLowerCase());
    if (!found) {
      setForm((prev) => ({ ...prev, cliente: name, cliente_id: "" }));
      return;
    }
    setForm((prev) => ({
      ...prev,
      cliente_id: found.id || "",
      cliente: name,
      cnpj: found.cnpj || prev.cnpj,
      razao_social: found.razao_social || found.nome_empresa || prev.razao_social,
      cidade_uf: cityUfFromClient(found) || prev.cidade_uf,
      cidade_uf_frete: prev.cidade_uf_frete || cityUfFromClient(found),
      endereco: prev.endereco || addressFromClient(found),
      responsavel: found.contato_principal?.nome || found.responsavel || prev.responsavel,
      telefone: found.contato_principal?.whatsapp || found.telefone || prev.telefone,
      email: found.contato_principal?.email || found.email || prev.email,
      email_destinatario: prev.email_destinatario || found.contato_principal?.email || found.email || "",
    }));
  };

  const setItemOrigin = (index, origin) => {
    setItems((prev) => prev.map((item, idx) => {
      if (idx !== index) return item;
      if (origin === "manual") {
        return {
          ...item,
          item_origem: "manual",
          sku_id: "",
          pd_request_id: "",
          pd_concluido: false,
          codigo_kuryos: "A definir",
        };
      }
      return { ...item, item_origem: "cadastrado", codigo_kuryos: item.codigo_kuryos === "A definir" ? "" : item.codigo_kuryos };
    }));
  };

  const syncInsumosFromSku = (sku) => {
    const bom = sku.composicao_embalagem || sku.bom_embalagem || sku.bom_items || sku.insumos || [];
    if (!Array.isArray(bom) || bom.length === 0) return;
    setInsumos(bom.map((row) => ({
      item: row.nome_material || row.nome || row.item || row.codigo_material || "",
      especificacoes: [row.codigo_material || row.codigo_interno, row.tipo, row.observacoes].filter(Boolean).join(" | "),
      quantidade: row.quantidade_por_unidade || row.quantidade || "",
      responsavel: "Kuryos",
    })));
  };

  const applySku = (index, code) => {
    updateItem(index, "codigo_kuryos", code);
    const sku = skus.find((item) => String(item.codigo_interno || "").toLowerCase() === String(code || "").toLowerCase() || item.id === code);
    if (!sku) return;
    setItems((prev) => prev.map((item, idx) => idx === index ? {
      ...item,
      item_origem: "cadastrado",
      sku_id: sku.id || "",
      pd_request_id: sku.pd_request_id || "",
      pd_concluido: !!sku.pd_concluido,
      codigo_kuryos: sku.codigo_interno || code,
      item: sku.nome_produto || item.item || "",
      valor_unitario: item.valor_unitario || sku.preco_unitario || "",
      valor_unitario_currency: sku.preco_unitario_currency || "BRL",
    } : item));
    syncInsumosFromSku(sku);
  };

  const validate = () => {
    if (!form.cliente.trim()) return "Informe o cliente.";
    const cnpjDigits = String(form.cnpj || "").replace(/\D/g, "");
    if (cnpjDigits && cnpjDigits.length !== 14) return "CNPJ deve ter 14 digitos.";
    if (!validItems.length) return "Inclua pelo menos um item com descricao.";
    const invalidQty = validItems.some((item) => numberValue(item.qtd) <= 0);
    if (invalidQty) return "Todos os itens preenchidos precisam de quantidade maior que zero.";
    const invalidValue = validItems.some((item) => numberValue(item.valor_unitario) < 0);
    if (invalidValue) return "Valor unitario nao pode ser negativo.";
    const pctNf = form.pct_nf === "" ? null : numberValue(form.pct_nf);
    if (pctNf !== null && (pctNf < 0 || pctNf > 100)) return "% NF deve ficar entre 0 e 100.";
    if (form.enviar_email && !String(form.email_destinatario || form.email || "").includes("@")) return "Informe um e-mail valido para o rascunho.";
    const duplicatedCodes = validItems
      .map((item) => String(item.codigo_kuryos || "").trim().toUpperCase())
      .filter((code) => code && code !== "A DEFINIR" && code !== "NA");
    if (new Set(duplicatedCodes).size !== duplicatedCodes.length) return "Ha SKU duplicado nos itens do pedido.";
    const invalidSku = validItems.find((item) => {
      const code = item.codigo_kuryos.trim();
      if (!code || code.toLowerCase() === "a definir") return false;
      if (item.item_origem === "manual") return false;
      return !skuOptions.some((sku) => sku.codigo_interno === code);
    });
    if (invalidSku) {
      return skuSource === "pd"
        ? `SKU ${invalidSku.codigo_kuryos} nao vem dos concluidos/aprovados do P&D deste cliente. Se for produto novo, deixe como A definir.`
        : `SKU ${invalidSku.codigo_kuryos} nao foi encontrado para este cliente.`;
    }
    return "";
  };

  const buildPayload = () => {
    const skuTrace = validItems
      .filter((item) => item.codigo_kuryos && item.codigo_kuryos !== "A definir")
      .map((item) => `${item.pd_concluido ? "SKU P&D concluido" : "SKU ativo"}: ${item.codigo_kuryos}${item.sku_id ? ` (sku_id ${item.sku_id})` : ""}`)
      .join("\n");
    const cadastroPendente = validItems
      .filter((item) => item.item_origem === "manual" || !item.sku_id)
      .map((item) => `Cadastro de produto pendente: ${item.item.trim()} (${item.codigo_kuryos?.trim() || "A definir"})`)
      .join("\n");

    const cleanItems = validItems.map((item) => {
      const qtd = numberValue(item.qtd);
      const valor = numberValue(item.valor_unitario);
      return {
        item: item.item.trim(),
        sku_id: item.sku_id || null,
        pd_request_id: item.pd_request_id || null,
        pd_concluido: !!item.pd_concluido,
        codigo_kuryos: item.sku_id ? item.codigo_kuryos.trim() : "A definir",
        codigo_cliente: item.codigo_cliente.trim() || "NA",
        prazo_entrega: item.prazo_entrega ? `${item.prazo_entrega} dias` : "",
        valor_unitario: valor,
        valor_unitario_currency: item.valor_unitario_currency || "BRL",
        desconto_percentual: 0,
        qtd,
        valor_total: Number((qtd * valor).toFixed(2)),
        tipo_servico: "producao",
      };
    });

    const cleanInsumos = insumos
      .filter((item) => item.item.trim() || item.especificacoes.trim() || item.quantidade)
      .map((item) => ({
        item: item.item.trim(),
        especificacoes: [item.especificacoes.trim(), item.responsavel ? `Responsavel: ${item.responsavel}` : ""].filter(Boolean).join(" | "),
        quantidade: String(item.quantidade || ""),
      }));

    const notes = [
      form.resumo ? `Resumo arquivo: ${form.resumo}` : "",
      form.gerado_por ? `Gerado por: ${form.gerado_por}` : "",
      form.pedido_num_cliente ? `Pedido do cliente: ${form.pedido_num_cliente}` : "",
      form.pct_nf ? `% NF: ${form.pct_nf}` : "",
      skuTrace,
      cadastroPendente,
      form.pedido_cliente_file_name ? `Anexo do cliente: ${form.pedido_cliente_file_name}` : "",
      form.enviar_email ? `Criar rascunho para cliente: ${form.email_destinatario || "sem destinatario"}` : "",
      form.observacoes,
    ].filter(Boolean).join("\n");

    return {
      data_pedido: form.data,
      pedido_cliente_ref: form.pedido_num_cliente.trim(),
      gerador_origem: "gerador_web",
      tipo_servico: "producao",
      nivel_formalizacao: 1,
      cliente: {
        nome: form.cliente,
        razao_social: form.razao_social,
        cnpj: form.cnpj,
        cidade_uf: form.cidade_uf,
        responsavel: form.responsavel,
        telefone: form.telefone,
        email: form.email,
      },
      frete: {
        tipo: form.tipo_frete,
        endereco: form.endereco,
        cidade_uf: form.cidade_uf_frete,
        prazo_coleta: form.prazo_coleta,
      },
      items: cleanItems,
      condicoes: {
        prazo: form.prazo_pgto_texto,
        forma_pgto: form.pct_nf ? `%NF ${form.pct_nf}` : "",
        condicao_pagamento: "000/000/000",
      },
      insumos: cleanInsumos,
      observacoes: notes,
    };
  };

  const downloadOrderPdf = async (order) => {
    const response = await api.get(`/orders/${order.id}/pdf`, { responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `ordem_producao_${order.numero_pedido || order.id}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const openReview = () => {
    const error = validate();
    if (error) return toast.error(error);
    setReviewOpen(true);
  };

  const saveOrder = async () => {
    if (form.modo_teste) {
      toast.info("Modo teste: revisao validada sem gravar pedido nem consumir numeracao.");
      setReviewOpen(false);
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/orders/generator", buildPayload());
      const warnings = [];
      if (pedidoClienteFile) {
        try {
          const formData = new FormData();
          formData.append("file", pedidoClienteFile);
          await api.post(`/orders/${data.id}/attachments`, formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch (err) {
          warnings.push("anexo nao enviado");
        }
      }
      if (downloadAfterCreate) {
        try {
          await downloadOrderPdf(data);
        } catch (err) {
          warnings.push("PDF nao baixado");
        }
      }
      if (warnings.length) {
        toast.warning(`Pedido #${data.numero_pedido} criado, mas ${warnings.join(" e ")}.`);
      } else {
        toast.success(`Pedido #${data.numero_pedido} criado${pedidoClienteFile ? " com anexo" : ""}`);
      }
      navigate(`/orders/${data.id}`);
    } catch (err) {
      toast.error(formatApiError(err) || "Erro ao criar pedido");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full overflow-auto bg-muted/20">
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <Button variant="ghost" size="sm" className="-ml-2 mb-2 gap-1.5" onClick={() => navigate("/orders")}>
              <ArrowLeft className="h-4 w-4" /> Pedidos
            </Button>
            <h1 className="flex items-center gap-2 text-2xl font-heading font-semibold tracking-tight">
              <ReceiptText className="h-6 w-6 text-primary" />
              Gerador de Pedidos
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Fluxo rapido para montar pedido comercial, revisar e gravar no ERP.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="gap-1.5 px-3 py-1.5">
              <ShieldCheck className="h-3.5 w-3.5" />
              Usa governanca atual de pedidos
            </Badge>
            {loadingRefs && <Badge variant="secondary" className="gap-1.5"><Loader2 className="h-3 w-3 animate-spin" /> carregando cadastros</Badge>}
            {!loadingRefs && (
              <Badge variant={skuSource === "pd" ? "secondary" : "outline"} className="gap-1.5">
                <ShieldCheck className="h-3 w-3" />
                {skuSource === "pd" ? "SKUs: P&D concluido" : "SKUs: ativos sem filtro P&D"}
              </Badge>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
          <div className="space-y-5">
            <Card className="border-blue-200 bg-blue-50/70 dark:border-blue-900 dark:bg-blue-950/20">
              <CardContent className="flex items-start gap-3 p-4">
                <Checkbox checked={form.modo_teste} onCheckedChange={(checked) => setField("modo_teste", !!checked)} className="mt-0.5 h-7 w-7 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-blue-900 dark:text-blue-200">Modo teste</p>
                  <p className="text-xs text-blue-800/80 dark:text-blue-200/70">
                    Valida e revisa o pedido sem gravar no banco e sem consumir numeracao.
                  </p>
                </div>
              </CardContent>
            </Card>

            <Section number="1" title="Informacoes Iniciais" icon={ClipboardList}>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field label="Cliente *" className="md:col-span-2" hint="Escolha uma sugestao para evitar grafias diferentes do mesmo cliente.">
                  <div className="relative">
                    <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input list="order-generator-clients" value={form.cliente} onChange={(e) => applyClient(e.target.value)} className="pl-9" placeholder="Nome do cliente" />
                    <datalist id="order-generator-clients">{clientOptions.map((name) => <option key={name} value={name} />)}</datalist>
                  </div>
                </Field>
                <Field label="Data"><Input type="date" value={form.data} onChange={(e) => setField("data", e.target.value)} /></Field>
                <Field label="Resumo p/ nome do arquivo"><Input value={form.resumo} onChange={(e) => setField("resumo", e.target.value)} placeholder="ex: 60k MR125" /></Field>
                <Field label="Gerado por" className="md:col-span-2" hint="Fica registrado na observacao interna do pedido.">
                  <Input value={form.gerado_por} onChange={(e) => setField("gerado_por", e.target.value)} placeholder="seu nome" />
                </Field>
              </div>
            </Section>

            <Section number="2" title="Dados do Cliente" icon={Building2}>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field label="CNPJ" className="md:col-span-2" hint="Ao escolher cliente cadastrado, razao social e contato sao preenchidos automaticamente.">
                  <Input value={form.cnpj} onChange={(e) => setField("cnpj", maskCnpj(e.target.value))} placeholder="00.000.000/0000-00" inputMode="numeric" />
                </Field>
                <Field label="Razao Social" className="md:col-span-2"><Input value={form.razao_social} onChange={(e) => setField("razao_social", e.target.value)} /></Field>
                <Field label="# Pedido do Cliente"><Input value={form.pedido_num_cliente} onChange={(e) => setField("pedido_num_cliente", e.target.value)} /></Field>
                <Field label="Cidade / UF"><Input value={form.cidade_uf} onChange={(e) => setField("cidade_uf", e.target.value)} /></Field>
                <Field label="Responsavel"><Input value={form.responsavel} onChange={(e) => setField("responsavel", e.target.value)} /></Field>
                <Field label="Telefone"><Input value={form.telefone} onChange={(e) => setField("telefone", e.target.value)} /></Field>
                <Field label="e-mail" className="md:col-span-2"><Input type="email" value={form.email} onChange={(e) => setField("email", e.target.value)} /></Field>
              </div>
            </Section>

            <Section number="3" title="Frete" icon={Truck}>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field label="Tipo de Frete">
                  <Select value={form.tipo_frete} onValueChange={(value) => setField("tipo_frete", value)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="FOB">FOB</SelectItem><SelectItem value="CIF">CIF</SelectItem></SelectContent>
                  </Select>
                </Field>
                <Field label="Cidade / UF (frete)"><Input value={form.cidade_uf_frete} onChange={(e) => setField("cidade_uf_frete", e.target.value)} /></Field>
                <Field label="Endereco" className="md:col-span-2"><Input value={form.endereco} onChange={(e) => setField("endereco", e.target.value)} /></Field>
                <Field label="Prazo p/ Coleta" className="md:col-span-2"><Input value={form.prazo_coleta} onChange={(e) => setField("prazo_coleta", e.target.value)} placeholder="ex: Ate 3 dias uteis apos liberacao" /></Field>
              </div>
            </Section>

            <Section number="4" title="Itens do Pedido" icon={PackagePlus}>
              <div className="space-y-3">
                {items.map((item, index) => (
                  <div key={index} className="rounded-lg border bg-muted/20 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">Item {index + 1}</p>
                      {items.length > 1 && (
                        <Button variant="ghost" size="sm" className="h-8 gap-1 text-red-600 hover:text-red-700" onClick={() => setItems((prev) => prev.filter((_, idx) => idx !== index))}>
                          <Trash2 className="h-3.5 w-3.5" /> remover
                        </Button>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-6">
                      <Field label="Tipo de item" className="md:col-span-2">
                        <Select value={item.item_origem} onValueChange={(value) => setItemOrigin(index, value)}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="cadastrado">Selecionar item cadastrado</SelectItem>
                            <SelectItem value="manual">Digitar item novo</SelectItem>
                          </SelectContent>
                        </Select>
                      </Field>
                      {item.item_origem === "cadastrado" ? (
                        <Field label="Produto cadastrado" className="md:col-span-4" hint="Seleciona produto ativo gerado pelo fluxo de amostra aprovada/SKU.">
                          <Select value={item.codigo_kuryos || ""} onValueChange={(value) => applySku(index, value)}>
                            <SelectTrigger><SelectValue placeholder="Selecione o SKU/produto" /></SelectTrigger>
                            <SelectContent>
                              {skuOptions.map((sku) => (
                                <SelectItem key={sku.id} value={sku.codigo_interno}>
                                  {sku.codigo_interno} - {sku.nome_produto || "Produto"}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </Field>
                      ) : (
                        <Field label="Descricao do Item *" className="md:col-span-4" hint="Item digitado fica com SKU A definir e pendencia para Cadastros.">
                          <Input value={item.item} onChange={(e) => updateItem(index, "item", e.target.value)} />
                        </Field>
                      )}
                      {item.item_origem === "cadastrado" && (
                        <Field label="Descricao do Item *" className="md:col-span-6">
                          <Input value={item.item} onChange={(e) => updateItem(index, "item", e.target.value)} />
                        </Field>
                      )}
                      {item.item_origem === "manual" && (
                        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200 md:col-span-6">
                          Este item sera salvo como "A definir" e marcado nas observacoes para acompanhamento do setor de Cadastros.
                        </div>
                      )}
                      <Field label="Codigo Kuryos" className="md:col-span-3" hint="Automatico quando o produto cadastrado e selecionado.">
                        <Input
                          list="order-generator-skus"
                          value={item.codigo_kuryos}
                          onChange={(e) => item.item_origem === "manual" ? updateItem(index, "codigo_kuryos", "A definir") : applySku(index, e.target.value)}
                          placeholder="A definir"
                          disabled={item.item_origem === "manual"}
                        />
                      </Field>
                      <Field label="Codigo Cliente" className="md:col-span-3">
                        <Input value={item.codigo_cliente} onChange={(e) => updateItem(index, "codigo_cliente", e.target.value)} placeholder="NA" />
                      </Field>
                      <Field label="Prazo Entrega (dias)" className="md:col-span-2">
                        <Input type="number" min="0" value={item.prazo_entrega} onChange={(e) => updateItem(index, "prazo_entrega", e.target.value)} />
                      </Field>
                      <Field label="Valor Unitario (R$)" className="md:col-span-2">
                        <Input type="number" min="0" step="0.01" value={item.valor_unitario} onChange={(e) => updateItem(index, "valor_unitario", e.target.value)} />
                      </Field>
                      <Field label="Qtd." className="md:col-span-2">
                        <Input type="number" min="0" step="1" value={item.qtd} onChange={(e) => updateItem(index, "qtd", e.target.value)} />
                      </Field>
                    </div>
                  </div>
                ))}
                <datalist id="order-generator-skus">
                  {skuOptions.map((sku) => (
                    <option key={sku.id} value={sku.codigo_interno}>
                      {`${sku.nome_produto || ""}${sku.pd_concluido ? " - P&D concluido" : ""}`}
                    </option>
                  ))}
                </datalist>
                <Button type="button" variant="outline" className="w-full border-dashed gap-2" onClick={() => setItems((prev) => [...prev, blankItem()])}>
                  <Plus className="h-4 w-4" /> adicionar item
                </Button>

                <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-2">
                  <Field label="Prazo de Pagamento" hint='Ex: "100% em 7 dias", "50% sinal, 50% na entrega".'>
                    <Input value={form.prazo_pgto_texto} onChange={(e) => setField("prazo_pgto_texto", e.target.value)} placeholder="ex: 100% em 7 dias" />
                  </Field>
                  <Field label="% NF" hint='Aparece registrado como "%NF" nas condicoes do pedido.'>
                    <Input type="number" step="0.1" value={form.pct_nf} onChange={(e) => setField("pct_nf", e.target.value)} placeholder="ex: 50" />
                  </Field>
                </div>
              </div>
            </Section>

            <Section number="5" title="Insumos Gerais" icon={Sparkles} description="Opcional">
              <div className="space-y-3">
                {insumos.map((insumo, index) => (
                  <div key={index} className="rounded-lg border bg-muted/20 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">Insumo {index + 1}</p>
                      <Button variant="ghost" size="sm" className="h-8 gap-1 text-red-600 hover:text-red-700" onClick={() => setInsumos((prev) => prev.filter((_, idx) => idx !== index))}>
                        <Trash2 className="h-3.5 w-3.5" /> remover
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      <Field label="Item" className="md:col-span-2"><Input value={insumo.item} onChange={(e) => updateInsumo(index, "item", e.target.value)} /></Field>
                      <Field label="Especificacoes" className="md:col-span-2"><Input value={insumo.especificacoes} onChange={(e) => updateInsumo(index, "especificacoes", e.target.value)} /></Field>
                      <Field label="Quantidade"><Input type="number" min="0" value={insumo.quantidade} onChange={(e) => updateInsumo(index, "quantidade", e.target.value)} /></Field>
                      <Field label="Responsavel"><Input value={insumo.responsavel} onChange={(e) => updateInsumo(index, "responsavel", e.target.value)} placeholder="Kuryos" /></Field>
                    </div>
                  </div>
                ))}
                <Button type="button" variant="outline" className="w-full border-dashed gap-2" onClick={() => setInsumos((prev) => [...prev, blankInsumo()])}>
                  <Plus className="h-4 w-4" /> adicionar insumo
                </Button>
              </div>
            </Section>

            <Section number="6" title="Pedido do Cliente" icon={Paperclip} description="Opcional">
              <Field label="Anexo do cliente" hint="O arquivo sera salvo no pedido gerado e ficara disponivel no detalhe. Maximo 10 MB.">
                <Input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null;
                    setPedidoClienteFile(file);
                    setField("pedido_cliente_file_name", file?.name || "");
                  }}
                />
              </Field>
            </Section>

            <Section number="7" title="Entrega" icon={Mail}>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <Checkbox checked={downloadAfterCreate} onCheckedChange={(checked) => setDownloadAfterCreate(!!checked)} className="mt-0.5 h-7 w-7 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold">Baixar PDF apos criar o pedido</p>
                    <p className="text-xs text-muted-foreground">Tambem marca o PDF como gerado no status do pedido.</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Checkbox checked={form.enviar_email} onCheckedChange={(checked) => setField("enviar_email", !!checked)} className="mt-0.5 h-7 w-7 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold">Solicitar confirmacao do cliente</p>
                    <p className="text-xs text-muted-foreground">Fica registrado no pedido; enquanto nao aprovado, o status permanece aguardando confirmacao.</p>
                  </div>
                </div>
                <Field label="Destinatario"><Input type="email" value={form.email_destinatario} onChange={(e) => setField("email_destinatario", e.target.value)} placeholder="destinatario@empresa.com" /></Field>
                <Field label="Observacoes internas"><Textarea value={form.observacoes} onChange={(e) => setField("observacoes", e.target.value)} rows={3} /></Field>
              </div>
            </Section>
          </div>

          <aside className="lg:sticky lg:top-6 lg:h-fit">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Resumo</CardTitle>
                <CardDescription>Conferencia antes de revisar.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-lg bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Cliente</p>
                  <p className="truncate font-semibold">{form.cliente || "Nao informado"}</p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg bg-muted/40 p-3">
                    <p className="text-xs text-muted-foreground">Itens</p>
                    <p className="text-xl font-bold">{validItems.length}</p>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <p className="text-xs text-muted-foreground">Insumos</p>
                    <p className="text-xl font-bold">{insumos.length}</p>
                  </div>
                </div>
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950/20">
                  <p className="text-xs text-green-700 dark:text-green-300">Total estimado</p>
                  <p className="text-2xl font-bold text-green-700 dark:text-green-300">{brl(total)}</p>
                </div>
                <Separator />
                <Button className="w-full gap-2" size="lg" onClick={openReview}>
                  <CheckCircle2 className="h-4 w-4" /> Revisar Pedido
                </Button>
                <Button variant="outline" className="w-full gap-2" onClick={() => navigate("/orders")}>
                  <FileText className="h-4 w-4" /> Ver pedidos gerados
                </Button>
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>

      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Revisao do Pedido</DialogTitle>
          </DialogHeader>
          <div className="max-h-[65vh] space-y-5 overflow-y-auto pr-1">
            {form.modo_teste && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
                Modo teste ativo: confirmar nao grava pedido nem consome numeracao.
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Review label="Cliente" value={form.cliente} />
              <Review label="Data" value={form.data} />
              <Review label="Total" value={brl(total)} />
              <Review label="Razao social" value={form.razao_social} className="md:col-span-2" />
              <Review label="CNPJ" value={form.cnpj} />
              <Review label="Frete" value={`${form.tipo_frete} ${form.cidade_uf_frete ? `- ${form.cidade_uf_frete}` : ""}`} />
              <Review label="Pagamento" value={form.prazo_pgto_texto || "-"} />
              <Review label="% NF" value={form.pct_nf || "-"} />
              <Review label="Anexo" value={form.pedido_cliente_file_name || "-"} />
              <Review label="PDF" value={downloadAfterCreate ? "Baixar apos criar" : "Gerar depois no detalhe"} />
            </div>
            <div>
              <p className="mb-2 text-sm font-semibold">Itens</p>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="p-2 text-left">Descricao</th>
                      <th className="p-2 text-left">Kuryos</th>
                      <th className="p-2 text-right">Qtd.</th>
                      <th className="p-2 text-right">Unitario</th>
                      <th className="p-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validItems.map((item, index) => (
                      <tr key={index} className="border-t">
                        <td className="p-2 font-medium">{item.item}</td>
                        <td className="p-2 font-mono text-xs">{item.codigo_kuryos || "A definir"}</td>
                        <td className="p-2 text-right">{numberValue(item.qtd).toLocaleString("pt-BR")}</td>
                        <td className="p-2 text-right">{brl(numberValue(item.valor_unitario))}</td>
                        <td className="p-2 text-right font-semibold">{brl(numberValue(item.qtd) * numberValue(item.valor_unitario))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {insumos.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-semibold">Insumos gerais</p>
                <div className="space-y-2">
                  {insumos.map((item, index) => (
                    <div key={index} className="rounded-lg border p-3 text-sm">
                      <p className="font-medium">{item.item || "Insumo sem nome"}</p>
                      <p className="text-muted-foreground">{item.especificacoes || "-"} | qtd. {item.quantidade || "-"} | {item.responsavel || "Kuryos"}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReviewOpen(false)}>Editar Dados</Button>
            <Button onClick={saveOrder} disabled={saving} className="gap-2">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {form.modo_teste ? "Validar Teste" : "Criar Pedido"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Review({ label, value, className = "" }) {
  return (
    <div className={`rounded-lg bg-muted/40 p-3 ${className}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium">{value || "-"}</p>
    </div>
  );
}
