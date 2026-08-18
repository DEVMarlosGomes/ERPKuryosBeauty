import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  ArrowLeft, Save, Loader2, Pencil, X, Factory, ClipboardList,
  Play, Pause, RotateCcw, Plus, AlertTriangle, CheckCircle2,
} from "lucide-react";

const OP_STATUSES = ["aberta", "em_processo", "pausada", "concluida", "cancelada"];
const STATUS_CONFIG = {
  aberta:      { label: "Aberta",      cls: "bg-blue-500/10 text-blue-600 border-blue-300 dark:text-blue-300" },
  em_processo: { label: "Em Processo", cls: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  pausada:     { label: "Pausada",     cls: "bg-orange-500/10 text-orange-600 border-orange-300 dark:text-orange-300" },
  concluida:   { label: "Concluída",   cls: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
  cancelada:   { label: "Cancelada",   cls: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
};

const TURNO_LABELS = { manha: "Manhã", tarde: "Tarde", noite: "Noite", integral: "Integral" };
const PAUSA_TIPO_LABELS = { manutencao: "Manutenção", falta_material: "Falta de Material", almoco: "Almoço/Refeição", outro: "Outro" };
const PERDA_TIPO_LABELS = { processo: "Processo", material: "Material", embalagem: "Embalagem", outro: "Outro" };

function formatDT(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR"); } catch { return iso; }
}

function deepClone(o) { return JSON.parse(JSON.stringify(o)); }

function apiErrorMessage(e, fallback = "Erro") {
  const detail = e.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return fallback;
}

export default function OPDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [op, setOp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);

  // Apontamento
  const [showApontar, setShowApontar] = useState(false);
  const [apontForm, setApontForm] = useState({ item_idx: 0, qtd_produzida: "", turno: "integral", observacoes: "" });

  // Pausa
  const [showPausar, setShowPausar] = useState(false);
  const [pausaForm, setPausaForm] = useState({ motivo: "", tipo: "outro" });

  // Perda
  const [showPerda, setShowPerda] = useState(false);
  const [perdaForm, setPerdaForm] = useState({ item_idx: 0, tipo: "processo", quantidade: "", unidade: "un", motivo: "" });

  // Retrabalho para P&D
  const [showRework, setShowRework] = useState(false);
  const [reworkForm, setReworkForm] = useState({ motivo: "", anotacoes: "", prioridade: "normal" });

  const fetchOp = useCallback(async () => {
    try {
      const res = await api.get(`/ops/${id}`);
      setOp(res.data);
      setForm(deepClone(res.data));
    } catch {
      toast.error("Erro ao carregar OP");
      navigate("/ops");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => { fetchOp(); }, [fetchOp]);

  const startEdit = () => { setForm(deepClone(op)); setEditing(true); };
  const cancelEdit = () => { setForm(deepClone(op)); setEditing(false); };

  const saveOp = async () => {
    setSaving(true);
    try {
      const res = await api.put(`/ops/${id}`, {
        status: form.status,
        items: form.items,
        observacoes: form.observacoes,
      });
      setOp(res.data); setForm(deepClone(res.data)); setEditing(false);
      toast.success("OP atualizada");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao salvar");
    } finally { setSaving(false); }
  };

  const quickStatus = async (newStatus) => {
    try {
      const res = await api.put(`/ops/${id}`, { status: newStatus });
      setOp(res.data); setForm(deepClone(res.data));
      toast.success("Status atualizado");
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  const updateItem = (idx, key, value) => {
    setForm(p => {
      const items = [...(p.items || [])];
      items[idx] = { ...items[idx], [key]: value };
      return { ...p, items };
    });
  };

  // ── Apontamento ───────────────────────────────────────────────────────────
  const handleApontar = async () => {
    if (!apontForm.qtd_produzida || Number(apontForm.qtd_produzida) <= 0) {
      toast.error("Informe a quantidade produzida"); return;
    }
    setSaving(true);
    try {
      const res = await api.post(`/ops/${id}/apontar`, {
        item_idx: Number(apontForm.item_idx),
        qtd_produzida: Number(apontForm.qtd_produzida),
        turno: apontForm.turno,
        observacoes: apontForm.observacoes,
      });
      setOp(res.data); setForm(deepClone(res.data)); setShowApontar(false);
      toast.success("Apontamento registrado");
    } catch (e) { toast.error(apiErrorMessage(e)); }
    finally { setSaving(false); }
  };

  // ── Pausa ─────────────────────────────────────────────────────────────────
  const handlePausar = async () => {
    if (!pausaForm.motivo.trim()) { toast.error("Informe o motivo da pausa"); return; }
    setSaving(true);
    try {
      const res = await api.post(`/ops/${id}/pausar`, pausaForm);
      setOp(res.data); setForm(deepClone(res.data)); setShowPausar(false);
      toast.success("Produção pausada");
    } catch (e) { toast.error(apiErrorMessage(e)); }
    finally { setSaving(false); }
  };

  const handleRetomar = async () => {
    setSaving(true);
    try {
      const res = await api.post(`/ops/${id}/retomar`);
      setOp(res.data); setForm(deepClone(res.data));
      toast.success("Produção retomada");
    } catch (e) { toast.error(apiErrorMessage(e)); }
    finally { setSaving(false); }
  };

  // ── Perda ─────────────────────────────────────────────────────────────────
  const handlePerda = async () => {
    if (!perdaForm.quantidade || Number(perdaForm.quantidade) <= 0) {
      toast.error("Informe a quantidade de perda"); return;
    }
    setSaving(true);
    try {
      const res = await api.post(`/ops/${id}/perda`, {
        item_idx: Number(perdaForm.item_idx),
        tipo: perdaForm.tipo,
        quantidade: Number(perdaForm.quantidade),
        unidade: perdaForm.unidade,
        motivo: perdaForm.motivo,
      });
      setOp(res.data); setForm(deepClone(res.data)); setShowPerda(false);
      toast.success("Perda registrada");
    } catch (e) { toast.error(apiErrorMessage(e)); }
    finally { setSaving(false); }
  };

  const handleSendRework = async () => {
    if (reworkForm.motivo.trim().length < 5) {
      toast.error("Informe o motivo do retrabalho");
      return;
    }
    setSaving(true);
    try {
      await api.post(`/ops/${id}/rework`, reworkForm);
      setShowRework(false);
      setReworkForm({ motivo: "", anotacoes: "", prioridade: "normal" });
      await fetchOp();
      toast.success("Retrabalho enviado ao P&D");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Erro ao enviar retrabalho"));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !form) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[form.status] || STATUS_CONFIG.aberta;
  const totalPlanejado = (form.items || []).reduce((s, it) => s + (Number(it.qtd_planejada) || 0), 0);
  const totalProduzido = (form.items || []).reduce((s, it) => s + (Number(it.qtd_produzida) || 0), 0);
  const totalPerdas = (op.perdas || []).reduce((s, p) => s + (Number(p.quantidade) || 0), 0);
  const progressPct = totalPlanejado > 0 ? Math.min((totalProduzido / totalPlanejado) * 100, 100) : 0;
  const ativo = ["aberta", "em_processo", "pausada"].includes(form.status);
  const tecnico = form.tecnico || {};
  const bloqueiosTecnicos = tecnico.bloqueios || [];
  const alertasTecnicos = tecnico.alertas || [];

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-5">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate("/ops")}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-xl font-heading font-semibold flex items-center gap-2">
                <Factory className="h-5 w-5 text-primary" />
                Ordem de Produção <span className="font-mono text-primary">{form.numero_op}</span>
              </h1>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <Badge className={statusCfg.cls}>{statusCfg.label}</Badge>
                {form.numero_pedido && (
                  <Badge variant="outline" className="text-[10px] gap-1 cursor-pointer"
                    onClick={() => navigate(`/orders/${form.pedido_id}`)}>
                    <ClipboardList className="h-2.5 w-2.5" /> PI #{form.numero_pedido}
                  </Badge>
                )}
                {form.pcp_numero && (
                  <Badge variant="outline" className="text-[10px]">{form.pcp_numero}</Badge>
                )}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            {form.status === "aberta" && !editing && (
              <Button size="sm" onClick={() => quickStatus("em_processo")}>
                <Play className="h-3.5 w-3.5 mr-1" />Iniciar Produção
              </Button>
            )}
            {form.status === "em_processo" && !editing && (
              <>
                <Button size="sm" variant="outline" onClick={() => { setApontForm({ item_idx: 0, qtd_produzida: "", turno: "integral", observacoes: "" }); setShowApontar(true); }}>
                  <Plus className="h-3.5 w-3.5 mr-1" />Apontar
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setPausaForm({ motivo: "", tipo: "outro" }); setShowPausar(true); }}>
                  <Pause className="h-3.5 w-3.5 mr-1" />Pausar
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setPerdaForm({ item_idx: 0, tipo: "processo", quantidade: "", unidade: "un", motivo: "" }); setShowPerda(true); }}>
                  <AlertTriangle className="h-3.5 w-3.5 mr-1" />Perda
                </Button>
                <Button size="sm" onClick={() => quickStatus("concluida")}>
                  <CheckCircle2 className="h-3.5 w-3.5 mr-1" />Concluir
                </Button>
              </>
            )}
            {!editing && (tecnico.revisao_obrigatoria || bloqueiosTecnicos.length > 0) && (
              <Button size="sm" variant="outline" onClick={() => setShowRework(true)}>
                <AlertTriangle className="h-3.5 w-3.5 mr-1" />Retrabalho P&D
              </Button>
            )}
            {form.status === "pausada" && !editing && (
              <Button size="sm" onClick={handleRetomar} disabled={saving}>
                <RotateCcw className="h-3.5 w-3.5 mr-1" />Retomar
              </Button>
            )}
            {!editing ? (
              <Button variant="outline" size="sm" onClick={startEdit}>
                <Pencil className="h-3.5 w-3.5 mr-1" />Editar
              </Button>
            ) : (
              <>
                <Button size="sm" onClick={saveOp} disabled={saving}>
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Save className="h-3.5 w-3.5 mr-1" />}Salvar
                </Button>
                <Button variant="ghost" size="sm" onClick={cancelEdit}><X className="h-3.5 w-3.5" /></Button>
              </>
            )}
          </div>
        </div>

        {/* Progress */}
        <Card>
          <CardContent className="pt-5 pb-4">
            <div className="flex items-center justify-between text-sm mb-2 flex-wrap gap-2">
              <span className="font-medium">Progresso de Produção</span>
              <div className="flex items-center gap-4 text-xs">
                <span className="font-mono font-semibold">{totalProduzido.toLocaleString("pt-BR")} / {totalPlanejado.toLocaleString("pt-BR")} un.</span>
                {totalPerdas > 0 && (
                  <span className="text-red-600 font-mono">Perdas: {totalPerdas.toLocaleString("pt-BR")}</span>
                )}
              </div>
            </div>
            <div className="h-3 rounded-full bg-muted overflow-hidden">
              <div className={`h-full rounded-full transition-all ${progressPct >= 100 ? "bg-green-500" : "bg-primary"}`}
                style={{ width: `${progressPct}%` }} />
            </div>
            <p className="text-xs text-muted-foreground mt-1.5 text-right">{progressPct.toFixed(1)}% concluído</p>
          </CardContent>
        </Card>

        {/* Info */}
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Informações</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            {[
              ["Cliente", form.cliente_nome || "—"],
              ["Projeto", form.project_name || "—"],
              ["Criado por", form.created_by_name || "—"],
              ["Criado em", form.created_at ? new Date(form.created_at).toLocaleDateString("pt-BR") : "—"],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="font-medium">{value}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        {(tecnico.revisao_obrigatoria || bloqueiosTecnicos.length > 0 || alertasTecnicos.length > 0) && (
          <Card className={bloqueiosTecnicos.length ? "border-red-200 dark:border-red-900/40" : "border-amber-200 dark:border-amber-900/40"}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <AlertTriangle className={`h-4 w-4 ${bloqueiosTecnicos.length ? "text-red-500" : "text-amber-500"}`} />
                Ficha tecnica operacional
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge className={tecnico.apto_operacao ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}>
                  {tecnico.apto_operacao ? "Apta para operacao" : "Bloqueada"}
                </Badge>
                <span className="text-xs text-muted-foreground">Snapshot: {formatDT(tecnico.snapshot_at)}</span>
              </div>
              {bloqueiosTecnicos.length > 0 && (
                <div className="rounded-md bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/30 p-3">
                  <p className="text-xs font-semibold text-red-700 dark:text-red-300 mb-1">Bloqueios</p>
                  <ul className="text-xs text-red-700 dark:text-red-300 space-y-1 list-disc pl-4">
                    {bloqueiosTecnicos.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
              {alertasTecnicos.length > 0 && (
                <div className="rounded-md bg-amber-50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/30 p-3">
                  <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-1">Alertas</p>
                  <ul className="text-xs text-amber-700 dark:text-amber-300 space-y-1 list-disc pl-4">
                    {alertasTecnicos.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
              {(tecnico.items || []).map((review, idx) => (
                <div key={idx} className="border rounded-md overflow-hidden">
                  <div className="flex items-center justify-between gap-2 px-3 py-2 bg-muted/30">
                    <div>
                      <p className="text-xs font-semibold">{review.codigo_kuryos || review.item || `Item ${idx + 1}`}</p>
                      <p className="text-[11px] text-muted-foreground">
                        Formula v{review.formula_versao || "?"} · total {Number(review.total_percentual || 0).toLocaleString("pt-BR")}%
                      </p>
                    </div>
                    <Badge variant="outline" className="text-[10px]">{review.formula_status || "sem status"}</Badge>
                  </div>
                  {(review.itens_formula || []).length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-t bg-muted/20">
                            <th className="text-left p-2">Fase</th>
                            <th className="text-left p-2">Ingrediente</th>
                            <th className="text-right p-2">%</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(review.itens_formula || []).slice(0, 12).map((it, i) => (
                            <tr key={i} className="border-t">
                              <td className="p-2 font-mono">{it.phase || "-"}</td>
                              <td className="p-2">{it.ingredient_name || "-"}</td>
                              <td className="p-2 text-right font-mono">{Number(it.percentage || 0).toLocaleString("pt-BR")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Items */}
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Itens e Apontamento de Produção</CardTitle></CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="text-left p-2.5 font-semibold text-xs">#</th>
                    <th className="text-left p-2.5 font-semibold text-xs">Item</th>
                    <th className="text-left p-2.5 font-semibold text-xs hidden sm:table-cell">Cód.</th>
                    <th className="text-left p-2.5 font-semibold text-xs">Lote</th>
                    <th className="text-right p-2.5 font-semibold text-xs">Plan.</th>
                    <th className="text-right p-2.5 font-semibold text-xs">Produzido</th>
                    <th className="text-right p-2.5 font-semibold text-xs hidden sm:table-cell">%</th>
                  </tr>
                </thead>
                <tbody>
                  {(form.items || []).map((it, idx) => {
                    const pct = it.qtd_planejada > 0 ? Math.min((it.qtd_produzida / it.qtd_planejada) * 100, 100) : 0;
                    return (
                      <tr key={idx} className="border-t">
                        <td className="p-2 font-mono text-xs text-muted-foreground">{idx + 1}</td>
                        <td className="p-2 font-medium">{it.item || "—"}</td>
                        <td className="p-2 font-mono text-xs text-muted-foreground hidden sm:table-cell">{it.codigo_kuryos || "—"}</td>
                        <td className="p-2">
                          {editing
                            ? <Input value={it.lote || ""} onChange={e => updateItem(idx, "lote", e.target.value)} className="h-7 text-xs w-28" />
                            : <span className="font-mono text-xs">{it.lote || "—"}</span>
                          }
                        </td>
                        <td className="p-2 text-right font-mono text-sm">{Number(it.qtd_planejada || 0).toLocaleString("pt-BR")}</td>
                        <td className="p-2 text-right font-mono text-sm font-semibold">{Number(it.qtd_produzida || 0).toLocaleString("pt-BR")}</td>
                        <td className="p-2 text-right hidden sm:table-cell">
                          <span className={`text-xs font-mono font-semibold ${pct >= 100 ? "text-green-600" : pct > 0 ? "text-amber-600" : "text-muted-foreground"}`}>
                            {pct.toFixed(0)}%
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Apontamentos */}
        {(op.apontamentos || []).length > 0 && (
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">Apontamentos de Produção</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-1.5">
                {op.apontamentos.map((a, i) => (
                  <div key={a.id || i} className="flex items-center justify-between gap-3 rounded-lg bg-muted/30 px-3 py-2 text-xs">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-muted-foreground">{formatDT(a.horario)}</span>
                      <span className="font-semibold">{a.item_nome || `Item ${a.item_idx + 1}`}</span>
                      <span className="text-muted-foreground">{TURNO_LABELS[a.turno] || a.turno}</span>
                      {a.observacoes && <span className="text-muted-foreground italic">"{a.observacoes}"</span>}
                    </div>
                    <span className="font-mono font-bold text-green-600 shrink-0">+{Number(a.qtd_produzida).toLocaleString("pt-BR")}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Pausas */}
        {(op.pausas || []).length > 0 && (
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">Pausas</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-1.5">
                {op.pausas.map((p, i) => (
                  <div key={p.id || i} className="rounded-lg bg-muted/30 px-3 py-2 text-xs">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${p.horario_fim ? "bg-slate-100 text-slate-600" : "bg-orange-100 text-orange-700"}`}>
                          {p.horario_fim ? "Encerrada" : "Em curso"}
                        </span>
                        <span className="font-medium">{PAUSA_TIPO_LABELS[p.tipo] || p.tipo}</span>
                        <span className="text-muted-foreground">{p.motivo}</span>
                      </div>
                      {p.duracao_min != null && (
                        <span className="font-mono text-muted-foreground">{p.duracao_min} min</span>
                      )}
                    </div>
                    <div className="mt-1 text-muted-foreground">
                      Início: {formatDT(p.horario_inicio)}{p.horario_fim ? ` → Fim: ${formatDT(p.horario_fim)}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Perdas */}
        {(op.perdas || []).length > 0 && (
          <Card className="border-red-200 dark:border-red-900/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-base text-red-600 dark:text-red-400 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4" />Perdas Registradas
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5">
                {op.perdas.map((p, i) => (
                  <div key={p.id || i} className="flex items-center justify-between gap-3 rounded-lg bg-red-50/50 dark:bg-red-900/10 px-3 py-2 text-xs border border-red-100 dark:border-red-900/30">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="font-medium">{PERDA_TIPO_LABELS[p.tipo] || p.tipo}</span>
                      <span className="text-muted-foreground">{p.item_nome || `Item ${p.item_idx + 1}`}</span>
                      {p.motivo && <span className="text-muted-foreground italic">"{p.motivo}"</span>}
                      <span className="text-muted-foreground">{formatDT(p.em)}</span>
                    </div>
                    <span className="font-mono font-bold text-red-600 shrink-0">-{Number(p.quantidade).toLocaleString("pt-BR")} {p.unidade}</span>
                  </div>
                ))}
                <div className="flex justify-end pt-1">
                  <span className="text-xs font-mono text-red-600 font-bold">
                    Total perdas: {totalPerdas.toLocaleString("pt-BR")}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Observações */}
        {(editing || form.observacoes) && (
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">Observações</CardTitle></CardHeader>
            <CardContent>
              {editing
                ? <Textarea value={form.observacoes || ""} onChange={e => setForm(p => ({ ...p, observacoes: e.target.value }))} rows={3} />
                : <p className="text-sm whitespace-pre-wrap">{form.observacoes}</p>
              }
            </CardContent>
          </Card>
        )}
      </div>

      {/* ── Apontar dialog ─────────────────────────────────────────────── */}
      <Dialog open={showRework} onOpenChange={setShowRework}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />Retrabalho para P&D
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Prioridade</Label>
              <Select value={reworkForm.prioridade}
                onValueChange={v => setReworkForm(f => ({ ...f, prioridade: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="normal">Normal</SelectItem>
                  <SelectItem value="alta">Alta</SelectItem>
                  <SelectItem value="critica">Critica</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Motivo *</Label>
              <Input value={reworkForm.motivo}
                onChange={e => setReworkForm(f => ({ ...f, motivo: e.target.value }))}
                placeholder="Ex: ajuste de odor, cor, estabilidade ou processo" className="mt-1" autoFocus />
            </div>
            <div>
              <Label>Anotacoes adicionais</Label>
              <Textarea value={reworkForm.anotacoes}
                onChange={e => setReworkForm(f => ({ ...f, anotacoes: e.target.value }))}
                rows={4} className="mt-1" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRework(false)} disabled={saving}>Cancelar</Button>
            <Button onClick={handleSendRework} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <AlertTriangle className="h-4 w-4 mr-1" />}
              Enviar ao P&D
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showApontar} onOpenChange={setShowApontar}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Apontar Produção</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {(op.items || []).length > 1 && (
              <div>
                <Label>Item</Label>
                <Select value={String(apontForm.item_idx)}
                  onValueChange={v => setApontForm(f => ({ ...f, item_idx: Number(v) }))}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(op.items || []).map((it, i) => (
                      <SelectItem key={i} value={String(i)}>{it.item || `Item ${i + 1}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <Label>Qtd. Produzida *</Label>
              <Input type="number" value={apontForm.qtd_produzida} min="0.01" step="0.01"
                onChange={e => setApontForm(f => ({ ...f, qtd_produzida: e.target.value }))}
                placeholder="0" className="mt-1" autoFocus />
            </div>
            <div>
              <Label>Turno</Label>
              <Select value={apontForm.turno}
                onValueChange={v => setApontForm(f => ({ ...f, turno: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(TURNO_LABELS).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Observações</Label>
              <Input value={apontForm.observacoes}
                onChange={e => setApontForm(f => ({ ...f, observacoes: e.target.value }))}
                placeholder="Opcional" className="mt-1" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowApontar(false)} disabled={saving}>Cancelar</Button>
            <Button onClick={handleApontar} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
              Registrar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Pausar dialog ──────────────────────────────────────────────── */}
      <Dialog open={showPausar} onOpenChange={setShowPausar}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Pausar Produção</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Tipo de Pausa</Label>
              <Select value={pausaForm.tipo}
                onValueChange={v => setPausaForm(f => ({ ...f, tipo: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(PAUSA_TIPO_LABELS).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Motivo *</Label>
              <Input value={pausaForm.motivo}
                onChange={e => setPausaForm(f => ({ ...f, motivo: e.target.value }))}
                placeholder="Descreva o motivo" className="mt-1" autoFocus />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPausar(false)} disabled={saving}>Cancelar</Button>
            <Button onClick={handlePausar} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Pause className="h-4 w-4 mr-1" />}
              Pausar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Perda dialog ────────────────────────────────────────────────── */}
      <Dialog open={showPerda} onOpenChange={setShowPerda}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500" />Registrar Perda
          </DialogTitle></DialogHeader>
          <div className="space-y-3">
            {(op.items || []).length > 1 && (
              <div>
                <Label>Item</Label>
                <Select value={String(perdaForm.item_idx)}
                  onValueChange={v => setPerdaForm(f => ({ ...f, item_idx: Number(v) }))}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(op.items || []).map((it, i) => (
                      <SelectItem key={i} value={String(i)}>{it.item || `Item ${i + 1}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <Label>Tipo de Perda</Label>
              <Select value={perdaForm.tipo}
                onValueChange={v => setPerdaForm(f => ({ ...f, tipo: v }))}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(PERDA_TIPO_LABELS).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label>Quantidade *</Label>
                <Input type="number" min="0.01" step="0.01" value={perdaForm.quantidade}
                  onChange={e => setPerdaForm(f => ({ ...f, quantidade: e.target.value }))}
                  placeholder="0" className="mt-1" autoFocus />
              </div>
              <div>
                <Label>Unidade</Label>
                <Select value={perdaForm.unidade}
                  onValueChange={v => setPerdaForm(f => ({ ...f, unidade: v }))}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["un", "kg", "L", "g", "mL"].map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label>Motivo</Label>
              <Input value={perdaForm.motivo}
                onChange={e => setPerdaForm(f => ({ ...f, motivo: e.target.value }))}
                placeholder="Descreva a causa" className="mt-1" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPerda(false)} disabled={saving}>Cancelar</Button>
            <Button variant="destructive" onClick={handlePerda} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <AlertTriangle className="h-4 w-4 mr-1" />}
              Registrar Perda
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
