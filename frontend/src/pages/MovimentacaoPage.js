import { useState, useEffect, useCallback, useMemo } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
    TrendingUp, TrendingDown, ArrowLeftRight, AlertTriangle, RefreshCw,
    Download, Printer, Package, FlaskConical, ChevronDown, ChevronRight, Loader2,
} from "lucide-react";
import {
    ResponsiveContainer, LineChart, Line, BarChart, Bar,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtDate(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleDateString("pt-BR"); } catch { return iso; }
}

function fmtDateTime(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("pt-BR"); } catch { return iso; }
}

function fmtQtd(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

// Agrupa movimentos por data (YYYY-MM-DD) para o gráfico de linha
function buildTimeSeries(movimentos) {
    const map = {};
    for (const m of movimentos) {
        const day = (m.created_at || m.data || "").slice(0, 10);
        if (!day) continue;
        if (!map[day]) map[day] = { date: day, entradas: 0, saidas: 0 };
        const q = Number(m.quantidade || 0);
        if (m.tipo === "entrada" || m.tipo === "ENTRADA_RECEBIMENTO" || m.tipo === "AJUSTE_ENTRADA" || m.tipo === "TRANSFERENCIA_ENTRADA")
            map[day].entradas += q;
        else
            map[day].saidas += q;
    }
    return Object.values(map).sort((a, b) => a.date.localeCompare(b.date)).map(d => ({
        ...d,
        date: d.date.split("-").reverse().slice(0, 2).join("/"),
        entradas: Math.round(d.entradas * 1000) / 1000,
        saidas: Math.round(d.saidas * 1000) / 1000,
    }));
}

// Top 10 itens por volume movimentado
function buildTopItems(movimentos) {
    const map = {};
    for (const m of movimentos) {
        const key = m.item_nome || m.item_id || m.stock_item_id || "?";
        if (!map[key]) map[key] = { nome: key, total: 0 };
        map[key].total += Number(m.quantidade || 0);
    }
    return Object.values(map)
        .sort((a, b) => b.total - a.total)
        .slice(0, 10)
        .map(d => ({ ...d, total: Math.round(d.total * 1000) / 1000 }));
}

// Exporta para CSV com BOM UTF-8 (abre corretamente no Excel)
function exportCSV(movimentos, deposito) {
    const headers = ["Data/Hora", "Depósito", "Item", "Código", "Tipo", "Quantidade", "Usuário", "Observação"];
    const rows = movimentos.map(m => [
        fmtDateTime(m.created_at || m.data),
        m.deposito === "lab" ? "Estoque Lab" : "Estoque Geral",
        m.item_nome || m.nome || "",
        m.item_codigo || m.codigo_interno || "",
        m.tipo || "",
        m.quantidade ?? "",
        m.user_name || m.criado_por_nome || "",
        m.motivo || m.observacao || "",
    ]);
    const csv = [headers, ...rows].map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
    const bom = "﻿";
    const blob = new Blob([bom + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `movimentacao_estoque_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ─── constants ────────────────────────────────────────────────────────────────

const TIPO_LABELS = {
    entrada: "Entrada",
    saida: "Saída",
    ajuste: "Ajuste",
    ENTRADA_RECEBIMENTO: "Entrada (Recebimento/CQ)",
    SAIDA_CONSUMO_OP: "Saída — Consumo OP",
    SAIDA_EXPEDICAO: "Saída — Expedição",
    AJUSTE_ENTRADA: "Ajuste +",
    AJUSTE_SAIDA: "Ajuste −",
    AMOSTRA: "Amostra CQ",
    TRANSFERENCIA_ENTRADA: "Transf. (Entrada)",
    TRANSFERENCIA_SAIDA: "Transf. (Saída)",
};

function isTipoEntrada(tipo) {
    return ["entrada", "ENTRADA_RECEBIMENTO", "AJUSTE_ENTRADA", "TRANSFERENCIA_ENTRADA"].includes(tipo);
}

function TipoBadge({ tipo }) {
    const entrada = isTipoEntrada(tipo);
    return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
            entrada
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/45 dark:text-emerald-300"
                : "bg-red-100 text-red-700 dark:bg-red-950/45 dark:text-red-300"
        }`}>
            {entrada ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
            {TIPO_LABELS[tipo] || tipo}
        </span>
    );
}

// ─── main component ───────────────────────────────────────────────────────────

export default function MovimentacaoPage() {
    // Filtros
    const [deposito, setDeposito] = useState("all");
    const [tipoFiltro, setTipoFiltro] = useState("all");
    const [dataInicio, setDataInicio] = useState(() => {
        const d = new Date();
        d.setDate(d.getDate() - 30);
        return d.toISOString().slice(0, 10);
    });
    const [dataFim, setDataFim] = useState(() => new Date().toISOString().slice(0, 10));
    const [busca, setBusca] = useState("");

    // Dados
    const [labMovs, setLabMovs] = useState([]);
    const [geralMovs, setGeralMovs] = useState([]);
    const [labKpis, setLabKpis] = useState(null);
    const [geralItems, setGeralItems] = useState([]);
    const [loading, setLoading] = useState(false);

    // UI
    const [drillItem, setDrillItem] = useState(null);

    // ── Fetch ───────────────────────────────────────────────────────────────

    const fetchLab = useCallback(async () => {
        const params = { data_inicio: dataInicio, data_fim: dataFim, limit: 2000 };
        if (tipoFiltro !== "all") params.tipo = tipoFiltro;
        const { data } = await api.get("/pd/stock/movements", { params });
        setLabMovs((data.movimentos || []).map(m => ({ ...m, deposito: "lab" })));
        setLabKpis(data.kpis || null);
    }, [dataInicio, dataFim, tipoFiltro]);

    const fetchGeral = useCallback(async () => {
        const params = { limit: 2000 };
        if (dataInicio) params.data_inicio = dataInicio;
        if (dataFim) params.data_fim = dataFim + "T23:59:59";
        if (tipoFiltro !== "all") params.tipo = tipoFiltro;
        const { data } = await api.get("/estoque/movimentos", { params });
        setGeralMovs((Array.isArray(data) ? data : []).map(m => ({ ...m, deposito: "geral" })));
        // Buscar itens para enriquecer (nome, código)
        const itemsRes = await api.get("/estoque/items", { params: { limit: 5000 } }).catch(() => ({ data: [] }));
        setGeralItems(Array.isArray(itemsRes.data) ? itemsRes.data : []);
    }, [dataInicio, dataFim, tipoFiltro]);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const calls = [];
            if (deposito === "all" || deposito === "lab") calls.push(fetchLab());
            else calls.push(Promise.resolve());
            if (deposito === "all" || deposito === "geral") calls.push(fetchGeral());
            else calls.push(Promise.resolve());
            await Promise.all(calls);
        } catch (e) {
            toast.error("Erro ao carregar movimentações");
        } finally {
            setLoading(false);
        }
    }, [deposito, fetchLab, fetchGeral]);

    useEffect(() => { load(); }, [load]);

    // ── Dados combinados ────────────────────────────────────────────────────

    const geralItemsMap = useMemo(() => {
        const m = {};
        for (const i of geralItems) m[i.id] = i;
        return m;
    }, [geralItems]);

    const geralMovsEnriched = useMemo(() => geralMovs.map(m => ({
        ...m,
        item_nome: geralItemsMap[m.item_id]?.nome || m.item_nome || "",
        item_codigo: geralItemsMap[m.item_id]?.codigo_interno || "",
    })), [geralMovs, geralItemsMap]);

    const allMovimentos = useMemo(() => {
        const lab = deposito !== "geral" ? labMovs : [];
        const geral = deposito !== "lab" ? geralMovsEnriched : [];
        return [...lab, ...geral];
    }, [labMovs, geralMovsEnriched, deposito]);

    const filtered = useMemo(() => {
        if (!busca.trim()) return allMovimentos;
        const q = busca.toLowerCase();
        return allMovimentos.filter(m =>
            (m.item_nome || "").toLowerCase().includes(q) ||
            (m.item_codigo || "").toLowerCase().includes(q) ||
            (m.tipo || "").toLowerCase().includes(q)
        );
    }, [allMovimentos, busca]);

    // ── KPIs ────────────────────────────────────────────────────────────────

    const kpis = useMemo(() => {
        const entradas = filtered.filter(m => isTipoEntrada(m.tipo)).reduce((s, m) => s + Number(m.quantidade || 0), 0);
        const saidas = filtered.filter(m => !isTipoEntrada(m.tipo)).reduce((s, m) => s + Number(m.quantidade || 0), 0);
        const abaixoMinimo = (labKpis?.itens_abaixo_minimo || 0);
        return { entradas, saidas, saldo: entradas - saidas, abaixoMinimo };
    }, [filtered, labKpis]);

    const timeSeries = useMemo(() => buildTimeSeries(filtered), [filtered]);
    const topItems = useMemo(() => buildTopItems(filtered), [filtered]);

    // ── Drill-down por item ─────────────────────────────────────────────────

    const drillMovs = useMemo(() => {
        if (!drillItem) return [];
        return filtered.filter(m => (m.item_nome || m.item_id) === drillItem);
    }, [filtered, drillItem]);

    const chartTheme = {
        grid: "hsl(var(--border))",
        tick: { fontSize: 10, fill: "hsl(var(--muted-foreground))" },
        tooltip: {
            backgroundColor: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 8,
            color: "hsl(var(--popover-foreground))",
            boxShadow: "var(--shadow-soft)",
        },
    };

    return (
        <div className="p-4 md:p-6 space-y-5 max-w-7xl mx-auto print:p-2">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h1 className="text-2xl font-bold flex items-center gap-2">
                        <ArrowLeftRight className="h-6 w-6 text-primary" /> Movimentação de Estoque
                    </h1>
                    <p className="text-sm text-muted-foreground mt-0.5">Estoque Geral e Lab — entradas, saídas e saldo</p>
                </div>
                <div className="flex gap-2 print:hidden">
                    <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => exportCSV(filtered, deposito)}>
                        <Download className="h-4 w-4 mr-1" /> CSV
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => window.print()}>
                        <Printer className="h-4 w-4 mr-1" /> PDF
                    </Button>
                </div>
            </div>

            {/* Filtros */}
            <Card className="print:hidden">
                <CardContent className="p-4">
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                        <div className="space-y-1">
                            <Label className="text-xs">Data início</Label>
                            <Input type="date" value={dataInicio} onChange={e => setDataInicio(e.target.value)} className="h-8 text-xs" />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Data fim</Label>
                            <Input type="date" value={dataFim} onChange={e => setDataFim(e.target.value)} className="h-8 text-xs" />
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Depósito</Label>
                            <Select value={deposito} onValueChange={setDeposito}>
                                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Todos</SelectItem>
                                    <SelectItem value="lab">Estoque Lab</SelectItem>
                                    <SelectItem value="geral">Estoque Geral</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1">
                            <Label className="text-xs">Tipo</Label>
                            <Select value={tipoFiltro} onValueChange={setTipoFiltro}>
                                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="all">Todos</SelectItem>
                                    <SelectItem value="entrada">Entradas</SelectItem>
                                    <SelectItem value="saida">Saídas</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-1 lg:col-span-2">
                            <Label className="text-xs">Buscar item</Label>
                            <Input
                                placeholder="Nome ou código..."
                                value={busca}
                                onChange={e => setBusca(e.target.value)}
                                className="h-8 text-xs"
                            />
                        </div>
                    </div>
                </CardContent>
            </Card>

            {/* KPIs */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                    {
                        label: "Total Entradas",
                        value: fmtQtd(kpis.entradas),
                        icon: TrendingUp,
                        color: "text-emerald-600 dark:text-emerald-300",
                        bg: "border-emerald-200 bg-emerald-50 dark:border-emerald-900/60 dark:bg-emerald-950/30",
                        iconBg: "bg-white/75 dark:bg-emerald-400/10",
                    },
                    {
                        label: "Total Saídas",
                        value: fmtQtd(kpis.saidas),
                        icon: TrendingDown,
                        color: "text-red-500 dark:text-red-300",
                        bg: "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/30",
                        iconBg: "bg-white/75 dark:bg-red-400/10",
                    },
                    {
                        label: "Saldo Líquido",
                        value: fmtQtd(kpis.saldo),
                        icon: ArrowLeftRight,
                        color: kpis.saldo >= 0 ? "text-blue-600 dark:text-blue-300" : "text-red-600 dark:text-red-300",
                        bg: "border-blue-200 bg-blue-50 dark:border-blue-900/60 dark:bg-blue-950/30",
                        iconBg: "bg-white/75 dark:bg-blue-400/10",
                    },
                    {
                        label: "Abaixo do Mínimo (Lab)",
                        value: kpis.abaixoMinimo,
                        icon: AlertTriangle,
                        color: "text-amber-600 dark:text-amber-300",
                        bg: "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/30",
                        iconBg: "bg-white/75 dark:bg-amber-400/10",
                    },
                ].map(({ label, value, icon: Icon, color, bg, iconBg }) => (
                    <Card key={label} className={`border ${bg}`}>
                        <CardContent className="p-4 flex items-center gap-3">
                            <div className={`p-2 rounded-lg ${iconBg} ${color}`}>
                                <Icon className="h-5 w-5" />
                            </div>
                            <div>
                                <p className="text-xs text-muted-foreground">{label}</p>
                                <p className={`text-xl font-bold ${color}`}>{value}</p>
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </div>

            {/* Gráficos */}
            {timeSeries.length > 1 && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 print:grid-cols-2">
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm">Entradas × Saídas no Tempo</CardTitle>
                        </CardHeader>
                        <CardContent className="p-3">
                            <ResponsiveContainer width="100%" height={200}>
                                <LineChart data={timeSeries} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
                                    <XAxis dataKey="date" tick={chartTheme.tick} />
                                    <YAxis tick={chartTheme.tick} width={40} />
                                    <Tooltip formatter={(v) => fmtQtd(v)} contentStyle={chartTheme.tooltip} cursor={{ stroke: "hsl(var(--muted-foreground) / 0.25)" }} />
                                    <Legend wrapperStyle={{ fontSize: 11, color: "hsl(var(--muted-foreground))" }} />
                                    <Line type="monotone" dataKey="entradas" stroke="#10b981" strokeWidth={2} dot={false} name="Entradas" />
                                    <Line type="monotone" dataKey="saidas"   stroke="#ef4444" strokeWidth={2} dot={false} name="Saídas" />
                                </LineChart>
                            </ResponsiveContainer>
                        </CardContent>
                    </Card>

                    {topItems.length > 0 && (
                        <Card>
                            <CardHeader className="pb-2">
                                <CardTitle className="text-sm">Top Itens por Volume</CardTitle>
                            </CardHeader>
                            <CardContent className="p-3">
                                <ResponsiveContainer width="100%" height={200}>
                                    <BarChart data={topItems} layout="vertical" margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
                                        <XAxis type="number" tick={chartTheme.tick} />
                                        <YAxis dataKey="nome" type="category" tick={{ ...chartTheme.tick, fontSize: 9 }} width={100} />
                                        <Tooltip formatter={(v) => fmtQtd(v)} contentStyle={chartTheme.tooltip} cursor={{ fill: "hsl(var(--muted) / 0.35)" }} />
                                        <Bar dataKey="total" fill="#6366f1" name="Volume total" radius={[0, 3, 3, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </CardContent>
                        </Card>
                    )}
                </div>
            )}

            {/* Tabela de movimentações */}
            <Card>
                <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                        <CardTitle className="text-sm">
                            Movimentações {drillItem ? `— ${drillItem}` : ""}
                            <Badge variant="secondary" className="ml-2 text-xs">{(drillItem ? drillMovs : filtered).length}</Badge>
                        </CardTitle>
                        {drillItem && (
                            <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => setDrillItem(null)}>
                                ← Todos os itens
                            </Button>
                        )}
                    </div>
                </CardHeader>
                <CardContent className="p-0">
                    <div className="overflow-x-auto">
                        {loading ? (
                            <div className="py-12 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
                        ) : (drillItem ? drillMovs : filtered).length === 0 ? (
                            <p className="text-center py-10 text-sm text-muted-foreground">
                                Nenhuma movimentação no período / filtro selecionado.
                            </p>
                        ) : (
                            <table className="w-full text-xs">
                                <thead className="bg-muted/50 border-b">
                                    <tr>
                                        {["Data/Hora", "Depósito", "Item", "Cód.", "Tipo", "Quantidade", "Usuário"].map(h => (
                                            <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground whitespace-nowrap">{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y">
                                    {(drillItem ? drillMovs : filtered).map((m, idx) => (
                                        <tr
                                            key={idx}
                                            className="hover:bg-muted/30 cursor-pointer"
                                            onClick={() => !drillItem && setDrillItem(m.item_nome || m.item_id)}
                                        >
                                            <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{fmtDateTime(m.created_at || m.data)}</td>
                                            <td className="px-3 py-2">
                                                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                                    m.deposito === "lab"
                                                        ? "bg-violet-100 text-violet-700 dark:bg-violet-950/45 dark:text-violet-300"
                                                        : "bg-blue-100 text-blue-700 dark:bg-blue-950/45 dark:text-blue-300"
                                                }`}>
                                                    {m.deposito === "lab" ? <FlaskConical className="h-2.5 w-2.5" /> : <Package className="h-2.5 w-2.5" />}
                                                    {m.deposito === "lab" ? "Lab" : "Geral"}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2 max-w-[180px] truncate font-medium">{m.item_nome || "—"}</td>
                                            <td className="px-3 py-2 font-mono text-muted-foreground">{m.item_codigo || "—"}</td>
                                            <td className="px-3 py-2"><TipoBadge tipo={m.tipo} /></td>
                                            <td className="px-3 py-2 tabular-nums font-medium text-right">
                                                <span className={isTipoEntrada(m.tipo) ? "text-emerald-600 dark:text-emerald-300" : "text-red-500 dark:text-red-300"}>
                                                    {isTipoEntrada(m.tipo) ? "+" : "−"}{fmtQtd(m.quantidade)}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2 text-muted-foreground">{m.user_name || m.criado_por_nome || "—"}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
