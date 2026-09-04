import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { ArrowLeft, Loader2, CheckCircle2, X, Edit2, AlertTriangle, ChevronRight } from "lucide-react";

function ProgressBar({ revisados, total }) {
    const pct = total === 0 ? 0 : Math.round((revisados / total) * 100);
    return (
        <div className="flex items-center gap-3" data-testid="mrp-progress-bar">
            <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                <div className="h-2 bg-primary rounded-full transition-all" style={{ width: `${pct}%` }}
                    data-testid="mrp-progress-fill" data-pct={pct} />
            </div>
            <span className="text-xs text-muted-foreground font-mono" data-testid="mrp-progress-label">{revisados}/{total}</span>
        </div>
    );
}

export default function ComprasMRPRevisao() {
    const { id } = useParams();
    const nav = useNavigate();
    const [rodada, setRodada] = useState(null);
    const [loading, setLoading] = useState(true);
    const [aprovando, setAprovando] = useState(false);
    const [editando, setEditando] = useState({}); // item_id → {acao, qtd, just}
    const [salvandoItem, setSalvandoItem] = useState(null);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get(`/compras/mrp/${id}`);
            setRodada(data);
        } catch { toast.error("Erro ao carregar rodada MRP"); }
        finally { setLoading(false); }
    }, [id]);

    useEffect(() => { carregar(); }, [carregar]);

    const salvarItem = async (item_id, acao, qtd, just) => {
        setSalvandoItem(item_id);
        try {
            await api.put(`/compras/mrp/${id}/revisar-item`, { item_id, acao, quantidade_ajustada: qtd ? parseFloat(qtd) : null, justificativa: just || null });
            toast.success("Item revisado");
            setEditando(e => ({ ...e, [item_id]: null }));
            carregar();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao revisar item");
        } finally { setSalvandoItem(null); }
    };

    const aprovar = async () => {
        setAprovando(true);
        try {
            const { data } = await api.post(`/compras/mrp/${id}/aprovar`);
            toast.success(`MRP aprovado — ${data.demandas_criadas} demandas criadas`);
            nav("/compras/mrp");
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao aprovar rodada");
        } finally { setAprovando(false); }
    };

    if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>;
    if (!rodada) return <div className="p-6 text-muted-foreground">Rodada não encontrada.</div>;

    const itens = rodada.itens_sugeridos || [];
    const revisados = itens.filter(i => i.aprovado_pcp !== null).length;
    const todosPendentes = revisados < itens.length;
    const podAprovar = !todosPendentes && ["gerada", "em_revisao"].includes(rodada.status);

    const urgentes = itens.filter(i => i.urgente);
    const normais = itens.filter(i => !i.urgente);

    const renderItem = (it) => {
        const ed = editando[it.item_id] || null;
        const aprovado = it.aprovado_pcp;
        return (
            <div key={it.item_id} data-testid={`mrp-item-${it.item_id}`} data-urgente={it.urgente} data-aprovado={aprovado}
            className={`border rounded-lg p-3 text-xs transition ${it.urgente ? "border-red-300 bg-red-50" : "border-border"} ${aprovado === false ? "opacity-60" : ""}`}>
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                        <div className="flex items-center gap-2">
                            {it.urgente && <span className="flex items-center gap-0.5 text-red-600 font-semibold text-xs"><AlertTriangle className="h-3 w-3" /> URGENTE</span>}
                            <span className="font-medium text-sm">{it.item_descricao}</span>
                            <span className="text-muted-foreground">{it.categoria}</span>
                        </div>
                        <div className="grid grid-cols-4 gap-2 mt-1.5 text-muted-foreground">
                            <span>Bruta: <b className="text-foreground">{it.necessidade_bruta}</b></span>
                            <span>Estoque: <b className="text-foreground">{it.estoque_disponivel}</b></span>
                            <span>Trânsito: <b className="text-foreground">{it.em_transito}</b></span>
                            <span>Líquida: <b className="text-foreground">{it.necessidade_liquida}</b></span>
                        </div>
                        <div className="flex gap-3 mt-1 text-muted-foreground">
                            <span>MOQ: {it.moq_fornecedor}</span>
                            <span>Sugerido: <b className="text-foreground">{it.quantidade_sugerida}</b></span>
                            {it.data_limite_pedido && <span className={it.urgente ? "text-red-600 font-medium" : ""}>Limite: {it.data_limite_pedido}</span>}
                        </div>
                        {it.justificativa_remocao && (
                            <div className="mt-1 text-muted-foreground italic">Removido: {it.justificativa_remocao}</div>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                        {aprovado === true && !ed && <CheckCircle2 className="h-4 w-4 text-green-600" />}
                        {aprovado === false && !ed && <X className="h-4 w-4 text-red-600" />}

                        {rodada.status !== "aprovada" && aprovado !== false && !ed && (
                            <>
                                <Button size="sm" className="h-6 text-xs px-2"
                                    data-testid={`btn-aprovar-item-${it.item_id}`}
                                    onClick={() => salvarItem(it.item_id, "aprovar")} disabled={!!salvandoItem}>
                                    {salvandoItem === it.item_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                                </Button>
                                <Button size="sm" variant="outline" className="h-6 text-xs px-2"
                                    data-testid={`btn-ajustar-item-${it.item_id}`}
                                    onClick={() => setEditando(e => ({ ...e, [it.item_id]: { acao: "ajustar", qtd: it.quantidade_sugerida, just: "" } }))}>
                                    <Edit2 className="h-3 w-3" />
                                </Button>
                                <Button size="sm" variant="outline" className="h-6 text-xs px-2 text-red-600 border-red-300 hover:bg-red-50"
                                    data-testid={`btn-remover-item-${it.item_id}`}
                                    onClick={() => setEditando(e => ({ ...e, [it.item_id]: { acao: "remover", qtd: "", just: "" } }))}>
                                    <X className="h-3 w-3" />
                                </Button>
                            </>
                        )}
                    </div>
                </div>

                {ed && (
                    <div className="mt-2 border-t pt-2 space-y-2">
                        {ed.acao === "ajustar" && (
                            <div>
                                <Label className="text-xs">Quantidade Ajustada</Label>
                                <Input type="number" className="h-7 text-xs mt-0.5" value={ed.qtd}
                                    onChange={e => setEditando(prev => ({ ...prev, [it.item_id]: { ...ed, qtd: e.target.value } }))} />
                            </div>
                        )}
                        {ed.acao === "remover" && (
                            <div>
                                <Label className="text-xs">Justificativa *</Label>
                                <Textarea className="text-xs mt-0.5 min-h-[52px]" value={ed.just}
                                    onChange={e => setEditando(prev => ({ ...prev, [it.item_id]: { ...ed, just: e.target.value } }))} />
                            </div>
                        )}
                        <div className="flex gap-2">
                            <Button size="sm" className="h-6 text-xs" disabled={!!salvandoItem}
                                onClick={() => salvarItem(it.item_id, ed.acao, ed.qtd, ed.just)}>
                                {salvandoItem === it.item_id ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null} Salvar
                            </Button>
                            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditando(e => ({ ...e, [it.item_id]: null }))}>Cancelar</Button>
                        </div>
                    </div>
                )}
            </div>
        );
    };

    return (
        <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={() => nav("/compras/mrp")}><ArrowLeft className="h-4 w-4" /></Button>
                <div className="flex-1">
                    <h1 className="text-lg font-bold">{rodada.numero_mrp}</h1>
                    <div className="text-sm text-muted-foreground">{rodada.created_at?.slice(0, 10)} · {rodada.disparado_por_nome}</div>
                </div>
                <Button size="sm" disabled={!podAprovar || aprovando} onClick={aprovar}
                    data-testid="btn-aprovar-mrp"
                    className={podAprovar ? "bg-green-600 hover:bg-green-700" : ""}>
                    {aprovando ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                    Aprovar Lista
                </Button>
            </div>

            <ProgressBar revisados={revisados} total={itens.length} />
            {todosPendentes && <p className="text-xs text-muted-foreground">Revise todos os itens antes de aprovar.</p>}
            <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                <span>Origem: <b className="text-foreground">{rodada.origem_demanda || "manual"}</b></span>
                <span className="mx-2">|</span>
                <span>Horizonte: <b className="text-foreground">{rodada.horizonte_dias || 90} dias</b></span>
                {(rodada.itens_nao_resolvidos || []).length > 0 && (
                    <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-amber-800">
                        <div className="font-semibold">Itens de formula sem vinculo em Compras ({rodada.itens_nao_resolvidos.length})</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                            {rodada.itens_nao_resolvidos.slice(0, 8).map((item, idx) => (
                                <span key={`${item.op_id || "op"}-${idx}`} className="rounded bg-white/70 px-2 py-0.5">
                                    {item.ingredient_name || item.catalog_id || item.motivo}
                                </span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {urgentes.length > 0 && (
                <div>
                    <div className="text-xs font-semibold text-red-600 mb-2 flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" /> URGENTES ({urgentes.length})</div>
                    <div className="space-y-2">{urgentes.map(renderItem)}</div>
                </div>
            )}

            {normais.length > 0 && (
                <div>
                    {urgentes.length > 0 && <div className="text-xs font-semibold text-muted-foreground mb-2">DEMAIS ITENS ({normais.length})</div>}
                    <div className="space-y-2">{normais.map(renderItem)}</div>
                </div>
            )}

            {itens.length === 0 && (
                <div className="text-center py-10 text-muted-foreground text-sm">Nenhum item nesta rodada MRP.</div>
            )}
        </div>
    );
}
