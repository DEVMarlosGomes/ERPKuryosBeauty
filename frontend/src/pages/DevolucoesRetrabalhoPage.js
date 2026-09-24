import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowRight, FileText, Loader2, PackageCheck, Plus, RotateCcw, Truck } from "lucide-react";
import { toast } from "sonner";

import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const STATUS = {
  aguardando_retrabalho: "Aguardando retrabalho",
  em_quarentena: "Em quarentena",
  aguardando_cq: "Aguardando CQ",
  liberado_cq: "Liberado pelo CQ",
  aguardando_reexpedicao: "Aguardando reexpedição",
  reexpedido: "Reexpedido",
  cancelada: "Cancelada",
};

const newKey = (prefix) => window.crypto?.randomUUID?.() || `${prefix}-${Date.now()}`;

export default function DevolucoesRetrabalhoPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [expedicoes, setExpedicoes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showReexp, setShowReexp] = useState(false);
  const [form, setForm] = useState({ expedicao_id: "", item_index: "0", quantidade: "", motivo: "", observacoes: "", criar_retrabalho: true, idempotency_key: "" });
  const [reexp, setReexp] = useState({ endereco_entrega: "", transportadora: "", previsao_entrega: "", observacoes: "", idempotency_key: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [devolucoes, exps] = await Promise.all([
        api.get("/retrabalho/devolucoes"),
        api.get("/expedicao/ordens"),
      ]);
      setRows(Array.isArray(devolucoes.data) ? devolucoes.data : []);
      const list = Array.isArray(exps.data) ? exps.data : (exps.data?.ordens || []);
      setExpedicoes(list.filter(exp => ["expedido", "entregue"].includes(exp.status)));
    } catch (error) {
      toast.error(formatApiError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const expedition = useMemo(() => expedicoes.find(exp => exp.id === form.expedicao_id), [expedicoes, form.expedicao_id]);
  const item = expedition?.items?.[Number(form.item_index || 0)];
  const metrics = useMemo(() => ({
    total: rows.length,
    retrabalho: rows.filter(row => ["aguardando_retrabalho", "aguardando_cq"].includes(row.status)).length,
    liberadas: rows.filter(row => row.status === "liberado_cq").length,
    reexpedidas: rows.filter(row => row.status === "reexpedido").length,
  }), [rows]);

  const openCreate = () => {
    setForm({ expedicao_id: "", item_index: "0", quantidade: "", motivo: "", observacoes: "", criar_retrabalho: true, idempotency_key: newKey("devolucao") });
    setShowCreate(true);
  };

  const submitReturn = async () => {
    if (!form.expedicao_id || !form.motivo.trim() || Number(form.quantidade) <= 0) {
      toast.error("Informe a expedição, a quantidade e o motivo da devolução.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/retrabalho/devolucoes", { ...form, item_index: Number(form.item_index), quantidade: Number(form.quantidade) });
      toast.success("Devolução registrada, saldo segregado e RNC criada.");
      setShowCreate(false);
      await load();
    } catch (error) {
      toast.error(formatApiError(error));
    } finally { setSaving(false); }
  };

  const openReexp = (row) => {
    setSelected(row);
    setReexp({ endereco_entrega: "", transportadora: "", previsao_entrega: "", observacoes: "", idempotency_key: newKey("reexpedicao") });
    setShowReexp(true);
  };

  const submitReexp = async () => {
    setSaving(true);
    try {
      await api.post(`/retrabalho/devolucoes/${selected.id}/gerar-reexpedicao`, reexp);
      toast.success("Reexpedição gerada e encaminhada para a Expedição.");
      setShowReexp(false);
      await load();
    } catch (error) {
      toast.error(formatApiError(error));
    } finally { setSaving(false); }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold"><RotateCcw className="h-6 w-6" />Devoluções e Retrabalho</h1>
            <p className="mt-1 text-sm text-muted-foreground">Devolução do cliente → quarentena → retrabalho/CQ → reexpedição → NF-e</p>
          </div>
          <Button onClick={openCreate}><Plus className="mr-1 h-4 w-4" />Registrar devolução</Button>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[['Total', metrics.total], ['Em retrabalho/CQ', metrics.retrabalho], ['Liberadas', metrics.liberadas], ['Reexpedidas', metrics.reexpedidas]].map(([label, value]) => (
            <Card key={label}><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-bold">{value}</p></CardContent></Card>
          ))}
        </div>

        {loading ? <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin" /></div> : rows.length === 0 ? (
          <Card className="border-dashed"><CardContent className="py-16 text-center text-muted-foreground">Nenhuma devolução registrada.</CardContent></Card>
        ) : <div className="space-y-3">{rows.map(row => (
          <Card key={row.id} className="cursor-pointer hover:border-primary/40" onClick={() => setSelected(row)}>
            <CardContent className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2"><b>{row.produto_nome || row.sku}</b><Badge variant="outline">{STATUS[row.status] || row.status}</Badge></div>
                  <p className="text-sm">{row.cliente_nome || "Cliente"} · {row.quantidade} {row.unidade} · lote {row.lote}</p>
                  <p className="text-xs text-muted-foreground">EXP original {row.expedicao_original_numero || row.expedicao_original_id} · {row.motivo}</p>
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {row.rt_id && <p>RT: {row.rt_id}</p>}
                  {row.reexpedicao_numero && <p>Reexpedição: {row.reexpedicao_numero}</p>}
                  {row.nf_reexpedicao && <p>NF: {row.nf_reexpedicao.numero_nfe || row.nf_reexpedicao.numero_interno}</p>}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}</div>}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle>Registrar devolução do cliente</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Expedição original</Label><Select value={form.expedicao_id || "none"} onValueChange={value => setForm(prev => ({ ...prev, expedicao_id: value === 'none' ? '' : value, item_index: '0', quantidade: '' }))}><SelectTrigger><SelectValue placeholder="Selecione" /></SelectTrigger><SelectContent><SelectItem value="none">Selecione</SelectItem>{expedicoes.map(exp => <SelectItem key={exp.id} value={exp.id}>{exp.numero_exp || exp.id} - {exp.cliente_nome}</SelectItem>)}</SelectContent></Select></div>
            {expedition && <div><Label>Item expedido</Label><Select value={form.item_index} onValueChange={value => setForm(prev => ({ ...prev, item_index: value, quantidade: '' }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(expedition.items || []).map((line, index) => <SelectItem key={index} value={String(index)}>{line.produto_nome || line.sku} - {line.quantidade} {line.unidade}</SelectItem>)}</SelectContent></Select></div>}
            <div><Label>Quantidade devolvida {item ? `(máximo ${item.quantidade} ${item.unidade})` : ''}</Label><Input type="number" min="0" max={item?.quantidade} step="any" value={form.quantidade} onChange={event => setForm(prev => ({ ...prev, quantidade: event.target.value }))} /></div>
            <div><Label>Motivo</Label><Textarea value={form.motivo} onChange={event => setForm(prev => ({ ...prev, motivo: event.target.value }))} placeholder="Descreva a não conformidade informada pelo cliente" /></div>
            <div><Label>Observações</Label><Input value={form.observacoes} onChange={event => setForm(prev => ({ ...prev, observacoes: event.target.value }))} /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.criar_retrabalho} onChange={event => setForm(prev => ({ ...prev, criar_retrabalho: event.target.checked }))} />Criar ordem de retrabalho automaticamente</label>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setShowCreate(false)}>Cancelar</Button><Button onClick={submitReturn} disabled={saving}>{saving && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}Registrar</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {selected && !showReexp && <Dialog open onOpenChange={() => setSelected(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Devolução · {selected.produto_nome}</DialogTitle></DialogHeader>
          <div className="grid gap-3 text-sm md:grid-cols-2">
            <p><b>Status:</b> {STATUS[selected.status] || selected.status}</p><p><b>Cliente:</b> {selected.cliente_nome}</p>
            <p><b>Quantidade:</b> {selected.quantidade} {selected.unidade}</p><p><b>Lote devolvido:</b> {selected.lote}</p>
            <p><b>RNC:</b> {selected.rnc_id || "—"}</p><p><b>Retrabalho:</b> {selected.rt_id || "—"}</p>
            <p><b>EXP original:</b> {selected.expedicao_original_numero}</p><p><b>Reexpedição:</b> {selected.reexpedicao_numero || "—"}</p>
            <div className="md:col-span-2 rounded-md border p-3"><b>Motivo:</b> {selected.motivo}</div>
            {selected.nf_reexpedicao ? <div className="md:col-span-2 rounded-md border bg-muted/30 p-3"><p><b>NF vinculada:</b> {selected.nf_reexpedicao.numero_nfe || selected.nf_reexpedicao.numero_interno}</p><p><b>Status fiscal:</b> {selected.nf_reexpedicao.fiscal_status || selected.nf_reexpedicao.status}</p>{selected.nf_reexpedicao.chave_acesso && <p className="break-all font-mono text-xs">{selected.nf_reexpedicao.chave_acesso}</p>}</div> : <div className="md:col-span-2 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-800 dark:bg-amber-950/20"><AlertTriangle className="h-4 w-4" />A NF de reexpedição será criada após a confirmação da saída.</div>}
          </div>
          <DialogFooter className="gap-2">
            {selected.rt_id && <Button variant="outline" onClick={() => navigate('/cq/retrabalho')}><PackageCheck className="mr-1 h-4 w-4" />Abrir retrabalho</Button>}
            {selected.nf_reexpedicao && <Button variant="outline" onClick={() => navigate('/faturamento')}><FileText className="mr-1 h-4 w-4" />Abrir NF</Button>}
            {selected.reexpedicao_id && <Button variant="outline" onClick={() => navigate('/expedicao')}><Truck className="mr-1 h-4 w-4" />Abrir expedição</Button>}
            {selected.status === 'liberado_cq' && <Button onClick={() => openReexp(selected)}>Gerar reexpedição<ArrowRight className="ml-1 h-4 w-4" /></Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>}

      <Dialog open={showReexp} onOpenChange={setShowReexp}>
        <DialogContent>
          <DialogHeader><DialogTitle>Gerar reexpedição</DialogTitle></DialogHeader>
          <div className="space-y-3"><div><Label>Endereço de entrega</Label><Input value={reexp.endereco_entrega} onChange={event => setReexp(prev => ({ ...prev, endereco_entrega: event.target.value }))} /></div><div><Label>Transportadora</Label><Input value={reexp.transportadora} onChange={event => setReexp(prev => ({ ...prev, transportadora: event.target.value }))} /></div><div><Label>Previsão de entrega</Label><Input type="date" value={reexp.previsao_entrega} onChange={event => setReexp(prev => ({ ...prev, previsao_entrega: event.target.value }))} /></div><div><Label>Observações</Label><Textarea value={reexp.observacoes} onChange={event => setReexp(prev => ({ ...prev, observacoes: event.target.value }))} /></div></div>
          <DialogFooter><Button variant="outline" onClick={() => setShowReexp(false)}>Cancelar</Button><Button onClick={submitReexp} disabled={saving}>{saving && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}Gerar</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
