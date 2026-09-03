import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { BarChart3, Loader2, RefreshCw, ChevronRight, AlertTriangle, Plus, Package, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { useNavigate } from "react-router-dom";

const STATUS_CFG = {
    gerada:               { label: "Gerada",            cls: "bg-slate-100 text-slate-700" },
    em_revisao:           { label: "Em Revisão",        cls: "bg-blue-100 text-blue-700" },
    aprovada:             { label: "Aprovada",          cls: "bg-green-100 text-green-700" },
    parcialmente_aprovada: { label: "Parc. Aprovada",   cls: "bg-yellow-100 text-yellow-700" },
    descartada:           { label: "Descartada",        cls: "bg-red-100 text-red-700" },
};

function StatusBadge({ s }) {
    const cfg = STATUS_CFG[s] || STATUS_CFG.gerada;
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

export default function ComprasMRP() {
    const nav = useNavigate();
    const [rodadas, setRodadas] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [statusFiltro, setStatusFiltro] = useState("all");
    const [calculando, setCalculando] = useState(false);

    // R20 — Necessidades de material
    const [necessidades, setNecessidades] = useState([]);
    const [loadingNec, setLoadingNec] = useState(false);
    const [showNec, setShowNec] = useState(true);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const params = { limit: 50 };
            if (statusFiltro && statusFiltro !== "all") params.status = statusFiltro;
            const { data } = await api.get("/compras/mrp", { params });
            setRodadas(data.rodadas || []);
            setTotal(data.total || 0);
        } catch { toast.error("Erro ao carregar rodadas MRP"); }
        finally { setLoading(false); }
    }, [statusFiltro]);

    const loadNecessidades = useCallback(async () => {
        setLoadingNec(true);
        try {
            const { data } = await api.get("/compras/necessidades");
            setNecessidades(data || []);
        } catch { /* silencioso */ }
        finally { setLoadingNec(false); }
    }, []);

    useEffect(() => { carregar(); }, [carregar]);
    useEffect(() => { loadNecessidades(); }, [loadNecessidades]);

    const calcular = async () => {
        setCalculando(true);
        try {
            const { data } = await api.post("/compras/mrp/calcular", { ops_input: [] });
            toast.success(`Rodada ${data.numero_mrp} criada — ${data.itens_sugeridos?.length ?? 0} itens sugeridos`);
            carregar();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao calcular MRP");
        } finally { setCalculando(false); }
    };

    // Achata todos os materiais de todos os documentos de necessidades
    const todosItens = necessidades.flatMap(doc =>
        (doc.materiais || []).map(m => ({ ...m, proposta_id: doc.proposta_id, gerado_em: doc.gerado_em }))
    );

    return (
        <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold flex items-center gap-2">
                    <BarChart3 className="h-5 w-5 text-primary" /> MRP
                    <span className="text-muted-foreground text-sm font-normal">({total} rodadas)</span>
                </h1>
                <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => { carregar(); loadNecessidades(); }}><RefreshCw className="h-4 w-4" /></Button>
                    <Button size="sm" onClick={calcular} disabled={calculando}>
                        {calculando ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
                        Calcular MRP
                    </Button>
                </div>
            </div>

            {/* ── Painel R20: Necessidades de Material ── */}
            <div className="rounded-lg border overflow-hidden">
                <button
                    className="w-full flex items-center justify-between px-4 py-3 bg-blue-50 hover:bg-blue-100/70 transition-colors text-left"
                    onClick={() => setShowNec(v => !v)}
                >
                    <div className="flex items-center gap-2 text-blue-800">
                        <Package className="h-4 w-4" />
                        <span className="font-semibold text-sm">Necessidades de Material</span>
                        {!loadingNec && (
                            <Badge variant="secondary" className="text-xs">
                                {todosItens.length} {todosItens.length === 1 ? "item" : "itens"}
                            </Badge>
                        )}
                    </div>
                    {showNec ? <ChevronUp className="h-4 w-4 text-blue-600" /> : <ChevronDown className="h-4 w-4 text-blue-600" />}
                </button>
                {showNec && (
                    <div className="overflow-x-auto">
                        {loadingNec ? (
                            <div className="py-8 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
                        ) : todosItens.length === 0 ? (
                            <p className="text-center py-8 text-sm text-muted-foreground">Nenhuma necessidade de material pendente.</p>
                        ) : (
                            <table className="w-full text-xs">
                                <thead className="bg-muted/50 border-b">
                                    <tr>
                                        {["Código Material", "Descrição", "Qtd. Necessária", "Un. Compra", "Pedido", "Gerado em", ""].map(h => (
                                            <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y">
                                    {todosItens.map((m, idx) => (
                                        <tr key={idx} className={m.pendente_info ? "bg-amber-50/60" : "hover:bg-muted/20"}>
                                            <td className="px-3 py-2 font-mono">{m.codigo_material || "—"}</td>
                                            <td className="px-3 py-2">{m.descricao}</td>
                                            <td className="px-3 py-2 text-right tabular-nums font-medium">{m.qtd_necessaria_compra}</td>
                                            <td className="px-3 py-2 text-muted-foreground">{m.unidade_compra}</td>
                                            <td className="px-3 py-2 font-mono text-muted-foreground">{m.proposta_id?.slice(-8) || "—"}</td>
                                            <td className="px-3 py-2 text-muted-foreground">{m.gerado_em?.slice(0, 10) || "—"}</td>
                                            <td className="px-3 py-2">
                                                {m.pendente_info && (
                                                    <span className="flex items-center gap-1 text-amber-600">
                                                        <AlertCircle className="h-3 w-3" /> Incompleto
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                )}
            </div>

            <Select value={statusFiltro} onValueChange={setStatusFiltro}>
                <SelectTrigger className="h-8 w-44 text-xs"><SelectValue placeholder="Status" /></SelectTrigger>
                <SelectContent>
                    <SelectItem value="all">Todos</SelectItem>
                    {Object.entries(STATUS_CFG).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
                </SelectContent>
            </Select>

            <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-xs">
                    <thead className="bg-muted/60 border-b">
                        <tr>
                            <th className="text-left px-3 py-2 font-medium text-muted-foreground">Número</th>
                            <th className="text-left px-3 py-2 font-medium text-muted-foreground">Data</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Status</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Origem</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">OPs</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Disparado por</th>
                            <th className="px-3 py-2" />
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan={7} className="text-center py-10"><Loader2 className="h-5 w-5 animate-spin mx-auto text-muted-foreground" /></td></tr>
                        ) : rodadas.length === 0 ? (
                            <tr><td colSpan={7} className="text-center py-10 text-muted-foreground">Nenhuma rodada MRP encontrada.</td></tr>
                        ) : rodadas.map(r => (
                            <tr key={r.id} className="border-b last:border-0 hover:bg-muted/30 cursor-pointer" onClick={() => nav(`/compras/mrp/${r.id}`)}>
                                <td className="px-3 py-2 font-mono font-medium">{r.numero_mrp}</td>
                                <td className="px-3 py-2 text-muted-foreground">{r.created_at?.slice(0, 10)}</td>
                                <td className="px-3 py-2 text-center"><StatusBadge s={r.status} /></td>
                                <td className="px-3 py-2 text-center text-muted-foreground">{r.origem_demanda || "manual"}</td>
                                <td className="px-3 py-2 text-center">{(r.ops_consideradas || []).length}</td>
                                <td className="px-3 py-2 text-center text-muted-foreground">{r.disparado_por_nome}</td>
                                <td className="px-3 py-2"><ChevronRight className="h-4 w-4 text-muted-foreground" /></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
