import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { ArrowLeft, Loader2, Plus, ShoppingCart } from "lucide-react";
import { CurrencyInput, fmtCurrency } from "@/components/ui/CurrencyInput";

const FRETES = ["cif", "fob", "valor_fixo", "percentual"];

export default function ComprasCotacao() {
    const { demanda_id } = useParams();
    const nav = useNavigate();
    const [demanda, setDemanda] = useState(null);
    const [item, setItem] = useState(null);
    const [hist, setHist] = useState(null);
    const [fornecedores, setFornecedores] = useState([]);
    const [loading, setLoading] = useState(true);
    const [form, setForm] = useState({ fornecedor_id: "", preco_unitario: "", preco_unitario_currency: "BRL", prazo_pagamento_texto: "30 DDL", prazo_pagamento_dias: 30, prazo_entrega_dias_uteis: 7, moq: 1, frete_tipo: "cif", frete_valor: 0, frete_valor_currency: "BRL", valido_ate: "" });
    const [saving, setSaving] = useState(false);
    const [criandoPO, setCriandoPO] = useState(false);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const [dRes, fornRes] = await Promise.all([
                api.get(`/compras/demandas/${demanda_id}`).catch(() => ({ data: null })),
                api.get("/compras/fornecedores", { params: { limit: 200 } }),
            ]);
            const d = dRes.data;
            setDemanda(d);
            setFornecedores(fornRes.data?.fornecedores || []);
            if (d?.item_id) {
                const [iRes, hRes] = await Promise.all([
                    api.get(`/compras/itens/${d.item_id}`),
                    api.get(`/compras/itens/${d.item_id}/historico-precos`),
                ]);
                setItem(iRes.data);
                setHist(hRes.data);
                // Pré-preencher fornecedor se demanda tem preferencial
                if (d.fornecedor_selecionado_id) setForm(f => ({ ...f, fornecedor_id: d.fornecedor_selecionado_id }));
            }
        } catch { toast.error("Erro ao carregar cotação"); }
        finally { setLoading(false); }
    }, [demanda_id]);

    useEffect(() => { carregar(); }, [carregar]);

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

    const registrarCotacao = async () => {
        if (!item || !form.fornecedor_id || !form.preco_unitario) { toast.error("Selecione fornecedor e preencha o preço"); return; }
        setSaving(true);
        try {
            const body = { ...form, preco_unitario: parseFloat(form.preco_unitario), prazo_pagamento_dias: parseInt(form.prazo_pagamento_dias), prazo_entrega_dias_uteis: parseInt(form.prazo_entrega_dias_uteis), moq: parseFloat(form.moq), frete_valor: parseFloat(form.frete_valor || 0) };
            await api.post(`/compras/itens/${item.id}/cotar`, body);
            toast.success("Cotação registrada");
            carregar();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao registrar cotação"); }
        finally { setSaving(false); }
    };

    const criarPO = async () => {
        if (!form.fornecedor_id || !form.preco_unitario || !item) { toast.error("Preencha todos os campos antes de criar a PO"); return; }
        setCriandoPO(true);
        try {
            const poBody = {
                fornecedor_id: form.fornecedor_id,
                origem: "mrp",
                prazo_pagamento_texto: form.prazo_pagamento_texto,
                prazo_pagamento_dias: parseInt(form.prazo_pagamento_dias),
                demanda_ids: [demanda_id],
                itens: [{
                    item_id: item.id,
                    item_descricao: item.descricao,
                    quantidade_solicitada: demanda?.quantidade || 1,
                    unidade_compra: item.unidade_compra,
                    preco_unitario: parseFloat(form.preco_unitario),
                    frete_rateado: 0,
                }],
            };
            const { data } = await api.post("/compras/pos", poBody);
            toast.success(`PO criada — rascunho`);
            nav(`/compras/pos/${data.id}`);
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao criar PO"); }
        finally { setCriandoPO(false); }
    };

    if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>;

    return (
        <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={() => nav("/compras/mrp")}><ArrowLeft className="h-4 w-4" /></Button>
                <h1 className="text-lg font-bold">Cotação{demanda ? ` — ${demanda.item_descricao}` : ""}</h1>
            </div>

            {demanda && (
                <Card>
                    <CardContent className="pt-4">
                        <div className="grid grid-cols-3 gap-3 text-xs">
                            <div><span className="text-muted-foreground">Quantidade necessária</span><div className="font-bold text-base">{demanda.quantidade} {item?.unidade_compra}</div></div>
                            <div><span className="text-muted-foreground">Data limite pedido</span><div className={`font-medium ${demanda.urgente ? "text-red-600" : ""}`}>{demanda.data_limite_pedido || "—"}{demanda.urgente ? " ⚠️" : ""}</div></div>
                            <div><span className="text-muted-foreground">Motivo</span><div className="font-medium">{demanda.motivo}</div></div>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Histórico de cotações */}
            {hist?.comparativo_fornecedores?.length > 0 && (
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Cotações Anteriores</CardTitle></CardHeader>
                    <CardContent>
                        <table className="w-full text-xs">
                            <thead className="border-b">
                                <tr>
                                    <th className="text-left py-1 font-medium text-muted-foreground">Fornecedor</th>
                                    <th className="text-right py-1 font-medium text-muted-foreground">Preço</th>
                                    <th className="text-right py-1 font-medium text-muted-foreground">Prazo</th>
                                    <th className="text-right py-1 font-medium text-muted-foreground">MOQ</th>
                                    <th className="text-center py-1">
                                        <span className="text-muted-foreground font-medium">Selecionar</span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {hist.comparativo_fornecedores.map((f, i) => (
                                    <tr key={f.fornecedor_id} className={`border-b last:border-0 ${form.fornecedor_id === f.fornecedor_id ? "bg-primary/5" : ""}`}>
                                        <td className="py-1.5">{i === 0 && <span className="text-green-600 mr-1">★</span>}{f.fornecedor_nome}</td>
                                        <td className="py-1.5 text-right font-mono">{fmtCurrency(f.ultimo_preco, f.ultimo_preco_currency || "BRL")}</td>
                                        <td className="py-1.5 text-right">{f.prazo_entrega_dias_uteis}d</td>
                                        <td className="py-1.5 text-right">{f.moq}</td>
                                        <td className="py-1.5 text-center">
                                            <button className="text-primary hover:underline text-xs"
                                                onClick={() => setForm(ff => ({ ...ff, fornecedor_id: f.fornecedor_id, preco_unitario: f.ultimo_preco, preco_unitario_currency: f.ultimo_preco_currency || "BRL", prazo_entrega_dias_uteis: f.prazo_entrega_dias_uteis || 7, moq: f.moq || 1 }))}>
                                                Usar
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </CardContent>
                </Card>
            )}

            {/* Formulário de nova cotação */}
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Nova Cotação</CardTitle></CardHeader>
                <CardContent>
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
                    <div className="flex gap-2 mt-4">
                        <Button size="sm" variant="outline" onClick={registrarCotacao} disabled={saving}>
                            {saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />}<Plus className="h-3 w-3 mr-1" /> Registrar Cotação
                        </Button>
                        <Button size="sm" onClick={criarPO} disabled={criandoPO}>
                            {criandoPO && <Loader2 className="h-3 w-3 animate-spin mr-1" />}<ShoppingCart className="h-3 w-3 mr-1" /> Criar PO
                        </Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
