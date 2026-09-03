import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
    Package, AlertTriangle, Clock, Truck, TrendingDown, CheckCircle2,
    Loader2, RefreshCw, ChevronRight, ShieldCheck, DollarSign, ClipboardList,
    Handshake, ReceiptText, Send, Warehouse
} from "lucide-react";
import { useNavigate } from "react-router-dom";

function fmt(n) { return (n ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 }); }
function fmtBRL(n) { return (n ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }

function KpiCard({ title, value, sub, icon: Icon, color, onClick, testId }) {
    return (
        <button
            className={`text-left rounded-xl border p-4 w-full transition hover:shadow-md ${color}`}
            data-testid={testId}
            onClick={onClick}
        >
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-muted-foreground">{title}</span>
                {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
            </div>
            <div className="text-2xl font-bold">{value}</div>
            {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
        </button>
    );
}

function SectionList({ title, items, emptyMsg, renderItem, onVerMais, href }) {
    const nav = useNavigate();
    return (
        <Card>
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold flex items-center justify-between">
                    {title}
                    {href && (
                        <button className="text-xs text-primary flex items-center gap-1 hover:underline" onClick={() => nav(href)}>
                            Ver todos <ChevronRight className="h-3 w-3" />
                        </button>
                    )}
                </CardTitle>
            </CardHeader>
            <CardContent>
                {items.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-3 text-center">{emptyMsg}</div>
                ) : (
                    <div className="space-y-1.5">
                        {items.slice(0, 5).map((item, i) => renderItem(item, i))}
                        {items.length > 5 && (
                            <div className="text-xs text-muted-foreground pt-1 text-center">
                                + {items.length - 5} mais
                            </div>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}

function FlowAction({ icon: Icon, title, description, metric, action, onClick }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="rounded-xl border bg-card p-4 text-left transition hover:border-primary/40 hover:bg-muted/40"
        >
            <div className="flex items-start justify-between gap-3">
                <div className="rounded-md bg-primary/10 p-2 text-primary">
                    <Icon className="h-5 w-5" />
                </div>
                {metric != null && <span className="mono-num text-lg font-semibold">{metric}</span>}
            </div>
            <h3 className="mt-3 font-semibold">{title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            <p className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary">
                {action} <ChevronRight className="h-3 w-3" />
            </p>
        </button>
    );
}

export default function ComprasDashboard() {
    const nav = useNavigate();
    const [dash, setDash] = useState(null);
    const [loading, setLoading] = useState(true);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get("/compras/dashboard");
            setDash(data);
        } catch {
            toast.error("Erro ao carregar dashboard de compras");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { carregar(); }, [carregar]);

    const op = dash?.visao_operacional || {};
    const forn = dash?.visao_fornecedores || {};
    const est = dash?.visao_estoque_reposicao || {};
    const fin = dash?.visao_financeira || {};
    const ep = dash?.estoque_projetado_resumo || {};

    if (loading) {
        return (
            <div className="flex justify-center items-center h-64">
                <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold flex items-center gap-2">
                    <Package className="h-5 w-5 text-primary" /> Dashboard de Compras
                </h1>
                <Button size="sm" variant="outline" onClick={carregar}>
                    <RefreshCw className="h-4 w-4 mr-1.5" /> Atualizar
                </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <FlowAction
                    icon={ClipboardList}
                    title="Solicitacoes / MRP"
                    description="Consolida demanda real, estoque projetado e materiais abaixo do minimo antes de comprar."
                    metric={op.itens_urgentes_mrp?.length ?? 0}
                    action="Rodar MRP"
                    onClick={() => nav("/compras/mrp")}
                />
                <FlowAction
                    icon={Handshake}
                    title="Cotacao"
                    description="Compara fornecedores homologados, historico de preco, prazo e condicao comercial."
                    metric={forn.homologacao_vencendo_30_dias?.length ?? 0}
                    action="Analisar itens"
                    onClick={() => nav("/compras/itens")}
                />
                <FlowAction
                    icon={ReceiptText}
                    title="Pedido de Compra"
                    description="PO emitida segue confirmacao, entrega, recebimento parcial e rastreio financeiro."
                    metric={(op.pos_aguardando_confirmacao?.length ?? 0) + (op.pos_entrega_proximos_7_dias?.length ?? 0)}
                    action="Abrir POs"
                    onClick={() => nav("/compras/pos")}
                />
                <FlowAction
                    icon={Warehouse}
                    title="Recebimento / WMS"
                    description="Material entregue entra em quarentena CQ e so fica disponivel apos liberacao."
                    metric={est.abaixo_minimo_sem_po?.length ?? 0}
                    action="Ver estoque"
                    onClick={() => nav("/compras/estoque-projetado")}
                />
            </div>

            <Card>
                <CardContent className="p-4">
                    <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] md:items-center">
                        {[
                            ["MRP", "Demanda e necessidade", ClipboardList, "/compras/mrp"],
                            ["Cotacao", "Fornecedor, preco e prazo", Handshake, "/compras/itens"],
                            ["PO", "Emissao e confirmacao", Send, "/compras/pos"],
                            ["Recebimento", "Entrega e quarentena CQ", ShieldCheck, "/recebimento"],
                        ].map(([title, desc, Icon, href], index) => (
                            <div key={title} className="contents">
                                <button type="button" onClick={() => nav(href)} className="rounded-lg border p-4 text-left transition hover:bg-muted/40">
                                    <Icon className="mb-3 h-5 w-5 text-primary" />
                                    <p className="font-semibold">{title}</p>
                                    <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
                                </button>
                                {index < 3 && <ChevronRight className="hidden h-4 w-4 text-muted-foreground md:block" />}
                            </div>
                        ))}
                    </div>
                </CardContent>
            </Card>

            <Tabs defaultValue="operacao" className="w-full">
                <TabsList className="grid h-auto grid-cols-2 gap-1 md:grid-cols-4">
                    <TabsTrigger value="operacao">Operacao</TabsTrigger>
                    <TabsTrigger value="fornecedores">Fornecedores</TabsTrigger>
                    <TabsTrigger value="estoque">Estoque</TabsTrigger>
                    <TabsTrigger value="financeiro">Financeiro</TabsTrigger>
                </TabsList>

                <TabsContent value="operacao" className="space-y-4">

            {/* KPIs operacionais */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <KpiCard title="Aguardando Confirmação" value={op.pos_aguardando_confirmacao?.length ?? 0}
                    sub=">2 dias sem retorno" icon={Clock} testId="kpi-aguardando-confirmacao"
                    color={op.pos_aguardando_confirmacao?.length > 0 ? "border-orange-300 bg-orange-50" : "border-border bg-card"}
                    onClick={() => nav("/compras/pos?status=emitida")} />
                <KpiCard title="Entregas Próximos 7d" value={op.pos_entrega_proximos_7_dias?.length ?? 0}
                    sub="Confirmar recebimento" icon={Truck} testId="kpi-entregas-proximas"
                    color="border-blue-200 bg-blue-50"
                    onClick={() => nav("/compras/pos?status=confirmada")} />
                <KpiCard title="POs Atrasadas" value={op.pos_atrasadas?.length ?? 0}
                    sub="Entrega vencida" icon={AlertTriangle} testId="kpi-pos-atrasadas"
                    color={op.pos_atrasadas?.length > 0 ? "border-red-300 bg-red-50" : "border-border bg-card"}
                    onClick={() => nav("/compras/pos")} />
                <KpiCard title="Itens Urgentes MRP" value={op.itens_urgentes_mrp?.length ?? 0}
                    sub="Data-limite ultrapassada" icon={TrendingDown} testId="kpi-itens-urgentes-mrp"
                    color={op.itens_urgentes_mrp?.length > 0 ? "border-red-300 bg-red-50" : "border-border bg-card"}
                    onClick={() => nav("/compras/mrp")} />
            </div>

            {/* Estoque projetado resumo */}
            <div>
                <div className="text-xs font-semibold text-muted-foreground mb-2">ESTOQUE PROJETADO</div>
                <div className="grid grid-cols-4 gap-2">
                    {[
                        { k: "ruptura", label: "Ruptura", cls: "border-red-500 bg-red-50 text-red-700" },
                        { k: "critico", label: "Crítico", cls: "border-orange-400 bg-orange-50 text-orange-700" },
                        { k: "atencao", label: "Atenção", cls: "border-yellow-400 bg-yellow-50 text-yellow-700" },
                        { k: "ok",      label: "OK",     cls: "border-green-400 bg-green-50 text-green-700" },
                    ].map(({ k, label, cls }) => (
                        <button key={k} className={`rounded-lg border-2 p-2 text-center hover:shadow-md transition ${cls}`}
                            onClick={() => nav(`/compras/estoque-projetado`)}>
                            <div className="text-xl font-bold">{ep[k] ?? 0}</div>
                            <div className="text-xs font-medium">{label}</div>
                        </button>
                    ))}
                </div>
            </div>

            {/* Grid de seções */}
            <div className="grid md:grid-cols-2 gap-4">
                <SectionList
                    title="POs Atrasadas"
                    items={op.pos_atrasadas || []}
                    emptyMsg="Nenhuma PO atrasada"
                    href="/compras/pos"
                    renderItem={(p) => (
                        <button key={p.id} className="w-full text-left flex items-center justify-between rounded-md p-2 hover:bg-muted/50 transition"
                            onClick={() => nav(`/compras/pos/${p.id}`)}>
                            <div>
                                <div className="text-xs font-medium">{p.numero_po}</div>
                                <div className="text-xs text-muted-foreground">{p.fornecedor_nome} · vencia {p.data_entrega_confirmada}</div>
                            </div>
                            <span className="text-xs font-semibold text-red-600">{fmtBRL(p.valor_total_po)}</span>
                        </button>
                    )}
                />

                <SectionList
                    title="Fornecedores Suspensos por RNCs"
                    items={forn.suspensos_por_rncs || []}
                    emptyMsg="Nenhum fornecedor suspenso"
                    href="/compras/fornecedores"
                    renderItem={(f) => (
                        <button key={f.id} className="w-full text-left flex items-center justify-between rounded-md p-2 hover:bg-muted/50 transition"
                            onClick={() => nav(`/compras/fornecedores/${f.id}`)}>
                            <div>
                                <div className="text-xs font-medium">{f.codigo_interno} · {f.razao_social}</div>
                                <div className="text-xs text-muted-foreground">{f.homologacao?.historico_rncs_criticas_12m} RNCs críticas 12m</div>
                            </div>
                            <span className="text-xs font-semibold text-orange-600">Suspenso</span>
                        </button>
                    )}
                />

                <SectionList
                    title="Homologações Vencendo 30d"
                    items={forn.homologacao_vencendo_30_dias || []}
                    emptyMsg="Nenhuma reavaliação próxima"
                    href="/compras/fornecedores"
                    renderItem={(f) => (
                        <button key={f.id} className="w-full text-left flex items-center justify-between rounded-md p-2 hover:bg-muted/50 transition"
                            onClick={() => nav(`/compras/fornecedores/${f.id}`)}>
                            <div className="text-xs font-medium">{f.codigo_interno} · {f.razao_social}</div>
                            <span className="text-xs text-orange-600 font-medium">Até {f.homologacao?.proxima_reavaliacao}</span>
                        </button>
                    )}
                />

                <SectionList
                    title="Abaixo do Mínimo sem PO"
                    items={est.abaixo_minimo_sem_po || []}
                    emptyMsg="Nenhum item em reposição urgente"
                    href="/compras/estoque-projetado?apenas_criticos=true"
                    renderItem={(i) => (
                        <div key={i.item_id} className="flex items-center justify-between rounded-md p-2 bg-orange-50 border border-orange-200">
                            <div className="text-xs font-medium">{i.descricao}</div>
                            <span className="text-xs text-orange-700 font-mono">{fmt(i.estoque_atual)} / {fmt(i.estoque_minimo)}</span>
                        </div>
                    )}
                />
            </div>

            {/* Visão financeira */}
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-semibold flex items-center gap-2">
                        <DollarSign className="h-4 w-4" /> Visão Financeira
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                        <div className="bg-muted/40 rounded-lg p-3 text-center">
                            <div className="text-lg font-bold text-primary">{fmtBRL(fin.total_a_pagar_semana)}</div>
                            <div className="text-xs text-muted-foreground">A pagar esta semana</div>
                        </div>
                        <div className="bg-muted/40 rounded-lg p-3 text-center">
                            <div className="text-lg font-bold">{fmtBRL(fin.total_a_pagar_mes)}</div>
                            <div className="text-xs text-muted-foreground">A pagar este mês</div>
                        </div>
                        <div className="bg-muted/40 rounded-lg p-3 text-center">
                            <div className="text-lg font-bold text-orange-600">{fin.vencendo_proximos_7_dias?.length ?? 0}</div>
                            <div className="text-xs text-muted-foreground">NFs vencendo 7d</div>
                        </div>
                        <div className="bg-muted/40 rounded-lg p-3 text-center">
                            <div className="text-lg font-bold">{fin.aguardando_pagamento?.length ?? 0}</div>
                            <div className="text-xs text-muted-foreground">Em aberto</div>
                        </div>
                    </div>
                    {fin.top_fornecedores_volume?.length > 0 && (
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground mb-2">TOP FORNECEDORES (VOLUME COMPRADO)</div>
                            <div className="space-y-1">
                                {fin.top_fornecedores_volume.map((f, i) => (
                                    <div key={i} className="flex items-center gap-2">
                                        <span className="text-xs text-muted-foreground w-4">{i + 1}</span>
                                        <div className="flex-1 bg-muted/30 rounded h-5 relative overflow-hidden">
                                            <div className="h-5 bg-primary/20 rounded transition-all"
                                                style={{ width: `${Math.min(100, (f.total / (fin.top_fornecedores_volume[0]?.total || 1)) * 100)}%` }} />
                                        </div>
                                        <span className="text-xs font-medium w-24 text-right">{fmtBRL(f.total)}</span>
                                        <span className="text-xs text-muted-foreground truncate max-w-[120px]">{f.fornecedor_nome}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </CardContent>
            </Card>
                </TabsContent>

                <TabsContent value="fornecedores" className="grid gap-4 md:grid-cols-2">
                    <SectionList
                        title="Fornecedores Suspensos por RNCs"
                        items={forn.suspensos_por_rncs || []}
                        emptyMsg="Nenhum fornecedor suspenso"
                        href="/compras/fornecedores"
                        renderItem={(f) => (
                            <button key={f.id} className="w-full text-left flex items-center justify-between rounded-md p-2 hover:bg-muted/50 transition"
                                onClick={() => nav(`/compras/fornecedores/${f.id}`)}>
                                <div>
                                    <div className="text-xs font-medium">{f.codigo_interno} - {f.razao_social}</div>
                                    <div className="text-xs text-muted-foreground">{f.homologacao?.historico_rncs_criticas_12m} RNCs criticas 12m</div>
                                </div>
                                <span className="text-xs font-semibold text-orange-600">Suspenso</span>
                            </button>
                        )}
                    />
                    <SectionList
                        title="Homologacoes Vencendo 30d"
                        items={forn.homologacao_vencendo_30_dias || []}
                        emptyMsg="Nenhuma reavaliacao proxima"
                        href="/compras/fornecedores"
                        renderItem={(f) => (
                            <button key={f.id} className="w-full text-left flex items-center justify-between rounded-md p-2 hover:bg-muted/50 transition"
                                onClick={() => nav(`/compras/fornecedores/${f.id}`)}>
                                <div className="text-xs font-medium">{f.codigo_interno} - {f.razao_social}</div>
                                <span className="text-xs text-orange-600 font-medium">Ate {f.homologacao?.proxima_reavaliacao}</span>
                            </button>
                        )}
                    />
                </TabsContent>

                <TabsContent value="estoque" className="space-y-4">
                    <div>
                        <div className="text-xs font-semibold text-muted-foreground mb-2">ESTOQUE PROJETADO</div>
                        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                            {[
                                { k: "ruptura", label: "Ruptura", cls: "border-red-500 bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300" },
                                { k: "critico", label: "Critico", cls: "border-orange-400 bg-orange-50 text-orange-700 dark:bg-orange-950/20 dark:text-orange-300" },
                                { k: "atencao", label: "Atencao", cls: "border-yellow-400 bg-yellow-50 text-yellow-700 dark:bg-yellow-950/20 dark:text-yellow-300" },
                                { k: "ok", label: "OK", cls: "border-green-400 bg-green-50 text-green-700 dark:bg-green-950/20 dark:text-green-300" },
                            ].map(({ k, label, cls }) => (
                                <button key={k} className={`rounded-lg border-2 p-3 text-center hover:shadow-md transition ${cls}`}
                                    onClick={() => nav("/compras/estoque-projetado")}>
                                    <div className="text-xl font-bold">{ep[k] ?? 0}</div>
                                    <div className="text-xs font-medium">{label}</div>
                                </button>
                            ))}
                        </div>
                    </div>
                    <SectionList
                        title="Abaixo do Minimo sem PO"
                        items={est.abaixo_minimo_sem_po || []}
                        emptyMsg="Nenhum item em reposicao urgente"
                        href="/compras/estoque-projetado?apenas_criticos=true"
                        renderItem={(i) => (
                            <div key={i.item_id} className="flex items-center justify-between rounded-md p-2 bg-orange-50 border border-orange-200 dark:bg-orange-950/20 dark:border-orange-900/40">
                                <div className="text-xs font-medium">{i.descricao}</div>
                                <span className="text-xs text-orange-700 dark:text-orange-300 font-mono">{fmt(i.estoque_atual)} / {fmt(i.estoque_minimo)}</span>
                            </div>
                        )}
                    />
                </TabsContent>

                <TabsContent value="financeiro" className="space-y-4">
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm font-semibold flex items-center gap-2">
                                <DollarSign className="h-4 w-4" /> Contas e compromisso de compras
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-4">
                            <div className="bg-muted/40 rounded-lg p-3 text-center">
                                <div className="text-lg font-bold text-primary">{fmtBRL(fin.total_a_pagar_semana)}</div>
                                <div className="text-xs text-muted-foreground">Semana</div>
                            </div>
                            <div className="bg-muted/40 rounded-lg p-3 text-center">
                                <div className="text-lg font-bold">{fmtBRL(fin.total_a_pagar_mes)}</div>
                                <div className="text-xs text-muted-foreground">Mes</div>
                            </div>
                            <div className="bg-muted/40 rounded-lg p-3 text-center">
                                <div className="text-lg font-bold text-orange-600">{fin.vencendo_proximos_7_dias?.length ?? 0}</div>
                                <div className="text-xs text-muted-foreground">Vencendo 7d</div>
                            </div>
                            <div className="bg-muted/40 rounded-lg p-3 text-center">
                                <div className="text-lg font-bold">{fin.aguardando_pagamento?.length ?? 0}</div>
                                <div className="text-xs text-muted-foreground">Em aberto</div>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
        </div>
    );
}
