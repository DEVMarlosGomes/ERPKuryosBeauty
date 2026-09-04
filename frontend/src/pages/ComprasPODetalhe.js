import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
    ArrowLeft, Loader2, FileText, MessageSquare, CheckCircle2, X,
    Truck, AlertTriangle, ShieldAlert, Copy, Check
} from "lucide-react";

const STATUS_CFG = {
    rascunho:               { label: "Rascunho",         cls: "bg-slate-100 text-slate-700 border-slate-300" },
    emitida:                { label: "Emitida",          cls: "bg-blue-100 text-blue-700 border-blue-300" },
    confirmada:             { label: "Confirmada",       cls: "bg-indigo-100 text-indigo-700 border-indigo-300" },
    parcialmente_recebida:  { label: "Parc. Recebida",   cls: "bg-yellow-100 text-yellow-700 border-yellow-300" },
    recebida:               { label: "Recebida",         cls: "bg-green-100 text-green-700 border-green-300" },
    encerrada:              { label: "Encerrada",        cls: "bg-emerald-100 text-emerald-700 border-emerald-300" },
    cancelada:              { label: "Cancelada",        cls: "bg-red-100 text-red-700 border-red-300" },
};

function fmtBRL(n) { return (n ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }

function TimelineStep({ label, done, active }) {
    return (
        <div className={`flex items-center gap-2 text-xs ${done ? "text-green-700" : active ? "text-primary font-semibold" : "text-muted-foreground"}`}>
            <div className={`h-4 w-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${done ? "bg-green-600 border-green-600" : active ? "border-primary bg-primary/10" : "border-muted-foreground"}`}>
                {done && <Check className="h-2.5 w-2.5 text-white" />}
            </div>
            {label}
        </div>
    );
}

export default function ComprasPODetalhe() {
    const { id } = useParams();
    const nav = useNavigate();
    const [po, setPo] = useState(null);
    const [loading, setLoading] = useState(true);
    const [modal, setModal] = useState(null); // "confirmar"|"cancelar"|"receber"|"whatsapp"
    const [waText, setWaText] = useState("");
    const [copied, setCopied] = useState(false);
    const [form, setForm] = useState({});
    const [saving, setSaving] = useState(false);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get(`/compras/pos/${id}`);
            setPo(data);
        } catch { toast.error("Erro ao carregar PO"); }
        finally { setLoading(false); }
    }, [id]);

    useEffect(() => { carregar(); }, [carregar]);

    const emitir = async () => {
        setSaving(true);
        try {
            const { data } = await api.post(`/compras/pos/${id}/emitir`);
            if (data._alerta) toast.warning(data._alerta);
            else toast.success("PO emitida");
            carregar();
        } catch (e) {
            const detail = e.response?.data?.detail;
            if (detail?.error === "hard_stop_fornecedor_reprovado") {
                toast.error("BLOQUEIO: Fornecedor reprovado não pode receber POs");
            } else {
                toast.error(typeof detail === "string" ? detail : "Erro ao emitir PO");
            }
        } finally { setSaving(false); }
    };

    const abrirPDF = async () => {
        try {
            const res = await api.get(`/compras/pos/${id}/pdf`, { responseType: "blob" });
            const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
            const a = document.createElement("a");
            a.href = url; a.download = `PO_${po?.numero_po || id}.pdf`; a.click();
            window.URL.revokeObjectURL(url);
        } catch { toast.error("Erro ao gerar PDF"); }
    };

    const abrirWA = async () => {
        setSaving(true);
        try {
            const { data } = await api.get(`/compras/pos/${id}/whatsapp`);
            setWaText(data.texto);
            setModal("whatsapp");
        } catch { toast.error("Erro ao gerar texto WhatsApp"); }
        finally { setSaving(false); }
    };

    const copiar = () => {
        navigator.clipboard.writeText(waText).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
    };

    const confirmar = async () => {
        if (!form.data_entrega_confirmada) { toast.error("Informe a data de entrega confirmada"); return; }
        setSaving(true);
        try {
            await api.post(`/compras/pos/${id}/confirmar`, { data_entrega_confirmada: form.data_entrega_confirmada });
            toast.success("PO confirmada"); setModal(null); carregar();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao confirmar"); }
        finally { setSaving(false); }
    };

    const cancelar = async () => {
        if (!form.motivo?.trim()) { toast.error("Motivo obrigatório"); return; }
        setSaving(true);
        try {
            await api.post(`/compras/pos/${id}/cancelar`, { motivo: form.motivo });
            toast.success("PO cancelada"); setModal(null); carregar();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao cancelar"); }
        finally { setSaving(false); }
    };

    const receberParcial = async () => {
        if (!form.nf_numero || !form.nf_data) { toast.error("NF número e data são obrigatórios"); return; }
        setSaving(true);
        try {
            const itens_recebidos = (po?.itens || []).map(it => ({
                item_id: it.item_id,
                quantidade_recebida: parseFloat(form[`rec_${it.item_id}`] || 0),
            })).filter(i => i.quantidade_recebida > 0);
            if (!itens_recebidos.length) { toast.error("Informe pelo menos uma quantidade recebida"); setSaving(false); return; }
            const { data } = await api.post(`/compras/pos/${id}/receber-parcial`, { nf_numero: form.nf_numero, nf_data: form.nf_data, itens_recebidos });
            if (data.divergencias?.length > 0) toast.warning(`Divergências detectadas: ${data.divergencias.join("; ")}`);
            else toast.success("Recebimento registrado");
            setModal(null); carregar();
        } catch (e) { toast.error(e.response?.data?.detail || "Erro ao registrar recebimento"); }
        finally { setSaving(false); }
    };

    if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>;
    if (!po) return <div className="p-6 text-muted-foreground">PO não encontrada.</div>;

    const cfg = STATUS_CFG[po.status] || STATUS_CFG.rascunho;
    const statusOrder = ["rascunho", "emitida", "confirmada", "parcialmente_recebida", "recebida", "encerrada"];
    const curIdx = statusOrder.indexOf(po.status);
    const hom = po.fornecedor_homologado;

    return (
        <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-5">
            {/* Header */}
            <div className="flex items-center gap-3 flex-wrap">
                <Button variant="ghost" size="sm" onClick={() => nav("/compras/pos")}><ArrowLeft className="h-4 w-4" /></Button>
                <div className="flex-1">
                    <h1 className="text-lg font-bold">{po.numero_po || "(Rascunho)"}</h1>
                    <div className="text-sm text-muted-foreground">{po.fornecedor_nome} · {po.fornecedor_cnpj}</div>
                </div>
                <span className={`px-3 py-1 rounded-full text-sm font-semibold border ${cfg.cls}`}
                    data-testid="po-status-badge" data-status={po.status}>{cfg.label}</span>
            </div>

            {/* Alertas */}
            {!hom && po.status !== "cancelada" && (
                <div className="flex items-center gap-2 rounded-lg border border-yellow-300 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                    <ShieldAlert className="h-4 w-4 flex-shrink-0" />
                    Fornecedor sem homologação completa. Esta PO foi emitida com ressalva.
                </div>
            )}
            {po.urgente && (
                <div className="flex items-center gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    PO com entrega atrasada!
                </div>
            )}

            {/* Timeline */}
            <div className="flex items-center gap-2 overflow-x-auto pb-1">
                {statusOrder.map((s, i) => (
                    <div key={s} className="flex items-center gap-2 flex-shrink-0">
                        <TimelineStep label={STATUS_CFG[s]?.label} done={curIdx > i} active={curIdx === i} />
                        {i < statusOrder.length - 1 && <div className="w-6 h-px bg-border flex-shrink-0" />}
                    </div>
                ))}
            </div>

            {/* Ações */}
            <div className="flex flex-wrap gap-2">
                {po.status === "rascunho" && <Button size="sm" data-testid="btn-emitir-po" onClick={emitir} disabled={saving}>{saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Emitir PO</Button>}
                {po.status === "emitida" && <Button size="sm" data-testid="btn-confirmar-po" onClick={() => setModal("confirmar")}>Registrar Confirmação</Button>}
                {["emitida", "confirmada", "parcialmente_recebida"].includes(po.status) && <Button size="sm" variant="outline" data-testid="btn-receber-po" onClick={() => setModal("receber")}><Truck className="h-3.5 w-3.5 mr-1" /> Registrar Recebimento</Button>}
                {!["recebida", "encerrada", "cancelada"].includes(po.status) && <Button size="sm" variant="outline" className="text-red-600 border-red-300" data-testid="btn-cancelar-po" onClick={() => setModal("cancelar")}><X className="h-3.5 w-3.5 mr-1" /> Cancelar</Button>}
                <Button size="sm" variant="outline" data-testid="btn-pdf-po" onClick={abrirPDF}><FileText className="h-3.5 w-3.5 mr-1" /> Gerar PDF</Button>
                <Button size="sm" variant="outline" data-testid="btn-whatsapp-po" onClick={abrirWA}><MessageSquare className="h-3.5 w-3.5 mr-1" /> WhatsApp</Button>
            </div>

            {/* Itens */}
            <Card>
                <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                        <CardTitle className="text-sm">Itens</CardTitle>
                        <span className="text-sm font-bold">{fmtBRL(po.valor_total_po)}</span>
                    </div>
                </CardHeader>
                <CardContent>
                    <table className="w-full text-xs">
                        <thead className="border-b">
                            <tr>
                                <th className="text-left py-1.5 font-medium text-muted-foreground">Item</th>
                                <th className="text-right py-1.5 font-medium text-muted-foreground">Solicitado</th>
                                <th className="text-right py-1.5 font-medium text-muted-foreground">Recebido</th>
                                <th className="text-right py-1.5 font-medium text-muted-foreground">Preço Unit.</th>
                                <th className="text-right py-1.5 font-medium text-muted-foreground">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(po.itens || []).map(it => {
                                const rec = it.quantidade_recebida ?? 0;
                                const sol = it.quantidade_solicitada ?? 0;
                                const completo = rec >= sol;
                                return (
                                    <tr key={it.id} className="border-b last:border-0">
                                        <td className="py-2">{it.item_descricao || it.item_id}</td>
                                        <td className="py-2 text-right font-mono">{sol} {it.unidade_compra}</td>
                                        <td className={`py-2 text-right font-mono ${completo ? "text-green-700" : rec > 0 ? "text-orange-600" : "text-muted-foreground"}`}>{rec}</td>
                                        <td className="py-2 text-right font-mono">{fmtBRL(it.preco_unitario)}</td>
                                        <td className="py-2 text-right font-mono font-medium">{fmtBRL(it.valor_total_item)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </CardContent>
            </Card>

            {/* Condições + NFs */}
            <div className="grid md:grid-cols-2 gap-4">
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Condições Comerciais</CardTitle></CardHeader>
                    <CardContent className="space-y-1.5 text-xs">
                        {[
                            ["Prazo Pagamento", po.prazo_pagamento_texto],
                            ["Entrega Solicitada", po.data_entrega_solicitada || "—"],
                            ["Entrega Confirmada", po.data_entrega_confirmada || "—"],
                            ["Vencimento Pagamento", po.data_vencimento_pagamento || "—"],
                            ["Origem", po.origem],
                        ].map(([k, v]) => (
                            <div key={k} className="flex justify-between">
                                <span className="text-muted-foreground">{k}</span>
                                <span className="font-medium">{v}</span>
                            </div>
                        ))}
                        {po.gatilho_financeiro_acionado && (
                            <div className="mt-2 flex items-center gap-1 text-green-700 font-medium">
                                <CheckCircle2 className="h-3.5 w-3.5" /> Gatilho financeiro acionado
                            </div>
                        )}
                    </CardContent>
                </Card>

                {po.nfs_vinculadas?.length > 0 && (
                    <Card>
                        <CardHeader className="pb-2"><CardTitle className="text-sm">NFs Vinculadas</CardTitle></CardHeader>
                        <CardContent className="space-y-1.5">
                            {po.nfs_vinculadas.map((nf, i) => (
                                <div key={i} className="text-xs flex items-center justify-between border-b last:border-0 pb-1">
                                    <span className="font-mono">{nf.nf_numero}</span>
                                    <span className="text-muted-foreground">{nf.nf_data}</span>
                                    <span className={nf.status_cq === "aprovado" ? "text-green-700" : "text-muted-foreground"}>
                                        CQ: {nf.status_cq || "aguardando"}
                                    </span>
                                </div>
                            ))}
                        </CardContent>
                    </Card>
                )}
            </div>

            {/* Log */}
            {po.log_auditoria?.length > 0 && (
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Histórico</CardTitle></CardHeader>
                    <CardContent>
                        <div className="space-y-1 max-h-40 overflow-y-auto">
                            {[...po.log_auditoria].reverse().map((l, i) => (
                                <div key={i} className="text-xs flex items-start gap-3 border-b last:border-0 pb-1">
                                    <span className="font-mono text-muted-foreground w-20 flex-shrink-0">{l.em?.slice(0, 10)}</span>
                                    <span>{l.acao?.replace(/_/g, " ")} — {l.por_nome}</span>
                                    {l.motivo && <span className="text-muted-foreground">({l.motivo})</span>}
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Modal Confirmar */}
            <Dialog open={modal === "confirmar"} onOpenChange={() => setModal(null)}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Confirmar Entrega</DialogTitle></DialogHeader>
                    <div>
                        <Label className="text-xs">Data de Entrega Confirmada *</Label>
                        <Input type="date" className="h-8 text-sm mt-1" value={form.data_entrega_confirmada || ""}
                            onChange={e => setForm(f => ({ ...f, data_entrega_confirmada: e.target.value }))} />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" size="sm" onClick={() => setModal(null)}>Cancelar</Button>
                        <Button size="sm" onClick={confirmar} disabled={saving}>{saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Confirmar</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Modal Cancelar */}
            <Dialog open={modal === "cancelar"} onOpenChange={() => setModal(null)}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Cancelar PO</DialogTitle></DialogHeader>
                    <div>
                        <Label className="text-xs">Motivo *</Label>
                        <Textarea className="text-sm mt-1" rows={3} value={form.motivo || ""}
                            onChange={e => setForm(f => ({ ...f, motivo: e.target.value }))} />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" size="sm" onClick={() => setModal(null)}>Voltar</Button>
                        <Button size="sm" variant="destructive" onClick={cancelar} disabled={saving}>{saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Cancelar PO</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Modal Receber */}
            <Dialog open={modal === "receber"} onOpenChange={() => setModal(null)}>
                <DialogContent className="max-w-lg">
                    <DialogHeader><DialogTitle>Registrar Recebimento</DialogTitle></DialogHeader>
                    <div className="space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                            <div><Label className="text-xs">NF Número *</Label><Input className="h-8 text-sm mt-1" value={form.nf_numero || ""} onChange={e => setForm(f => ({ ...f, nf_numero: e.target.value }))} /></div>
                            <div><Label className="text-xs">Data NF *</Label><Input type="date" className="h-8 text-sm mt-1" value={form.nf_data || ""} onChange={e => setForm(f => ({ ...f, nf_data: e.target.value }))} /></div>
                        </div>
                        <div>
                            <Label className="text-xs">Quantidades Recebidas</Label>
                            <div className="space-y-1.5 mt-1">
                                {(po.itens || []).map(it => (
                                    <div key={it.item_id} className="flex items-center gap-2 text-xs">
                                        <span className="flex-1">{it.item_descricao}</span>
                                        <span className="text-muted-foreground">sol: {it.quantidade_solicitada}</span>
                                        <Input type="number" className="h-7 w-24 text-xs"
                                            placeholder="0"
                                            value={form[`rec_${it.item_id}`] || ""}
                                            onChange={e => setForm(f => ({ ...f, [`rec_${it.item_id}`]: e.target.value }))} />
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" size="sm" onClick={() => setModal(null)}>Cancelar</Button>
                        <Button size="sm" onClick={receberParcial} disabled={saving}>{saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Registrar</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Modal WhatsApp */}
            <Dialog open={modal === "whatsapp"} onOpenChange={() => setModal(null)}>
                <DialogContent className="max-w-lg">
                    <DialogHeader><DialogTitle>Texto WhatsApp</DialogTitle></DialogHeader>
                    <textarea className="w-full border rounded-md p-3 text-xs font-mono min-h-[200px] resize-none bg-muted/30"
                        value={waText} onChange={e => setWaText(e.target.value)} />
                    <DialogFooter>
                        <Button size="sm" onClick={copiar} variant="outline">
                            {copied ? <><Check className="h-3.5 w-3.5 mr-1 text-green-600" /> Copiado!</> : <><Copy className="h-3.5 w-3.5 mr-1" /> Copiar</>}
                        </Button>
                        <Button size="sm" onClick={() => setModal(null)}>Fechar</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
