import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
    Truck, Plus, Search, Loader2, ChevronRight, Trash2,
    Building2, Calendar, Package, ClipboardCheck, Printer,
    CheckCircle2, XCircle, FileText,
} from "lucide-react";

const STATUS_CONFIG = {
    pendente:   { label: "Pendente",    cls: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
    preparando: { label: "Preparando",  cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
    conferido:  { label: "Conferido",   cls: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300" },
    expedido:   { label: "Expedido",    cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" },
    entregue:   { label: "Entregue",    cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
    cancelado:  { label: "Cancelado",   cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
};

// preparando → requires conferencia dialog; conferido → requires dispatch dialog
const NEXT_STATUS = {
    pendente:   { to: "preparando",  label: "Iniciar Separação",   dialog: null },
    preparando: { to: "conferido",   label: "Conferir Itens",       dialog: "conferencia" },
    conferido:  { to: "expedido",    label: "Confirmar Despacho",   dialog: "dispatch" },
    expedido:   { to: "entregue",    label: "Confirmar Entrega",    dialog: null },
};

function emptyItem() {
    return { order_item_id: "", produto_nome: "", sku: "", quantidade: "", unidade: "un", lote: "", volumes: 1, peso_unitario: 0 };
}

function emptyForm() {
    return {
        order_id: "",
        order_numero: "",
        cliente_nome: "",
        endereco_entrega: "",
        transportadora: "",
        previsao_entrega: "",
        numero_nf_saida: "",
        observacoes: "",
        items: [emptyItem()],
    };
}

function formatDate(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleDateString("pt-BR"); } catch { return iso; }
}

function StatusBadge({ status }) {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pendente;
    return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

export default function ExpedicaoPage() {
    const [ordens, setOrdens] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState("all");
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState(emptyForm());
    const [saving, setSaving] = useState(false);
    const [selectedExp, setSelectedExp] = useState(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [orders, setOrders] = useState([]);
    const [fulfillment, setFulfillment] = useState(null);

    // Dispatch dialog (conferido → expedido)
    const [showDispatch, setShowDispatch] = useState(false);
    const [dispatchForm, setDispatchForm] = useState({ codigo_rastreio: "", transportadora: "", numero_nf_saida: "" });

    // Conferência dialog (preparando → conferido)
    const [showConferencia, setShowConferencia] = useState(false);
    const [confItems, setConfItems] = useState([]);
    const [confConferente, setConfConferente] = useState("");
    const [confObs, setConfObs] = useState("");

    // Romaneio dialog
    const [showRomaneio, setShowRomaneio] = useState(false);
    const [romaneioData, setRomaneioData] = useState(null);

    const loadOrdens = useCallback(async () => {
        setLoading(true);
        try {
            const params = {};
            if (statusFilter !== "all") params.status = statusFilter;
            if (search.trim()) params.q = search.trim();
            const { data } = await api.get("/expedicao/ordens", { params });
            setOrdens(data || []);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    }, [search, statusFilter]);

    const loadOrders = useCallback(async () => {
        try {
            const [concluidos, emProducao] = await Promise.all([
                api.get("/orders", { params: { status: "concluido" } }).catch(() => ({ data: [] })),
                api.get("/orders", { params: { status: "em_producao" } }).catch(() => ({ data: [] })),
            ]);
            const merged = [...(concluidos.data || []), ...(emProducao.data || [])];
            setOrders(Array.from(new Map(merged.map(o => [o.id, o])).values()));
        } catch { /* optional */ }
    }, []);

    useEffect(() => { loadOrdens(); }, [loadOrdens]);
    useEffect(() => { loadOrders(); }, [loadOrders]);

    const setField = (k, v) => setForm(f => ({ ...f, [k]: v }));
    const setItem = (idx, k, v) => setForm(f => {
        const items = [...f.items];
        items[idx] = { ...items[idx], [k]: v };
        return { ...f, items };
    });
    const addItem = () => setForm(f => ({ ...f, items: [...f.items, emptyItem()] }));
    const removeItem = (idx) => setForm(f => ({
        ...f, items: f.items.length > 1 ? f.items.filter((_, i) => i !== idx) : f.items,
    }));

    const onSelectOrder = async (orderId) => {
        const o = orders.find(x => x.id === orderId);
        if (!o) { setField("order_id", ""); setFulfillment(null); return; }
        let summary = null;
        try {
            const { data } = await api.get(`/orders/${orderId}/fulfillment-summary`);
            summary = data;
            setFulfillment(data);
        } catch {
            setFulfillment(null);
        }
        const balanceByItem = new Map((summary?.items || []).map(row => [row.order_item_id, row]));
        setForm(f => ({
            ...f,
            order_id: o.id,
            order_numero: o.numero_pedido || "",
            cliente_nome: o.cliente?.razao_social || o.cliente?.nome || f.cliente_nome,
            endereco_entrega: o.frete?.endereco || f.endereco_entrega,
            items: (o.items || []).map((i, idx) => {
                const orderItemId = i.id || `item-${idx + 1}`;
                const balance = balanceByItem.get(orderItemId);
                return ({
                order_item_id: orderItemId,
                produto_nome: i.item || i.descricao || i.produto || "",
                sku: i.codigo_kuryos || i.sku || "",
                quantidade: String(balance?.saldo_produzido_disponivel ?? i.qtd ?? i.quantidade ?? ""),
                unidade: i.unidade || "un",
                lote: "",
                volumes: 1,
                peso_unitario: 0,
                qtd_pedido: balance?.qtd_pedido,
                qtd_produzida: balance?.qtd_produzida,
                qtd_expedida: balance?.qtd_expedida,
                saldo_produzido_disponivel: balance?.saldo_produzido_disponivel,
                saldo_pedido_a_expedir: balance?.saldo_pedido_a_expedir,
            });
            }).filter(i => i.produto_nome) || [emptyItem()],
        }));
    };

    const handleCreate = async () => {
        if (!form.cliente_nome.trim()) { toast.error("Informe o nome do cliente"); return; }
        const itemsValidos = form.items.filter(i => i.produto_nome.trim() && Number(i.quantidade) > 0);
        if (!itemsValidos.length) { toast.error("Adicione ao menos 1 item válido"); return; }
        setSaving(true);
        try {
            const partialItems = itemsValidos.filter(i => i.order_item_id);
            if (form.order_id && fulfillment?.items?.length && partialItems.length === itemsValidos.length) {
                await api.post("/expedicao/ordens/from-order-items", {
                    order_id: form.order_id,
                    endereco_entrega: form.endereco_entrega,
                    transportadora: form.transportadora,
                    previsao_entrega: form.previsao_entrega || null,
                    numero_nf_saida: form.numero_nf_saida,
                    observacoes: form.observacoes,
                    items: partialItems.map(i => ({
                        order_item_id: i.order_item_id,
                        quantidade: Number(i.quantidade),
                        lote: i.lote,
                        volumes: Number(i.volumes) || 1,
                        peso_unitario: Number(i.peso_unitario) || 0,
                    })),
                });
                toast.success("Ordem de expediÃ§Ã£o criada");
                setShowForm(false);
                setForm(emptyForm());
                setFulfillment(null);
                loadOrdens();
                return;
            }
            await api.post("/expedicao/ordens", {
                order_id: form.order_id || null,
                order_numero: form.order_numero || null,
                cliente_nome: form.cliente_nome.trim(),
                endereco_entrega: form.endereco_entrega,
                transportadora: form.transportadora,
                previsao_entrega: form.previsao_entrega || null,
                numero_nf_saida: form.numero_nf_saida,
                observacoes: form.observacoes,
                items: itemsValidos.map(i => ({
                    produto_nome: i.produto_nome.trim(),
                    sku: i.sku,
                    quantidade: Number(i.quantidade),
                    unidade: i.unidade,
                    lote: i.lote,
                    volumes: Number(i.volumes) || 1,
                    peso_unitario: Number(i.peso_unitario) || 0,
                })),
            });
            toast.success("Ordem de expedição criada");
            setShowForm(false);
            setForm(emptyForm());
            loadOrdens();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setSaving(false);
        }
    };

    const handleAdvance = async (exp) => {
        const next = NEXT_STATUS[exp.status];
        if (!next) return;

        if (next.dialog === "conferencia") {
            setSelectedExp(exp);
            setConfItems((exp.items || []).map(i => ({
                produto_nome: i.produto_nome,
                quantidade_esperada: i.quantidade,
                quantidade_conferida: i.quantidade,
                lote_conferido: i.lote || "",
                ok: true,
                divergencia: "",
            })));
            setConfConferente("");
            setConfObs("");
            setShowConferencia(true);
            return;
        }

        if (next.dialog === "dispatch") {
            setSelectedExp(exp);
            setDispatchForm({
                codigo_rastreio: "",
                transportadora: exp.transportadora || "",
                numero_nf_saida: exp.numero_nf_saida || "",
            });
            setShowDispatch(true);
            return;
        }

        setActionLoading(true);
        try {
            const { data: updated } = await api.put(`/expedicao/ordens/${exp.id}`, { status: next.to });
            toast.success(next.label + " — concluído");
            loadOrdens();
            if (selectedExp?.id === exp.id) setSelectedExp(updated);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleConfirmConferencia = async () => {
        if (!selectedExp) return;
        setActionLoading(true);
        try {
            const { data: updated } = await api.post(`/expedicao/ordens/${selectedExp.id}/conferir`, {
                items: confItems.map(i => ({
                    produto_nome: i.produto_nome,
                    quantidade_conferida: Number(i.quantidade_conferida),
                    lote_conferido: i.lote_conferido,
                    ok: i.ok,
                    divergencia: i.divergencia,
                })),
                conferente_nome: confConferente,
                observacoes: confObs,
            });
            toast.success("Conferência registrada — status: conferido");
            setShowConferencia(false);
            setSelectedExp(updated);
            loadOrdens();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleConfirmDispatch = async () => {
        if (!selectedExp) return;
        setActionLoading(true);
        try {
            const { data: updated } = await api.put(`/expedicao/ordens/${selectedExp.id}`, {
                status: "expedido",
                codigo_rastreio: dispatchForm.codigo_rastreio,
                transportadora: dispatchForm.transportadora,
                numero_nf_saida: dispatchForm.numero_nf_saida,
            });
            toast.success("Despacho confirmado — estoque atualizado");
            setShowDispatch(false);
            setSelectedExp(updated);
            loadOrdens();
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleCancel = async (exp) => {
        if (!window.confirm(`Cancelar ${exp.numero_exp}?`)) return;
        setActionLoading(true);
        try {
            await api.put(`/expedicao/ordens/${exp.id}`, { status: "cancelado" });
            toast.success("Expedição cancelada");
            loadOrdens();
            if (selectedExp?.id === exp.id) setSelectedExp(null);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setActionLoading(false);
        }
    };

    const handleOpenRomaneio = async (exp) => {
        try {
            const { data } = await api.get(`/expedicao/ordens/${exp.id}/romaneio`);
            setRomaneioData(data);
            setShowRomaneio(true);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const handleSelectExp = async (exp) => {
        setSelectedExp(exp);
        try {
            const { data } = await api.get(`/expedicao/ordens/${exp.id}`);
            setSelectedExp(data);
        } catch {
            setSelectedExp(exp);
        }
    };

    const counts = {
        total: ordens.length,
        pendente: ordens.filter(o => o.status === "pendente").length,
        preparando: ordens.filter(o => o.status === "preparando").length,
        conferido: ordens.filter(o => o.status === "conferido").length,
        expedido: ordens.filter(o => o.status === "expedido").length,
    };

    return (
        <div className="h-full overflow-auto">
            <div className="max-w-6xl mx-auto p-6 space-y-5">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div>
                        <h1 className="text-2xl font-heading font-semibold tracking-tight flex items-center gap-2">
                            <Truck className="h-6 w-6" />
                            Expedição
                        </h1>
                        <p className="text-sm text-muted-foreground mt-1">
                            Separação, conferência e despacho de produtos acabados
                        </p>
                    </div>
                    <Button onClick={() => { setForm(emptyForm()); setShowForm(true); }}>
                        <Plus className="h-4 w-4 mr-1" /> Nova Expedição
                    </Button>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {[
                        { label: "Total", value: counts.total, cls: "text-foreground" },
                        { label: "Pendentes", value: counts.pendente, cls: "text-slate-600" },
                        { label: "Preparando", value: counts.preparando, cls: "text-amber-600" },
                        { label: "Conferidos", value: counts.conferido, cls: "text-violet-600" },
                        { label: "Em Trânsito", value: counts.expedido, cls: "text-blue-600" },
                    ].map(s => (
                        <Card key={s.label}><CardContent className="p-3">
                            <div className="text-[11px] text-muted-foreground uppercase tracking-wider">{s.label}</div>
                            <div className={`text-2xl font-bold mt-0.5 ${s.cls}`}>{s.value}</div>
                        </CardContent></Card>
                    ))}
                </div>

                {/* Filters */}
                <div className="flex gap-2 flex-wrap">
                    <div className="relative flex-1 min-w-[240px]">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <Input placeholder="Buscar EXP, cliente, PI…" value={search}
                            onChange={e => setSearch(e.target.value)} className="pl-9" />
                    </div>
                    <Select value={statusFilter} onValueChange={setStatusFilter}>
                        <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">Todos os Status</SelectItem>
                            {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                                <SelectItem key={k} value={k}>{v.label}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {/* List */}
                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                ) : ordens.length === 0 ? (
                    <Card className="border-dashed"><CardContent className="py-16 text-center">
                        <Truck className="h-14 w-14 mx-auto mb-4 text-muted-foreground/30" />
                        <h3 className="text-lg font-semibold mb-1">Nenhuma expedição registrada</h3>
                        <p className="text-sm text-muted-foreground">Crie uma expedição a partir de um PI concluído.</p>
                    </CardContent></Card>
                ) : (
                    <div className="space-y-2">
                        {ordens.map(exp => (
                            <Card key={exp.id}
                                className="hover:border-primary/40 hover:shadow-sm transition-all cursor-pointer group"
                                onClick={() => handleSelectExp(exp)}
                            >
                                <CardContent className="p-4">
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="flex-1 min-w-0 space-y-1.5">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="font-mono text-sm font-bold text-primary">{exp.numero_exp}</span>
                                                <StatusBadge status={exp.status} />
                                                {exp.order_numero && (
                                                    <Badge variant="outline" className="text-[10px]">PI {exp.order_numero}</Badge>
                                                )}
                                                {exp.conferencia?.tem_divergencia && (
                                                    <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-300">
                                                        Divergência
                                                    </Badge>
                                                )}
                                            </div>
                                            <h3 className="font-semibold text-sm flex items-center gap-1">
                                                <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                                                {exp.cliente_nome}
                                            </h3>
                                            <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                                                <span>{exp.items?.length || 0} item(s)</span>
                                                {exp.transportadora && <span>Transportadora: {exp.transportadora}</span>}
                                                {exp.numero_nf_saida && <span className="font-mono">NF: {exp.numero_nf_saida}</span>}
                                                {exp.previsao_entrega && (
                                                    <span className="flex items-center gap-1">
                                                        <Calendar className="h-3 w-3" />Prev: {formatDate(exp.previsao_entrega)}
                                                    </span>
                                                )}
                                                {exp.codigo_rastreio && <span>Rastreio: {exp.codigo_rastreio}</span>}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2 shrink-0">
                                            {NEXT_STATUS[exp.status] && (
                                                <Button size="sm" variant="outline" className="h-8 text-xs"
                                                    disabled={actionLoading}
                                                    onClick={e => { e.stopPropagation(); handleAdvance(exp); }}
                                                >
                                                    {NEXT_STATUS[exp.status].label}
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
            </div>

            {/* ── Detail Dialog ── */}
            {selectedExp && !showDispatch && !showConferencia && (
                <Dialog open onOpenChange={() => setSelectedExp(null)}>
                    <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                <Truck className="h-5 w-5" />{selectedExp.numero_exp} — {selectedExp.cliente_nome}
                            </DialogTitle>
                        </DialogHeader>
                        <div className="space-y-4 text-sm">
                            <div className="flex items-center gap-3 flex-wrap">
                                <StatusBadge status={selectedExp.status} />
                                {selectedExp.order_numero && <Badge variant="outline">PI {selectedExp.order_numero}</Badge>}
                                {selectedExp.conferencia?.tem_divergencia && (
                                    <Badge className="bg-amber-100 text-amber-700 border-amber-200">Com Divergência</Badge>
                                )}
                            </div>
                            {selectedExp.delivery_snapshot?.summary && (
                                <div className="grid grid-cols-4 gap-2 rounded-md border bg-muted/30 p-2 text-xs">
                                    <div><span className="text-muted-foreground">Produzido</span><p className="font-semibold">{selectedExp.delivery_snapshot.summary.total_produzido}</p></div>
                                    <div><span className="text-muted-foreground">Expedido</span><p className="font-semibold">{selectedExp.delivery_snapshot.summary.total_expedido}</p></div>
                                    <div><span className="text-muted-foreground">NF</span><p className="font-semibold">{selectedExp.delivery_snapshot.operational_snapshot?.percentual_nf || 0}%</p></div>
                                    <div><span className="text-muted-foreground">Frete</span><p className="font-semibold">{selectedExp.delivery_snapshot.operational_snapshot?.frete_cif_fob || "—"}</p></div>
                                </div>
                            )}
                            <div className="grid grid-cols-2 gap-3">
                                <div><span className="text-muted-foreground">Transportadora:</span> {selectedExp.transportadora || "—"}</div>
                                <div><span className="text-muted-foreground">Prev. Entrega:</span> {formatDate(selectedExp.previsao_entrega)}</div>
                                <div><span className="text-muted-foreground">Despacho:</span> {formatDate(selectedExp.data_expedicao)}</div>
                                <div><span className="text-muted-foreground">Entregue em:</span> {formatDate(selectedExp.data_entrega)}</div>
                                {selectedExp.numero_nf_saida && (
                                    <div><span className="text-muted-foreground">NF de Saída:</span> <span className="font-mono font-semibold">{selectedExp.numero_nf_saida}</span></div>
                                )}
                                {selectedExp.codigo_rastreio && (
                                    <div><span className="text-muted-foreground">Rastreio:</span> <span className="font-mono">{selectedExp.codigo_rastreio}</span></div>
                                )}
                                {selectedExp.endereco_entrega && (
                                    <div className="col-span-2"><span className="text-muted-foreground">Endereço:</span> {selectedExp.endereco_entrega}</div>
                                )}
                            </div>
                            <Separator />
                            <div>
                                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Itens</p>
                                <div className="space-y-1.5">
                                    {(selectedExp.items || []).map((item, i) => (
                                        <div key={i} className="rounded-lg border border-border p-2.5 text-xs">
                                            <div className="flex items-center justify-between gap-2">
                                                <div>
                                                    <span className="font-medium">{item.produto_nome}</span>
                                                    {item.sku && <span className="ml-2 text-muted-foreground font-mono">{item.sku}</span>}
                                                    {item.lote && <span className="ml-2 text-muted-foreground">Lote: {item.lote}</span>}
                                                </div>
                                                <span className="font-semibold shrink-0">{item.quantidade} {item.unidade}</span>
                                            </div>
                                            {(item.volumes > 1 || item.peso_unitario > 0) && (
                                                <div className="mt-1 text-muted-foreground flex gap-3">
                                                    {item.volumes > 0 && <span>{item.volumes} vol.</span>}
                                                    {item.peso_unitario > 0 && <span>{(item.volumes * item.peso_unitario).toFixed(2)} kg</span>}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Conferência result */}
                            {selectedExp.conferencia && (
                                <>
                                    <Separator />
                                    <div>
                                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                                            Conferência Física
                                        </p>
                                        <div className="rounded-lg border p-3 space-y-2 text-xs">
                                            <div className="flex items-center gap-2">
                                                {selectedExp.conferencia.tem_divergencia
                                                    ? <XCircle className="h-4 w-4 text-amber-500" />
                                                    : <CheckCircle2 className="h-4 w-4 text-green-500" />
                                                }
                                                <span>{selectedExp.conferencia.tem_divergencia ? "Com divergências" : "Conferido sem divergências"}</span>
                                                <span className="text-muted-foreground ml-auto">
                                                    {selectedExp.conferencia.conferente_nome} · {formatDate(selectedExp.conferencia.data_conferencia)}
                                                </span>
                                            </div>
                                            {selectedExp.conferencia.items?.filter(i => !i.ok).map((ci, idx) => (
                                                <div key={idx} className="ml-6 text-amber-700 dark:text-amber-400">
                                                    {ci.produto_nome}: {ci.divergencia || "divergência não especificada"}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </>
                            )}

                            {(selectedExp.historico || []).length > 0 && (
                                <>
                                    <Separator />
                                    <div>
                                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Histórico</p>
                                        <div className="space-y-1">
                                            {selectedExp.historico.map((h, i) => (
                                                <div key={i} className="text-xs text-muted-foreground flex gap-2 flex-wrap">
                                                    <span>{new Date(h.em).toLocaleString("pt-BR")}</span>
                                                    <span>·</span>
                                                    <span>{h.para === "pendente" ? "Criada" : `${STATUS_CONFIG[h.de]?.label || h.de} → ${STATUS_CONFIG[h.para]?.label || h.para}`}</span>
                                                    {h.nota && <span className="text-amber-600">({h.nota})</span>}
                                                    <span>· por {h.por}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                        <DialogFooter className="flex flex-wrap gap-2 justify-between">
                            <div className="flex gap-2 flex-wrap">
                                {NEXT_STATUS[selectedExp.status] && (
                                    <Button size="sm" disabled={actionLoading}
                                        onClick={() => handleAdvance(selectedExp)}>
                                        {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                                        {NEXT_STATUS[selectedExp.status].label}
                                    </Button>
                                )}
                                {["pendente", "preparando", "conferido"].includes(selectedExp.status) && (
                                    <Button size="sm" variant="outline"
                                        className="text-destructive border-destructive/30 hover:text-destructive"
                                        disabled={actionLoading}
                                        onClick={() => handleCancel(selectedExp)}>
                                        Cancelar
                                    </Button>
                                )}
                                <Button size="sm" variant="outline"
                                    onClick={() => handleOpenRomaneio(selectedExp)}>
                                    <FileText className="h-3.5 w-3.5 mr-1" /> Romaneio
                                </Button>
                            </div>
                            <Button variant="outline" onClick={() => setSelectedExp(null)}>Fechar</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ── Conferência Dialog ── */}
            {showConferencia && selectedExp && (
                <Dialog open onOpenChange={() => setShowConferencia(false)}>
                    <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                <ClipboardCheck className="h-5 w-5" />
                                Conferência Física — {selectedExp.numero_exp}
                            </DialogTitle>
                        </DialogHeader>
                        <div className="space-y-4">
                            <p className="text-sm text-muted-foreground">
                                Confirme as quantidades e lotes de cada item antes do despacho.
                            </p>
                            <div className="space-y-3">
                                {confItems.map((ci, idx) => (
                                    <div key={idx} className="rounded-lg border p-3 space-y-2">
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium text-sm">{ci.produto_nome}</span>
                                            <span className="text-xs text-muted-foreground">Esperado: {ci.quantidade_esperada}</span>
                                        </div>
                                        <div className="grid grid-cols-3 gap-2">
                                            <div>
                                                <Label className="text-xs">Qtd Conferida</Label>
                                                <Input type="number" value={ci.quantidade_conferida}
                                                    onChange={e => setConfItems(prev => {
                                                        const arr = [...prev];
                                                        arr[idx] = { ...arr[idx], quantidade_conferida: e.target.value };
                                                        return arr;
                                                    })}
                                                    className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div>
                                                <Label className="text-xs">Lote Conferido</Label>
                                                <Input value={ci.lote_conferido}
                                                    onChange={e => setConfItems(prev => {
                                                        const arr = [...prev];
                                                        arr[idx] = { ...arr[idx], lote_conferido: e.target.value };
                                                        return arr;
                                                    })}
                                                    className="mt-0.5 h-8 text-sm" placeholder="Lote" />
                                            </div>
                                            <div className="flex items-end gap-2">
                                                <Button size="sm" variant={ci.ok ? "default" : "outline"}
                                                    className={ci.ok ? "h-8 bg-green-600 hover:bg-green-700 text-white" : "h-8 border-red-300 text-red-600"}
                                                    onClick={() => setConfItems(prev => {
                                                        const arr = [...prev];
                                                        arr[idx] = { ...arr[idx], ok: !arr[idx].ok };
                                                        return arr;
                                                    })}>
                                                    {ci.ok ? <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> : <XCircle className="h-3.5 w-3.5 mr-1" />}
                                                    {ci.ok ? "OK" : "Divergência"}
                                                </Button>
                                            </div>
                                        </div>
                                        {!ci.ok && (
                                            <div>
                                                <Label className="text-xs text-red-600">Descrever divergência *</Label>
                                                <Input value={ci.divergencia}
                                                    onChange={e => setConfItems(prev => {
                                                        const arr = [...prev];
                                                        arr[idx] = { ...arr[idx], divergencia: e.target.value };
                                                        return arr;
                                                    })}
                                                    className="mt-0.5 h-8 text-sm border-red-200"
                                                    placeholder="Ex: quantidade divergente, lote errado…" />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <Label className="text-xs">Conferente</Label>
                                    <Input value={confConferente} onChange={e => setConfConferente(e.target.value)}
                                        placeholder="Nome do conferente" className="mt-0.5" />
                                </div>
                                <div>
                                    <Label className="text-xs">Observações</Label>
                                    <Input value={confObs} onChange={e => setConfObs(e.target.value)}
                                        placeholder="Opcional" className="mt-0.5" />
                                </div>
                            </div>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setShowConferencia(false)} disabled={actionLoading}>Cancelar</Button>
                            <Button onClick={handleConfirmConferencia} disabled={actionLoading}>
                                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <ClipboardCheck className="h-4 w-4 mr-1" />}
                                Registrar Conferência
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ── Dispatch Dialog ── */}
            {showDispatch && selectedExp && (
                <Dialog open onOpenChange={() => setShowDispatch(false)}>
                    <DialogContent>
                        <DialogHeader><DialogTitle>Confirmar Despacho — {selectedExp.numero_exp}</DialogTitle></DialogHeader>
                        <div className="space-y-3">
                            <div>
                                <Label>Transportadora</Label>
                                <Input value={dispatchForm.transportadora}
                                    onChange={e => setDispatchForm(f => ({ ...f, transportadora: e.target.value }))}
                                    placeholder="Nome da transportadora" className="mt-1" />
                            </div>
                            <div>
                                <Label>NF de Saída</Label>
                                <Input value={dispatchForm.numero_nf_saida}
                                    onChange={e => setDispatchForm(f => ({ ...f, numero_nf_saida: e.target.value }))}
                                    placeholder="Número da NF fiscal" className="mt-1 font-mono" />
                            </div>
                            <div>
                                <Label>Código de Rastreio</Label>
                                <Input value={dispatchForm.codigo_rastreio}
                                    onChange={e => setDispatchForm(f => ({ ...f, codigo_rastreio: e.target.value }))}
                                    placeholder="Opcional" className="mt-1" />
                            </div>
                            <p className="text-xs text-muted-foreground">
                                O estoque de produto acabado será reduzido automaticamente para itens vinculados ao WMS.
                            </p>
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => setShowDispatch(false)} disabled={actionLoading}>Cancelar</Button>
                            <Button onClick={handleConfirmDispatch} disabled={actionLoading}>
                                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Truck className="h-4 w-4 mr-1" />}
                                Confirmar Despacho
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ── Romaneio Dialog ── */}
            {showRomaneio && romaneioData && (
                <Dialog open onOpenChange={() => setShowRomaneio(false)}>
                    <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2">
                                <Package className="h-5 w-5" />
                                Romaneio — {romaneioData.numero_exp}
                            </DialogTitle>
                        </DialogHeader>
                        <div className="space-y-4 text-sm print:text-black">
                            <div className="grid grid-cols-2 gap-2 p-3 rounded-lg bg-muted/50">
                                <div><span className="text-muted-foreground">Cliente:</span> <span className="font-semibold">{romaneioData.cliente_nome}</span></div>
                                <div><span className="text-muted-foreground">Status:</span> <StatusBadge status={romaneioData.status} /></div>
                                {romaneioData.numero_nf_saida && (
                                    <div><span className="text-muted-foreground">NF de Saída:</span> <span className="font-mono font-bold">{romaneioData.numero_nf_saida}</span></div>
                                )}
                                {romaneioData.transportadora && (
                                    <div><span className="text-muted-foreground">Transportadora:</span> {romaneioData.transportadora}</div>
                                )}
                                {romaneioData.endereco_entrega && (
                                    <div className="col-span-2"><span className="text-muted-foreground">Endereço:</span> {romaneioData.endereco_entrega}</div>
                                )}
                                {romaneioData.codigo_rastreio && (
                                    <div className="col-span-2"><span className="text-muted-foreground">Rastreio:</span> <span className="font-mono">{romaneioData.codigo_rastreio}</span></div>
                                )}
                            </div>
                            <Separator />
                            <table className="w-full text-xs border-collapse">
                                <thead>
                                    <tr className="border-b text-muted-foreground">
                                        <th className="text-left py-1.5 pr-2">Produto</th>
                                        <th className="text-right py-1.5 pr-2">Qtd</th>
                                        <th className="text-right py-1.5 pr-2">Volumes</th>
                                        <th className="text-right py-1.5">Peso (kg)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {romaneioData.items.map((item, i) => (
                                        <tr key={i} className="border-b border-border/50">
                                            <td className="py-1.5 pr-2">
                                                <div className="font-medium">{item.produto_nome}</div>
                                                {item.lote && <div className="text-muted-foreground">Lote: {item.lote}</div>}
                                                {item.sku && <div className="text-muted-foreground font-mono">{item.sku}</div>}
                                            </td>
                                            <td className="text-right py-1.5 pr-2">{item.quantidade} {item.unidade}</td>
                                            <td className="text-right py-1.5 pr-2">{item.volumes}</td>
                                            <td className="text-right py-1.5">{item.peso_total_item > 0 ? item.peso_total_item.toFixed(2) : "—"}</td>
                                        </tr>
                                    ))}
                                </tbody>
                                <tfoot>
                                    <tr className="font-semibold">
                                        <td className="py-2 text-right pr-2 col-span-1 text-muted-foreground text-[11px] uppercase tracking-wider" colSpan={1}>Totais</td>
                                        <td className="py-2 text-right pr-2">{romaneioData.totais.total_itens} itens</td>
                                        <td className="py-2 text-right pr-2">{romaneioData.totais.total_volumes} vol.</td>
                                        <td className="py-2 text-right">{romaneioData.totais.peso_total_kg > 0 ? `${romaneioData.totais.peso_total_kg} kg` : "—"}</td>
                                    </tr>
                                </tfoot>
                            </table>
                            {romaneioData.observacoes && (
                                <p className="text-xs text-muted-foreground">Obs: {romaneioData.observacoes}</p>
                            )}
                        </div>
                        <DialogFooter>
                            <Button variant="outline" onClick={() => window.print()}>
                                <Printer className="h-4 w-4 mr-1" /> Imprimir
                            </Button>
                            <Button variant="outline" onClick={() => setShowRomaneio(false)}>Fechar</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}

            {/* ── New form ── */}
            <Dialog open={showForm} onOpenChange={v => { if (!v) setShowForm(false); }}>
                <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto">
                    <DialogHeader><DialogTitle>Nova Ordem de Expedição</DialogTitle></DialogHeader>
                    <div className="space-y-4">
                        {orders.length > 0 && (
                            <div>
                                <Label>Importar de PI (opcional)</Label>
                                <Select onValueChange={onSelectOrder}>
                                    <SelectTrigger className="mt-1"><SelectValue placeholder="Selecionar PI concluído…" /></SelectTrigger>
                                    <SelectContent>
                                        {orders.map(o => (
                                            <SelectItem key={o.id} value={o.id}>
                                                #{o.numero_pedido} — {o.cliente?.razao_social || o.cliente?.nome || "—"}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                {fulfillment?.summary && (
                                    <div className="mt-2 grid grid-cols-3 gap-2 rounded-md border bg-muted/30 p-2 text-xs">
                                        <div>
                                            <span className="text-muted-foreground">Produzido</span>
                                            <p className="font-semibold">{fulfillment.summary.total_produzido}</p>
                                        </div>
                                        <div>
                                            <span className="text-muted-foreground">Expedido</span>
                                            <p className="font-semibold">{fulfillment.summary.total_expedido}</p>
                                        </div>
                                        <div>
                                            <span className="text-muted-foreground">NF</span>
                                            <p className="font-semibold">{fulfillment.operational_snapshot?.percentual_nf || 0}%</p>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <Label>Cliente *</Label>
                                <Input value={form.cliente_nome} onChange={e => setField("cliente_nome", e.target.value)}
                                    placeholder="Nome do cliente" className="mt-1" />
                            </div>
                            <div>
                                <Label>Transportadora</Label>
                                <Input value={form.transportadora} onChange={e => setField("transportadora", e.target.value)}
                                    placeholder="Opcional" className="mt-1" />
                            </div>
                            <div>
                                <Label>Endereço de Entrega</Label>
                                <Input value={form.endereco_entrega} onChange={e => setField("endereco_entrega", e.target.value)}
                                    placeholder="Rua, número, cidade…" className="mt-1" />
                            </div>
                            <div>
                                <Label>Previsão de Entrega</Label>
                                <Input type="date" value={form.previsao_entrega}
                                    onChange={e => setField("previsao_entrega", e.target.value)} className="mt-1" />
                            </div>
                            <div className="col-span-2">
                                <Label>NF de Saída</Label>
                                <Input value={form.numero_nf_saida} onChange={e => setField("numero_nf_saida", e.target.value)}
                                    placeholder="Número da nota fiscal (opcional)" className="mt-1 font-mono" />
                            </div>
                        </div>
                        <Separator />
                        <div>
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="font-semibold text-sm">Itens</h3>
                                <Button size="sm" variant="outline" onClick={addItem}>
                                    <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar
                                </Button>
                            </div>
                            <div className="space-y-2">
                                {form.items.map((item, idx) => (
                                    <div key={idx} className="rounded-lg border border-border p-3 space-y-2">
                                        <div className="grid grid-cols-5 gap-2 items-end">
                                            <div className="col-span-2">
                                                <Label className="text-xs">Produto *</Label>
                                                <Input value={item.produto_nome}
                                                    onChange={e => setItem(idx, "produto_nome", e.target.value)}
                                                    placeholder="Nome" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div>
                                                <Label className="text-xs">SKU</Label>
                                                <Input value={item.sku} onChange={e => setItem(idx, "sku", e.target.value)}
                                                    placeholder="—" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div>
                                                <Label className="text-xs">Qtd *</Label>
                                                <Input type="number" value={item.quantidade}
                                                    onChange={e => setItem(idx, "quantidade", e.target.value)}
                                                    placeholder="0" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div className="flex gap-1 items-end">
                                                <div className="flex-1">
                                                    <Label className="text-xs">Un</Label>
                                                    <Select value={item.unidade} onValueChange={v => setItem(idx, "unidade", v)}>
                                                        <SelectTrigger className="mt-0.5 h-8 text-sm"><SelectValue /></SelectTrigger>
                                                        <SelectContent>
                                                            {["un", "cx", "kg", "L"].map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                                                        </SelectContent>
                                                    </Select>
                                                </div>
                                                {form.items.length > 1 && (
                                                    <Button variant="ghost" size="icon"
                                                        className="h-8 w-8 text-destructive hover:text-destructive shrink-0"
                                                        onClick={() => removeItem(idx)}>
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                    </Button>
                                                )}
                                            </div>
                                        </div>
                                        {item.order_item_id && (
                                            <div className="grid grid-cols-4 gap-2 rounded-md bg-muted/30 px-2 py-1.5 text-[11px]">
                                                <span>Pedido: <strong>{item.qtd_pedido ?? "—"}</strong></span>
                                                <span>Produzido: <strong>{item.qtd_produzida ?? "—"}</strong></span>
                                                <span>Expedido: <strong>{item.qtd_expedida ?? "—"}</strong></span>
                                                <span>Disponivel: <strong>{item.saldo_produzido_disponivel ?? "—"}</strong></span>
                                            </div>
                                        )}
                                        <div className="grid grid-cols-3 gap-2">
                                            <div>
                                                <Label className="text-xs">Lote</Label>
                                                <Input value={item.lote} onChange={e => setItem(idx, "lote", e.target.value)}
                                                    placeholder="Opcional" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div>
                                                <Label className="text-xs">Volumes</Label>
                                                <Input type="number" value={item.volumes}
                                                    onChange={e => setItem(idx, "volumes", e.target.value)}
                                                    placeholder="1" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                            <div>
                                                <Label className="text-xs">Peso/vol (kg)</Label>
                                                <Input type="number" value={item.peso_unitario}
                                                    onChange={e => setItem(idx, "peso_unitario", e.target.value)}
                                                    placeholder="0" className="mt-0.5 h-8 text-sm" />
                                            </div>
                                        </div>
                                    </div>
                                ))}
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
                            {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Truck className="h-4 w-4 mr-1" />}
                            Criar Expedição
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
