import { useEffect, useMemo, useState, useCallback } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
    Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
    Warehouse, Plus, Search, ArrowDown, ArrowUp, ArrowLeftRight,
    AlertTriangle, Trash2, History, Package, FlaskConical, Tag, Box, ShieldCheck, RotateCcw,
} from "lucide-react";

const POSICAO_CQ_CONFIG = {
    livre:       { label: "Livre",       cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
    quarentena:  { label: "Quarentena",  cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
    aprovado:    { label: "Aprovado",    cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
    reprovado:   { label: "Reprovado",   cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" },
};

function PosicaoBadge({ posicao }) {
    const cfg = POSICAO_CQ_CONFIG[posicao] || POSICAO_CQ_CONFIG.livre;
    return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${cfg.cls}`}>
            {cfg.label}
        </span>
    );
}

const SETORES = [
    { key: "MANIPULACAO", label: "Matérias-Primas", sublabel: "Manipulação", icon: FlaskConical, tipo: "mp", tipoMP: "FORMULACAO", color: "bg-blue-500" },
    { key: "ROTULAGEM",   label: "Rótulos",         sublabel: "Rotulagem",   icon: Tag,          tipo: "mp", tipoMP: "ROTULO",     color: "bg-amber-500" },
    { key: "LOGISTICA",   label: "Insumos / Embalagens", sublabel: "Logística", icon: Box,      tipo: "mp", tipoMP: "EMBALAGEM",  color: "bg-emerald-500" },
    { key: "FABRICA",     label: "Produto Acabado", sublabel: "Fábrica",     icon: Package,      tipo: "produto_acabado", color: "bg-violet-500" },
    { key: "DEVOLUCAO",   label: "Devoluções",      sublabel: "Quarentena Especial", icon: RotateCcw, tipo: "mp", tipoMP: null, color: "bg-rose-500" },
];

const TIPO_MOV_LABELS = {
    ENTRADA_RECEBIMENTO: "Entrada (Recebimento/CQ)",
    SAIDA_CONSUMO_OP: "Saída — Consumo OP",
    SAIDA_EXPEDICAO: "Saída — Expedição",
    AJUSTE_ENTRADA: "Ajuste +",
    AJUSTE_SAIDA: "Ajuste −",
    AMOSTRA: "Amostra CQ",
    TRANSFERENCIA_ENTRADA: "Transf. (Entrada)",
    TRANSFERENCIA_SAIDA: "Transf. (Saída)",
};

const MOVS_ENTRADA_MANUAL = ["ENTRADA_RECEBIMENTO", "AJUSTE_ENTRADA"];
const MOVS_SAIDA_MANUAL = ["SAIDA_CONSUMO_OP", "SAIDA_EXPEDICAO", "AJUSTE_SAIDA", "AMOSTRA"];

function formatDateTime(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleString("pt-BR"); } catch { return iso; }
}

export default function EstoquePage() {
    const [dashboard, setDashboard] = useState(null);
    const [setorAtivo, setSetorAtivo] = useState("MANIPULACAO");
    const [items, setItems] = useState([]);
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(false);

    const [selectedItem, setSelectedItem] = useState(null);
    const [kardex, setKardex] = useState([]);
    const [updatingPosicao, setUpdatingPosicao] = useState(false);

    const [showNewItem, setShowNewItem] = useState(false);
    const [showMov, setShowMov] = useState(false);
    const [movDirection, setMovDirection] = useState("entrada"); // entrada | saida | transferencia
    const [wmsView, setWmsView] = useState("agregado");

    const setorConfig = useMemo(() => SETORES.find(s => s.key === setorAtivo), [setorAtivo]);

    const loadDashboard = useCallback(async () => {
        try {
            const { data } = await api.get("/estoque/dashboard");
            setDashboard(data);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    }, []);

    const loadItems = useCallback(async () => {
        setLoading(true);
        try {
            const params = { setor: setorAtivo };
            if (search) params.search = search;
            const { data } = await api.get("/estoque/items", { params });
            setItems(data);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    }, [setorAtivo, search]);

    useEffect(() => { loadDashboard(); }, [loadDashboard]);
    useEffect(() => { loadItems(); }, [loadItems]);

    const openItemDetail = async (item) => {
        setSelectedItem(item);
        try {
            const { data } = await api.get(`/estoque/kardex/${item.id}`);
            setKardex(data);
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const closeDetail = () => {
        setSelectedItem(null);
        setKardex([]);
    };

    const handleDeleteItem = async (item) => {
        if (!window.confirm(`Excluir "${item.nome}"? Movimentos antigos são preservados.`)) return;
        try {
            await api.delete(`/estoque/items/${item.id}`);
            toast.success("Item excluído.");
            closeDetail();
            loadItems();
            loadDashboard();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const updatePosicaoCQ = async (posicao) => {
        if (!selectedItem) return;
        setUpdatingPosicao(true);
        try {
            const { data } = await api.patch(`/estoque/items/${selectedItem.id}/posicao`, { posicao_cq: posicao });
            setSelectedItem(prev => ({ ...prev, posicao_cq: data.posicao_cq }));
            setItems(prev => prev.map(i => i.id === selectedItem.id ? { ...i, posicao_cq: data.posicao_cq } : i));
            toast.success(`Posição CQ: ${POSICAO_CQ_CONFIG[posicao]?.label}`);
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setUpdatingPosicao(false);
        }
    };

    const isLowStock = (item) => item.estoque_minimo > 0 && item.quantidade_atual <= item.estoque_minimo;
    const lotes = useMemo(
        () => items.filter((item) => item.lote || item.localizacao_estruturada || item.localizacao || item.validade),
        [items]
    );
    const vencendo = useMemo(() => {
        const hoje = new Date();
        const limite = new Date();
        limite.setDate(limite.getDate() + 45);
        return lotes
            .filter((item) => item.validade)
            .map((item) => ({ ...item, validadeDate: new Date(`${item.validade}T00:00:00`) }))
            .filter((item) => item.validadeDate <= limite)
            .sort((a, b) => a.validadeDate - b.validadeDate)
            .map((item) => ({
                ...item,
                vencido: item.validadeDate < hoje,
                dias: Math.ceil((item.validadeDate - hoje) / 86400000),
            }));
    }, [lotes]);
    const enderecoStats = useMemo(() => {
        const map = new Map();
        items.forEach((item) => {
            const endereco = item.localizacao_estruturada || item.localizacao || "Sem endereco";
            const atual = map.get(endereco) || { endereco, itens: 0, saldo: 0, quarentena: 0 };
            atual.itens += 1;
            atual.saldo += Number(item.quantidade_atual || 0);
            if ((item.posicao_cq || "livre") === "quarentena") atual.quarentena += 1;
            map.set(endereco, atual);
        });
        return Array.from(map.values()).sort((a, b) => a.endereco.localeCompare(b.endereco));
    }, [items]);

    return (
        <div className="p-6 space-y-5 min-h-screen" data-testid="estoque-page">
            {/* Header */}
            <div className="flex items-start justify-between flex-wrap gap-3">
                <div>
                    <h1 className="font-heading text-2xl font-semibold tracking-tight flex items-center gap-2">
                        <Warehouse className="h-6 w-6 text-primary" />
                        Controle de Estoque
                    </h1>
                    <p className="text-sm text-muted-foreground">
                        5 setores · Kardex imutável · FIFO · Alertas em tempo real
                    </p>
                </div>
            </div>

            {/* Dashboard cards */}
            {dashboard && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {dashboard.setores.map((s) => {
                        const cfg = SETORES.find(x => x.key === s.setor);
                        const Icon = cfg?.icon || Package;
                        return (
                            <button
                                key={s.setor}
                                onClick={() => setSetorAtivo(s.setor)}
                                className={`text-left rounded-xl border p-4 transition hover:bg-accent ${setorAtivo === s.setor ? "border-primary ring-1 ring-primary" : "border-border"}`}
                                data-testid={`setor-card-${s.setor}`}
                            >
                                <div className="flex items-center gap-2 mb-2">
                                    <div className={`${cfg?.color || "bg-gray-500"} rounded-md w-7 h-7 flex items-center justify-center`}>
                                        <Icon className="h-3.5 w-3.5 text-white" />
                                    </div>
                                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{cfg?.sublabel}</p>
                                </div>
                                <h3 className="font-medium text-sm leading-tight">{s.label.split(" (")[0]}</h3>
                                <div className="mt-3 flex items-baseline gap-2">
                                    <span className="text-2xl font-bold mono-num">{s.total_items}</span>
                                    <span className="text-xs text-muted-foreground">itens</span>
                                </div>
                            </button>
                        );
                    })}
                </div>
            )}

            {/* Alertas */}
            {dashboard?.alertas?.baixo_estoque?.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-3" data-testid="alertas-baixo-estoque">
                    <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                        <p className="text-sm font-medium">
                            {dashboard.alertas.baixo_estoque.length} item(s) com estoque mínimo atingido
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                            {dashboard.alertas.baixo_estoque.slice(0, 8).map((it) => (
                                <Badge
                                    key={it.id}
                                    variant="outline"
                                    className="cursor-pointer bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30"
                                    onClick={() => { setSetorAtivo(it.setor); openItemDetail(it); }}
                                >
                                    {it.nome} · {it.quantidade_atual}/{it.estoque_minimo}{it.unidade}
                                </Badge>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Obsolescence alert */}
            {dashboard?.alertas?.obsoletos?.length > 0 && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 flex items-start gap-3">
                    <RotateCcw className="h-5 w-5 text-rose-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                        <p className="text-sm font-medium">
                            {dashboard.alertas.obsoletos.length} item(s) sem movimentação há 90+ dias
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                            {dashboard.alertas.obsoletos.slice(0, 8).map((it) => (
                                <Badge
                                    key={it.id}
                                    variant="outline"
                                    className="cursor-pointer bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/30"
                                    onClick={() => { setSetorAtivo(it.setor); openItemDetail(it); }}
                                >
                                    {it.nome} · {it.quantidade_atual} {it.unidade}
                                </Badge>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            <Tabs value={wmsView} onValueChange={setWmsView} className="w-full">
                <TabsList className="grid h-auto grid-cols-2 gap-1 md:grid-cols-5">
                    <TabsTrigger value="agregado">Saldo Agregado</TabsTrigger>
                    <TabsTrigger value="lotes">Lote/Endereco</TabsTrigger>
                    <TabsTrigger value="vencendo">Vencimento</TabsTrigger>
                    <TabsTrigger value="historico">Historico</TabsTrigger>
                    <TabsTrigger value="enderecos">Enderecos</TabsTrigger>
                </TabsList>

                <TabsContent value="agregado" className="space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <Card>
                            <CardContent className="p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Itens no setor</p>
                                <p className="mt-1 text-2xl font-semibold mono-num">{items.length}</p>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Abaixo do minimo</p>
                                <p className="mt-1 text-2xl font-semibold mono-num text-amber-600">{items.filter(isLowStock).length}</p>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Em quarentena</p>
                                <p className="mt-1 text-2xl font-semibold mono-num text-amber-600">{items.filter((i) => (i.posicao_cq || "livre") === "quarentena").length}</p>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Enderecos usados</p>
                                <p className="mt-1 text-2xl font-semibold mono-num">{enderecoStats.length}</p>
                            </CardContent>
                        </Card>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Saldo atual, minimo, CQ e acoes de entrada/saida ficam na grade operacional abaixo. Clique em um item para abrir Kardex e alterar posicao CQ.
                    </p>
                </TabsContent>

                <TabsContent value="lotes" className="space-y-3">
                    <div className="rounded-lg border overflow-hidden">
                        <table className="w-full text-xs">
                            <thead className="bg-muted/60 border-b">
                                <tr>
                                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">Item</th>
                                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">Lote</th>
                                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">Endereco</th>
                                    <th className="px-3 py-2 text-right font-medium text-muted-foreground">Saldo</th>
                                    <th className="px-3 py-2 text-center font-medium text-muted-foreground">CQ</th>
                                </tr>
                            </thead>
                            <tbody>
                                {lotes.length === 0 ? (
                                    <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">Nenhum lote/endereco registrado neste setor.</td></tr>
                                ) : lotes.map((item) => (
                                    <tr key={item.id} className="border-b last:border-0 hover:bg-muted/30 cursor-pointer" onClick={() => openItemDetail(item)}>
                                        <td className="px-3 py-2 font-medium">{item.nome}</td>
                                        <td className="px-3 py-2 font-mono">{item.lote || "-"}</td>
                                        <td className="px-3 py-2 font-mono">{item.localizacao_estruturada || item.localizacao || "-"}</td>
                                        <td className="px-3 py-2 text-right font-mono">{item.quantidade_atual} {item.unidade}</td>
                                        <td className="px-3 py-2 text-center"><PosicaoBadge posicao={item.posicao_cq || "livre"} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </TabsContent>

                <TabsContent value="vencendo" className="space-y-3">
                    <div className="grid gap-2">
                        {vencendo.length === 0 ? (
                            <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Nenhum lote vencido ou vencendo nos proximos 45 dias.</CardContent></Card>
                        ) : vencendo.map((item) => (
                            <Card key={item.id} className={item.vencido ? "border-red-500/40" : "border-amber-500/30"}>
                                <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                                    <div>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-semibold">{item.nome}</span>
                                            <Badge className={item.vencido ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"}>
                                                {item.vencido ? "Vencido" : `${Math.max(0, item.dias)} dias`}
                                            </Badge>
                                        </div>
                                        <p className="mt-1 text-xs text-muted-foreground">Lote {item.lote || "-"} - {item.localizacao_estruturada || item.localizacao || "sem endereco"}</p>
                                    </div>
                                    <div className="text-left sm:text-right">
                                        <p className="font-mono text-sm">{new Date(`${item.validade}T00:00:00`).toLocaleDateString("pt-BR")}</p>
                                        <p className="text-xs text-muted-foreground">{item.quantidade_atual} {item.unidade}</p>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                </TabsContent>

                <TabsContent value="historico" className="space-y-3">
                    <Card>
                        <CardContent className="p-4">
                            <div className="flex items-start gap-3">
                                <History className="mt-0.5 h-5 w-5 text-primary" />
                                <div>
                                    <h3 className="font-semibold">Historico por item</h3>
                                    <p className="mt-1 text-sm text-muted-foreground">
                                        O Kardex detalhado abre no painel lateral ao clicar em qualquer item da grade. Para historico consolidado, use WMS / Movimentacao.
                                    </p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="enderecos" className="space-y-3">
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {enderecoStats.map((endereco) => (
                            <Card key={endereco.endereco}>
                                <CardContent className="p-4">
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <p className="font-mono text-sm font-semibold">{endereco.endereco}</p>
                                            <p className="mt-1 text-xs text-muted-foreground">{endereco.itens} item(ns) armazenado(s)</p>
                                        </div>
                                        <Badge variant="outline">{endereco.quarentena ? `${endereco.quarentena} CQ` : "Livre"}</Badge>
                                    </div>
                                    <div className="mt-3 h-2 rounded-full bg-muted">
                                        <div className="h-2 rounded-full bg-primary" style={{ width: `${Math.min(100, endereco.itens * 18)}%` }} />
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                </TabsContent>
            </Tabs>

            {/* Setor header + actions */}
            <div className="flex items-center justify-between flex-wrap gap-3 pt-2">
                <div>
                    <h2 className="font-heading text-lg font-semibold">
                        {setorConfig?.label} <span className="text-muted-foreground font-normal">— {setorConfig?.sublabel}</span>
                    </h2>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                        <Input
                            value={search} onChange={(e) => setSearch(e.target.value)}
                            placeholder="Buscar nome / código / lote"
                            className="pl-8 h-9 w-64"
                            data-testid="estoque-search"
                        />
                    </div>
                    <Button onClick={() => setShowNewItem(true)} data-testid="btn-novo-item">
                        <Plus className="h-4 w-4 mr-1" /> Novo Item
                    </Button>
                </div>
            </div>

            {/* Items table */}
            <div className="rounded-lg border border-border overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead className="bg-muted/40">
                            <tr>
                                <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Nome</th>
                                <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Código</th>
                                <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Lote</th>
                                <th className="text-right px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Saldo</th>
                                <th className="text-right px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Mín.</th>
                                <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Local</th>
                                <th className="text-center px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">CQ</th>
                                <th className="text-center px-4 py-2.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading && (
                                <tr><td colSpan={8} className="px-4 py-6 text-center text-muted-foreground">Carregando…</td></tr>
                            )}
                            {!loading && items.length === 0 && (
                                <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground italic">
                                    Nenhum item neste setor. Clique em "Novo Item" para começar.
                                </td></tr>
                            )}
                            {items.map((it) => (
                                <tr
                                    key={it.id}
                                    className={`border-t border-border hover:bg-accent/40 cursor-pointer ${isLowStock(it) ? "bg-amber-500/5" : ""}`}
                                    onClick={() => openItemDetail(it)}
                                    data-testid={`item-row-${it.id}`}
                                >
                                    <td className="px-4 py-2.5">
                                        <div className="font-medium">{it.nome}</div>
                                        {isLowStock(it) && (
                                            <Badge className="text-[10px] mt-0.5 bg-amber-500/20 text-amber-700 dark:text-amber-400 hover:bg-amber-500/20">
                                                <AlertTriangle className="h-3 w-3 mr-0.5" /> Estoque mínimo
                                            </Badge>
                                        )}
                                    </td>
                                    <td className="px-4 py-2.5 text-muted-foreground mono-num">{it.codigo || "—"}</td>
                                    <td className="px-4 py-2.5 text-muted-foreground mono-num">{it.lote || "—"}</td>
                                    <td className="px-4 py-2.5 text-right font-semibold mono-num">
                                        {it.quantidade_atual} <span className="text-xs text-muted-foreground font-normal">{it.unidade}</span>
                                    </td>
                                    <td className="px-4 py-2.5 text-right text-muted-foreground mono-num">
                                        {it.estoque_minimo || "—"}
                                    </td>
                                    <td className="px-4 py-2.5 text-muted-foreground font-mono text-xs">
                                        {it.localizacao_estruturada || it.localizacao || "—"}
                                    </td>
                                    <td className="px-4 py-2.5 text-center">
                                        <PosicaoBadge posicao={it.posicao_cq || "livre"} />
                                    </td>
                                    <td className="px-4 py-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                                        <div className="flex items-center justify-center gap-1">
                                            <Button
                                                variant="ghost" size="icon" className="h-7 w-7 text-emerald-600 hover:bg-emerald-500/10"
                                                onClick={() => { setSelectedItem(it); setMovDirection("entrada"); setShowMov(true); }}
                                                title="Entrada"
                                                data-testid={`btn-entrada-${it.id}`}
                                            >
                                                <ArrowDown className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button
                                                variant="ghost" size="icon" className="h-7 w-7 text-rose-600 hover:bg-rose-500/10"
                                                onClick={() => { setSelectedItem(it); setMovDirection("saida"); setShowMov(true); }}
                                                title="Saída"
                                                data-testid={`btn-saida-${it.id}`}
                                            >
                                                <ArrowUp className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button
                                                variant="ghost" size="icon" className="h-7 w-7 text-indigo-600 hover:bg-indigo-500/10"
                                                onClick={() => { setSelectedItem(it); setMovDirection("transferencia"); setShowMov(true); }}
                                                title="Transferir"
                                                data-testid={`btn-transfer-${it.id}`}
                                            >
                                                <ArrowLeftRight className="h-3.5 w-3.5" />
                                            </Button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Detail sheet with Kardex */}
            <Sheet open={!!selectedItem && !showMov && !showNewItem} onOpenChange={(v) => { if (!v) closeDetail(); }}>
                <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
                    {selectedItem && (
                        <>
                            <SheetHeader>
                                <SheetTitle className="font-heading flex items-center gap-2">
                                    <Package className="h-5 w-5 text-primary" />
                                    {selectedItem.nome}
                                </SheetTitle>
                                <p className="text-xs text-muted-foreground">
                                    {SETORES.find(s => s.key === selectedItem.setor)?.label}
                                </p>
                            </SheetHeader>

                            <div className="mt-4 space-y-4">
                                <div className="grid grid-cols-2 gap-3">
                                    <Stat label="Saldo atual" value={`${selectedItem.quantidade_atual} ${selectedItem.unidade}`} highlight />
                                    <Stat label="Estoque mínimo" value={`${selectedItem.estoque_minimo || 0} ${selectedItem.unidade}`} />
                                    <Stat label="Código" value={selectedItem.codigo || "—"} />
                                    <Stat label="Lote" value={selectedItem.lote || "—"} />
                                    <Stat label="Localização" value={selectedItem.localizacao_estruturada || selectedItem.localizacao || "—"} />
                                    <Stat label="Validade" value={selectedItem.validade ? new Date(selectedItem.validade).toLocaleDateString("pt-BR") : "—"} />
                                </div>

                                {/* Posição CQ */}
                                <div className="rounded-lg border border-border p-3 space-y-2">
                                    <div className="flex items-center gap-2">
                                        <ShieldCheck className="h-4 w-4 text-primary" />
                                        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Posição CQ</span>
                                        <PosicaoBadge posicao={selectedItem.posicao_cq || "livre"} />
                                    </div>
                                    <div className="flex gap-1.5 flex-wrap">
                                        {Object.entries(POSICAO_CQ_CONFIG).map(([key, cfg]) => (
                                            <Button
                                                key={key}
                                                size="sm"
                                                variant={(selectedItem.posicao_cq || "livre") === key ? "default" : "outline"}
                                                className="h-7 text-xs"
                                                disabled={updatingPosicao || (selectedItem.posicao_cq || "livre") === key}
                                                onClick={() => updatePosicaoCQ(key)}
                                            >
                                                {cfg.label}
                                            </Button>
                                        ))}
                                    </div>
                                </div>

                                {isLowStock(selectedItem) && (
                                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2">
                                        <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5" />
                                        <p className="text-xs">Saldo abaixo do estoque mínimo. Solicitar reposição.</p>
                                    </div>
                                )}

                                <div className="flex items-center gap-2 flex-wrap">
                                    <Button size="sm" variant="outline" onClick={() => { setMovDirection("entrada"); setShowMov(true); }} data-testid="sheet-btn-entrada">
                                        <ArrowDown className="h-3.5 w-3.5 mr-1 text-emerald-600" /> Entrada
                                    </Button>
                                    <Button size="sm" variant="outline" onClick={() => { setMovDirection("saida"); setShowMov(true); }} data-testid="sheet-btn-saida">
                                        <ArrowUp className="h-3.5 w-3.5 mr-1 text-rose-600" /> Saída
                                    </Button>
                                    <Button size="sm" variant="outline" onClick={() => { setMovDirection("transferencia"); setShowMov(true); }} data-testid="sheet-btn-transfer">
                                        <ArrowLeftRight className="h-3.5 w-3.5 mr-1 text-indigo-600" /> Transferir
                                    </Button>
                                </div>

                                <Separator />

                                <div>
                                    <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5 mb-2">
                                        <History className="h-3.5 w-3.5" /> Kardex ({kardex.length} movimento{kardex.length !== 1 ? "s" : ""})
                                    </h4>
                                    <div className="space-y-1.5 max-h-96 overflow-y-auto pr-2">
                                        {kardex.length === 0 && (
                                            <p className="text-xs italic text-muted-foreground py-4 text-center">Sem movimentos registrados.</p>
                                        )}
                                        {kardex.map((m) => {
                                            const entrada = m.direcao === "entrada";
                                            return (
                                                <div key={m.id} className={`rounded-md border p-2 text-xs ${entrada ? "border-emerald-500/30 bg-emerald-500/5" : "border-rose-500/30 bg-rose-500/5"}`}>
                                                    <div className="flex items-center justify-between">
                                                        <span className="font-medium flex items-center gap-1">
                                                            {entrada ? <ArrowDown className="h-3 w-3 text-emerald-600" /> : <ArrowUp className="h-3 w-3 text-rose-600" />}
                                                            {TIPO_MOV_LABELS[m.tipo] || m.tipo}
                                                        </span>
                                                        <span className="mono-num font-semibold">
                                                            {entrada ? "+" : "−"}{m.quantidade} {m.unidade}
                                                        </span>
                                                    </div>
                                                    <div className="mt-1 text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5">
                                                        <span>{formatDateTime(m.created_at)}</span>
                                                        <span>por {m.usuario}</span>
                                                        <span className="mono-num">{m.quantidade_antes} → {m.quantidade_depois}</span>
                                                    </div>
                                                    {m.motivo && <p className="mt-1 italic">{m.motivo}</p>}
                                                    {m.referencia && <p className="mt-0.5 text-[10px]">Ref: {m.referencia}</p>}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>

                                <Separator />
                                <Button
                                    variant="outline" size="sm"
                                    className="w-full text-destructive border-destructive/30 hover:text-destructive"
                                    onClick={() => handleDeleteItem(selectedItem)}
                                    disabled={selectedItem.quantidade_atual > 0}
                                    title={selectedItem.quantidade_atual > 0 ? "Zere o saldo antes" : "Excluir item"}
                                    data-testid="btn-delete-item"
                                >
                                    <Trash2 className="h-3.5 w-3.5 mr-1" /> Excluir Item
                                </Button>
                            </div>
                        </>
                    )}
                </SheetContent>
            </Sheet>

            {/* Movement dialog */}
            {showMov && selectedItem && (
                <MovDialog
                    open={showMov}
                    onOpenChange={setShowMov}
                    item={selectedItem}
                    direction={movDirection}
                    onSuccess={async () => {
                        setShowMov(false);
                        const { data: fresh } = await api.get(`/estoque/items/${selectedItem.id}`);
                        setSelectedItem(fresh);
                        const { data: k } = await api.get(`/estoque/kardex/${selectedItem.id}`);
                        setKardex(k);
                        loadItems();
                        loadDashboard();
                    }}
                />
            )}

            {/* New item dialog */}
            <NewItemDialog
                open={showNewItem}
                onOpenChange={setShowNewItem}
                setor={setorAtivo}
                onCreated={() => {
                    setShowNewItem(false);
                    loadItems();
                    loadDashboard();
                }}
            />
        </div>
    );
}

function Stat({ label, value, highlight }) {
    return (
        <div className="rounded-md border border-border p-2.5">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
            <p className={`text-sm mt-0.5 ${highlight ? "font-bold text-base" : "font-medium"} mono-num`}>{value}</p>
        </div>
    );
}

function NewItemDialog({ open, onOpenChange, setor, onCreated }) {
    const [form, setForm] = useState({
        nome: "", codigo: "", unidade: "kg", estoque_minimo: "", localizacao: "", localizacao_estruturada: "", lote: "", validade: "", observacoes: "",
    });
    const [mps, setMps] = useState([]);
    const [mpId, setMpId] = useState("__none__");
    const setorCfg = SETORES.find(s => s.key === setor);

    useEffect(() => {
        if (!open) return;
        setForm({ nome: "", codigo: "", unidade: "kg", estoque_minimo: "", localizacao: "", localizacao_estruturada: "", lote: "", validade: "", observacoes: "" });
        setMpId("__none__");
        // Pre-carrega MPs homologadas do tipo correspondente
        if (setor !== "FABRICA" && setor !== "DEVOLUCAO" && setorCfg?.tipoMP) {
            api.get("/pd/homologacao/mps", { params: { tipo_mp: setorCfg.tipoMP, status: "homologada" } })
                .then(({ data }) => setMps(data))
                .catch(() => {});
        }
    }, [open, setor, setorCfg?.tipoMP]);

    const handleMpSelect = (id) => {
        setMpId(id);
        if (id === "__none__") return;
        const mp = mps.find(m => m.id === id);
        if (mp) {
            setForm({ ...form, nome: mp.nome, codigo: mp.codigo_interno || "", unidade: mp.unidade || "kg" });
        }
    };

    const handleSubmit = async () => {
        if (!form.nome.trim()) {
            toast.error("Nome é obrigatório");
            return;
        }
        try {
            const payload = {
                tipo_item: setor === "FABRICA" ? "produto_acabado" : "mp",
                setor,
                nome: form.nome,
                codigo: form.codigo,
                unidade: form.unidade || "un",
                estoque_minimo: parseFloat(form.estoque_minimo) || 0,
                localizacao: form.localizacao,
                localizacao_estruturada: form.localizacao_estruturada,
                lote: form.lote,
                validade: form.validade || null,
                observacoes: form.observacoes,
                mp_id: mpId !== "__none__" ? mpId : null,
                produto_id: null,
            };
            await api.post("/estoque/items", payload);
            toast.success("Item criado!");
            onCreated();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle className="font-heading flex items-center gap-2">
                        <Plus className="h-5 w-5 text-primary" /> Novo Item — {setorCfg?.label}
                    </DialogTitle>
                    <DialogDescription className="text-xs">
                        Saldo inicial = 0. Use "Entrada" para receber quantidade.
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3 py-2">
                    {setor !== "FABRICA" && mps.length > 0 && (
                        <div className="space-y-1">
                            <Label className="text-xs">Vincular a MP Homologada (opcional)</Label>
                            <Select value={mpId} onValueChange={handleMpSelect}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Selecionar MP homologada…" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__none__">— Sem vínculo —</SelectItem>
                                    {mps.map(m => (
                                        <SelectItem key={m.id} value={m.id}>{m.nome} {m.fornecedor_nome && `· ${m.fornecedor_nome}`}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                    <div className="space-y-1">
                        <Label className="text-xs">Nome *</Label>
                        <Input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} data-testid="new-item-nome" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1">
                            <Label className="text-xs">Código</Label>
                            <Input value={form.codigo} onChange={(e) => setForm({ ...form, codigo: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Unidade</Label>
                            <Input value={form.unidade} onChange={(e) => setForm({ ...form, unidade: e.target.value })} placeholder="kg, L, un…" />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Estoque mínimo</Label>
                            <Input type="number" step="0.01" value={form.estoque_minimo} onChange={(e) => setForm({ ...form, estoque_minimo: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Localização (livre)</Label>
                            <Input value={form.localizacao} onChange={(e) => setForm({ ...form, localizacao: e.target.value })} placeholder="Prateleira A-03" />
                        </div>
                        <div className="space-y-1 col-span-2">
                            <Label className="text-xs">Endereço Estruturado <span className="text-muted-foreground">(GAL-B-04-1)</span></Label>
                            <Input
                                value={form.localizacao_estruturada}
                                onChange={(e) => setForm({ ...form, localizacao_estruturada: e.target.value.toUpperCase() })}
                                placeholder="ex: GAL-B-04-1"
                                className="font-mono"
                            />
                            <p className="text-[10px] text-muted-foreground">Formato: GALERIA-CORREDOR-PRATELEIRA-POSIÇÃO</p>
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Lote</Label>
                            <Input value={form.lote} onChange={(e) => setForm({ ...form, lote: e.target.value })} />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Validade</Label>
                            <Input type="date" value={form.validade} onChange={(e) => setForm({ ...form, validade: e.target.value })} />
                        </div>
                    </div>
                    <div className="space-y-1">
                        <Label className="text-xs">Observações</Label>
                        <Textarea rows={2} value={form.observacoes} onChange={(e) => setForm({ ...form, observacoes: e.target.value })} />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
                    <Button onClick={handleSubmit} data-testid="btn-create-item">Criar Item</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function MovDialog({ open, onOpenChange, item, direction, onSuccess }) {
    const [tipo, setTipo] = useState(direction === "entrada" ? "ENTRADA_RECEBIMENTO" : direction === "saida" ? "SAIDA_CONSUMO_OP" : "");
    const [quantidade, setQuantidade] = useState("");
    const [motivo, setMotivo] = useState("");
    const [referencia, setReferencia] = useState("");
    const [documento, setDocumento] = useState("");
    const [setorDestino, setSetorDestino] = useState("");

    useEffect(() => {
        if (open) {
            setTipo(direction === "entrada" ? "ENTRADA_RECEBIMENTO" : direction === "saida" ? "SAIDA_CONSUMO_OP" : "");
            setQuantidade("");
            setMotivo("");
            setReferencia("");
            setDocumento("");
            const outros = SETORES.filter(s => s.key !== item.setor);
            setSetorDestino(outros[0]?.key || "");
        }
    }, [open, direction, item.setor, item.tipo_item]);

    const isAjuste = tipo === "AJUSTE_ENTRADA" || tipo === "AJUSTE_SAIDA";

    const handleSubmit = async () => {
        const qty = parseFloat(quantidade);
        if (!qty || qty <= 0) {
            toast.error("Informe uma quantidade > 0");
            return;
        }
        if (isAjuste && !motivo.trim()) {
            toast.error("Motivo é obrigatório em ajustes manuais.");
            return;
        }

        try {
            if (direction === "transferencia") {
                if (!setorDestino) {
                    toast.error("Selecione o setor destino");
                    return;
                }
                await api.post("/estoque/transferencias", {
                    item_origem_id: item.id,
                    setor_destino: setorDestino,
                    quantidade: qty,
                    motivo,
                });
                toast.success("Transferência registrada.");
            } else {
                await api.post("/estoque/movimentos", {
                    item_id: item.id,
                    tipo,
                    quantidade: qty,
                    motivo,
                    referencia,
                    documento,
                });
                toast.success("Movimento registrado.");
            }
            onSuccess();
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };

    const titulo = direction === "entrada" ? "Entrada" : direction === "saida" ? "Saída" : "Transferência";
    const icon = direction === "entrada" ? <ArrowDown className="h-5 w-5 text-emerald-600" /> : direction === "saida" ? <ArrowUp className="h-5 w-5 text-rose-600" /> : <ArrowLeftRight className="h-5 w-5 text-indigo-600" />;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle className="font-heading flex items-center gap-2">{icon} {titulo} — {item.nome}</DialogTitle>
                    <DialogDescription className="text-xs">
                        Saldo atual: <span className="font-semibold mono-num">{item.quantidade_atual} {item.unidade}</span>
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3 py-2">
                    {direction !== "transferencia" && (
                        <div className="space-y-1">
                            <Label className="text-xs">Tipo de Movimento</Label>
                            <Select value={tipo} onValueChange={setTipo}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {(direction === "entrada" ? MOVS_ENTRADA_MANUAL : MOVS_SAIDA_MANUAL).map(t => (
                                        <SelectItem key={t} value={t}>{TIPO_MOV_LABELS[t]}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                    {direction === "transferencia" && (
                        <div className="space-y-1">
                            <Label className="text-xs">Setor Destino</Label>
                            <Select value={setorDestino} onValueChange={setSetorDestino}>
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {SETORES.filter(s => s.key !== item.setor)
                                        .map(s => <SelectItem key={s.key} value={s.key}>{s.label} ({s.sublabel})</SelectItem>)}
                                </SelectContent>
                            </Select>
                        </div>
                    )}
                    <div className="space-y-1">
                        <Label className="text-xs">Quantidade *</Label>
                        <Input
                            type="number" step="0.001"
                            value={quantidade} onChange={(e) => setQuantidade(e.target.value)}
                            placeholder={`Em ${item.unidade}`}
                            data-testid="mov-qty"
                            autoFocus
                        />
                    </div>
                    <div className="space-y-1">
                        <Label className="text-xs">Motivo {isAjuste && "*"}</Label>
                        <Textarea rows={2} value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder={isAjuste ? "Obrigatório para ajustes" : "Opcional"} />
                    </div>
                    {direction !== "transferencia" && (
                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1">
                                <Label className="text-xs">Referência</Label>
                                <Input value={referencia} onChange={(e) => setReferencia(e.target.value)} placeholder="OP, lote…" />
                            </div>
                            <div className="space-y-1">
                                <Label className="text-xs">Documento</Label>
                                <Input value={documento} onChange={(e) => setDocumento(e.target.value)} placeholder="NF, req…" />
                            </div>
                        </div>
                    )}
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
                    <Button onClick={handleSubmit} data-testid="btn-submit-mov">Registrar {titulo}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
