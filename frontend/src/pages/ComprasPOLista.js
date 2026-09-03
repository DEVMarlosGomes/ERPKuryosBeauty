import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ShoppingCart, Loader2, RefreshCw, ChevronRight, AlertTriangle, Plus } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

const STATUS_CFG = {
    rascunho:               { label: "Rascunho",         cls: "bg-slate-100 text-slate-700" },
    emitida:                { label: "Emitida",          cls: "bg-blue-100 text-blue-700" },
    confirmada:             { label: "Confirmada",       cls: "bg-indigo-100 text-indigo-700" },
    parcialmente_recebida:  { label: "Parc. Recebida",   cls: "bg-yellow-100 text-yellow-700" },
    recebida:               { label: "Recebida",         cls: "bg-green-100 text-green-700" },
    encerrada:              { label: "Encerrada",        cls: "bg-emerald-100 text-emerald-700" },
    cancelada:              { label: "Cancelada",        cls: "bg-red-100 text-red-700" },
};

function StatusBadge({ s }) {
    const cfg = STATUS_CFG[s] || STATUS_CFG.rascunho;
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

function fmtBRL(n) { return (n ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }

export default function ComprasPOLista() {
    const nav = useNavigate();
    const [searchParams] = useSearchParams();
    const [pos, setPos] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [statusFiltro, setStatusFiltro] = useState(searchParams.get("status") || "all");
    const [urgenteOnly, setUrgenteOnly] = useState(false);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const params = { limit: 100 };
            if (statusFiltro && statusFiltro !== "all") params.status = statusFiltro;
            if (urgenteOnly) params.urgente = true;
            const { data } = await api.get("/compras/pos", { params });
            setPos(data.pos || []);
            setTotal(data.total || 0);
        } catch { toast.error("Erro ao carregar POs"); }
        finally { setLoading(false); }
    }, [statusFiltro, urgenteOnly]);

    useEffect(() => { carregar(); }, [carregar]);

    return (
        <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold flex items-center gap-2">
                    <ShoppingCart className="h-5 w-5 text-primary" /> Pedidos de Compra
                    <span className="text-muted-foreground text-sm font-normal">({total})</span>
                </h1>
                <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={carregar}><RefreshCw className="h-4 w-4" /></Button>
                    <Button size="sm" data-testid="btn-nova-po" onClick={() => nav("/compras/mrp")}><Plus className="h-4 w-4 mr-1" /> Gerar via MRP</Button>
                </div>
            </div>

            <div className="flex flex-wrap gap-2">
                <Select value={statusFiltro} onValueChange={setStatusFiltro}>
                    <SelectTrigger className="h-8 w-44 text-xs"><SelectValue placeholder="Status" /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">Todos</SelectItem>
                        {Object.entries(STATUS_CFG).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
                    </SelectContent>
                </Select>
                <button
                    className={`h-8 px-3 text-xs rounded-md border transition ${urgenteOnly ? "bg-red-100 border-red-400 text-red-700 font-medium" : "border-border text-muted-foreground hover:bg-muted"}`}
                    onClick={() => setUrgenteOnly(v => !v)}>
                    Só urgentes
                </button>
            </div>

            <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-xs">
                    <thead className="bg-muted/60 border-b">
                        <tr>
                            <th className="text-left px-3 py-2 font-medium text-muted-foreground">Número PO</th>
                            <th className="text-left px-3 py-2 font-medium text-muted-foreground">Fornecedor</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Status</th>
                            <th className="text-right px-3 py-2 font-medium text-muted-foreground">Valor Total</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Emissão</th>
                            <th className="text-center px-3 py-2 font-medium text-muted-foreground">Entrega</th>
                            <th className="px-3 py-2" />
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan={7} className="text-center py-10"><Loader2 className="h-5 w-5 animate-spin mx-auto text-muted-foreground" /></td></tr>
                        ) : pos.length === 0 ? (
                            <tr><td colSpan={7} className="text-center py-10 text-muted-foreground">Nenhuma PO encontrada.</td></tr>
                        ) : pos.map(p => (
                            <tr key={p.id} data-testid={`po-row-${p.id}`} data-status={p.status} data-urgente={p.urgente}
                                className={`border-b last:border-0 hover:bg-muted/30 cursor-pointer ${p.urgente ? "bg-red-50/40" : ""}`}
                                onClick={() => nav(`/compras/pos/${p.id}`)}>
                                <td className="px-3 py-2 font-mono font-medium">
                                    <div className="flex items-center gap-1">
                                        {p.urgente && <AlertTriangle className="h-3 w-3 text-red-600" />}
                                        {p.numero_po || "(rascunho)"}
                                    </div>
                                </td>
                                <td className="px-3 py-2">{p.fornecedor_nome}</td>
                                <td className="px-3 py-2 text-center"><StatusBadge s={p.status} /></td>
                                <td className="px-3 py-2 text-right font-mono">{fmtBRL(p.valor_total_po)}</td>
                                <td className="px-3 py-2 text-center text-muted-foreground">{p.data_emissao?.slice(0, 10) || "—"}</td>
                                <td className="px-3 py-2 text-center">
                                    <span className={p.urgente ? "text-red-600 font-medium" : "text-muted-foreground"}>
                                        {p.data_entrega_confirmada || p.data_entrega_solicitada || "—"}
                                    </span>
                                </td>
                                <td className="px-3 py-2"><ChevronRight className="h-4 w-4 text-muted-foreground" /></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
