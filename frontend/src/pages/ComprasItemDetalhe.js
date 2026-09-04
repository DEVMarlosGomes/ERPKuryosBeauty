import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ArrowLeft, Loader2, Plus, TrendingUp, TrendingDown } from "lucide-react";
import { CurrencyInput, fmtCurrency } from "@/components/ui/CurrencyInput";
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const CORES = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"];
const FRETES = ["cif", "fob", "valor_fixo", "percentual"];

function NovaCotacaoDialog({ open, itemId, onClose, onCreated }) {
    const [form, setForm] = useState({ fornecedor_id: "", preco_unitario: "", preco_unitario_currency: "BRL", prazo_pagamento_texto: "30 DDL", prazo_pagamento_dias: 30, prazo_entrega_dias_uteis: 7, moq: 1, frete_tipo: "cif", frete_valor: 0, valido_ate: "" });
    const [fornecedores, setFornecedores] = useState([]);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open) return;
        api.get("/compras/fornecedores", { params: { limit: 200 } }).then(r => setFornecedores(r.data?.fornecedores || []));
    }, [open]);

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
    const salvar = async () => {
        if (!form.fornecedor_id || !form.preco_unitario) { toast.error("Fornecedor e preço são obrigatórios"); return; }
        setSaving(true);
        try {
            const body = { ...form, preco_unitario: parseFloat(form.preco_unitario), prazo_pagamento_dias: parseInt(form.prazo_pagamento_dias), prazo_entrega_dias_uteis: parseInt(form.prazo_entrega_dias_uteis), moq: parseFloat(form.moq), frete_valor: parseFloat(form.frete_valor || 0) };
            await api.post(`/compras/itens/${itemId}/cotar`, body);
            toast.success("Cotação registrada");
            onCreated(); onClose();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao registrar cotação"); }
        finally { setSaving(false); }
    };

    return (
        <Dialog open={open} onOpenChange={onClose}>
            <DialogContent className="max-w-lg">
                <DialogHeader><DialogTitle>Registrar Cotação</DialogTitle></DialogHeader>
                <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2">
                        <Label className="text-xs">Fornecedor *</Label>
                        <Select value={form.fornecedor_id} onValueChange={v => set("fornecedor_id", v)}>
                            <SelectTrigger className="h-8 text-sm mt-1"><SelectValue placeholder="Selecionar..." /></SelectTrigger>
                            <SelectContent>{fornecedores.map(f => <SelectItem key={f.id} value={f.id}>{f.codigo_interno} — {f.razao_social}</SelectItem>)}</SelectContent>
                        </Select>
                    </div>
                    <div>
                        <Label className="text-xs">Preço Unitário *</Label>
                        <CurrencyInput
                            value={form.preco_unitario}
                            currency={form.preco_unitario_currency}
                            onValueChange={v => set("preco_unitario", v)}
                            onCurrencyChange={c => set("preco_unitario_currency", c)}
                            size="sm"
                            className="mt-1"
                        />
                    </div>
                    <div>
                        <Label className="text-xs">MOQ</Label>
                        <Input type="number" className="h-8 text-sm mt-1" value={form.moq} onChange={e => set("moq", e.target.value)} />
                    </div>
                    <div>
                        <Label className="text-xs">Prazo Pagamento</Label>
                        <Input className="h-8 text-sm mt-1" value={form.prazo_pagamento_texto} onChange={e => set("prazo_pagamento_texto", e.target.value)} />
                    </div>
                    <div>
                        <Label className="text-xs">Prazo Pagamento (dias)</Label>
                        <Input type="number" className="h-8 text-sm mt-1" value={form.prazo_pagamento_dias} onChange={e => set("prazo_pagamento_dias", e.target.value)} />
                    </div>
                    <div>
                        <Label className="text-xs">Prazo Entrega (dias úteis)</Label>
                        <Input type="number" className="h-8 text-sm mt-1" value={form.prazo_entrega_dias_uteis} onChange={e => set("prazo_entrega_dias_uteis", e.target.value)} />
                    </div>
                    <div>
                        <Label className="text-xs">Frete</Label>
                        <Select value={form.frete_tipo} onValueChange={v => set("frete_tipo", v)}>
                            <SelectTrigger className="h-8 text-sm mt-1"><SelectValue /></SelectTrigger>
                            <SelectContent>{FRETES.map(f => <SelectItem key={f} value={f}>{f.toUpperCase()}</SelectItem>)}</SelectContent>
                        </Select>
                    </div>
                    <div>
                        <Label className="text-xs">Válida até</Label>
                        <Input type="date" className="h-8 text-sm mt-1" value={form.valido_ate} onChange={e => set("valido_ate", e.target.value)} />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" size="sm" onClick={onClose}>Cancelar</Button>
                    <Button size="sm" onClick={salvar} disabled={saving}>{saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Registrar</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default function ComprasItemDetalhe() {
    const { id } = useParams();
    const nav = useNavigate();
    const [item, setItem] = useState(null);
    const [hist, setHist] = useState(null);
    const [loading, setLoading] = useState(true);
    const [cotacaoOpen, setCotacaoOpen] = useState(false);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const [itemRes, histRes] = await Promise.all([
                api.get(`/compras/itens/${id}`),
                api.get(`/compras/itens/${id}/historico-precos`),
            ]);
            setItem(itemRes.data);
            setHist(histRes.data);
        } catch { toast.error("Erro ao carregar item"); }
        finally { setLoading(false); }
    }, [id]);

    useEffect(() => { carregar(); }, [carregar]);

    // Preparar dados para o gráfico de linhas
    const chartData = (() => {
        if (!hist?.historico?.length) return [];
        // Agrupar por data, uma série por fornecedor
        const byDate = {};
        const fornNames = {};
        hist.historico.forEach(c => {
            const dt = c.created_at?.slice(0, 10) || "";
            if (!byDate[dt]) byDate[dt] = {};
            byDate[dt][c.fornecedor_id] = c.preco_unitario;
            fornNames[c.fornecedor_id] = c.fornecedor_nome || c.fornecedor_id;
        });
        const dates = Object.keys(byDate).sort();
        return { points: dates.map(d => ({ data: d, ...byDate[d] })), fornIds: Object.keys(fornNames), fornNames };
    })();

    if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>;
    if (!item) return <div className="p-6 text-muted-foreground">Item não encontrado.</div>;

    const { points = [], fornIds = [], fornNames = {} } = chartData || {};

    return (
        <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-5">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={() => nav("/compras/itens")}><ArrowLeft className="h-4 w-4" /></Button>
                <div className="flex-1">
                    <h1 className="text-lg font-bold">{item.descricao}</h1>
                    <div className="text-sm text-muted-foreground">{item.codigo_interno} · {item.categoria} · {item.unidade_compra}</div>
                </div>
                <Button size="sm" onClick={() => setCotacaoOpen(true)}><Plus className="h-4 w-4 mr-1" /> Registrar Cotação</Button>
            </div>

            {/* Dados do item */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                    ["Estoque Mínimo", item.estoque_minimo != null ? `${item.estoque_minimo} ${item.unidade_compra}` : "—"],
                    ["Estoque Segurança", `${item.estoque_seguranca ?? 0} ${item.unidade_compra}`],
                    ["Lead Time", `${item.lead_time_dias ?? 0} dias`],
                    ["Último Preço Pago", hist?.ultimo_preco_pago != null ? hist.ultimo_preco_pago.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "—"],
                ].map(([label, val]) => (
                    <div key={label} className="bg-muted/40 rounded-lg p-3 text-center">
                        <div className="text-base font-bold">{val}</div>
                        <div className="text-xs text-muted-foreground">{label}</div>
                    </div>
                ))}
            </div>

            {/* Gráfico histórico de preços */}
            {points.length > 1 && (
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Histórico de Preços por Fornecedor</CardTitle></CardHeader>
                    <CardContent>
                        <ResponsiveContainer width="100%" height={220}>
                            <LineChart data={points} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                                <XAxis dataKey="data" tick={{ fontSize: 10 }} />
                                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `R$${v}`} />
                                <Tooltip
                                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                                    formatter={(v, name) => [`R$ ${Number(v).toFixed(4)}`, fornNames[name] || name]}
                                />
                                <Legend formatter={name => fornNames[name] || name} />
                                {fornIds.map((fid, i) => (
                                    <Line key={fid} type="monotone" dataKey={fid} stroke={CORES[i % CORES.length]}
                                        strokeWidth={2} dot={{ r: 3 }} connectNulls />
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>
            )}

            {/* Comparativo de fornecedores */}
            {hist?.comparativo_fornecedores?.length > 0 && (
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Comparativo de Fornecedores (melhor preço primeiro)</CardTitle></CardHeader>
                    <CardContent>
                        <table className="w-full text-xs">
                            <thead className="border-b">
                                <tr>
                                    <th className="text-left py-1.5 font-medium text-muted-foreground">Fornecedor</th>
                                    <th className="text-right py-1.5 font-medium text-muted-foreground">Último Preço</th>
                                    <th className="text-right py-1.5 font-medium text-muted-foreground">Prazo Entrega</th>
                                    <th className="text-right py-1.5 font-medium text-muted-foreground">MOQ</th>
                                    <th className="text-center py-1.5 font-medium text-muted-foreground">Válida até</th>
                                    <th className="text-center py-1.5 font-medium text-muted-foreground">Homolog.</th>
                                </tr>
                            </thead>
                            <tbody>
                                {hist.comparativo_fornecedores.map((f, i) => (
                                    <tr key={f.fornecedor_id} className="border-b last:border-0">
                                        <td className="py-2">
                                            {i === 0 && <span className="text-green-600 mr-1">★</span>}
                                            {f.fornecedor_nome || f.fornecedor_codigo}
                                        </td>
                                        <td className="py-2 text-right font-mono font-medium">
                                            {f.ultimo_preco != null ? `R$ ${Number(f.ultimo_preco).toFixed(4)}` : "—"}
                                        </td>
                                        <td className="py-2 text-right">{f.prazo_entrega_dias_uteis ?? "—"}d</td>
                                        <td className="py-2 text-right">{f.moq ?? "—"}</td>
                                        <td className="py-2 text-center">
                                            {f.valido_ate
                                                ? <span className={f.vencida ? "text-red-600" : ""}>{f.valido_ate}</span>
                                                : "—"}
                                        </td>
                                        <td className="py-2 text-center">
                                            <span className={`text-xs ${f.status_homologacao === "homologado" ? "text-green-600" : "text-orange-500"}`}>
                                                {f.status_homologacao === "homologado" ? "✓" : "⚠"}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </CardContent>
                </Card>
            )}

            {/* Histórico completo */}
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center justify-between">
                        Histórico de Cotações ({hist?.total_cotacoes ?? 0})
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="space-y-1.5 max-h-60 overflow-y-auto">
                        {(hist?.historico || []).map((c, i) => (
                            <div key={i} className="flex items-center gap-3 text-xs border-b last:border-0 pb-1.5">
                                <span className="text-muted-foreground font-mono w-20 flex-shrink-0">{c.created_at?.slice(0, 10)}</span>
                                <span className="text-muted-foreground flex-1">{c.fornecedor_nome}</span>
                                <span className="font-mono font-medium">{fmtCurrency(c.preco_unitario, c.preco_unitario_currency || "BRL")}</span>
                                {c.variacao_pct != null && (
                                    <span className={`flex items-center gap-0.5 ${c.variacao_pct > 0 ? "text-red-600" : "text-green-600"}`}>
                                        {c.variacao_pct > 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                                        {Math.abs(c.variacao_pct).toFixed(1)}%
                                    </span>
                                )}
                                <span className="text-muted-foreground">{c.prazo_entrega_dias_uteis}d · {c.frete_tipo?.toUpperCase()}</span>
                            </div>
                        ))}
                    </div>
                </CardContent>
            </Card>

            <NovaCotacaoDialog open={cotacaoOpen} itemId={id} onClose={() => setCotacaoOpen(false)} onCreated={carregar} />
        </div>
    );
}
