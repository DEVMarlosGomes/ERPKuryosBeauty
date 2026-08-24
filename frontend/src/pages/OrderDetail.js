import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { ArrowLeft, Save, Download, Loader2, Plus, Trash2, FileText, Pencil, Check, X, ShieldCheck, AlertTriangle, Factory, Lock, CheckCircle2, Copy, Paperclip, Upload } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { CurrencyInput, fmtCurrency } from "@/components/ui/CurrencyInput";
import { useAuth } from "@/contexts/AuthContext";

const TIPOS_SERVICO = [
  { value: "producao",    label: "Produção",    desc: "Primeiro pedido — amostra aprovada, gera novo SKU" },
  { value: "reposicao",  label: "Reposição",   desc: "SKU existente, sem nova amostra, fluxo simplificado" },
  { value: "retrabalho", label: "Retrabalho",  desc: "Reprocessamento de lote com não conformidade" },
];

const NIVEIS_FORMALIZACAO = [
  { value: 1, label: "Nível 1 — Aceite simples",   desc: "Cliente recorrente + valor dentro do threshold" },
  { value: 2, label: "Nível 2 — Aceite formal",    desc: "Cliente novo OU valor acima do threshold" },
  { value: 3, label: "Nível 3 — Aditivo ao CGI",   desc: "Alto valor, condições atípicas ou risco elevado" },
];

const CATEGORIAS_INSUMO = [
  "Arte / Aprovação de arte",
  "Cadastro ANVISA / Notificação",
  "Rótulos / Gravação",
  "Frascos / Potes",
  "Tampas / Sobretampa",
  "Cartucho",
  "Válvulas",
  "Celofane / Sleeve",
  "Display",
  "Caixa de embarque",
  "Essência / Fragrância",
  "Matérias-primas específicas",
];

const INSUMO_STATUS_CFG = {
  pendente:     { label: "Pendente",     cls: "bg-slate-100 text-slate-600" },
  em_andamento: { label: "Em andamento", cls: "bg-amber-100 text-amber-700" },
  confirmado:   { label: "Confirmado",   cls: "bg-blue-100 text-blue-700" },
  recebido:     { label: "Recebido",     cls: "bg-green-100 text-green-700" },
};

function buildDefaultChecklist() {
  return CATEGORIAS_INSUMO.map(cat => ({
    categoria: cat, ativo: false, origem: "kuryos",
    status: "pendente", responsavel: "", data_prevista: null, observacoes: "",
  }));
}

// NNN/NNN/NNN auto-mask
function maskCondicaoPgto(raw) {
  const digits = raw.replace(/\D/g, "").slice(0, 9);
  if (digits.length <= 3) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 3)}/${digits.slice(3)}`;
  return `${digits.slice(0, 3)}/${digits.slice(3, 6)}/${digits.slice(6)}`;
}

const STATUSES_IMUTAVEL = new Set(["confirmado", "em_producao", "concluido"]);

const STATUS_OPTIONS = [
  { value: "rascunho", label: "Rascunho" },
  { value: "confirmado", label: "Confirmado" },
  { value: "em_producao", label: "Em Produção" },
  { value: "concluido", label: "Concluído" },
  { value: "cancelado", label: "Cancelado" },
];

const STATUS_COLORS = {
  rascunho: "bg-slate-500/10 text-slate-600 border-slate-300 dark:text-slate-300",
  confirmado: "bg-blue-500/10 text-blue-600 border-blue-300 dark:text-blue-300",
  em_producao: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300",
  concluido: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300",
  cancelado: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300",
};

function formatCurrencyBR(value) {
  if (value === null || value === undefined || value === "") return "R$ 0,00";
  const n = Number(value);
  if (isNaN(n)) return "R$ 0,00";
  return `R$ ${n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function dateInputValue(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toISOString().slice(0, 10);
  } catch { return ""; }
}

export default function OrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  const [justificativa, setJustificativa] = useState("");
  const [showReproduzir, setShowReproduzir] = useState(false);
  const [reproducaoData, setReproducaoData] = useState({ items_override: [], endereco_entrega: "", observacoes: "" });
  const [reproducaoLoading, setReproducaoLoading] = useState(false);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);

  const fetchOrder = useCallback(async () => {
    try {
      const res = await api.get(`/orders/${id}`);
      setOrder(res.data);
      setForm(deepClone(res.data));
    } catch (err) {
      toast.error("Erro ao carregar pedido");
      navigate("/orders");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => { fetchOrder(); }, [fetchOrder]);

  const startEdit = () => {
    setForm(deepClone(order));
    ensureChecklist();
    setEditing(true);
  };

  const cancelEdit = () => {
    setForm(deepClone(order));
    setEditing(false);
    setJustificativa("");
  };

  const openReproduzir = () => {
    setReproducaoData({
      items_override: (order.items || []).map(it => ({
        codigo_kuryos: it.codigo_kuryos || "",
        valor_unitario: it.valor_unitario,
        prazo_entrega: it.prazo_entrega || "",
        qtd: it.qtd,
      })),
      endereco_entrega: order.frete?.endereco || "",
      observacoes: "",
    });
    setShowReproduzir(true);
  };

  const saveOrder = async () => {
    setSaving(true);
    try {
      const isLocked = STATUSES_IMUTAVEL.has(order.status);
      const payload = isLocked
        ? {
            status: form.status,
            observacoes: form.observacoes,
            checklist_insumos: form.checklist_insumos,
            // R21: always include full payload for locked orders; backend decides
            numero_pedido: form.numero_pedido,
            data_pedido: form.data_pedido,
            tipo_servico: form.tipo_servico,
            nivel_formalizacao: form.nivel_formalizacao,
            cliente: form.cliente,
            frete: form.frete,
            items: form.items,
            condicoes: form.condicoes,
            insumos: form.insumos,
            ...(justificativa.trim() ? { justificativa: justificativa.trim() } : {}),
          }
        : {
            numero_pedido: form.numero_pedido,
            data_pedido: form.data_pedido,
            status: form.status,
            tipo_servico: form.tipo_servico,
            nivel_formalizacao: form.nivel_formalizacao,
            cliente: form.cliente,
            frete: form.frete,
            items: form.items,
            condicoes: form.condicoes,
            insumos: form.insumos,
            checklist_insumos: form.checklist_insumos,
            observacoes: form.observacoes,
          };
      const res = await api.put(`/orders/${id}`, payload);
      setOrder(res.data);
      setForm(deepClone(res.data));
      setEditing(false);
      setJustificativa("");
      toast.success("Pedido atualizado!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const reproduzirPedido = async () => {
    setReproducaoLoading(true);
    try {
      const res = await api.post(`/orders/${id}/reproduzir`, {
        items_override: reproducaoData.items_override.filter(ov => ov.codigo_kuryos),
        endereco_entrega: reproducaoData.endereco_entrega || null,
        observacoes: reproducaoData.observacoes || null,
      });
      toast.success(`Nova produção criada! Pedido #${res.data.order.numero_pedido} → OP ${res.data.op.numero_op}`);
      setShowReproduzir(false);
      navigate(`/orders/${res.data.order.id}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao reproduzir pedido");
    } finally {
      setReproducaoLoading(false);
    }
  };

  const updateStatus = async (newStatus) => {
    try {
      const res = await api.put(`/orders/${id}`, { status: newStatus });
      setOrder(res.data);
      setForm(deepClone(res.data));
      toast.success("Status atualizado!");
    } catch (err) {
      toast.error("Erro ao alterar status");
    }
  };

  const downloadPDF = async () => {
    try {
      const response = await api.get(`/orders/${id}/pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `ordem_producao_${order?.numero_pedido || id}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      fetchOrder();
      toast.success("PDF gerado!");
    } catch (err) {
      toast.error("Erro ao gerar PDF");
    }
  };

  const uploadAttachment = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploadingAttachment(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      await api.post(`/orders/${id}/attachments`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Anexo enviado");
      fetchOrder();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao enviar anexo");
    } finally {
      setUploadingAttachment(false);
    }
  };

  const downloadAttachment = async (attachment) => {
    try {
      const response = await api.get(`/orders/${id}/attachments/${attachment.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: attachment.content_type || "application/octet-stream" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = attachment.original_filename || "anexo";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.error("Erro ao baixar anexo");
    }
  };

  const signCGI = async () => {
    try {
      const res = await api.post(`/orders/${id}/sign-cgi`);
      setOrder(res.data);
      setForm(deepClone(res.data));
      toast.success("CGI assinado com sucesso!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao assinar CGI");
    }
  };

  const approveCliente = async () => {
    try {
      const res = await api.post(`/orders/${id}/aprovar-cliente`, { observacoes: "" });
      setOrder(res.data); setForm(deepClone(res.data));
      toast.success("Aprovação do cliente registrada");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro");
    }
  };

  const requestClientConfirmation = async () => {
    try {
      const res = await api.post(`/orders/${id}/solicitar-confirmacao-cliente`);
      setOrder(res.data); setForm(deepClone(res.data));
      toast.success("Solicitacao de confirmacao enviada ao cliente");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao solicitar confirmacao");
    }
  };

  const approveComercial = async () => {
    try {
      const res = await api.post(`/orders/${id}/aprovar-comercial`, { observacoes: "" });
      setOrder(res.data); setForm(deepClone(res.data));
      toast.success("Aprovação comercial registrada");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Sem permissão ou erro ao aprovar");
    }
  };

  const rejectComercial = async () => {
    const obs = window.prompt("Motivo da rejeição (obrigatório):");
    if (!obs?.trim()) return;
    try {
      const res = await api.post(`/orders/${id}/rejeitar-comercial`, { observacoes: obs });
      setOrder(res.data); setForm(deepClone(res.data));
      toast.success("Pedido rejeitado comercialmente");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Sem permissão ou erro");
    }
  };

  const ensureChecklist = () => {
    if (!form.checklist_insumos || form.checklist_insumos.length < CATEGORIAS_INSUMO.length) {
      const existing = form.checklist_insumos || [];
      const existingCats = new Set(existing.map(c => c.categoria));
      const missing = CATEGORIAS_INSUMO.filter(cat => !existingCats.has(cat)).map(cat => ({
        categoria: cat, ativo: false, origem: "kuryos", status: "pendente", responsavel: "", data_prevista: null, observacoes: "",
      }));
      setForm(p => ({ ...p, checklist_insumos: [...existing, ...missing] }));
    }
  };

  const generateOP = async () => {
    try {
      const res = await api.post(`/orders/${id}/create-op`);
      toast.success(`OP ${res.data.numero_op} enviada ao PCP!`);
      fetchOrder();
      navigate(`/pcp/controle-ops?op=${encodeURIComponent(res.data.id)}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao gerar OP");
    }
  };

  if (loading || !form) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const onCli = (k, v) => setForm(p => ({ ...p, cliente: { ...p.cliente, [k]: v } }));
  const onFre = (k, v) => setForm(p => ({ ...p, frete: { ...p.frete, [k]: v } }));
  const onCnd = (k, v) => setForm(p => ({ ...p, condicoes: { ...p.condicoes, [k]: v } }));

  const updateItem = (idx, key, value) => {
    setForm(p => {
      const items = [...(p.items || [])];
      const it = { ...items[idx], [key]: value };
      // Auto-recompute valor_total applying discount
      if (key === "valor_unitario" || key === "qtd" || key === "desconto_percentual") {
        const vu = parseFloat(key === "valor_unitario" ? value : it.valor_unitario) || 0;
        const q = parseFloat(key === "qtd" ? value : it.qtd) || 0;
        const desc = Math.max(0, Math.min(100, parseFloat(key === "desconto_percentual" ? value : (it.desconto_percentual || 0)) || 0));
        const bruto = vu * q;
        it.valor_desconto = +(bruto * desc / 100).toFixed(2);
        it.valor_total = +(bruto - it.valor_desconto).toFixed(2);
      }
      items[idx] = it;
      return { ...p, items };
    });
  };

  const addItem = () => {
    setForm(p => ({
      ...p,
      items: [...(p.items || []), {
        codigo_kuryos: "", codigo_cliente: "", item: "",
        prazo_entrega: "20 Dias", valor_unitario: 0, valor_unitario_currency: "BRL",
        desconto_percentual: 0, valor_desconto: 0, qtd: 0, valor_total: 0,
      }],
    }));
  };

  const removeItem = (idx) => {
    setForm(p => ({ ...p, items: (p.items || []).filter((_, i) => i !== idx) }));
  };

  const totalCalc = (form.items || []).reduce((s, it) => s + (Number(it.valor_total) || 0), 0);
  const totalBruto = (form.items || []).reduce((s, it) => s + ((it.valor_unitario || 0) * (it.qtd || 0)), 0);
  const totalDesconto = totalBruto - totalCalc;
  const descontoPct = totalBruto > 0 ? (totalDesconto / totalBruto * 100) : 0;
  const statusCfg = STATUS_COLORS[form.status] || STATUS_COLORS.rascunho;
  const apCom = form.aprovacao_comercial || "nao_necessaria";
  const attachments = form.attachments || [];
  const pdfMeta = form.pdf || {};
  const isGeneratorOrder = form.origem === "gerador" || !!form.gerador_origem;

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate("/orders")} data-testid="back-to-orders">
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-xl font-heading font-semibold flex items-center gap-2">
                Ordem de Produção
                <span className="font-mono text-primary">#{form.numero_pedido}</span>
              </h1>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <Badge className={statusCfg}>
                  {STATUS_OPTIONS.find(s => s.value === form.status)?.label || form.status}
                </Badge>
                {form.auto_created && (
                  <Badge variant="outline" className="text-[10px] gap-1">
                    <FileText className="h-2.5 w-2.5" /> Auto-gerado a partir do P&D
                  </Badge>
                )}
                {(form.origem === "gerador" || form.gerador_origem) && (
                  <Badge variant="outline" className="text-[10px] gap-1 border-blue-300 text-blue-700 dark:text-blue-300">
                    <FileText className="h-2.5 w-2.5" /> Gerador
                  </Badge>
                )}
                {form.kickoff_id && (
                  <Badge variant="outline" className="text-[10px] gap-1 border-violet-300 text-violet-700 dark:text-violet-300">
                    <ShieldCheck className="h-2.5 w-2.5" /> KO vinculado
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {!editing && (
              <Select value={form.status} onValueChange={updateStatus}>
                <SelectTrigger className="w-44" data-testid="order-status-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map(s => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
            {form.status === "confirmado" && !form.op_id && (
              <Button onClick={generateOP} variant="default" className="gap-1.5 bg-emerald-600 hover:bg-emerald-700" data-testid="generate-op-btn">
                <Factory className="h-4 w-4" /> Gerar OP
              </Button>
            )}
            {form.op_id && (
              <Button variant="outline" onClick={() => navigate(`/pcp/controle-ops?op=${encodeURIComponent(form.op_id)}`)} className="gap-1.5" data-testid="view-op-btn">
                <Factory className="h-4 w-4" /> Abrir no PCP
              </Button>
            )}
            {STATUSES_IMUTAVEL.has(form.status) && ["admin", "vendedor", "sales_ops"].includes(user?.role) && !editing && (
              <Button variant="outline" onClick={openReproduzir} className="gap-1.5 border-violet-400 text-violet-700 hover:bg-violet-50 dark:text-violet-300 dark:border-violet-600" data-testid="reproduzir-btn">
                <Copy className="h-4 w-4" /> Nova Produção
              </Button>
            )}
            <Button onClick={downloadPDF} className="gap-1.5" data-testid="download-pdf-btn">
              <Download className="h-4 w-4" /> Gerar PDF
            </Button>
            {!editing ? (
              <Button variant="outline" onClick={startEdit} className="gap-1.5" data-testid="edit-order-btn">
                <Pencil className="h-4 w-4" /> Editar
              </Button>
            ) : (
              <>
                <Button onClick={saveOrder} disabled={saving} className="gap-1.5" data-testid="save-order-btn">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Salvar
                </Button>
                <Button variant="ghost" onClick={cancelEdit} data-testid="cancel-edit-btn">
                  <X className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        </div>

        {/* CGI Panel (RN-PI-01) */}
        <div className={`rounded-xl border px-5 py-4 flex items-center justify-between gap-4 ${form.cgi_status === "assinado" ? "bg-green-50 border-green-300 dark:bg-green-950/30 dark:border-green-800" : "bg-amber-50 border-amber-300 dark:bg-amber-950/30 dark:border-amber-800"}`}>
          <div className="flex items-center gap-3">
            {form.cgi_status === "assinado"
              ? <ShieldCheck className="h-5 w-5 text-green-600 shrink-0" />
              : <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
            }
            <div>
              <p className="text-sm font-semibold">
                {form.cgi_status === "assinado" ? "CGI Assinado" : "CGI Pendente (RN-PI-01)"}
              </p>
              <p className="text-xs text-muted-foreground">
                {form.cgi_status === "assinado"
                  ? `Assinado por ${form.cgi_assinado_por || "—"} em ${form.cgi_assinado_em ? new Date(form.cgi_assinado_em).toLocaleDateString("pt-BR") : "—"}`
                  : "O Contrato Geral de Industrialização deve ser assinado antes de confirmar o pedido."
                }
              </p>
            </div>
          </div>
          {form.cgi_status !== "assinado" && (
            <Button size="sm" variant="outline" onClick={signCGI} className="shrink-0 gap-1.5 border-amber-400 text-amber-700 hover:bg-amber-100" data-testid="sign-cgi-btn">
              <ShieldCheck className="h-3.5 w-3.5" /> Assinar CGI
            </Button>
          )}
        </div>

        {/* Imutabilidade banner */}
        {STATUSES_IMUTAVEL.has(form.status) && (
          <div className="rounded-xl border border-blue-300 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-800 px-5 py-3 space-y-2">
            <div className="flex items-center gap-3">
              <Lock className="h-4 w-4 text-blue-600 shrink-0" />
              <p className="text-sm text-blue-700 dark:text-blue-300">
                <strong>Pedido imutável (RN-PI-05)</strong> — Status <em>{form.status}</em>. Campos comerciais bloqueados. Forneça uma justificativa para editar e registrar no audit log (R21).
              </p>
            </div>
            {editing && (
              <div className="pl-7">
                <Label className="text-xs text-blue-700 dark:text-blue-400">Justificativa para edição (obrigatória para campos comerciais)</Label>
                <Textarea
                  value={justificativa}
                  onChange={e => setJustificativa(e.target.value)}
                  placeholder="Descreva o motivo da alteração..."
                  rows={2}
                  className="mt-1 text-sm border-blue-300 focus:border-blue-500"
                  data-testid="justificativa-input"
                />
              </div>
            )}
          </div>
        )}

        {/* Aprovação do Cliente */}
        <div className={`rounded-xl border px-5 py-4 flex items-center justify-between gap-4 ${form.aprovacao_cliente === "aprovado" ? "bg-green-50 border-green-300 dark:bg-green-950/30 dark:border-green-800" : "bg-slate-50 border-slate-300 dark:bg-slate-900/30 dark:border-slate-700"}`}>
          <div className="flex items-center gap-3">
            {form.aprovacao_cliente === "aprovado"
              ? <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
              : <AlertTriangle className="h-5 w-5 text-slate-400 shrink-0" />
            }
            <div>
              <p className="text-sm font-semibold">
                {form.aprovacao_cliente === "aprovado" ? "Cliente Aprovou o Pedido" : "Aprovação do Cliente Pendente (RN-PI-04)"}
              </p>
              <p className="text-xs text-muted-foreground">
                {form.aprovacao_cliente === "aprovado"
                  ? `Registrado por ${form.aprovacao_cliente_por || "—"} em ${form.aprovacao_cliente_em ? new Date(form.aprovacao_cliente_em).toLocaleDateString("pt-BR") : "—"}`
                  : `Solicitacao: ${form.confirmacao_cliente?.solicitada_em ? new Date(form.confirmacao_cliente.solicitada_em).toLocaleString("pt-BR") : "pendente de envio"}`
                }
              </p>
            </div>
          </div>
          {form.aprovacao_cliente !== "aprovado" && (
            <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
              <Button size="sm" variant="outline" onClick={requestClientConfirmation}
                className="gap-1.5 border-slate-400 text-slate-700 hover:bg-slate-100">
                <FileText className="h-3.5 w-3.5" /> Solicitar confirmacao
              </Button>
              <Button size="sm" variant="outline" onClick={approveCliente}
                className="gap-1.5 border-slate-400 text-slate-700 hover:bg-slate-100">
                <CheckCircle2 className="h-3.5 w-3.5" /> Registrar Aprovacao
              </Button>
            </div>
          )}
        </div>

        {/* Aprovação Comercial — RN-PI-10 (só exibe se há desconto além do tier automático) */}
        {apCom !== "nao_necessaria" && (
          <div className={`rounded-xl border px-5 py-4 flex items-center justify-between gap-4 ${
            apCom === "aprovada" ? "bg-green-50 border-green-300 dark:bg-green-950/30 dark:border-green-800"
            : apCom === "rejeitada" ? "bg-red-50 border-red-300 dark:bg-red-950/30 dark:border-red-800"
            : "bg-orange-50 border-orange-300 dark:bg-orange-950/30 dark:border-orange-800"
          }`}>
            <div className="flex items-center gap-3">
              {apCom === "aprovada"
                ? <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
                : apCom === "rejeitada"
                ? <X className="h-5 w-5 text-red-600 shrink-0" />
                : <AlertTriangle className="h-5 w-5 text-orange-600 shrink-0" />
              }
              <div>
                <p className="text-sm font-semibold">
                  {apCom === "aprovada" ? "Aprovação Comercial Concedida"
                   : apCom === "rejeitada" ? "Pedido Rejeitado Comercialmente"
                   : `Aprovação Comercial Pendente (RN-PI-10) — ${(form.aprovacao_comercial_nivel || "gerente_vendas").replace("_", " ")}`}
                </p>
                <p className="text-xs text-muted-foreground">
                  {apCom === "aprovada" || apCom === "rejeitada"
                    ? `${form.aprovacao_comercial_por || "—"} em ${form.aprovacao_comercial_em ? new Date(form.aprovacao_comercial_em).toLocaleDateString("pt-BR") : "—"}${form.aprovacao_comercial_obs ? ` · "${form.aprovacao_comercial_obs}"` : ""}`
                    : `Desconto de ${descontoPct.toFixed(1)}% acima do limite automático de 5%. Aguardando aprovação.`
                  }
                </p>
              </div>
            </div>
            {apCom === "pendente" && (
              <div className="flex gap-2 shrink-0">
                <Button size="sm" onClick={approveComercial}
                  className="gap-1.5 bg-green-600 hover:bg-green-700 text-white">
                  <Check className="h-3.5 w-3.5" /> Aprovar
                </Button>
                <Button size="sm" variant="outline" onClick={rejectComercial}
                  className="gap-1.5 border-red-400 text-red-600 hover:bg-red-50">
                  <X className="h-3.5 w-3.5" /> Rejeitar
                </Button>
              </div>
            )}
          </div>
        )}

        {(isGeneratorOrder || attachments.length > 0 || pdfMeta.generated_at) && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" /> Fluxo do Gerador
                  </CardTitle>
                  <p className="text-xs text-muted-foreground mt-1">
                    Status minimo do pedido criado no gerador, sem duplicar a tela de Pedidos.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={downloadPDF} className="gap-1.5">
                    <Download className="h-3.5 w-3.5" /> Baixar PDF
                  </Button>
                  <label className="inline-flex">
                    <input
                      type="file"
                      className="sr-only"
                      accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx"
                      onChange={uploadAttachment}
                      disabled={uploadingAttachment}
                    />
                    <span className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground">
                      {uploadingAttachment ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                      Anexar
                    </span>
                  </label>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                <GeneratorStep label="Anexo" done={attachments.length > 0} detail={attachments.length ? `${attachments.length} arquivo(s)` : "pendente"} />
                <GeneratorStep label="PDF" done={!!pdfMeta.generated_at} detail={pdfMeta.generated_at ? new Date(pdfMeta.generated_at).toLocaleString("pt-BR") : "nao gerado"} />
                <GeneratorStep label="Cliente" done={form.aprovacao_cliente === "aprovado"} detail={form.aprovacao_cliente || "pendente"} />
                <GeneratorStep label="Comercial" done={apCom === "nao_necessaria" || apCom === "aprovada"} detail={apCom} />
                <GeneratorStep label="OP" done={!!form.op_id} detail={form.op_id ? "gerada" : "pendente"} />
              </div>

              {attachments.length > 0 && (
                <div className="rounded-lg border">
                  <div className="border-b bg-muted/30 px-3 py-2 text-xs font-semibold text-muted-foreground">Anexos do cliente</div>
                  <div className="divide-y">
                    {attachments.map((attachment) => (
                      <button
                        key={attachment.id}
                        type="button"
                        onClick={() => downloadAttachment(attachment)}
                        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted/40"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Paperclip className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="truncate font-medium">{attachment.original_filename}</span>
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {attachment.uploaded_at ? new Date(attachment.uploaded_at).toLocaleDateString("pt-BR") : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* 1) Informações Iniciais */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="font-mono text-primary">1)</span> Informações Iniciais
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Field label="Cliente" value={form.cliente?.nome} onChange={(v) => onCli("nome", v)} editing={editing} testid="field-cliente-nome" />
              <Field label="# Pedido" value={form.numero_pedido} onChange={(v) => setForm(p => ({ ...p, numero_pedido: v }))} editing={editing} testid="field-numero-pedido" />
              <Field
                label="Data"
                type="date"
                value={editing ? dateInputValue(form.data_pedido) : (form.data_pedido ? new Date(form.data_pedido).toLocaleDateString("pt-BR") : "")}
                onChange={(v) => setForm(p => ({ ...p, data_pedido: v ? new Date(v).toISOString() : null }))}
                editing={editing}
                testid="field-data-pedido"
              />
            </div>
            {/* Tipo de Serviço + Nível de Formalização */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground">Tipo de Serviço</Label>
                {editing && !STATUSES_IMUTAVEL.has(order.status) ? (
                  <Select value={form.tipo_servico || "producao"}
                    onValueChange={v => setForm(p => ({ ...p, tipo_servico: v }))}>
                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TIPOS_SERVICO.map(t => (
                        <SelectItem key={t.value} value={t.value}>
                          <div><div className="font-medium">{t.label}</div><div className="text-xs text-muted-foreground">{t.desc}</div></div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-sm font-medium mt-1">
                    {TIPOS_SERVICO.find(t => t.value === form.tipo_servico)?.label || form.tipo_servico || "Produção"}
                  </p>
                )}
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">Nível de Formalização</Label>
                {editing && !STATUSES_IMUTAVEL.has(order.status) ? (
                  <Select value={String(form.nivel_formalizacao || 1)}
                    onValueChange={v => setForm(p => ({ ...p, nivel_formalizacao: Number(v) }))}>
                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {NIVEIS_FORMALIZACAO.map(n => (
                        <SelectItem key={n.value} value={String(n.value)}>
                          <div><div className="font-medium">{n.label}</div><div className="text-xs text-muted-foreground">{n.desc}</div></div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-sm font-medium mt-1">
                    {NIVEIS_FORMALIZACAO.find(n => n.value === (form.nivel_formalizacao || 1))?.label || `Nível ${form.nivel_formalizacao || 1}`}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 2) Dados do Cliente */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="font-mono text-primary">2)</span> Dados do Cliente
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Razão Social" value={form.cliente?.razao_social} onChange={(v) => onCli("razao_social", v)} editing={editing} testid="field-razao-social" />
            <Field label="CNPJ" value={form.cliente?.cnpj} onChange={(v) => onCli("cnpj", v)} editing={editing} testid="field-cnpj" />
            <Field label="Cidade / UF" value={form.cliente?.cidade_uf} onChange={(v) => onCli("cidade_uf", v)} editing={editing} testid="field-cidade-uf" />
            <Field label="Responsável" value={form.cliente?.responsavel} onChange={(v) => onCli("responsavel", v)} editing={editing} testid="field-responsavel" />
            <Field label="Telefone" value={form.cliente?.telefone} onChange={(v) => onCli("telefone", v)} editing={editing} testid="field-telefone" />
            <Field label="E-mail" value={form.cliente?.email} onChange={(v) => onCli("email", v)} editing={editing} testid="field-email" />
          </CardContent>
        </Card>

        {/* 3) Frete */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="font-mono text-primary">3)</span> Frete
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground">Tipo de Frete</Label>
              {editing ? (
                <Select value={form.frete?.tipo || "FOB"} onValueChange={(v) => onFre("tipo", v)}>
                  <SelectTrigger className="mt-1" data-testid="field-frete-tipo"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="FOB">FOB</SelectItem>
                    <SelectItem value="CIF">CIF</SelectItem>
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm font-medium mt-1">{form.frete?.tipo || "—"}</p>
              )}
            </div>
            <Field label="Cidade / UF" value={form.frete?.cidade_uf} onChange={(v) => onFre("cidade_uf", v)} editing={editing} testid="field-frete-cidade" />
            <div className="md:col-span-2">
              <Field label="Endereço" value={form.frete?.endereco} onChange={(v) => onFre("endereco", v)} editing={editing} testid="field-frete-endereco" />
            </div>
            <div className="md:col-span-2">
              <Field label="Prazo p/ Coleta" value={form.frete?.prazo_coleta} onChange={(v) => onFre("prazo_coleta", v)} editing={editing} testid="field-frete-prazo" />
            </div>
          </CardContent>
        </Card>

        {/* 4) Pedido (Items) */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <span className="font-mono text-primary">4)</span> Pedido
              </CardTitle>
              {editing && (
                <Button size="sm" variant="outline" onClick={addItem} className="gap-1.5" data-testid="add-item-btn">
                  <Plus className="h-3.5 w-3.5" /> Adicionar Item
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#1F2C5C] text-white text-xs">
                    <th className="text-left p-2 font-medium">#</th>
                    <th className="text-left p-2 font-medium">Cód. Kuryos</th>
                    <th className="text-left p-2 font-medium">Cód. Cliente</th>
                    <th className="text-left p-2 font-medium">Item</th>
                    <th className="text-left p-2 font-medium">Prazo</th>
                    <th className="text-right p-2 font-medium">Valor Unit.</th>
                    <th className="text-right p-2 font-medium">Desc. %</th>
                    <th className="text-right p-2 font-medium">Qtd.</th>
                    <th className="text-right p-2 font-medium">Total</th>
                    {editing && <th className="w-10"></th>}
                  </tr>
                </thead>
                <tbody>
                  {(form.items || []).map((it, idx) => (
                    <tr key={idx} className="border-t hover:bg-muted/30">
                      <td className="p-2 font-mono text-xs">{idx + 1}</td>
                      <td className="p-1">
                        {editing ? (
                          <Input value={it.codigo_kuryos || ""} onChange={(e) => updateItem(idx, "codigo_kuryos", e.target.value)} className="h-8 text-xs" data-testid={`item-${idx}-codigo-kuryos`} />
                        ) : (it.codigo_kuryos || "—")}
                      </td>
                      <td className="p-1">
                        {editing ? (
                          <Input value={it.codigo_cliente || ""} onChange={(e) => updateItem(idx, "codigo_cliente", e.target.value)} className="h-8 text-xs" data-testid={`item-${idx}-codigo-cliente`} />
                        ) : (it.codigo_cliente || "—")}
                      </td>
                      <td className="p-1">
                        {editing ? (
                          <Input value={it.item || ""} onChange={(e) => updateItem(idx, "item", e.target.value)} className="h-8 text-xs" data-testid={`item-${idx}-nome`} />
                        ) : (it.item || "—")}
                      </td>
                      <td className="p-1">
                        {editing ? (
                          <Input value={it.prazo_entrega || ""} onChange={(e) => updateItem(idx, "prazo_entrega", e.target.value)} className="h-8 text-xs" data-testid={`item-${idx}-prazo`} />
                        ) : (it.prazo_entrega || "—")}
                      </td>
                      <td className="p-1 text-right">
                        {editing ? (
                          <CurrencyInput
                            value={it.valor_unitario || 0}
                            currency={it.valor_unitario_currency || "BRL"}
                            onValueChange={v => updateItem(idx, "valor_unitario", v)}
                            onCurrencyChange={c => updateItem(idx, "valor_unitario_currency", c)}
                            showHint={false}
                            size="sm"
                          />
                        ) : fmtCurrency(it.valor_unitario, it.valor_unitario_currency || "BRL")}
                      </td>
                      <td className="p-1 text-right">
                        {editing ? (
                          <div className="flex items-center gap-0.5 justify-end">
                            <Input
                              type="number" min="0" max="100" step="0.5"
                              value={it.desconto_percentual || 0}
                              onChange={(e) => updateItem(idx, "desconto_percentual", e.target.value)}
                              className="h-8 text-xs text-right font-mono w-16"
                              data-testid={`item-${idx}-desconto`}
                            />
                            <span className="text-xs text-muted-foreground">%</span>
                          </div>
                        ) : (it.desconto_percentual > 0 ? (
                          <span className="text-orange-600 font-mono text-xs font-semibold">{Number(it.desconto_percentual).toFixed(1)}%</span>
                        ) : <span className="text-muted-foreground text-xs">—</span>)}
                      </td>
                      <td className="p-1 text-right">
                        {editing ? (
                          <Input type="number" value={it.qtd || 0} onChange={(e) => updateItem(idx, "qtd", e.target.value)} className="h-8 text-xs text-right font-mono" data-testid={`item-${idx}-qtd`} />
                        ) : (Number(it.qtd) || 0).toLocaleString("pt-BR")}
                      </td>
                      <td className="p-2 text-right font-mono text-xs font-semibold">
                        {fmtCurrency(it.valor_total, it.valor_unitario_currency || "BRL")}
                        {it.desconto_percentual > 0 && (
                          <div className="text-[10px] text-orange-500 font-normal">
                            - {fmtCurrency(it.valor_desconto || 0, it.valor_unitario_currency || "BRL")}
                          </div>
                        )}
                      </td>
                      {editing && (
                        <td className="p-2 text-center">
                          <button onClick={() => removeItem(idx)} className="text-muted-foreground hover:text-red-500" data-testid={`remove-item-${idx}`}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                  {(form.items || []).length === 0 && (
                    <tr><td colSpan={editing ? 9 : 8} className="p-6 text-center text-xs text-muted-foreground">
                      Nenhum item. {editing && "Clique em 'Adicionar Item'."}
                    </td></tr>
                  )}
                </tbody>
                <tfoot>
                  {totalDesconto > 0 && (
                    <>
                      <tr className="border-t text-muted-foreground text-xs">
                        <td colSpan={8} className="p-2 text-right">Total bruto</td>
                        <td className="p-2 text-right font-mono">{formatCurrencyBR(totalBruto)}</td>
                        {editing && <td></td>}
                      </tr>
                      <tr className="text-xs text-orange-700">
                        <td colSpan={8} className="p-2 text-right">Desconto ({descontoPct.toFixed(1)}%)</td>
                        <td className="p-2 text-right font-mono">- {formatCurrencyBR(totalDesconto)}</td>
                        {editing && <td></td>}
                      </tr>
                    </>
                  )}
                  <tr className="border-t-2 bg-muted/30 font-bold">
                    <td colSpan={8} className="p-2 text-right">Total do Pedido</td>
                    <td className="p-2 text-right text-green-600 font-mono">{formatCurrencyBR(totalCalc)}</td>
                    {editing && <td></td>}
                  </tr>
                </tfoot>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* 5) Condições */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="font-mono text-primary">5)</span> Condições de Prazo e Pagamento
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Prazo de Entrega" value={form.condicoes?.prazo} onChange={(v) => onCnd("prazo", v)} editing={editing} testid="field-cond-prazo" />
            <div>
              <Label className="text-xs text-muted-foreground">Condição de Pagamento (RN-PI-08)</Label>
              {editing && !STATUSES_IMUTAVEL.has(order.status) ? (
                <div>
                  <Input
                    value={form.condicoes?.condicao_pagamento || ""}
                    onChange={(e) => onCnd("condicao_pagamento", maskCondicaoPgto(e.target.value))}
                    placeholder="000/000/000"
                    className="mt-1 font-mono"
                    maxLength={11}
                    data-testid="field-cond-pgto"
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">Formato obrigatório: NNN/NNN/NNN (ex: 030/060/090)</p>
                </div>
              ) : (
                <p className="text-sm font-medium mt-1 min-h-[28px] flex items-center font-mono" data-testid="field-cond-pgto">
                  {form.condicoes?.condicao_pagamento || form.condicoes?.forma_pgto || "—"}
                </p>
              )}
            </div>
            <Field label="Validade da Proposta" value={form.condicoes?.validade} onChange={(v) => onCnd("validade", v)} editing={editing} testid="field-cond-validade" />
          </CardContent>
        </Card>

        {/* 6) Checklist de Insumos */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="font-mono text-primary">6)</span> Checklist de Insumos (RN-PI-06)
                </CardTitle>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {(form.checklist_insumos || []).filter(c => c.ativo && c.status === "recebido").length} / {(form.checklist_insumos || []).filter(c => c.ativo).length} insumos ativos recebidos
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-[#1F2C5C] text-white">
                    <th className="text-left p-2 font-medium">Categoria</th>
                    <th className="text-center p-2 font-medium w-14">Aplica?</th>
                    <th className="text-center p-2 font-medium w-24">Origem</th>
                    <th className="text-center p-2 font-medium w-28">Status</th>
                    <th className="text-left p-2 font-medium w-32">Responsável</th>
                    <th className="text-left p-2 font-medium w-28">Data Prevista</th>
                  </tr>
                </thead>
                <tbody>
                  {(form.checklist_insumos || buildDefaultChecklist()).map((ci, idx) => {
                    const statusCfg = INSUMO_STATUS_CFG[ci.status] || INSUMO_STATUS_CFG.pendente;
                    const updateCI = (key, val) => setForm(p => {
                      const cl = [...(p.checklist_insumos || buildDefaultChecklist())];
                      cl[idx] = { ...cl[idx], [key]: val };
                      return { ...p, checklist_insumos: cl };
                    });
                    return (
                      <tr key={idx} className={`border-t ${ci.ativo ? "hover:bg-muted/30" : "opacity-50 hover:opacity-70"}`}>
                        <td className="p-2 font-medium">{ci.categoria}</td>
                        <td className="p-2 text-center">
                          <Checkbox
                            checked={!!ci.ativo}
                            onCheckedChange={editing ? (v) => updateCI("ativo", v) : undefined}
                            disabled={!editing}
                            data-testid={`ci-${idx}-ativo`}
                          />
                        </td>
                        <td className="p-1 text-center">
                          {editing && ci.ativo ? (
                            <Select value={ci.origem || "kuryos"} onValueChange={v => updateCI("origem", v)}>
                              <SelectTrigger className="h-6 text-[10px] px-1.5"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="kuryos">Kuryos</SelectItem>
                                <SelectItem value="cliente">Cliente</SelectItem>
                              </SelectContent>
                            </Select>
                          ) : (
                            <span className={`text-[10px] rounded px-1.5 py-0.5 font-medium ${ci.origem === "cliente" ? "bg-purple-100 text-purple-700" : "bg-slate-100 text-slate-600"}`}>
                              {ci.origem === "cliente" ? "Cliente" : "Kuryos"}
                            </span>
                          )}
                        </td>
                        <td className="p-1 text-center">
                          {editing && ci.ativo ? (
                            <Select value={ci.status || "pendente"} onValueChange={v => updateCI("status", v)}>
                              <SelectTrigger className="h-6 text-[10px] px-1.5"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                {Object.entries(INSUMO_STATUS_CFG).map(([k, cfg]) => (
                                  <SelectItem key={k} value={k}>{cfg.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            <span className={`text-[10px] rounded px-1.5 py-0.5 font-medium ${statusCfg.cls}`}>{statusCfg.label}</span>
                          )}
                        </td>
                        <td className="p-1">
                          {editing && ci.ativo ? (
                            <Input value={ci.responsavel || ""} onChange={e => updateCI("responsavel", e.target.value)} className="h-6 text-[10px]" placeholder="Nome" data-testid={`ci-${idx}-resp`} />
                          ) : (
                            <span className="text-muted-foreground">{ci.responsavel || "—"}</span>
                          )}
                        </td>
                        <td className="p-1">
                          {editing && ci.ativo ? (
                            <Input type="date" value={ci.data_prevista || ""} onChange={e => updateCI("data_prevista", e.target.value)} className="h-6 text-[10px]" data-testid={`ci-${idx}-data`} />
                          ) : (
                            <span className="text-muted-foreground">
                              {ci.data_prevista ? new Date(ci.data_prevista).toLocaleDateString("pt-BR") : "—"}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Observações */}
        {(editing || form.observacoes) && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Observações</CardTitle>
            </CardHeader>
            <CardContent>
              {editing ? (
                <Textarea
                  value={form.observacoes || ""}
                  onChange={(e) => setForm(p => ({ ...p, observacoes: e.target.value }))}
                  rows={3}
                  data-testid="field-observacoes"
                />
              ) : (
                <p className="text-sm whitespace-pre-wrap">{form.observacoes}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Follow-up marcos (R19) */}
        {(order.followups || []).length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">Follow-ups de Pós-Produção</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-3 flex-wrap">
                {(order.followups || []).map(fu => {
                  const vence = new Date(fu.vence_em);
                  const overdue = vence < new Date() && !fu.notificado;
                  return (
                    <div key={fu.marco} className={`rounded-lg border px-4 py-3 text-center min-w-[120px] ${fu.notificado ? "bg-green-50 border-green-300" : overdue ? "bg-red-50 border-red-300" : "bg-slate-50 border-slate-200"}`}>
                      <div className={`text-lg font-bold font-mono ${fu.notificado ? "text-green-700" : overdue ? "text-red-700" : "text-slate-700"}`}>{fu.marco}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{vence.toLocaleDateString("pt-BR")}</div>
                      <div className={`text-[10px] mt-1 font-medium ${fu.notificado ? "text-green-600" : overdue ? "text-red-600" : "text-slate-500"}`}>
                        {fu.notificado ? "Notificado" : overdue ? "Vencido" : "Pendente"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Footer info */}
        <div className="text-[11px] text-muted-foreground pt-2">
          Criado por <strong>{order.created_by_name}</strong> em {order.created_at ? new Date(order.created_at).toLocaleString("pt-BR") : "—"}
          {order.pd_request_id && (
            <> • <button onClick={() => navigate(`/pd/${order.pd_request_id}`)} className="text-primary hover:underline" data-testid="link-to-pd">Ver projeto P&D</button></>
          )}
          {order.reproducao_de && (
            <> • <button onClick={() => navigate(`/orders/${order.reproducao_de}`)} className="text-primary hover:underline">Ver pedido original</button></>
          )}
        </div>
      </div>

      {/* R15: Reproduzir Pedido Dialog */}
      <Dialog open={showReproduzir} onOpenChange={setShowReproduzir}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Copy className="h-5 w-5 text-violet-600" />
              Nova Produção — Reproduzir Pedido #{form?.numero_pedido}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Cria um novo pedido clonando os dados deste, gera OP automaticamente. Ajuste valores, prazos e endereço conforme necessário.
            </p>
            {/* Item overrides */}
            <div>
              <Label className="text-sm font-medium">Itens (ajuste valor unitário e prazo)</Label>
              <div className="mt-2 space-y-2">
                {(reproducaoData.items_override || []).map((ov, idx) => (
                  <div key={idx} className="grid grid-cols-12 gap-2 items-center text-xs">
                    <div className="col-span-4 font-mono text-muted-foreground truncate">{ov.codigo_kuryos || `Item ${idx + 1}`}</div>
                    <div className="col-span-3">
                      <Label className="text-[10px] text-muted-foreground">Valor Unit.</Label>
                      <Input
                        type="number"
                        value={ov.valor_unitario ?? ""}
                        onChange={e => {
                          const ovs = [...reproducaoData.items_override];
                          ovs[idx] = { ...ovs[idx], valor_unitario: parseFloat(e.target.value) || 0 };
                          setReproducaoData(p => ({ ...p, items_override: ovs }));
                        }}
                        className="h-7 text-xs"
                        placeholder="0.00"
                      />
                    </div>
                    <div className="col-span-3">
                      <Label className="text-[10px] text-muted-foreground">Prazo</Label>
                      <Input
                        value={ov.prazo_entrega ?? ""}
                        onChange={e => {
                          const ovs = [...reproducaoData.items_override];
                          ovs[idx] = { ...ovs[idx], prazo_entrega: e.target.value };
                          setReproducaoData(p => ({ ...p, items_override: ovs }));
                        }}
                        className="h-7 text-xs"
                        placeholder="ex: 20 Dias"
                      />
                    </div>
                    <div className="col-span-2">
                      <Label className="text-[10px] text-muted-foreground">Qtd</Label>
                      <Input
                        type="number"
                        value={ov.qtd ?? ""}
                        onChange={e => {
                          const ovs = [...reproducaoData.items_override];
                          ovs[idx] = { ...ovs[idx], qtd: parseFloat(e.target.value) || 0 };
                          setReproducaoData(p => ({ ...p, items_override: ovs }));
                        }}
                        className="h-7 text-xs"
                        placeholder="0"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {/* Endereço */}
            <div>
              <Label className="text-sm font-medium">Endereço de Entrega</Label>
              <Input
                value={reproducaoData.endereco_entrega}
                onChange={e => setReproducaoData(p => ({ ...p, endereco_entrega: e.target.value }))}
                className="mt-1"
                placeholder="Endereço completo..."
              />
            </div>
            {/* Observações */}
            <div>
              <Label className="text-sm font-medium">Observações (opcional)</Label>
              <Textarea
                value={reproducaoData.observacoes}
                onChange={e => setReproducaoData(p => ({ ...p, observacoes: e.target.value }))}
                rows={2}
                className="mt-1"
                placeholder="Notas sobre esta reprodução..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowReproduzir(false)}>Cancelar</Button>
            <Button onClick={reproduzirPedido} disabled={reproducaoLoading} className="gap-1.5 bg-violet-600 hover:bg-violet-700 text-white">
              {reproducaoLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Copy className="h-4 w-4" />}
              Criar Nova Produção
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function GeneratorStep({ label, done, detail }) {
  return (
    <div className={`rounded-lg border p-3 ${done ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/20" : "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20"}`}>
      <div className="flex items-center gap-2">
        {done ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
        <p className="text-xs font-semibold">{label}</p>
      </div>
      <p className="mt-1 truncate text-[11px] text-muted-foreground">{detail || "-"}</p>
    </div>
  );
}

function Field({ label, value, onChange, editing, type = "text", testid }) {
  return (
    <div>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {editing ? (
        <Input
          type={type}
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1"
          data-testid={testid}
        />
      ) : (
        <p className="text-sm font-medium mt-1 min-h-[28px] flex items-center" data-testid={testid}>
          {value || "—"}
        </p>
      )}
    </div>
  );
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}
