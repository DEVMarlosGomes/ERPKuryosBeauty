import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
    Receipt, Plus, Search, Loader2, ChevronRight, DollarSign,
    Building2, Calendar, CheckCircle2, AlertTriangle, FileText,
    TrendingUp, Clock, Banknote, RefreshCw, AlertCircle,
} from "lucide-react";

// ===== STATUS CONFIGS =====
const NF_STATUS_CONFIG = {
    rascunho:  { label: "Rascunho",  cls: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
    processando: { label: "Processando SEFAZ", cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
    rejeitada: { label: "Rejeitada", cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
    emitida:   { label: "Emitida",   cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" },
    cancelada: { label: "Cancelada", cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
};

const PGTO_CONFIG = {
    aguardando:   { label: "Aguardando",   cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
    pago_parcial: { label: "Pago Parcial", cls: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" },
    pago:         { label: "Pago",         cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
    vencido:      { label: "Vencido",      cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
};

const DUP_STATUS_CONFIG = {
    aberta:     { label: "Em Aberto",  cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
    paga:       { label: "Paga",       cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
    vencida:    { label: "Vencida",    cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
    protestada: { label: "Protestada", cls: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300" },
    cancelada:  { label: "Cancelada",  cls: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
};

// ===== FORMATTERS =====
function formatCurrency(val) {
    if (!val && val !== 0) return "R$ 0,00";
    return `R$ ${Number(val).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(iso) {
    if (!iso) return "—";
    try { return new Date(iso + "T12:00:00").toLocaleDateString("pt-BR"); } catch { return iso; }
}

function daysUntil(iso) {
    if (!iso) return null;
    const diff = Math.round((new Date(iso + "T12:00:00") - new Date()) / 86400000);
    return diff;
}

// ===== HELPERS =====
function emptyNFForm() {
    return {
        order_id: "", order_numero: "", exp_id: "", exp_numero: "",
        cliente_nome: "", cliente_cnpj: "",
        valor_produtos: "", valor_frete: "", valor_impostos: "",
        forma_pagamento: "pix", condicao_pagamento: "à vista",
        data_emissao: new Date().toISOString().slice(0, 10),
        data_vencimento: "", observacoes: "",
    };
}

// ===== BADGE COMPONENTS =====
function NFBadge({ status }) {
    const cfg = NF_STATUS_CONFIG[status] || NF_STATUS_CONFIG.rascunho;
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

function PgtoBadge({ status }) {
    const cfg = PGTO_CONFIG[status] || PGTO_CONFIG.aguardando;
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

function DupBadge({ status }) {
    const cfg = DUP_STATUS_CONFIG[status] || DUP_STATUS_CONFIG.aberta;
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

// ===== MAIN PAGE =====
export default function FaturamentoPage() {
    // ── NF state ──
    const [notas, setNotas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState("all");
    const [pgtoFilter, setPgtoFilter] = useState("all");
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState(emptyNFForm());
    const [saving, setSaving] = useState(false);
    const [selectedNF, setSelectedNF] = useState(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [showEmitir, setShowEmitir] = useState(false);
    const [emitirForm, setEmitirForm] = useState({ fiscal_payload: "{}" });
    const [showPagamento, setShowPagamento] = useState(false);
    const [pgtoForm, setPgtoForm] = useState({ status_pagamento: "pago", valor_pago: "", data_pagamento: "" });
    const [orders, setOrders] = useState([]);
    const [expeditions, setExpeditions] = useState([]);
    const [dashboard, setDashboard] = useState(null);

    // ── Duplicatas state ──
    const [activeTab, setActiveTab] = useState("notas");
    const [duplicatas, setDuplicatas] = useState([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupSearch, setDupSearch] = useState("");
    const [dupStatusFilter, setDupStatusFilter] = useState("all");
    const [dupDashboard, setDupDashboard] = useState(null);
    const [selectedDup, setSelectedDup] = useState(null);
    const [showBaixa, setShowBaixa] = useState(false);
    const [baixaForm, setBaixaForm] = useState({ valor_pago: "", data_pagamento: "", forma_pagamento: "", observacoes: "" });
    const [gerandoDups, setGerandoDups] = useState(false);

    // ── NF loaders ──
    const loadNotas = useCallback(async () => {
        setLoading(true);
        try {
            const params = {};
            if (statusFilter !== "all") params.status = statusFilter;
            if (pgtoFilter !== "all") params.status_pagamento = pgtoFilter;
            if (search.trim()) params.q = search.trim();
            const { data } = await api.get("/faturamento/notas", { params });
            setNotas(data || []);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    }, [search, statusFilter, pgtoFilter]);

    const loadDashboard = useCallback(async () => {
        try {
            const { data } = await api.get("/faturamento/dashboard");
            setDashboard(data);
        } catch { /* optional */ }
    }, []);

    const loadRefs = useCallback(async () => {
        try {
            const [ordRes, expRes] = await Promise.all([
                api.get("/orders", { params: { status: "concluido" } }),
                api.get("/expedicao/ordens", { params: { status: "expedido" } }),
            ]);
            setOrders(Array.isArray(ordRes.data) ? ordRes.data : []);
            setExpeditions(Array.isArray(expRes.data) ? expRes.data : []);
        } catch { /* optional */ }
    }, []);

    // ── Duplicatas loaders ──
    const loadDuplicatas = useCallback(async () => {
        setDupLoading(true);
        try {
            const params = {};
            if (dupStatusFilter !== "all") params.status = dupStatusFilter;
            if (dupSearch.trim()) params.q = dupSearch.trim();
            const { data } = await api.get("/faturamento/duplicatas", { params });
            setDuplicatas(data || []);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setDupLoading(false);
        }
    }, [dupSearch, dupStatusFilter]);

    const loadDupDashboard = useCallback(async () => {
        try {
            const { data } = await api.get("/faturamento/duplicatas/dashboard");
            setDupDashboard(data);
        } catch { /* optional */ }
    }, []);

    useEffect(() => { loadNotas(); }, [loadNotas]);
    useEffect(() => { loadDashboard(); }, [loadDashboard]);
    useEffect(() => { loadRefs(); }, [loadRefs]);
    useEffect(() => {
        if (activeTab === "duplicatas") { loadDuplicatas(); loadDupDashboard(); }
    }, [activeTab, loadDuplicatas, loadDupDashboard]);

    // ── NF helpers ──
    const setField = (k, v) => setForm(f => ({ ...f, [k]: v }));

    const onSelectOrder = (orderId) => {
        const o = orders.find(x => x.id === orderId);
        if (!o) { setField("order_id", ""); return; }
        setForm(f => ({
            ...f,
            order_id: o.id,
            order_numero: o.numero_pedido || "",
            cliente_nome: o.cliente?.razao_social || o.cliente?.nome || f.cliente_nome,
            cliente_cnpj: o.cliente?.cnpj || f.cliente_cnpj,
            valor_produtos: String(o.total_pedido || ""),
        }));
    };

    const onSelectExp = (expId) => {
        const e = expeditions.find(x => x.id === expId);
        if (!e) { setField("exp_id", ""); return; }
        setForm(f => ({
            ...f,
            exp_id: e.id,
            exp_numero: e.numero_exp || "",
            cliente_nome: e.cliente_nome || f.cliente_nome,
        }));
    };

    const calcTotal = () => {
        const p = Number(form.valor_produtos) || 0;
        const fr = Number(form.valor_frete) || 0;
        const im = Number(form.valor_impostos) || 0;
        return p + fr + im;
    };

    // ── NF handlers ──
    const handleCreate = async () => {
        if (!form.cliente_nome.trim()) { toast.error("Informe o nome do cliente"); return; }
        setSaving(true);
        try {
            const total = calcTotal();
            await api.post("/faturamento/notas", {
                order_id: form.order_id || null,
                order_numero: form.order_numero || null,
                exp_id: form.exp_id || null,
                exp_numero: form.exp_numero || null,
                cliente_nome: form.cliente_nome.trim(),
                cliente_cnpj: form.cliente_cnpj,
                valor_produtos: Number(form.valor_produtos) || 0,
                valor_frete: Number(form.valor_frete) || 0,
                valor_impostos: Number(form.valor_impostos) || 0,
                valor_total: total,
                forma_pagamento: form.forma_pagamento,
                condicao_pagamento: form.condicao_pagamento,
                data_emissao: form.data_emissao || null,
                data_vencimento: form.data_vencimento || null,
                observacoes: form.observacoes,
            });
            toast.success("Nota Fiscal criada");
            setShowForm(false);
            setForm(emptyNFForm());
            loadNotas();
            loadDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(false);
        }
    };

    const handleEmitir = async () => {
        if (!selectedNF) return;
        setActionLoading(true);
        try {
            const fiscalPayload = JSON.parse(emitirForm.fiscal_payload || "{}");
            const updated = await api.post(`/faturamento/notas/${selectedNF.id}/transmitir`, { fiscal_payload: fiscalPayload });
            toast.success(updated.data.status === "emitida" ? "NF-e autorizada pela SEFAZ" : "NF-e transmitida e em processamento");
            setShowEmitir(false);
            setSelectedNF(updated.data);
            loadNotas();
            loadDashboard();
        } catch (e) {
            toast.error(e instanceof SyntaxError ? "JSON fiscal inválido." : formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleSincronizarFiscal = async (nf) => {
        setActionLoading(true);
        try {
            const updated = await api.post(`/faturamento/notas/${nf.id}/sincronizar-fiscal`);
            setSelectedNF(current => current?.id === nf.id ? updated.data : current);
            toast.success(updated.data.status === "emitida" ? "NF-e autorizada pela SEFAZ" : `Status fiscal: ${updated.data.fiscal_status}`);
            loadNotas();
            loadDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally { setActionLoading(false); }
    };

    const handleRegistrarPagamento = async () => {
        if (!selectedNF) return;
        setActionLoading(true);
        try {
            const updated = await api.put(`/faturamento/notas/${selectedNF.id}`, {
                status_pagamento: pgtoForm.status_pagamento,
                valor_pago: Number(pgtoForm.valor_pago) || selectedNF.valor_total,
                data_pagamento: pgtoForm.data_pagamento || new Date().toISOString().slice(0, 10),
            });
            toast.success("Pagamento registrado");
            setShowPagamento(false);
            setSelectedNF(updated.data);
            loadNotas();
            loadDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleCancel = async (nf) => {
        if (!window.confirm(`Cancelar ${nf.numero_interno}?`)) return;
        setActionLoading(true);
        try {
            const updated = await api.put(`/faturamento/notas/${nf.id}`, { status: "cancelada" });
            toast.success("NF cancelada");
            loadNotas();
            loadDashboard();
            if (selectedNF?.id === nf.id) setSelectedNF(updated.data);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleGerarDuplicatas = async (nf) => {
        setGerandoDups(true);
        try {
            const { data } = await api.post(`/faturamento/notas/${nf.id}/gerar-duplicatas`);
            const qtd = Array.isArray(data) ? data.length : 0;
            toast.success(`${qtd} duplicata${qtd !== 1 ? "s" : ""} gerada${qtd !== 1 ? "s" : ""}`);
            // Refresh NF to show duplicatas_geradas flag
            const updated = await api.get(`/faturamento/notas/${nf.id}`);
            setSelectedNF(updated.data);
            loadNotas();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setGerandoDups(false);
        }
    };

    // ── Duplicata handlers ──
    const openBaixa = (dup) => {
        setSelectedDup(dup);
        setBaixaForm({
            valor_pago: String(dup.valor),
            data_pagamento: new Date().toISOString().slice(0, 10),
            forma_pagamento: dup.forma_pagamento || "",
            observacoes: "",
        });
        setShowBaixa(true);
    };

    const handleBaixar = async () => {
        if (!selectedDup) return;
        setActionLoading(true);
        try {
            const updated = await api.put(`/faturamento/duplicatas/${selectedDup.id}`, {
                valor_pago: Number(baixaForm.valor_pago) || selectedDup.valor,
                data_pagamento: baixaForm.data_pagamento || new Date().toISOString().slice(0, 10),
                forma_pagamento: baixaForm.forma_pagamento || undefined,
                observacoes: baixaForm.observacoes || undefined,
            });
            toast.success("Duplicata baixada");
            setShowBaixa(false);
            setSelectedDup(null);
            loadDuplicatas();
            loadDupDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleProtestaDup = async (dup) => {
        if (!window.confirm(`Marcar duplicata ${dup.label} como protestada?`)) return;
        setActionLoading(true);
        try {
            await api.put(`/faturamento/duplicatas/${dup.id}`, {
                status: "protestada",
                data_protesto: new Date().toISOString().slice(0, 10),
            });
            toast.success("Duplicata marcada como protestada");
            loadDuplicatas();
            loadDupDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    return (
        <div className="h-full overflow-auto">
            <div className="max-w-6xl mx-auto p-6 space-y-5">
                {/* Header */}
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div>
                        <h1 className="text-2xl font-heading font-semibold tracking-tight flex items-center gap-2">
                            <Receipt className="h-6 w-6" />
                            Faturamento
                        </h1>
                        <p className="text-sm text-muted-foreground mt-1">
                            Notas Fiscais de saída e Contas a Receber
                        </p>
                    </div>
                    {activeTab === "notas" && (
                        <Button onClick={() => { setForm(emptyNFForm()); setShowForm(true); }}>
                            <Plus className="h-4 w-4 mr-1" /> Nova NF
                        </Button>
                    )}
                </div>

                {/* Tabs */}
                <Tabs value={activeTab} onValueChange={setActiveTab}>
                    <TabsList>
                        <TabsTrigger value="notas" className="flex items-center gap-1.5">
                            <FileText className="h-3.5 w-3.5" /> Notas Fiscais
                        </TabsTrigger>
                        <TabsTrigger value="duplicatas" className="flex items-center gap-1.5">
                            <Banknote className="h-3.5 w-3.5" /> Contas a Receber
                            {dupDashboard?.vencidas > 0 && (
                                <span className="ml-1 h-4 min-w-4 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center px-1">
                                    {dupDashboard.vencidas}
                                </span>
                            )}
                        </TabsTrigger>
                    </TabsList>

                    {/* ───────────── TAB: NOTAS FISCAIS ───────────── */}
                    <TabsContent value="notas" className="space-y-4 mt-4">
                        {/* NF Dashboard */}
                        {dashboard && (
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                {[
                                    { label: "NFs Emitidas",     value: dashboard.emitidas,              cls: "text-blue-600" },
                                    { label: "Aguard. Pagamento",value: dashboard.aguardando_pagamento,   cls: "text-amber-600" },
                                    { label: "Vencidas",         value: dashboard.vencidas,              cls: "text-red-600" },
                                    { label: "A Receber",        value: formatCurrency(dashboard.total_a_receber), cls: "text-green-600", isText: true },
                                ].map(s => (
                                    <Card key={s.label}><CardContent className="p-3">
                                        <div className="text-[11px] text-muted-foreground uppercase tracking-wider">{s.label}</div>
                                        <div className={`font-bold mt-0.5 ${s.cls} ${s.isText ? "text-base" : "text-2xl"}`}>{s.value}</div>
                                    </CardContent></Card>
                                ))}
                            </div>
                        )}

                        {/* NF Filters */}
                        <div className="flex gap-2 flex-wrap">
                            <div className="relative flex-1 min-w-[220px]">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                <Input placeholder="Buscar NF, cliente, PI…" value={search}
                                    onChange={e => setSearch(e.target.value)} className="pl-9" />
                            </div>
                            <Select value={statusFilter} onValueChange={setStatusFilter}>
                                <SelectTrigger className="w-36"><SelectValue placeholder="Status NF" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Todos</SelectItem>
                                    {Object.entries(NF_STATUS_CONFIG).map(([k, v]) => (
                                        <SelectItem key={k} value={k}>{v.label}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Select value={pgtoFilter} onValueChange={setPgtoFilter}>
                                <SelectTrigger className="w-40"><SelectValue placeholder="Pagamento" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Todos Pagamentos</SelectItem>
                                    {Object.entries(PGTO_CONFIG).map(([k, v]) => (
                                        <SelectItem key={k} value={k}>{v.label}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* NF List */}
                        {loading ? (
                            <div className="flex items-center justify-center py-20">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                            </div>
                        ) : notas.length === 0 ? (
                            <Card className="border-dashed"><CardContent className="py-16 text-center">
                                <Receipt className="h-14 w-14 mx-auto mb-4 text-muted-foreground/30" />
                                <h3 className="text-lg font-semibold mb-1">Nenhuma nota fiscal</h3>
                                <p className="text-sm text-muted-foreground">Crie uma NF vinculada a um PI ou EXP.</p>
                            </CardContent></Card>
                        ) : (
                            <div className="space-y-2">
                                {notas.map(nf => (
                                    <Card key={nf.id}
                                        className="hover:border-primary/40 hover:shadow-sm transition-all cursor-pointer group"
                                        onClick={() => setSelectedNF(nf)}
                                        data-testid={`nf-card-${nf.id}`}
                                    >
                                        <CardContent className="p-4">
                                            <div className="flex items-start justify-between gap-4">
                                                <div className="flex-1 min-w-0 space-y-1.5">
                                                    <div className="flex items-center gap-2 flex-wrap">
                                                        <span className="font-mono text-sm font-bold text-primary">
                                                            {nf.numero_nfe || nf.numero_interno}
                                                        </span>
                                                        <NFBadge status={nf.status} />
                                                        <PgtoBadge status={nf.status_pagamento} />
                                                        {nf.duplicatas_geradas && (
                                                            <Badge variant="outline" className="text-[10px] text-teal-600 border-teal-300">
                                                                {nf.total_parcelas}x Duplicata{nf.total_parcelas !== 1 ? "s" : ""}
                                                            </Badge>
                                                        )}
                                                        {nf.order_numero && <Badge variant="outline" className="text-[10px]">PI {nf.order_numero}</Badge>}
                                                        {nf.exp_numero && <Badge variant="outline" className="text-[10px]">EXP {nf.exp_numero}</Badge>}
                                                    </div>
                                                    <h3 className="font-semibold text-sm flex items-center gap-1">
                                                        <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                                                        {nf.cliente_nome}
                                                    </h3>
                                                    <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                                                        <span className="flex items-center gap-1">
                                                            <DollarSign className="h-3 w-3" />{formatCurrency(nf.valor_total)}
                                                        </span>
                                                        <span>Emissão: {formatDate(nf.data_emissao)}</span>
                                                        {nf.data_vencimento && (
                                                            <span className="flex items-center gap-1">
                                                                <Calendar className="h-3 w-3" />Venc: {formatDate(nf.data_vencimento)}
                                                            </span>
                                                        )}
                                                        <span>{nf.forma_pagamento} · {nf.condicao_pagamento}</span>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-2 shrink-0">
                                                    {["rascunho", "rejeitada"].includes(nf.status) && (
                                                        <Button size="sm" variant="outline" className="h-8 text-xs"
                                                            disabled={actionLoading}
                                                            onClick={e => { e.stopPropagation(); setSelectedNF(nf); setEmitirForm({ fiscal_payload: JSON.stringify(nf.fiscal_payload || {}, null, 2) }); setShowEmitir(true); }}>
                                                            Emitir NF
                                                        </Button>
                                                    )}
                                                    {nf.status === "processando" && (
                                                        <Button size="sm" variant="outline" className="h-8 text-xs" disabled={actionLoading}
                                                            onClick={e => { e.stopPropagation(); handleSincronizarFiscal(nf); }}>
                                                            <RefreshCw className="mr-1 h-3.5 w-3.5" />Consultar SEFAZ
                                                        </Button>
                                                    )}
                                                    {nf.status === "emitida" && ["aguardando", "pago_parcial"].includes(nf.status_pagamento) && (
                                                        <Button size="sm" variant="outline" className="h-8 text-xs"
                                                            disabled={actionLoading}
                                                            onClick={e => { e.stopPropagation(); setSelectedNF(nf); setPgtoForm({ status_pagamento: "pago", valor_pago: String(nf.valor_total), data_pagamento: new Date().toISOString().slice(0, 10) }); setShowPagamento(true); }}>
                                                            Registrar Pgto
                                                        </Button>
                                                    )}
                                                    <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
                                                </div>
                                            </div>
                                        </CardContent>
                                    </Card>
                                ))}
                            </div>
                        )}
                    </TabsContent>

                    {/* ───────────── TAB: CONTAS A RECEBER ───────────── */}
                    <TabsContent value="duplicatas" className="space-y-4 mt-4">
                        {/* Dup Dashboard */}
                        {dupDashboard && (
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                {[
                                    { label: "Em Aberto",         value: dupDashboard.em_aberto,             icon: Clock,         cls: "text-amber-600" },
                                    { label: "Vencidas",          value: dupDashboard.vencidas,              icon: AlertCircle,   cls: "text-red-600" },
                                    { label: "A Vencer (30d)",    value: dupDashboard.a_vencer_30_dias,      icon: Calendar,      cls: "text-blue-600" },
                                    { label: "Total em Aberto",   value: formatCurrency(dupDashboard.total_em_aberto), icon: TrendingUp, cls: "text-green-600", isText: true },
                                ].map(s => (
                                    <Card key={s.label}><CardContent className="p-3">
                                        <div className="flex items-center gap-1 mb-0.5">
                                            <s.icon className={`h-3 w-3 ${s.cls}`} />
                                            <span className="text-[11px] text-muted-foreground uppercase tracking-wider">{s.label}</span>
                                        </div>
                                        <div className={`font-bold ${s.cls} ${s.isText ? "text-base" : "text-2xl"}`}>{s.value}</div>
                                    </CardContent></Card>
                                ))}
                            </div>
                        )}

                        {/* Dup Filters */}
                        <div className="flex gap-2 flex-wrap">
                            <div className="relative flex-1 min-w-[220px]">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                <Input placeholder="Buscar NF, cliente, PI…" value={dupSearch}
                                    onChange={e => setDupSearch(e.target.value)} className="pl-9" />
                            </div>
                            <Select value={dupStatusFilter} onValueChange={setDupStatusFilter}>
                                <SelectTrigger className="w-40"><SelectValue placeholder="Status" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Todos</SelectItem>
                                    {Object.entries(DUP_STATUS_CONFIG).map(([k, v]) => (
                                        <SelectItem key={k} value={k}>{v.label}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button variant="outline" size="sm" onClick={() => { loadDuplicatas(); loadDupDashboard(); }}
                                disabled={dupLoading} className="h-10">
                                <RefreshCw className={`h-3.5 w-3.5 mr-1 ${dupLoading ? "animate-spin" : ""}`} />
                                Atualizar
                            </Button>
                        </div>

                        {/* Dup Table */}
                        {dupLoading ? (
                            <div className="flex items-center justify-center py-20">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                            </div>
                        ) : duplicatas.length === 0 ? (
                            <Card className="border-dashed"><CardContent className="py-16 text-center">
                                <Banknote className="h-14 w-14 mx-auto mb-4 text-muted-foreground/30" />
                                <h3 className="text-lg font-semibold mb-1">Nenhuma duplicata</h3>
                                <p className="text-sm text-muted-foreground">
                                    Abra uma NF emitida e clique em <strong>Gerar Duplicatas</strong> para criar as parcelas a receber.
                                </p>
                            </CardContent></Card>
                        ) : (
                            <Card>
                                <div className="overflow-x-auto">
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="bg-[#1F2C5C] text-white text-xs">
                                                <th className="text-left p-3 font-medium">Parcela</th>
                                                <th className="text-left p-3 font-medium">NF</th>
                                                <th className="text-left p-3 font-medium">Cliente</th>
                                                <th className="text-right p-3 font-medium">Valor</th>
                                                <th className="text-center p-3 font-medium">Vencimento</th>
                                                <th className="text-center p-3 font-medium">Status</th>
                                                <th className="text-center p-3 font-medium">Ações</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {duplicatas.map((dup, idx) => {
                                                const days = daysUntil(dup.data_vencimento);
                                                const isOverdue = dup.status === "vencida";
                                                const isDueSoon = dup.status === "aberta" && days !== null && days >= 0 && days <= 7;
                                                return (
                                                    <tr key={dup.id}
                                                        className={`border-t transition-colors ${idx % 2 === 0 ? "bg-background" : "bg-muted/20"} ${isOverdue ? "bg-red-50/50 dark:bg-red-900/10" : ""} hover:bg-muted/40`}
                                                    >
                                                        <td className="p-3">
                                                            <span className="font-mono font-semibold text-primary text-xs bg-primary/10 px-1.5 py-0.5 rounded">
                                                                {dup.label || `${dup.numero_parcela}/${dup.total_parcelas}`}
                                                            </span>
                                                        </td>
                                                        <td className="p-3">
                                                            <div className="font-mono text-xs text-muted-foreground">{dup.nf_numero}</div>
                                                            {dup.order_numero && <div className="text-[10px] text-muted-foreground">PI {dup.order_numero}</div>}
                                                        </td>
                                                        <td className="p-3">
                                                            <div className="font-medium text-sm leading-tight">{dup.cliente_nome}</div>
                                                            {dup.cliente_cnpj && <div className="text-[10px] text-muted-foreground">{dup.cliente_cnpj}</div>}
                                                        </td>
                                                        <td className="p-3 text-right">
                                                            <div className="font-mono font-semibold">{formatCurrency(dup.valor)}</div>
                                                            {dup.forma_pagamento && <div className="text-[10px] text-muted-foreground">{dup.forma_pagamento}</div>}
                                                        </td>
                                                        <td className="p-3 text-center">
                                                            <div className={`text-xs font-medium ${isOverdue ? "text-red-600" : isDueSoon ? "text-amber-600" : ""}`}>
                                                                {formatDate(dup.data_vencimento)}
                                                            </div>
                                                            {isOverdue && days !== null && (
                                                                <div className="text-[10px] text-red-500 font-semibold">{Math.abs(days)}d atraso</div>
                                                            )}
                                                            {isDueSoon && (
                                                                <div className="text-[10px] text-amber-500 font-semibold">vence em {days}d</div>
                                                            )}
                                                            {dup.status === "paga" && dup.data_pagamento && (
                                                                <div className="text-[10px] text-green-600">pago {formatDate(dup.data_pagamento)}</div>
                                                            )}
                                                        </td>
                                                        <td className="p-3 text-center">
                                                            <DupBadge status={dup.status} />
                                                        </td>
                                                        <td className="p-3 text-center">
                                                            <div className="flex items-center justify-center gap-1">
                                                                {["aberta", "vencida"].includes(dup.status) && (
                                                                    <Button size="sm" variant="outline"
                                                                        className="h-7 text-xs px-2 text-green-700 border-green-300 hover:bg-green-50 dark:hover:bg-green-900/20"
                                                                        disabled={actionLoading}
                                                                        onClick={() => openBaixa(dup)}>
                                                                        <CheckCircle2 className="h-3 w-3 mr-1" />Baixar
                                                                    </Button>
                                                                )}
                                                                {dup.status === "vencida" && (
                                                                    <Button size="sm" variant="ghost"
                                                                        className="h-7 text-xs px-2 text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-900/20"
                                                                        disabled={actionLoading}
                                                                        onClick={() => handleProtestaDup(dup)}>
                                                                        Protestar
                                                                    </Button>
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            </Card>
                        )}
                    </TabsContent>
                </Tabs>
            </div>

            {/* ═══ NF DETAIL DIALOG ═══ */}
            {selectedNF && !showEmitir && !showPagamento && (
                <Dialog open onOpenChange={() => setSelectedNF(null)}>
                    <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                <Receipt className="h-5 w-5" />
                                {selectedNF.numero_nfe || selectedNF.numero_interno}
                            </DialogTitle>
                        </DialogHeader>
                        <div className="space-y-4 text-sm">
                            <div className="flex items-center gap-2 flex-wrap">
                                <NFBadge status={selectedNF.status} />
                                <PgtoBadge status={selectedNF.status_pagamento} />
                                {selectedNF.duplicatas_geradas && (
                                    <Badge variant="outline" className="text-teal-600 border-teal-300 text-[10px]">
                                        {selectedNF.total_parcelas}x duplicata{selectedNF.total_parcelas !== 1 ? "s" : ""} gerada{selectedNF.total_parcelas !== 1 ? "s" : ""}
                                    </Badge>
                                )}
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div><span className="text-muted-foreground">Cliente:</span> {selectedNF.cliente_nome}</div>
                                <div><span className="text-muted-foreground">CNPJ:</span> {selectedNF.cliente_cnpj || "—"}</div>
                                <div><span className="text-muted-foreground">Emissão:</span> {formatDate(selectedNF.data_emissao)}</div>
                                <div><span className="text-muted-foreground">Vencimento:</span> {formatDate(selectedNF.data_vencimento)}</div>
                                <div><span className="text-muted-foreground">Pagamento:</span> {selectedNF.forma_pagamento} / {selectedNF.condicao_pagamento}</div>
                                <div><span className="text-muted-foreground">Pago:</span> {formatCurrency(selectedNF.valor_pago)}</div>
                            </div>
                            {selectedNF.numero_nfe && (
                                <div className="rounded-lg bg-muted/40 p-3 text-xs space-y-1">
                                    <div><span className="font-semibold">NF-e:</span> {selectedNF.numero_nfe}</div>
                                    {selectedNF.chave_acesso && <div className="break-all font-mono text-[10px]">{selectedNF.chave_acesso}</div>}
                                </div>
                            )}
                            <Separator />
                            <div className="grid grid-cols-3 gap-3 text-center">
                                {[
                                    ["Produtos", selectedNF.valor_produtos],
                                    ["Frete", selectedNF.valor_frete],
                                    ["Impostos", selectedNF.valor_impostos],
                                ].map(([label, val]) => (
                                    <div key={label} className="rounded-lg bg-muted/30 p-2">
                                        <div className="text-xs text-muted-foreground">{label}</div>
                                        <div className="font-semibold text-sm">{formatCurrency(val)}</div>
                                    </div>
                                ))}
                            </div>
                            <div className="rounded-lg bg-primary/10 p-3 flex items-center justify-between">
                                <span className="font-semibold">Total</span>
                                <span className="text-lg font-bold text-primary">{formatCurrency(selectedNF.valor_total)}</span>
                            </div>

                            {/* Duplicatas section */}
                            {selectedNF.status === "emitida" && (
                                <>
                                    <Separator />
                                    <div className="rounded-lg border border-teal-200 bg-teal-50/50 dark:border-teal-800 dark:bg-teal-900/10 p-3 space-y-2">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <div className="font-semibold text-sm flex items-center gap-1.5">
                                                    <Banknote className="h-4 w-4 text-teal-600" />
                                                    Duplicatas / Contas a Receber
                                                </div>
                                                <div className="text-xs text-muted-foreground mt-0.5">
                                                    Condição: <strong>{selectedNF.condicao_pagamento || "à vista"}</strong>
                                                    {selectedNF.duplicatas_geradas
                                                        ? ` · ${selectedNF.total_parcelas} parcela${selectedNF.total_parcelas !== 1 ? "s" : ""} gerada${selectedNF.total_parcelas !== 1 ? "s" : ""}`
                                                        : " · Nenhuma duplicata gerada ainda"}
                                                </div>
                                            </div>
                                            <Button size="sm" variant={selectedNF.duplicatas_geradas ? "outline" : "default"}
                                                className={selectedNF.duplicatas_geradas ? "h-8 text-xs" : "h-8 text-xs bg-teal-600 hover:bg-teal-700 text-white"}
                                                disabled={gerandoDups || actionLoading}
                                                onClick={() => handleGerarDuplicatas(selectedNF)}>
                                                {gerandoDups
                                                    ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                                                    : <RefreshCw className="h-3.5 w-3.5 mr-1" />}
                                                {selectedNF.duplicatas_geradas ? "Regenerar" : "Gerar Duplicatas"}
                                            </Button>
                                        </div>
                                        {selectedNF.duplicatas_geradas && (
                                            <Button size="sm" variant="ghost" className="h-7 text-xs text-teal-700 hover:bg-teal-100 dark:hover:bg-teal-900/20 w-full"
                                                onClick={() => { setSelectedNF(null); setActiveTab("duplicatas"); }}>
                                                Ver na aba Contas a Receber →
                                            </Button>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                        <DialogFooter className="flex flex-wrap gap-2 justify-between">
                            <div className="flex gap-2 flex-wrap">
                                {["rascunho", "rejeitada"].includes(selectedNF.status) && (
                                    <Button size="sm"
                                        onClick={() => { setEmitirForm({ fiscal_payload: JSON.stringify(selectedNF.fiscal_payload || {}, null, 2) }); setShowEmitir(true); }}>
                                        Transmitir NF-e
                                    </Button>
                                )}
                                {selectedNF.status === "processando" && (
                                    <Button size="sm" variant="outline" disabled={actionLoading} onClick={() => handleSincronizarFiscal(selectedNF)}>
                                        <RefreshCw className="mr-1 h-4 w-4" />Consultar SEFAZ
                                    </Button>
                                )}
                                {selectedNF.status === "emitida" && ["aguardando", "pago_parcial"].includes(selectedNF.status_pagamento) && (
                                    <Button size="sm" variant="outline"
                                        onClick={() => { setPgtoForm({ status_pagamento: "pago", valor_pago: String(selectedNF.valor_total), data_pagamento: new Date().toISOString().slice(0, 10) }); setShowPagamento(true); }}>
                                        <CheckCircle2 className="h-4 w-4 mr-1" />Registrar Pagamento
                                    </Button>
                                )}
                                {["rascunho", "emitida"].includes(selectedNF.status) && (
                                    <Button size="sm" variant="outline"
                                        className="text-destructive border-destructive/30 hover:text-destructive"
                                        disabled={actionLoading}
                                        onClick={() => handleCancel(selectedNF)}>
                                        Cancelar NF
                                    </Button>
                                )}
                            </div>
                            <Button variant="outline" onClick={() => setSelectedNF(null)}>Fechar</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ═══ EMITIR DIALOG ═══ */}
            {showEmitir && selectedNF && (
                <Dialog open onOpenChange={() => setShowEmitir(false)}>
                    <DialogContent>
                        <DialogHeader><DialogTitle>Transmitir NF-e — {selectedNF.numero_interno}</DialogTitle></DialogHeader>
                        <div className="space-y-3">
                            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/20 dark:text-amber-200">
                                Número, chave e protocolo serão preenchidos somente após autorização fiscal. A NF não será marcada como emitida por digitação manual.
                            </div>
                            <div>
                                <Label>Payload fiscal NF-e 4.00</Label>
                                <Textarea value={emitirForm.fiscal_payload}
                                    onChange={e => setEmitirForm({ fiscal_payload: e.target.value })}
                                    className="mt-1 min-h-64 font-mono text-xs"
                                    placeholder='{"natureza_operacao":"Venda", "tipo_documento":1, "finalidade_emissao":1, "items":[]}' />
                                <p className="mt-1 text-xs text-muted-foreground">A transmissão utiliza o provedor Focus NFe configurado no servidor.</p>
                            </div>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setShowEmitir(false)} disabled={actionLoading}>Cancelar</Button>
                            <Button onClick={handleEmitir} disabled={actionLoading}>
                                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Receipt className="h-4 w-4 mr-1" />}
                                Transmitir para SEFAZ
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ═══ PAGAMENTO NF DIALOG ═══ */}
            {showPagamento && selectedNF && (
                <Dialog open onOpenChange={() => setShowPagamento(false)}>
                    <DialogContent>
                        <DialogHeader><DialogTitle>Registrar Pagamento — {selectedNF.numero_nfe || selectedNF.numero_interno}</DialogTitle></DialogHeader>
                        <div className="space-y-3">
                            <div>
                                <Label>Status do Pagamento</Label>
                                <Select value={pgtoForm.status_pagamento}
                                    onValueChange={v => setPgtoForm(f => ({ ...f, status_pagamento: v }))}>
                                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="pago">Pago Integralmente</SelectItem>
                                        <SelectItem value="pago_parcial">Pago Parcial</SelectItem>
                                        <SelectItem value="vencido">Vencido</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div>
                                <Label>Valor Pago</Label>
                                <Input type="number" min="0" step="0.01"
                                    value={pgtoForm.valor_pago}
                                    onChange={e => setPgtoForm(f => ({ ...f, valor_pago: e.target.value }))}
                                    placeholder="0,00" className="mt-1" />
                            </div>
                            <div>
                                <Label>Data do Pagamento</Label>
                                <Input type="date" value={pgtoForm.data_pagamento}
                                    onChange={e => setPgtoForm(f => ({ ...f, data_pagamento: e.target.value }))}
                                    className="mt-1" />
                            </div>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setShowPagamento(false)} disabled={actionLoading}>Cancelar</Button>
                            <Button onClick={handleRegistrarPagamento} disabled={actionLoading}>
                                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <CheckCircle2 className="h-4 w-4 mr-1" />}
                                Confirmar
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ═══ BAIXA DUPLICATA DIALOG ═══ */}
            {showBaixa && selectedDup && (
                <Dialog open onOpenChange={() => { setShowBaixa(false); setSelectedDup(null); }}>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                <CheckCircle2 className="h-5 w-5 text-green-600" />
                                Baixar Duplicata {selectedDup.label}
                            </DialogTitle>
                        </DialogHeader>
                        <div className="space-y-1 text-sm rounded-lg bg-muted/40 p-3 mb-2">
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Cliente</span>
                                <span className="font-medium">{selectedDup.cliente_nome}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">NF</span>
                                <span className="font-mono">{selectedDup.nf_numero}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Valor original</span>
                                <span className="font-semibold">{formatCurrency(selectedDup.valor)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Vencimento</span>
                                <span className={selectedDup.status === "vencida" ? "text-red-600 font-medium" : ""}>
                                    {formatDate(selectedDup.data_vencimento)}
                                </span>
                            </div>
                        </div>
                        <div className="space-y-3">
                            <div>
                                <Label>Valor Recebido *</Label>
                                <Input type="number" min="0" step="0.01"
                                    value={baixaForm.valor_pago}
                                    onChange={e => setBaixaForm(f => ({ ...f, valor_pago: e.target.value }))}
                                    className="mt-1 font-mono" />
                                {Number(baixaForm.valor_pago) < selectedDup.valor && Number(baixaForm.valor_pago) > 0 && (
                                    <p className="text-[11px] text-amber-600 mt-1">
                                        Valor parcial — duplicata ficará em aberto pelo saldo restante
                                    </p>
                                )}
                            </div>
                            <div>
                                <Label>Data de Recebimento</Label>
                                <Input type="date" value={baixaForm.data_pagamento}
                                    onChange={e => setBaixaForm(f => ({ ...f, data_pagamento: e.target.value }))}
                                    className="mt-1" />
                            </div>
                            <div>
                                <Label>Forma de Pagamento</Label>
                                <Select value={baixaForm.forma_pagamento || "pix"}
                                    onValueChange={v => setBaixaForm(f => ({ ...f, forma_pagamento: v }))}>
                                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        {["pix", "boleto", "transferencia", "cheque", "cartao", "dinheiro"].map(v => (
                                            <SelectItem key={v} value={v}>{v}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div>
                                <Label>Observações</Label>
                                <Input value={baixaForm.observacoes}
                                    onChange={e => setBaixaForm(f => ({ ...f, observacoes: e.target.value }))}
                                    placeholder="Opcional" className="mt-1" />
                            </div>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => { setShowBaixa(false); setSelectedDup(null); }} disabled={actionLoading}>
                                Cancelar
                            </Button>
                            <Button onClick={handleBaixar} disabled={actionLoading || !baixaForm.valor_pago}
                                className="bg-green-600 hover:bg-green-700 text-white">
                                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <CheckCircle2 className="h-4 w-4 mr-1" />}
                                Confirmar Baixa
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ═══ CREATE NF DIALOG ═══ */}
            <Dialog open={showForm} onOpenChange={v => { if (!v) setShowForm(false); }}>
                <DialogContent className="max-w-2xl max-h-[92vh] overflow-y-auto">
                    <DialogHeader><DialogTitle>Nova Nota Fiscal</DialogTitle></DialogHeader>
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-3">
                            {orders.length > 0 && (
                                <div>
                                    <Label>Vincular PI</Label>
                                    <Select onValueChange={onSelectOrder}>
                                        <SelectTrigger className="mt-1"><SelectValue placeholder="Selecionar PI…" /></SelectTrigger>
                                        <SelectContent>
                                            {orders.map(o => (
                                                <SelectItem key={o.id} value={o.id}>
                                                    #{o.numero_pedido} — {o.cliente?.razao_social || "—"}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                            {expeditions.length > 0 && (
                                <div>
                                    <Label>Vincular EXP</Label>
                                    <Select onValueChange={onSelectExp}>
                                        <SelectTrigger className="mt-1"><SelectValue placeholder="Selecionar EXP…" /></SelectTrigger>
                                        <SelectContent>
                                            {expeditions.map(e => (
                                                <SelectItem key={e.id} value={e.id}>
                                                    {e.numero_exp} — {e.cliente_nome}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <Label>Cliente *</Label>
                                <Input value={form.cliente_nome} onChange={e => setField("cliente_nome", e.target.value)}
                                    placeholder="Razão social" className="mt-1" />
                            </div>
                            <div>
                                <Label>CNPJ</Label>
                                <Input value={form.cliente_cnpj} onChange={e => setField("cliente_cnpj", e.target.value)}
                                    placeholder="00.000.000/0000-00" className="mt-1" />
                            </div>
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                            <div>
                                <Label>Valor Produtos (R$)</Label>
                                <Input type="number" value={form.valor_produtos}
                                    onChange={e => setField("valor_produtos", e.target.value)}
                                    placeholder="0,00" className="mt-1" />
                            </div>
                            <div>
                                <Label>Frete (R$)</Label>
                                <Input type="number" value={form.valor_frete}
                                    onChange={e => setField("valor_frete", e.target.value)}
                                    placeholder="0,00" className="mt-1" />
                            </div>
                            <div>
                                <Label>Impostos (R$)</Label>
                                <Input type="number" value={form.valor_impostos}
                                    onChange={e => setField("valor_impostos", e.target.value)}
                                    placeholder="0,00" className="mt-1" />
                            </div>
                        </div>
                        <div className="rounded-lg bg-primary/10 p-3 flex items-center justify-between">
                            <span className="font-semibold text-sm">Total</span>
                            <span className="text-lg font-bold text-primary">{formatCurrency(calcTotal())}</span>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <Label>Forma de Pagamento</Label>
                                <Select value={form.forma_pagamento} onValueChange={v => setField("forma_pagamento", v)}>
                                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        {["pix", "boleto", "transferencia", "cheque", "cartao", "prazo"].map(v => (
                                            <SelectItem key={v} value={v}>{v}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div>
                                <Label>Condição de Pagamento</Label>
                                <Input value={form.condicao_pagamento}
                                    onChange={e => setField("condicao_pagamento", e.target.value)}
                                    placeholder="à vista / 30/60/90…" className="mt-1" />
                                <p className="text-[11px] text-muted-foreground mt-0.5">
                                    Ex: "30/60/90" gera 3 duplicatas ao emitir
                                </p>
                            </div>
                            <div>
                                <Label>Data de Emissão</Label>
                                <Input type="date" value={form.data_emissao}
                                    onChange={e => setField("data_emissao", e.target.value)} className="mt-1" />
                            </div>
                            <div>
                                <Label>Data de Vencimento</Label>
                                <Input type="date" value={form.data_vencimento}
                                    onChange={e => setField("data_vencimento", e.target.value)} className="mt-1" />
                            </div>
                        </div>
                        <div>
                            <Label>Observações</Label>
                            <Input value={form.observacoes} onChange={e => setField("observacoes", e.target.value)}
                                placeholder="Opcional" className="mt-1" />
                        </div>
                    </div>
                    <DialogFooter className="mt-4">
                        <Button variant="outline" onClick={() => setShowForm(false)} disabled={saving}>Cancelar</Button>
                        <Button onClick={handleCreate} disabled={saving}>
                            {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Receipt className="h-4 w-4 mr-1" />}
                            Criar Nota Fiscal
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
