import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import {
    Package, AlertTriangle, TrendingDown, CheckCircle2, RefreshCw, Loader2,
    ChevronRight, Clock, Truck, ShoppingCart, X
} from "lucide-react";
import { useNavigate } from "react-router-dom";

// ── Constantes ─────────────────────────────────────────────────────────────────

const RISCO_CONFIG = {
    ruptura:  { label: "Ruptura",  cls: "bg-red-600 text-white",                icon: AlertTriangle },
    critico:  { label: "Crítico",  cls: "bg-orange-500 text-white",              icon: TrendingDown },
    atencao:  { label: "Atenção",  cls: "bg-yellow-400 text-slate-900",          icon: Clock },
    ok:       { label: "OK",       cls: "bg-green-100 text-green-800 border border-green-300", icon: CheckCircle2 },
};

const TIPO_CONFIG = {
    op_aberta:   { cls: "bg-blue-50 border-l-2 border-blue-500",   label: "OP",      sign: "-" },
    pedido_crm:  { cls: "bg-purple-50 border-l-2 border-purple-400", label: "Pedido", sign: "-" },
    po_transito: { cls: "bg-green-50 border-l-2 border-green-500", label: "PO",      sign: "+" },
};

function fmt(n) { return (n ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 3 }); }
function fmtBRL(n) { return (n ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }

// ── RiscoBadge ─────────────────────────────────────────────────────────────────

function RiscoBadge({ risco }) {
    const cfg = RISCO_CONFIG[risco] || RISCO_CONFIG.ok;
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${cfg.cls}`}>
            <cfg.icon className="h-3 w-3" />
            {cfg.label}
        </span>
    );
}

// ── ResumoCards ────────────────────────────────────────────────────────────────

function ResumoCards({ resumo, filtroRisco, onFiltro }) {
    const cards = [
        { key: "ruptura",  label: "Ruptura",  cls: "border-red-500 bg-red-50",      text: "text-red-700" },
        { key: "critico",  label: "Crítico",  cls: "border-orange-500 bg-orange-50", text: "text-orange-700" },
        { key: "atencao",  label: "Atenção",  cls: "border-yellow-400 bg-yellow-50", text: "text-yellow-700" },
        { key: "ok",       label: "OK",       cls: "border-green-500 bg-green-50",   text: "text-green-700" },
    ];
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            {cards.map(c => (
                <button
                    key={c.key}
                    onClick={() => onFiltro(filtroRisco === c.key ? null : c.key)}
                    className={`rounded-lg border-2 p-3 text-left transition-all hover:shadow-md
                        ${c.cls} ${filtroRisco === c.key ? "ring-2 ring-offset-1 ring-slate-700" : ""}`}
                >
                    <div className={`text-2xl font-bold ${c.text}`}>{resumo?.[c.key] ?? 0}</div>
                    <div className={`text-xs font-medium ${c.text}`}>{c.label}</div>
                </button>
            ))}
        </div>
    );
}

// ── TimelineItem ───────────────────────────────────────────────────────────────

function TimelineItem({ ev }) {
    const cfg = TIPO_CONFIG[ev.tipo] || { cls: "bg-slate-50 border-l-2 border-slate-300", sign: "?" };
    const isEntrada = ev.tipo === "po_transito";
    return (
        <div className={`flex items-start gap-2 p-2 rounded-md mb-1 ${cfg.cls}`}>
            <div className="text-xs font-mono text-slate-400 w-20 flex-shrink-0 pt-0.5">{ev.data}</div>
            <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-slate-800 truncate">{ev.descricao}</div>
                {ev.tipo === "pedido_crm" && !ev.tem_op && (
                    <span className="text-xs text-purple-600 flex items-center gap-1 mt-0.5">
                        <Clock className="h-3 w-3" /> Sem OP criada ainda
                        {ev.tem_kickoff && <span className="text-green-600 ml-1">· Kickoff aprovado</span>}
                    </span>
                )}
            </div>
            <div className={`text-xs font-mono font-bold flex-shrink-0 ${isEntrada ? "text-green-700" : "text-red-700"}`}>
                {isEntrada ? "+" : "-"}{fmt(ev.quantidade)}
            </div>
        </div>
    );
}

// ── SheetDetalhe ──────────────────────────────────────────────────────────────

function SheetDetalhe({ item, onClose }) {
    const navigate = useNavigate();
    const [detalhe, setDetalhe] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!item) return;
        setLoading(true);
        api.get(`/compras/estoque-projetado/${item.item_id}`)
            .then(r => setDetalhe(r.data))
            .catch(() => toast.error("Erro ao carregar detalhes do item"))
            .finally(() => setLoading(false));
    }, [item]);

    if (!item) return null;

    return (
        <div className="fixed inset-0 z-50 flex justify-end">
            <div className="fixed inset-0 bg-black/30" onClick={onClose} />
            <div className="relative z-50 w-full max-w-lg bg-background border-l shadow-2xl overflow-y-auto">
                <div className="sticky top-0 bg-background border-b px-5 py-3 flex items-center justify-between">
                    <div>
                        <div className="font-semibold text-sm">{item.descricao}</div>
                        <div className="text-xs text-muted-foreground">{item.categoria} · {item.unidade}</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <RiscoBadge risco={item.risco} />
                        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                {loading ? (
                    <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                ) : detalhe ? (
                    <div className="p-5 space-y-5">

                        {/* Resumo numérico */}
                        <div className="grid grid-cols-3 gap-2 text-center">
                            {[
                                { label: "Estoque Atual", val: fmt(detalhe.estoque_atual), cls: "text-slate-700" },
                                { label: "Saldo Firme",   val: fmt(item.saldo_firme),    cls: item.saldo_firme < 0 ? "text-red-600" : "text-slate-700" },
                                { label: "Saldo Cons.",   val: fmt(item.saldo_conservador), cls: item.saldo_conservador < 0 ? "text-red-600" : "text-slate-700" },
                            ].map(s => (
                                <div key={s.label} className="bg-muted/50 rounded-lg p-2">
                                    <div className={`text-base font-bold ${s.cls}`}>{s.val}</div>
                                    <div className="text-xs text-muted-foreground">{s.label}</div>
                                </div>
                            ))}
                        </div>

                        {/* Sugestão de compra */}
                        {detalhe.sugestao_compra && (
                            <div className={`rounded-lg border p-3 ${detalhe.sugestao_compra.urgente ? "border-red-400 bg-red-50" : "border-orange-300 bg-orange-50"}`}>
                                <div className="text-xs font-semibold text-orange-800 mb-1 flex items-center gap-1">
                                    <AlertTriangle className="h-3 w-3" /> Sugestão de Compra
                                </div>
                                <div className="text-sm font-bold text-orange-900">
                                    {fmt(detalhe.sugestao_compra.quantidade_sugerida)} {item.unidade}
                                </div>
                                <div className="text-xs text-orange-700 mt-0.5">{detalhe.sugestao_compra.motivo}</div>
                                {detalhe.sugestao_compra.data_limite_pedido && (
                                    <div className={`text-xs font-medium mt-1 ${detalhe.sugestao_compra.urgente ? "text-red-700" : "text-orange-700"}`}>
                                        Pedido até: {detalhe.sugestao_compra.data_limite_pedido}
                                        {detalhe.sugestao_compra.urgente && " ⚠️ URGENTE"}
                                    </div>
                                )}
                                <Button
                                    size="sm"
                                    className="mt-2 h-7 text-xs"
                                    onClick={() => navigate(`/compras?criar_cotacao=${item.item_id}`)}
                                >
                                    <ShoppingCart className="h-3 w-3 mr-1" /> Criar Demanda de Compra
                                </Button>
                            </div>
                        )}

                        {/* Timeline */}
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground mb-2">TIMELINE DE DEMANDA</div>
                            {detalhe.timeline_demanda.length === 0 ? (
                                <div className="text-xs text-muted-foreground">Nenhum evento encontrado.</div>
                            ) : (
                                detalhe.timeline_demanda.map((ev, i) => <TimelineItem key={i} ev={ev} />)
                            )}
                        </div>

                        {/* Saldo por data */}
                        {detalhe.saldo_por_data.length > 0 && (
                            <div>
                                <div className="text-xs font-semibold text-muted-foreground mb-2">SALDO PROJETADO</div>
                                <div className="space-y-0.5">
                                    {detalhe.saldo_por_data.map((s, i) => (
                                        <div key={i} className="flex justify-between text-xs py-1 border-b last:border-0">
                                            <span className="text-muted-foreground font-mono">{s.data}</span>
                                            <span className={`font-mono font-medium ${s.saldo_apos < 0 ? "text-red-600" : s.saldo_apos < (item.estoque_minimo || 0) ? "text-orange-600" : "text-green-700"}`}>
                                                {fmt(s.saldo_apos)}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Fornecedores */}
                        {detalhe.fornecedores_disponiveis.length > 0 && (
                            <div>
                                <div className="text-xs font-semibold text-muted-foreground mb-2">FORNECEDORES DISPONÍVEIS</div>
                                <div className="space-y-2">
                                    {detalhe.fornecedores_disponiveis.map((f, i) => (
                                        <div key={i} className="flex items-center justify-between border rounded-md px-3 py-2 text-xs">
                                            <div>
                                                <div className="font-medium">{f.nome || f.fornecedor_id}</div>
                                                <div className="text-muted-foreground">
                                                    Prazo: {f.prazo_entrega_dias ?? "—"}d · MOQ: {fmt(f.moq)}
                                                    {f.cotacao_valida_ate && ` · Válida até ${f.cotacao_valida_ate}`}
                                                </div>
                                            </div>
                                            <div className="text-right">
                                                <div className="font-semibold text-green-700">{fmtBRL(f.ultimo_preco)}</div>
                                                {f.homologado
                                                    ? <span className="text-green-600 text-xs">✓ Homologado</span>
                                                    : <span className="text-orange-500 text-xs">⚠ Não homologado</span>
                                                }
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="p-5 text-sm text-muted-foreground">Não foi possível carregar os detalhes.</div>
                )}
            </div>
        </div>
    );
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function ComprasEstoqueProjetado() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [horizonte, setHorizonte] = useState("90");
    const [categoria, setCategoria] = useState("all");
    const [apenasCriticos, setApenasCriticos] = useState(false);
    const [filtroRisco, setFiltroRisco] = useState(null);
    const [itemSelecionado, setItemSelecionado] = useState(null);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const params = { horizonte_dias: horizonte };
            if (categoria && categoria !== "all") params.categoria = categoria;
            if (apenasCriticos) params.apenas_criticos = true;
            const res = await api.get("/compras/estoque-projetado", { params });
            setData(res.data);
        } catch (e) {
            toast.error("Erro ao carregar estoque projetado");
        } finally {
            setLoading(false);
        }
    }, [horizonte, categoria, apenasCriticos]);

    useEffect(() => { carregar(); }, [carregar]);

    const itensFiltrados = (data?.itens || []).filter(i => !filtroRisco || i.risco === filtroRisco);

    return (
        <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
            {/* Cabeçalho */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h1 className="text-xl font-bold flex items-center gap-2">
                        <Package className="h-5 w-5 text-primary" /> Estoque Projetado
                    </h1>
                    <p className="text-sm text-muted-foreground mt-0.5">
                        4 camadas: WMS aprovado · OPs · Pedidos CRM · POs em trânsito
                        {data?.data_calculo && ` — calculado em ${data.data_calculo}`}
                    </p>
                </div>
                <Button size="sm" variant="outline" onClick={carregar} disabled={loading}>
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    <span className="ml-1.5">Recalcular</span>
                </Button>
            </div>

            {/* Filtros */}
            <div className="flex flex-wrap gap-2 items-center">
                <Select value={horizonte} onValueChange={setHorizonte}>
                    <SelectTrigger className="h-8 w-32 text-xs">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {[30, 60, 90, 180].map(d => (
                            <SelectItem key={d} value={String(d)}>{d} dias</SelectItem>
                        ))}
                    </SelectContent>
                </Select>

                <Select value={categoria} onValueChange={setCategoria}>
                    <SelectTrigger className="h-8 w-36 text-xs">
                        <SelectValue placeholder="Categoria" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">Todas</SelectItem>
                        {["mp", "fragrancia", "embalagem"].map(c => (
                            <SelectItem key={c} value={c}>{c}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>

                <button
                    onClick={() => setApenasCriticos(v => !v)}
                    className={`h-8 px-3 text-xs rounded-md border transition-colors
                        ${apenasCriticos ? "bg-orange-100 border-orange-400 text-orange-800 font-medium" : "border-border text-muted-foreground hover:bg-muted"}`}
                >
                    Só críticos
                </button>

                {filtroRisco && (
                    <button
                        onClick={() => setFiltroRisco(null)}
                        className="h-8 px-3 text-xs rounded-md border border-primary text-primary flex items-center gap-1"
                    >
                        <X className="h-3 w-3" /> {RISCO_CONFIG[filtroRisco]?.label}
                    </button>
                )}
            </div>

            {/* Cards de resumo */}
            {data?.resumo && (
                <ResumoCards resumo={data.resumo} filtroRisco={filtroRisco} onFiltro={setFiltroRisco} />
            )}

            {/* Tabela */}
            {loading && !data ? (
                <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>
            ) : (
                <div className="rounded-lg border overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead className="bg-muted/60 border-b">
                                <tr>
                                    <th className="text-left px-3 py-2 font-medium text-muted-foreground">Item</th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">Estoque</th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">D. Firme</th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">
                                        <span className="text-purple-600">D. Projetada</span>
                                    </th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">Em Trânsito</th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">Saldo Firme</th>
                                    <th className="text-right px-3 py-2 font-medium text-muted-foreground">Saldo Cons.</th>
                                    <th className="text-center px-3 py-2 font-medium text-muted-foreground">Risco</th>
                                </tr>
                            </thead>
                            <tbody>
                                {itensFiltrados.length === 0 ? (
                                    <tr>
                                        <td colSpan={8} className="text-center py-10 text-muted-foreground">
                                            {data ? "Nenhum item encontrado." : "Carregando..."}
                                        </td>
                                    </tr>
                                ) : (
                                    itensFiltrados.map(item => (
                                        <tr
                                            key={item.item_id}
                                            data-testid={`ep-row-${item.item_id}`}
                                            data-risco={item.risco}
                                            className="border-b last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
                                            onClick={() => setItemSelecionado(item)}
                                        >
                                            <td className="px-3 py-2">
                                                <div className="font-medium text-foreground">{item.descricao}</div>
                                                <div className="text-muted-foreground text-xs">
                                                    {item.categoria} · {item.unidade}
                                                    {item.pedidos_origem_projetada?.length > 0 && (
                                                        <span className="ml-2 text-purple-600">
                                                            · {item.pedidos_origem_projetada.length} pedido{item.pedidos_origem_projetada.length > 1 ? "s" : ""} CRM
                                                        </span>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-3 py-2 text-right font-mono">{fmt(item.estoque_atual)}</td>
                                            <td className="px-3 py-2 text-right font-mono text-blue-700">{fmt(item.demanda_firme)}</td>
                                            <td className="px-3 py-2 text-right font-mono text-purple-700">
                                                {fmt(item.demanda_projetada)}
                                                {item.pedidos_origem_projetada?.length > 0 && (
                                                    <div className="text-xs text-purple-500 leading-tight">
                                                        {item.pedidos_origem_projetada.slice(0, 2).map((p, i) => (
                                                            <div key={i} className="truncate max-w-[120px]" title={`${p.projeto_nome} — ${p.cliente}`}>
                                                                ⏳ {p.projeto_nome || p.projeto_id}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </td>
                                            <td className="px-3 py-2 text-right font-mono text-green-700">{fmt(item.suprimento_transito)}</td>
                                            <td className={`px-3 py-2 text-right font-mono font-medium ${item.saldo_firme < 0 ? "text-red-600" : item.saldo_firme < (item.estoque_minimo || 0) ? "text-orange-600" : "text-foreground"}`}>
                                                {fmt(item.saldo_firme)}
                                            </td>
                                            <td className={`px-3 py-2 text-right font-mono font-medium ${item.saldo_conservador < 0 ? "text-red-600" : item.saldo_conservador < (item.estoque_minimo || 0) ? "text-orange-600" : "text-foreground"}`}>
                                                {fmt(item.saldo_conservador)}
                                            </td>
                                            <td className="px-3 py-2 text-center">
                                                <RiscoBadge risco={item.risco} />
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Sheet lateral de detalhe */}
            {itemSelecionado && (
                <SheetDetalhe item={itemSelecionado} onClose={() => setItemSelecionado(null)} />
            )}
        </div>
    );
}
