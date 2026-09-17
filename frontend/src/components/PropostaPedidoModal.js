import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Trash2, X, AlertCircle, CheckCircle2, Clock, Paperclip, XCircle } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";

const STATUS_LABELS = {
    aprovada:     { label: "Aprovada",     icon: CheckCircle2, color: "text-emerald-600" },
    em_andamento: { label: "Em andamento", icon: Clock,        color: "text-amber-600"  },
    reprovada:    { label: "Reprovada",    icon: X,            color: "text-red-500"    },
    plano_futuro: { label: "Plano futuro", icon: Clock,        color: "text-slate-500"  },
};

function emptyItem() {
    return { codigo_kuryos: "", codigo_cliente: "", item: "", prazo_entrega: "", qtd: "", valor_unitario: "", valor_total: "" };
}

function emptyInsumo() {
    return { descricao: "", qtd: "", unidade: "" };
}

function calcTotal(item) {
    const q = parseFloat(item.qtd) || 0;
    const v = parseFloat(item.valor_unitario) || 0;
    return q * v;
}

function defaultTabForProjectStage(stage) {
    if (stage === "orcamento_completo" || stage === "em_negociacao" || stage === "pedido_aprovado") {
        return "pedido";
    }
    return "proposta";
}

function modalCopyForProjectStage(stage) {
    if (stage === "cotacao") {
        return {
            title: "Cotacao",
            propostaTab: "Cotacao Comercial",
            pedidoTab: "Orcamento Completo",
            saveLabel: "Salvar cotacao",
        };
    }
    if (stage === "orcamento_completo") {
        return {
            title: "Orcamento Completo",
            propostaTab: "Cotacao Comercial",
            pedidoTab: "Orcamento Completo",
            saveLabel: "Salvar orcamento",
        };
    }
    return {
        title: "Proposta & Pedido",
        propostaTab: "Bloco A - Proposta Comercial",
        pedidoTab: "Bloco B - Pedido de Fabricacao",
        saveLabel: "Salvar rascunho",
    };
}

export default function PropostaPedidoModal({ open, onOpenChange, projeto, onSaved, initialTab }) {
    const [tab, setTab] = useState("proposta");

    // Bloco A
    const [tipoProduto, setTipoProduto] = useState("");
    const [variacaoProduto, setVariacaoProduto] = useState("");
    const [precoUnitario, setPrecoUnitario] = useState("");
    const [insumosInclusos, setInsumosInclusos] = useState([]);
    const [insumoInput, setInsumoInput] = useState("");
    const [observacoesProposta, setObservacoesProposta] = useState("");

    // Bloco B
    const [itemsPedido, setItemsPedido] = useState([emptyItem()]);
    const [condicoesPagamento, setCondicoesPagamento] = useState("");
    const [insumosFabricacao, setInsumosFabricacao] = useState([emptyInsumo()]);
    const [rodapeObservacoes, setRodapeObservacoes] = useState("");
    const [status, setStatus] = useState("rascunho");

    // R18
    const [amostrasStatus, setAmostrasStatus] = useState(null);
    const [loadingStatus, setLoadingStatus] = useState(false);

    // R20
    const [materialRequirements, setMaterialRequirements] = useState(null);
    const [showRequirements, setShowRequirements] = useState(false);

    const [saving, setSaving] = useState(false);
    const [deciding, setDeciding] = useState(false);
    const [decisionReason, setDecisionReason] = useState("");

    const projetoId = projeto?.id;
    const copy = modalCopyForProjectStage(projeto?.stage);

    useEffect(() => {
        if (open) {
            setTab(initialTab || defaultTabForProjectStage(projeto?.stage));
        }
    }, [open, initialTab, projeto?.stage]);

    useEffect(() => {
        if (!open || !projetoId) return;

        const init = async () => {
            setLoadingStatus(true);

            // 1. Tentar carregar proposta existente
            let hasExisting = false;
            try {
                const { data } = await api.get(`/crm/projects/${projetoId}/proposta`);
                if (data && data.projeto_id) {
                    hasExisting = true;
                    setTipoProduto(data.tipo_produto || "");
                    setVariacaoProduto(data.variacao_produto || "");
                    setPrecoUnitario(data.preco_unitario ?? "");
                    setInsumosInclusos(data.insumos_inclusos || []);
                    setObservacoesProposta(data.observacoes_proposta || "");
                    setItemsPedido(
                        (data.items_pedido || []).length > 0
                            ? data.items_pedido.map((i) => ({ ...i, qtd: i.qtd ?? "", valor_unitario: i.valor_unitario ?? "", valor_total: i.valor_total ?? "" }))
                            : [emptyItem()]
                    );
                    setCondicoesPagamento(data.condicoes_pagamento || "");
                    setInsumosFabricacao(
                        (data.insumos_fabricacao || []).length > 0
                            ? data.insumos_fabricacao.map((i) => ({ ...i, qtd: i.qtd ?? "" }))
                            : [emptyInsumo()]
                    );
                    setRodapeObservacoes(data.rodape_observacoes || "");
                    setStatus(data.status || "rascunho");
                }
            } catch { /* proposta ainda não existe */ }

            // 2. Carregar status das amostras
            try {
                const { data: sd } = await api.get(`/crm/projects/${projetoId}/amostras-status`);
                setAmostrasStatus(sd);

                // Auto-popular apenas se não há proposta salva ainda
                if (!hasExisting && sd) {
                    const aprovadas = (sd.variacoes || []).filter((v) => v.aprovada);

                    if (aprovadas.length > 0) {
                        // Bloco A: nome do produto e variações aprovadas
                        setTipoProduto(aprovadas[0].nome_produto || "");
                        setVariacaoProduto(
                            aprovadas.map((v) => v.descricao).filter(Boolean).join(", ")
                        );

                        // Bloco B: uma linha por variação aprovada
                        setItemsPedido(
                            aprovadas.map((v) => ({
                                ...emptyItem(),
                                codigo_kuryos: v.sku_codigo || "",
                                codigo_cliente: v.codigo || "",
                                item: [v.nome_produto, v.descricao].filter(Boolean).join(" — "),
                            }))
                        );
                    }
                }
            } catch {
                setAmostrasStatus(null);
            } finally {
                setLoadingStatus(false);
            }
        };

        init();
    }, [open, projetoId]);

    // ── Bloco A helpers ───────────────────────────────────────────────────────

    const addInsumoIncluso = (texto) => {
        const t = texto.trim();
        if (!t || insumosInclusos.includes(t)) return;
        setInsumosInclusos([...insumosInclusos, t]);
        setInsumoInput("");
    };

    const removeInsumoIncluso = (i) => setInsumosInclusos(insumosInclusos.filter((_, idx) => idx !== i));

    // ── Bloco B helpers ───────────────────────────────────────────────────────

    const updateItem = (index, field, value) => {
        const next = [...itemsPedido];
        next[index] = { ...next[index], [field]: value };
        if (field === "qtd" || field === "valor_unitario") {
            next[index].valor_total = calcTotal(next[index]).toFixed(2);
        }
        setItemsPedido(next);
    };

    const addItem = () => setItemsPedido([...itemsPedido, emptyItem()]);
    const removeItem = (i) => setItemsPedido(itemsPedido.filter((_, idx) => idx !== i));

    const updateInsumoFab = (index, field, value) => {
        const next = [...insumosFabricacao];
        next[index] = { ...next[index], [field]: value };
        setInsumosFabricacao(next);
    };
    const addInsumoFab = () => setInsumosFabricacao([...insumosFabricacao, emptyInsumo()]);
    const removeInsumoFab = (i) => setInsumosFabricacao(insumosFabricacao.filter((_, idx) => idx !== i));

    // ── Totais ────────────────────────────────────────────────────────────────

    const totalGeral = itemsPedido.reduce((acc, item) => acc + calcTotal(item), 0);

    // ── Salvar ────────────────────────────────────────────────────────────────

    const handleSave = async (novoStatus, advanceToBudget = false, keepOpen = false) => {
        if (!projetoId) return false;
        setSaving(true);
        try {
            const payload = {
                tipo_produto: tipoProduto,
                variacao_produto: variacaoProduto,
                preco_unitario: precoUnitario !== "" ? parseFloat(precoUnitario) : null,
                insumos_inclusos: insumosInclusos,
                observacoes_proposta: observacoesProposta,
                items_pedido: itemsPedido.map((i) => ({
                    ...i,
                    qtd: i.qtd !== "" ? parseFloat(i.qtd) : null,
                    valor_unitario: i.valor_unitario !== "" ? parseFloat(i.valor_unitario) : null,
                    valor_total: i.valor_total !== "" ? parseFloat(i.valor_total) : calcTotal(i),
                })),
                condicoes_pagamento: condicoesPagamento,
                insumos_fabricacao: insumosFabricacao.map((i) => ({
                    ...i,
                    qtd: i.qtd !== "" ? parseFloat(i.qtd) : null,
                })),
                rodape_observacoes: rodapeObservacoes,
                status: novoStatus || status,
            };
            const { data } = await api.post(`/crm/projects/${projetoId}/proposta`, payload);
            if (advanceToBudget) {
                await api.put(`/crm/projects/${projetoId}/move`, { stage: "orcamento_completo" });
                toast.success("Cotação concluída. Orçamento liberado para decisão do cliente.");
            } else {
                toast.success("Proposta salva.");
            }
            onSaved?.(data);

            // R20: buscar necessidades geradas e exibir painel
            if (novoStatus === "confirmado") {
                try {
                    const { data: reqs } = await api.get(`/crm/projects/${projetoId}/material-requirements`);
                    if (reqs && reqs.materiais?.length > 0) {
                        setMaterialRequirements(reqs);
                        setShowRequirements(true);
                        return; // mantém modal aberto para exibir resultado
                    }
                } catch { /* ignora */ }
            }
            if (!keepOpen) onOpenChange(false);
            return true;
        } catch (e) {
            toast.error(formatApiError(e));
            return false;
        } finally {
            setSaving(false);
        }
    };

    const handleDecision = async (decision) => {
        if (decision === "reprovado" && !decisionReason.trim()) {
            toast.error("Informe o motivo da reprovação.");
            return;
        }
        setDeciding(true);
        try {
            const saved = await handleSave("enviado", false, true);
            if (!saved) return;
            const { data } = await api.post(`/crm/projects/${projetoId}/proposta/decisao`, {
                decisao: decision,
                motivo: decisionReason.trim(),
            });
            if (decision === "aprovado") {
                toast.success("Orçamento aprovado. Pedido em rascunho e Kickoff criados.");
            } else {
                toast.success("Orçamento reprovado e projeto arquivado.");
            }
            onSaved?.(data);
            onOpenChange(false);
        } catch (error) {
            toast.error(formatApiError(error));
        } finally {
            setDeciding(false);
        }
    };

    const podeConfirmar = amostrasStatus?.pode_confirmar === true;
    const totalVariacoes = amostrasStatus?.total ?? 0;
    const totalAprovadas = amostrasStatus?.total_aprovadas ?? 0;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-5xl max-h-[92vh] flex flex-col p-0 overflow-hidden">
                <DialogHeader className="p-6 pb-3 border-b bg-gradient-to-r from-amber-50 to-amber-100/60">
                    <DialogTitle className="font-heading text-2xl">{copy.title}</DialogTitle>
                    <p className="text-sm text-muted-foreground">
                        {projeto?.nome_projeto && <span className="font-medium">{projeto.nome_projeto}</span>}
                        {projeto?.cliente_nome && <span> — {projeto.cliente_nome}</span>}
                    </p>
                </DialogHeader>

                {/* R18 — banner de status de amostras */}
                {!loadingStatus && amostrasStatus && (
                    <div className={`mx-6 mt-4 rounded-lg px-4 py-3 flex items-start gap-3 text-sm ${
                        podeConfirmar
                            ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
                            : "bg-amber-50 border border-amber-200 text-amber-800"
                    }`}>
                        {podeConfirmar
                            ? <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                            : <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                        }
                        <div>
                            <p className="font-medium">
                                {podeConfirmar
                                    ? `${totalAprovadas} de ${totalVariacoes} variação(ões) aprovada(s)`
                                    : "Nenhuma amostra aprovada pelo cliente ainda"
                                }
                            </p>
                            {!podeConfirmar && totalVariacoes > 0 && (
                                <ul className="mt-1 space-y-0.5 text-xs">
                                    {amostrasStatus.variacoes.map((v) => {
                                        const meta = STATUS_LABELS[v.status] || STATUS_LABELS.em_andamento;
                                        const Icon = meta.icon;
                                        return (
                                            <li key={v.variacao_id} className="flex items-center gap-1.5">
                                                <Icon className={`h-3 w-3 ${meta.color}`} />
                                                <span>{v.codigo} {v.nome_produto && `— ${v.nome_produto}`}</span>
                                                <span className={meta.color}>({meta.label})</span>
                                            </li>
                                        );
                                    })}
                                </ul>
                            )}
                        </div>
                    </div>
                )}

                {/* R20 — Painel de Necessidades (exibido após confirmação) */}
                {showRequirements && materialRequirements ? (
                <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-4">
                    <div className="flex items-center gap-2 text-emerald-700">
                        <CheckCircle2 className="h-5 w-5" />
                        <h3 className="font-semibold text-base">Pedido confirmado — Necessidades de material geradas</h3>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        A lista abaixo foi enviada aos setores de <strong>Compras</strong> e <strong>PCP</strong>.
                    </p>
                    <div className="rounded-lg border overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/60">
                                <tr>
                                    {["Código", "Descrição", "Qtd. Necessária", "Un. Compra", "Setor", ""].map((h) => (
                                        <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground text-xs">{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {materialRequirements.materiais.map((m, idx) => (
                                    <tr key={idx} className={m.pendente_info ? "bg-amber-50/60" : ""}>
                                        <td className="px-3 py-2 font-mono text-xs">{m.codigo_material || "—"}</td>
                                        <td className="px-3 py-2">{m.descricao}</td>
                                        <td className="px-3 py-2 text-right font-medium tabular-nums">{m.qtd_necessaria_compra}</td>
                                        <td className="px-3 py-2 text-muted-foreground">{m.unidade_compra}</td>
                                        <td className="px-3 py-2">
                                            <Badge variant={m.responsavel === "compras" ? "default" : "secondary"} className="text-xs">
                                                {m.responsavel === "compras" ? "Compras" : "PCP"}
                                            </Badge>
                                        </td>
                                        <td className="px-3 py-2">
                                            {m.pendente_info && (
                                                <span className="text-xs text-amber-600 flex items-center gap-1">
                                                    <AlertCircle className="h-3 w-3" /> Dados incompletos
                                                </span>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {materialRequirements.materiais.some((m) => m.pendente_info) && (
                        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                            Itens com "Dados incompletos" precisam de <strong>qtd_envase</strong> configurada no produto-pai para o cálculo correto da quantidade de granel.
                        </p>
                    )}
                </div>
                ) : (
                <>
                {/* Tabs */}
                <div className="flex gap-1 px-6 pt-4 pb-0 border-b">
                    {[
                        { id: "proposta", label: copy.propostaTab },
                        { id: "pedido",   label: copy.pedidoTab },
                    ].map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                                tab === t.id
                                    ? "border-amber-500 text-amber-700"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">

                    {/* ── Bloco A ── */}
                    {tab === "proposta" && (
                        <div className="space-y-5">
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Label>Tipo de produto</Label>
                                    <Input
                                        value={tipoProduto}
                                        onChange={(e) => setTipoProduto(e.target.value)}
                                        placeholder="Ex: Shampoo, Condicionador, Sérum..."
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Variação</Label>
                                    <Input
                                        value={variacaoProduto}
                                        onChange={(e) => setVariacaoProduto(e.target.value)}
                                        placeholder="Ex: 300ml Coco, 500ml Rosa..."
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Preço por unidade (R$)</Label>
                                    <Input
                                        type="number"
                                        value={precoUnitario}
                                        onChange={(e) => setPrecoUnitario(e.target.value)}
                                        placeholder="0,00"
                                    />
                                </div>
                            </div>

                            <div className="space-y-2">
                                <Label>Insumos inclusos</Label>
                                <div className="flex gap-2">
                                    <Input
                                        value={insumoInput}
                                        onChange={(e) => setInsumoInput(e.target.value)}
                                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addInsumoIncluso(insumoInput); } }}
                                        placeholder="Adicione um insumo e pressione Enter"
                                    />
                                    <Button type="button" variant="outline" size="sm" onClick={() => addInsumoIncluso(insumoInput)}>
                                        <Plus className="h-4 w-4" />
                                    </Button>
                                </div>
                                {insumosInclusos.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5 mt-2">
                                        {insumosInclusos.map((ins, i) => (
                                            <Badge key={i} variant="secondary" className="gap-1 text-xs">
                                                {ins}
                                                <button type="button" onClick={() => removeInsumoIncluso(i)}>
                                                    <X className="h-3 w-3" />
                                                </button>
                                            </Badge>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div className="space-y-2">
                                <Label>Observações da proposta</Label>
                                <Textarea
                                    rows={4}
                                    value={observacoesProposta}
                                    onChange={(e) => setObservacoesProposta(e.target.value)}
                                    placeholder="Validade da proposta, condições especiais, exclusões..."
                                />
                            </div>
                        </div>
                    )}

                    {/* ── Bloco B ── */}
                    {tab === "pedido" && (
                        <div className="space-y-6">
                            {/* Cliente (read-only) */}
                            {projeto?.cliente_nome && (
                                <div className="rounded-lg border bg-muted/40 px-4 py-3 text-sm">
                                    <span className="text-muted-foreground">Cliente: </span>
                                    <span className="font-medium">{projeto.cliente_nome}</span>
                                </div>
                            )}

                            {/* Tabela de itens */}
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <Label>Itens do pedido</Label>
                                    <Button type="button" variant="outline" size="sm" onClick={addItem}>
                                        <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar item
                                    </Button>
                                </div>

                                <div className="rounded-lg border overflow-hidden">
                                    <table className="w-full text-sm">
                                        <thead className="bg-muted/60">
                                            <tr>
                                                {["Cód. KURYOS", "Cód. Cliente", "Item", "Prazo", "Qtd", "Vlr. Unit.", "Total", ""].map((h) => (
                                                    <th key={h} className="px-2 py-2 text-left font-medium text-muted-foreground text-xs">{h}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y">
                                            {itemsPedido.map((item, idx) => (
                                                <tr key={idx}>
                                                    <td className="px-2 py-1.5"><Input className="h-7 text-xs" value={item.codigo_kuryos} onChange={(e) => updateItem(idx, "codigo_kuryos", e.target.value)} placeholder="SKU" /></td>
                                                    <td className="px-2 py-1.5"><Input className="h-7 text-xs" value={item.codigo_cliente} onChange={(e) => updateItem(idx, "codigo_cliente", e.target.value)} placeholder="Ref." /></td>
                                                    <td className="px-2 py-1.5 min-w-[140px]"><Input className="h-7 text-xs" value={item.item} onChange={(e) => updateItem(idx, "item", e.target.value)} placeholder="Descrição" /></td>
                                                    <td className="px-2 py-1.5"><Input className="h-7 text-xs" type="date" value={item.prazo_entrega} onChange={(e) => updateItem(idx, "prazo_entrega", e.target.value)} /></td>
                                                    <td className="px-2 py-1.5 w-20"><Input className="h-7 text-xs" type="number" value={item.qtd} onChange={(e) => updateItem(idx, "qtd", e.target.value)} placeholder="0" /></td>
                                                    <td className="px-2 py-1.5 w-28"><Input className="h-7 text-xs" type="number" value={item.valor_unitario} onChange={(e) => updateItem(idx, "valor_unitario", e.target.value)} placeholder="0,00" /></td>
                                                    <td className="px-2 py-1.5 w-28 text-xs font-medium text-right pr-3">
                                                        R$ {calcTotal(item).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                                                    </td>
                                                    <td className="px-1 py-1.5">
                                                        {itemsPedido.length > 1 && (
                                                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => removeItem(idx)}>
                                                                <Trash2 className="h-3.5 w-3.5 text-red-500" />
                                                            </Button>
                                                        )}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                        <tfoot className="bg-muted/40 border-t">
                                            <tr>
                                                <td colSpan={6} className="px-3 py-2 text-sm font-semibold text-right">Total Geral:</td>
                                                <td className="px-3 py-2 text-sm font-bold text-right">
                                                    R$ {totalGeral.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                                                </td>
                                                <td />
                                            </tr>
                                        </tfoot>
                                    </table>
                                </div>
                            </div>

                            <Separator />

                            <div className="space-y-2">
                                <Label>Condições de pagamento</Label>
                                <Textarea
                                    rows={2}
                                    value={condicoesPagamento}
                                    onChange={(e) => setCondicoesPagamento(e.target.value)}
                                    placeholder="Ex: 50% na aprovação + 50% na entrega, boleto 30 dias..."
                                />
                            </div>

                            {/* Insumos de fabricação */}
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <Label>Insumos de fabricação</Label>
                                    <Button type="button" variant="outline" size="sm" onClick={addInsumoFab}>
                                        <Plus className="h-3.5 w-3.5 mr-1" /> Adicionar
                                    </Button>
                                </div>
                                <div className="space-y-2">
                                    {insumosFabricacao.map((ins, idx) => (
                                        <div key={idx} className="flex gap-2 items-center">
                                            <Input
                                                className="flex-1"
                                                value={ins.descricao}
                                                onChange={(e) => updateInsumoFab(idx, "descricao", e.target.value)}
                                                placeholder="Descrição do insumo"
                                            />
                                            <Input
                                                className="w-24"
                                                type="number"
                                                value={ins.qtd}
                                                onChange={(e) => updateInsumoFab(idx, "qtd", e.target.value)}
                                                placeholder="Qtd"
                                            />
                                            <Input
                                                className="w-20"
                                                value={ins.unidade}
                                                onChange={(e) => updateInsumoFab(idx, "unidade", e.target.value)}
                                                placeholder="kg/un"
                                            />
                                            {insumosFabricacao.length > 1 && (
                                                <Button variant="ghost" size="sm" onClick={() => removeInsumoFab(idx)}>
                                                    <Trash2 className="h-4 w-4 text-red-500" />
                                                </Button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="space-y-2">
                                <Label>Observações / rodapé</Label>
                                <Textarea
                                    rows={3}
                                    value={rodapeObservacoes}
                                    onChange={(e) => setRodapeObservacoes(e.target.value)}
                                    placeholder="Notas finais, responsabilidades, validade do pedido..."
                                />
                            </div>
                        </div>
                    )}
                </div>
                </>
                )}

                <DialogFooter className="p-6 pt-3 border-t flex gap-2 justify-end">
                    {showRequirements ? (
                        <Button onClick={() => onOpenChange(false)}>Fechar</Button>
                    ) : (
                        <>
                            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
                            <Button variant="secondary" disabled={saving || deciding} onClick={() => handleSave("rascunho")}>
                                {copy.saveLabel}
                            </Button>
                            {projeto?.stage === "cotacao" && (
                                <Button
                                    disabled={saving || !podeConfirmar}
                                    title={!podeConfirmar ? "A amostra precisa da aprovação do P&D e do Comercial" : ""}
                                    onClick={() => handleSave("enviado", true)}
                                >
                                    {!podeConfirmar && <AlertCircle className="h-4 w-4 mr-1.5" />}
                                    Finalizar cotação
                                </Button>
                            )}
                            {["orcamento_completo", "em_negociacao"].includes(projeto?.stage) && (
                                <div className="w-full sm:w-auto flex flex-col sm:flex-row gap-2">
                                    <Input
                                        value={decisionReason}
                                        onChange={(event) => setDecisionReason(event.target.value)}
                                        placeholder="Motivo (obrigatório se reprovado)"
                                        className="sm:w-72"
                                    />
                                    <Button
                                        variant="destructive"
                                        disabled={saving || deciding}
                                        onClick={() => handleDecision("reprovado")}
                                    >
                                        <XCircle className="h-4 w-4 mr-1.5" /> Reprovado
                                    </Button>
                                    <Button
                                        disabled={saving || deciding || !podeConfirmar}
                                        title={!podeConfirmar ? "A amostra precisa da aprovação do P&D e do Comercial" : ""}
                                        onClick={() => handleDecision("aprovado")}
                                    >
                                        <CheckCircle2 className="h-4 w-4 mr-1.5" /> Aprovado
                                    </Button>
                                </div>
                            )}
                        </>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
