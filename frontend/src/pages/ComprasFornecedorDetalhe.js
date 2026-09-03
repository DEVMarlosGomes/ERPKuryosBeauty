import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ArrowLeft, Loader2, ShieldCheck, ShieldAlert, ShieldOff, ShieldQuestion } from "lucide-react";

const HOM_CFG = {
    nao_iniciada: { label: "Não iniciada", cls: "bg-slate-100 text-slate-600", icon: ShieldQuestion },
    em_processo:  { label: "Em processo",  cls: "bg-blue-100 text-blue-700",   icon: ShieldAlert },
    homologado:   { label: "Homologado",   cls: "bg-green-100 text-green-700", icon: ShieldCheck },
    suspenso:     { label: "Suspenso",     cls: "bg-orange-100 text-orange-700", icon: ShieldOff },
    reprovado:    { label: "Reprovado",    cls: "bg-red-100 text-red-700",     icon: ShieldOff },
};

function HomBadge({ status }) {
    const cfg = HOM_CFG[status] || HOM_CFG.nao_iniciada;
    return <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold ${cfg.cls}`}><cfg.icon className="h-3.5 w-3.5" />{cfg.label}</span>;
}

export default function ComprasFornecedorDetalhe() {
    const { id } = useParams();
    const nav = useNavigate();
    const [forn, setForn] = useState(null);
    const [loading, setLoading] = useState(true);
    const [modal, setModal] = useState(null); // "iniciar" | "decidir" | "suspender"
    const [form, setForm] = useState({});
    const [saving, setSaving] = useState(false);

    const carregar = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await api.get(`/compras/fornecedores/${id}`);
            setForn(data);
        } catch { toast.error("Erro ao carregar fornecedor"); }
        finally { setLoading(false); }
    }, [id]);

    useEffect(() => { carregar(); }, [carregar]);

    const acao = async (endpoint, body = {}) => {
        setSaving(true);
        try {
            await api.post(`/compras/fornecedores/${id}/homologacao/${endpoint}`, body);
            toast.success("Ação realizada com sucesso");
            setModal(null);
            carregar();
        } catch (e) {
            toast.error(e.response?.data?.detail || "Erro ao executar ação");
        } finally { setSaving(false); }
    };

    if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-muted-foreground" /></div>;
    if (!forn) return <div className="p-6 text-muted-foreground">Fornecedor não encontrado.</div>;

    const hom = forn.homologacao || {};
    const status = hom.status || "nao_iniciada";

    return (
        <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">
            {/* Header */}
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={() => nav("/compras/fornecedores")}><ArrowLeft className="h-4 w-4" /></Button>
                <div className="flex-1">
                    <h1 className="text-lg font-bold">{forn.razao_social}</h1>
                    <div className="text-sm text-muted-foreground">{forn.codigo_interno} · {forn.cnpj}</div>
                </div>
                <HomBadge status={status} />
            </div>

            {/* Ações de homologação */}
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Homologação</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                    <div className="grid grid-cols-3 gap-3 text-center">
                        <div className="bg-muted/40 rounded-lg p-3">
                            <div className="text-lg font-bold">{hom.historico_rncs_count ?? 0}</div>
                            <div className="text-xs text-muted-foreground">RNCs total</div>
                        </div>
                        <div className={`rounded-lg p-3 ${hom.historico_rncs_criticas_12m >= 3 ? "bg-red-50 border border-red-200" : "bg-muted/40"}`}>
                            <div className={`text-lg font-bold ${hom.historico_rncs_criticas_12m >= 3 ? "text-red-600" : ""}`}>{hom.historico_rncs_criticas_12m ?? 0}</div>
                            <div className="text-xs text-muted-foreground">RNCs críticas 12m</div>
                        </div>
                        <div className="bg-muted/40 rounded-lg p-3">
                            <div className="text-sm font-medium">{hom.proxima_reavaliacao || "—"}</div>
                            <div className="text-xs text-muted-foreground">Próxima reavaliação</div>
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        {status === "nao_iniciada" || status === "reprovado" ? (
                            <Button size="sm" onClick={() => acao("iniciar")} disabled={saving}>Iniciar Homologação</Button>
                        ) : null}
                        {status === "em_processo" && (
                            <>
                                <Button size="sm" onClick={() => setModal("decidir")}>Decidir</Button>
                                <Button size="sm" variant="outline" onClick={() => setModal("suspender")}>Suspender</Button>
                            </>
                        )}
                        {status === "homologado" && (
                            <Button size="sm" variant="outline" onClick={() => setModal("suspender")}>Suspender</Button>
                        )}
                    </div>
                </CardContent>
            </Card>

            {/* Dados cadastrais */}
            <div className="grid md:grid-cols-2 gap-4">
                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Dados Cadastrais</CardTitle></CardHeader>
                    <CardContent className="space-y-1.5 text-sm">
                        {[["Razão Social", forn.razao_social], ["Nome Fantasia", forn.nome_fantasia || "—"],
                          ["CNPJ", forn.cnpj], ["IE", forn.ie || "—"], ["IM", forn.im || "—"],
                          ["Status", forn.status_cadastro]].map(([k, v]) => (
                            <div key={k} className="flex items-start justify-between gap-2">
                                <span className="text-xs text-muted-foreground">{k}</span>
                                <span className="text-xs font-medium text-right">{v}</span>
                            </div>
                        ))}
                        <div className="pt-1">
                            <span className="text-xs text-muted-foreground">Categorias</span>
                            <div className="flex flex-wrap gap-1 mt-1">
                                {(forn.categorias || []).map(c => <span key={c} className="px-1.5 py-0.5 bg-muted rounded text-xs">{c}</span>)}
                            </div>
                        </div>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Contatos</CardTitle></CardHeader>
                    <CardContent>
                        {(forn.contatos || []).length === 0
                            ? <div className="text-xs text-muted-foreground">Nenhum contato cadastrado.</div>
                            : (forn.contatos || []).map(c => (
                                <div key={c.id} className="border-b last:border-0 py-2 text-xs space-y-0.5">
                                    <div className="font-medium">{c.nome} {c.principal_compras && <span className="text-primary text-xs">(principal)</span>}</div>
                                    {c.cargo && <div className="text-muted-foreground">{c.cargo}</div>}
                                    {c.email && <div>{c.email}</div>}
                                    {c.telefone && <div>{c.telefone}</div>}
                                </div>
                            ))
                        }
                    </CardContent>
                </Card>
            </div>

            {/* Log de auditoria */}
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Histórico</CardTitle></CardHeader>
                <CardContent>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto">
                        {[...(forn.log_auditoria || [])].reverse().map((l, i) => (
                            <div key={i} className="flex items-start gap-3 text-xs border-b last:border-0 pb-1.5">
                                <span className="text-muted-foreground font-mono w-20 flex-shrink-0">{l.em?.slice(0, 10)}</span>
                                <div>
                                    <span className="font-medium">{l.acao?.replace(/_/g, " ")}</span>
                                    {l.motivo && <span className="text-muted-foreground"> — {l.motivo}</span>}
                                    {l.justificativa && <span className="text-muted-foreground"> — {l.justificativa}</span>}
                                    <span className="text-muted-foreground ml-1">por {l.por_nome}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </CardContent>
            </Card>

            {/* Modal Decidir */}
            <Dialog open={modal === "decidir"} onOpenChange={() => setModal(null)}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Decidir Homologação</DialogTitle></DialogHeader>
                    <div className="space-y-3">
                        <div>
                            <Label className="text-xs">Decisão *</Label>
                            <Select value={form.decisao || ""} onValueChange={v => setForm(f => ({ ...f, decisao: v }))}>
                                <SelectTrigger className="h-8 text-sm mt-1"><SelectValue placeholder="Selecionar" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="homologado">Homologado</SelectItem>
                                    <SelectItem value="reprovado">Reprovado</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        {form.decisao === "homologado" && (
                            <div>
                                <Label className="text-xs">Validade (dias)</Label>
                                <Input type="number" className="h-8 text-sm mt-1" value={form.validade_dias || 365}
                                    onChange={e => setForm(f => ({ ...f, validade_dias: parseInt(e.target.value) }))} />
                            </div>
                        )}
                        {form.decisao === "reprovado" && (
                            <div>
                                <Label className="text-xs">Justificativa *</Label>
                                <Textarea className="text-sm mt-1" rows={3} value={form.justificativa || ""}
                                    onChange={e => setForm(f => ({ ...f, justificativa: e.target.value }))} />
                            </div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" size="sm" onClick={() => setModal(null)}>Cancelar</Button>
                        <Button size="sm" disabled={saving || !form.decisao}
                            onClick={() => acao("decidir", { decisao: form.decisao, justificativa: form.justificativa, validade_dias: form.validade_dias || 365 })}>
                            {saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Confirmar
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Modal Suspender */}
            <Dialog open={modal === "suspender"} onOpenChange={() => setModal(null)}>
                <DialogContent>
                    <DialogHeader><DialogTitle>Suspender Fornecedor</DialogTitle></DialogHeader>
                    <div>
                        <Label className="text-xs">Motivo *</Label>
                        <Textarea className="text-sm mt-1" rows={3} value={form.motivo || ""}
                            onChange={e => setForm(f => ({ ...f, motivo: e.target.value }))} />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" size="sm" onClick={() => setModal(null)}>Cancelar</Button>
                        <Button size="sm" variant="destructive" disabled={saving || !form.motivo?.trim()}
                            onClick={() => acao("suspender", { motivo: form.motivo })}>
                            {saving && <Loader2 className="h-3 w-3 animate-spin mr-1" />} Suspender
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
