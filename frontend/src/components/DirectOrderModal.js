import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Check, Package, Building2 } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { CurrencyInput } from "@/components/ui/CurrencyInput";
import { fmtVolumeDisplay, parseVolumeInput } from "@/lib/masks";

/**
 * A12: Pedido Direto — cria um pedido para um cliente e SKU já existentes, sem
 * passar pelo funil lead → projeto → amostra. Usa o mesmo POST /orders/direct
 * que entra no mesmo ciclo de vida dos demais pedidos (checklist, aprovação,
 * CGI, imutabilidade) — aqui só cuidamos da busca de cliente/SKU e do payload.
 */
export default function DirectOrderModal({ open, onOpenChange, onCreated }) {
    const [clienteQuery, setClienteQuery] = useState("");
    const [clientes, setClientes] = useState([]);
    const [cliente, setCliente] = useState(null);

    const [skuQuery, setSkuQuery] = useState("");
    const [skus, setSkus] = useState([]);
    const [sku, setSku] = useState(null);

    const [qtdDisplay, setQtdDisplay] = useState("");
    const [valorUnitario, setValorUnitario] = useState("");
    const [valorUnitarioCurrency, setValorUnitarioCurrency] = useState("BRL");
    const [prazoEntrega, setPrazoEntrega] = useState("");
    const [pedidoClienteRef, setPedidoClienteRef] = useState("");
    const [tipoServico, setTipoServico] = useState("producao");
    const [observacoes, setObservacoes] = useState("");
    const [submitting, setSubmitting] = useState(false);

    const reset = useCallback(() => {
        setClienteQuery(""); setClientes([]); setCliente(null);
        setSkuQuery(""); setSkus([]); setSku(null);
        setQtdDisplay(""); setValorUnitario(""); setValorUnitarioCurrency("BRL");
        setPrazoEntrega(""); setPedidoClienteRef(""); setTipoServico("producao"); setObservacoes("");
    }, []);

    useEffect(() => { if (!open) reset(); }, [open, reset]);

    // Busca de cliente (debounced)
    useEffect(() => {
        if (cliente || !clienteQuery.trim()) { setClientes([]); return; }
        const t = setTimeout(async () => {
            try {
                const { data } = await api.get("/crm/clients", { params: { search: clienteQuery.trim() } });
                setClientes((data || []).slice(0, 8));
            } catch { setClientes([]); }
        }, 300);
        return () => clearTimeout(t);
    }, [clienteQuery, cliente]);

    // Busca de SKU (escopada ao cliente selecionado, só produtos ativos)
    useEffect(() => {
        if (!cliente || sku) { setSkus([]); return; }
        const t = setTimeout(async () => {
            try {
                const { data } = await api.get("/crm/skus", {
                    params: { cliente_id: cliente.id, status: "ativo", pd_concluidos: true, search: skuQuery.trim() || undefined },
                });
                setSkus((data || []).slice(0, 8));
            } catch { setSkus([]); }
        }, 300);
        return () => clearTimeout(t);
    }, [cliente, skuQuery, sku]);

    const pickSku = (s) => {
        setSku(s);
        setSkus([]);
        // Bugfix pos-auditoria: a moeda do SKU nunca era lida — o preço pré-preenchido
        // sempre aparecia (e era enviado) como se fosse BRL, mesmo quando o SKU foi
        // cadastrado em USD.
        if (s.preco_unitario) setValorUnitario(String(s.preco_unitario));
        setValorUnitarioCurrency(s.preco_unitario_currency || "BRL");
    };

    // CurrencyInput usa <input type="number"> nativo (ponto decimal puro, ex: "25.5") —
    // NUNCA o formato mascarado pt-BR de lib/masks (onde ponto = separador de milhar).
    // Usar parsePriceInput aqui corromperia o valor (25.5 -> 255); parseFloat direto é o certo.
    const valorUnitarioNumeric = parseFloat(valorUnitario) || 0;
    const canSubmit = cliente && sku && parseVolumeInput(qtdDisplay) > 0 && valorUnitarioNumeric > 0;

    const handleSubmit = async () => {
        if (!canSubmit) return;
        setSubmitting(true);
        try {
            const { data } = await api.post("/orders/direct", {
                cliente_id: cliente.id,
                sku_id: sku.id,
                qtd: parseVolumeInput(qtdDisplay),
                valor_unitario: valorUnitarioNumeric,
                valor_unitario_currency: valorUnitarioCurrency,
                prazo_entrega: prazoEntrega,
                pedido_cliente_ref: pedidoClienteRef,
                tipo_servico: tipoServico,
                observacoes,
            });
            toast.success(`Pedido #${data.numero_pedido} criado!`);
            onOpenChange(false);
            onCreated?.(data);
        } catch (err) {
            toast.error(formatApiError(err) || "Erro ao criar pedido direto");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="w-[calc(100vw-2rem)] max-w-lg max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>Novo Pedido Direto</DialogTitle>
                    <p className="text-xs text-muted-foreground">
                        Para cliente e produto (SKU) já cadastrados — pula o fluxo de lead/projeto/amostra.
                        O pedido segue o mesmo ciclo normal a partir daqui (CGI, aprovação, expedição).
                    </p>
                </DialogHeader>

                <div className="space-y-4">
                    {/* Cliente */}
                    <div className="space-y-2">
                        <Label>Cliente</Label>
                        {cliente ? (
                            <div className="flex items-center justify-between rounded-md border p-2 bg-muted/30">
                                <span className="text-sm flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5" />{cliente.nome_empresa}</span>
                                <Button variant="ghost" size="sm" onClick={() => { setCliente(null); setSku(null); }}>Trocar</Button>
                            </div>
                        ) : (
                            <div className="relative">
                                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                                <Input className="pl-8" placeholder="Buscar cliente por nome, CNPJ..." value={clienteQuery} onChange={(e) => setClienteQuery(e.target.value)} />
                                {clientes.length > 0 && (
                                    <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover shadow-md max-h-48 overflow-y-auto">
                                        {clientes.map((c) => (
                                            <button key={c.id} type="button" className="w-full text-left px-3 py-2 text-sm hover:bg-muted flex items-center justify-between" onClick={() => { setCliente(c); setClienteQuery(""); setClientes([]); }}>
                                                {c.nome_empresa}
                                                {c.cnpj && <span className="text-xs text-muted-foreground">{c.cnpj}</span>}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* SKU */}
                    {cliente && (
                        <div className="space-y-2">
                            <Label>Produto (SKU)</Label>
                            {sku ? (
                                <div className="flex items-center justify-between rounded-md border p-2 bg-muted/30">
                                    <span className="text-sm flex items-center gap-1.5"><Package className="h-3.5 w-3.5" />{sku.nome_produto} <span className="text-xs text-muted-foreground font-mono">{sku.codigo_interno}</span>{sku.pd_concluido && <span className="text-[10px] text-green-600">P&D concluido</span>}</span>
                                    <Button variant="ghost" size="sm" onClick={() => setSku(null)}>Trocar</Button>
                                </div>
                            ) : (
                                <div className="relative">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                                    <Input className="pl-8" placeholder="Buscar produto ativo deste cliente..." value={skuQuery} onChange={(e) => setSkuQuery(e.target.value)} />
                                    {skus.length > 0 && (
                                        <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover shadow-md max-h-48 overflow-y-auto">
                                            {skus.map((s) => (
                                                <button key={s.id} type="button" className="w-full text-left px-3 py-2 text-sm hover:bg-muted flex items-center justify-between gap-2" onClick={() => pickSku(s)}>
                                                    <span className="truncate">{s.nome_produto}</span>
                                                    <span className="flex shrink-0 items-center gap-1">
                                                        {s.pd_concluido && <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] text-green-700">P&D</span>}
                                                        <span className="text-xs text-muted-foreground font-mono">{s.codigo_interno}</span>
                                                    </span>
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    {skuQuery.trim() && skus.length === 0 && (
                                        <p className="text-[11px] text-muted-foreground mt-1">Nenhum produto ativo encontrado para este cliente.</p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {sku && (
                        <>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-2">
                                    <Label>Quantidade</Label>
                                    <Input
                                        type="text" inputMode="numeric" placeholder="1.000"
                                        value={qtdDisplay}
                                        onChange={(e) => setQtdDisplay(e.target.value)}
                                        onBlur={(e) => setQtdDisplay(fmtVolumeDisplay(e.target.value))}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Valor unitário</Label>
                                    <CurrencyInput
                                        value={valorUnitario}
                                        currency={valorUnitarioCurrency}
                                        onValueChange={setValorUnitario}
                                        onCurrencyChange={setValorUnitarioCurrency}
                                        showHint={false}
                                    />
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-2">
                                    <Label>Tipo de serviço</Label>
                                    <Select value={tipoServico} onValueChange={setTipoServico}>
                                        <SelectTrigger><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="producao">Produção</SelectItem>
                                            <SelectItem value="reposicao">Reposição</SelectItem>
                                            <SelectItem value="retrabalho">Retrabalho</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-2">
                                    <Label>Prazo de entrega</Label>
                                    <Input placeholder="Ex: 20 dias" value={prazoEntrega} onChange={(e) => setPrazoEntrega(e.target.value)} />
                                </div>
                            </div>
                            <div className="space-y-2">
                                <Label># Pedido do cliente</Label>
                                <Input placeholder="Opcional, usado para evitar duplicidade" value={pedidoClienteRef} onChange={(e) => setPedidoClienteRef(e.target.value)} />
                            </div>
                            <div className="space-y-2">
                                <Label>Observações</Label>
                                <Input placeholder="Opcional" value={observacoes} onChange={(e) => setObservacoes(e.target.value)} />
                            </div>
                        </>
                    )}
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
                    <Button onClick={handleSubmit} disabled={!canSubmit || submitting} className="gap-1.5">
                        <Check className="h-4 w-4" /> Criar Pedido
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
