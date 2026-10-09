import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { CheckCircle2, Eye, Loader2, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { toast } from "sonner";
import LegacyStructuredFields from "@/components/legacy/LegacyStructuredFields";

export default function SectorInventoryReviewPanel({ sector, title }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [action, setAction] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/cadastros/revisoes-corte-estoque", { params: { assigned_sector: sector, limit: 300 } });
      setRows(response.data.registros || []);
      setSummary(response.data.resumo || {});
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar a fila legada do setor.");
    } finally {
      setLoading(false);
    }
  }, [sector]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (row) => {
    try {
      const response = await api.get(`/cadastros/revisoes-corte-estoque/${row.id}`);
      setDetail(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível abrir o registro legado.");
    }
  };

  const openAction = (row, decision) => setAction({
    row, decision, observacoes: "", endereco_codigo: row.legacy_address_code || row.legacy_code || "",
    quantidade_contada: row.legacy_quantity ?? "", unidade: row.legacy_unit || "",
  });

  const submitAction = async () => {
    if (!action || action.observacoes.trim().length < 3) {
      toast.error("Informe uma justificativa ou observação com pelo menos 3 caracteres.");
      return;
    }
    setSaving(true);
    try {
      if (sector === "qualidade") {
        await api.post(`/cadastros/revisoes-corte-estoque/${action.row.id}/decisao-cq`, {
          decision: action.decision, justificativa: action.observacoes.trim(),
        });
        toast.success(action.decision === "aprovar" ? "Lote aprovado pelo CQ e encaminhado à Logística." : "Decisão do CQ registrada.");
      } else {
        await api.post(`/cadastros/revisoes-corte-estoque/${action.row.id}/conferencia-logistica`, {
          decision: action.decision, observacoes: action.observacoes.trim(),
          endereco_codigo: action.endereco_codigo.trim(),
          quantidade_contada: action.row.record_type === "lot" && action.quantidade_contada !== "" ? Number(action.quantidade_contada) : null,
          unidade: action.row.record_type === "lot" ? action.unidade.trim() : null,
        });
        toast.success(action.decision === "confirmar" ? "Conferência registrada. O item continua bloqueado até o corte administrativo." : "Divergência registrada.");
      }
      setAction(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível registrar a revisão setorial.");
    } finally {
      setSaving(false);
    }
  };

  return <>
    <Card className="border-amber-500/30">
      <CardHeader className="pb-3"><div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex-1"><CardTitle className="flex items-center gap-2 text-base"><ShieldAlert className="h-5 w-5 text-amber-500" />{title}</CardTitle><p className="mt-1 text-xs text-muted-foreground">Fila histórica bloqueada. A revisão não cria saldo nem movimentação de estoque.</p></div>
        <div className="flex items-center gap-2"><Badge variant="secondary">{summary.blocked || 0} pendentes</Badge><Button size="sm" variant="outline" onClick={load} disabled={loading}>{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}</Button></div>
      </div></CardHeader>
      <CardContent>{loading ? <div className="py-8 text-center text-muted-foreground"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></div> : <div className="max-h-[460px] overflow-auto rounded-md border"><Table>
        <TableHeader><TableRow><TableHead>Tipo</TableHead><TableHead>Código/lote</TableHead><TableHead>Material/área</TableHead><TableHead>Endereço</TableHead><TableHead>Saldo legado</TableHead><TableHead>Etapa</TableHead><TableHead>Ações</TableHead></TableRow></TableHeader>
        <TableBody>{rows.map((row) => <TableRow key={row.id}>
          <TableCell><Badge variant="outline">{row.record_type === "address" ? "Endereço" : "Lote"}</Badge></TableCell>
          <TableCell className="font-mono text-xs">{row.legacy_code}</TableCell><TableCell>{row.legacy_name || "-"}</TableCell>
          <TableCell className="font-mono text-xs">{row.legacy_address_code || (row.record_type === "address" ? row.legacy_code : "-")}</TableCell>
          <TableCell>{row.record_type === "lot" ? `${row.legacy_quantity ?? "-"} ${row.legacy_unit || ""}` : "-"}</TableCell>
          <TableCell><Badge variant="secondary">{String(row.review_stage || "pendente").replaceAll("_", " ")}</Badge></TableCell>
          <TableCell><div className="flex flex-wrap gap-1"><Button size="icon" variant="ghost" onClick={() => openDetail(row)}><Eye className="h-4 w-4" /></Button>{row.sector_status === "pendente" && sector === "qualidade" && <><Button size="sm" onClick={() => openAction(row, "aprovar")}>Aprovar</Button><Button size="sm" variant="destructive" onClick={() => openAction(row, "reprovar")}>Reprovar</Button><Button size="sm" variant="outline" onClick={() => openAction(row, "reter")}>Reter</Button></>}{row.sector_status === "pendente" && sector === "logistica" && <><Button size="sm" onClick={() => openAction(row, "confirmar")}>Conferir</Button><Button size="sm" variant="destructive" onClick={() => openAction(row, "divergencia")}>Divergência</Button></>}</div></TableCell>
        </TableRow>)}{!rows.length && <TableRow><TableCell colSpan={7} className="py-8 text-center text-muted-foreground">Nenhum registro atribuído ao setor.</TableCell></TableRow>}</TableBody>
      </Table></div>}</CardContent>
    </Card>
    <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>Revisão setorial — {detail?.legacy_code}</DialogTitle></DialogHeader>{detail && <div className="space-y-4 text-sm"><div className="grid gap-3 sm:grid-cols-3"><div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Setor atual</p><b>{detail.assigned_sector}</b></div><div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Próximo setor</p><b>{detail.next_sector || "Corte administrativo"}</b></div><div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Motivo</p><b>{detail.reason || "Conferência obrigatória"}</b></div></div><LegacyStructuredFields data={detail.source_payload || {}} /></div>}</DialogContent></Dialog>
    <Dialog open={Boolean(action)} onOpenChange={(open) => !open && setAction(null)}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{sector === "qualidade" ? "Decisão do CQ" : "Conferência física da Logística"} — {action?.row.legacy_code}</DialogTitle></DialogHeader>{action && <div className="space-y-4">
      {sector === "logistica" && <div className="grid gap-3 sm:grid-cols-2"><div className="space-y-1 sm:col-span-2"><Label>Código físico do endereço</Label><Input value={action.endereco_codigo} onChange={(event) => setAction({ ...action, endereco_codigo: event.target.value })} /></div>{action.row.record_type === "lot" && <><div className="space-y-1"><Label>Quantidade contada</Label><Input type="number" min="0" value={action.quantidade_contada} onChange={(event) => setAction({ ...action, quantidade_contada: event.target.value })} /></div><div className="space-y-1"><Label>Unidade</Label><Input value={action.unidade} onChange={(event) => setAction({ ...action, unidade: event.target.value })} /></div></>}</div>}
      <div className="space-y-1"><Label>{action.decision === "confirmar" || action.decision === "aprovar" ? "Evidência / observações" : "Motivo obrigatório"}</Label><Textarea value={action.observacoes} onChange={(event) => setAction({ ...action, observacoes: event.target.value })} /></div>
      <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-muted-foreground">Esta ação registra a revisão, mas não cria saldo, endereço operacional ou movimento no ledger.</div>
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setAction(null)}>Cancelar</Button><Button variant={["reprovar", "divergencia"].includes(action.decision) ? "destructive" : "default"} onClick={submitAction} disabled={saving} className="gap-1">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : ["reprovar", "divergencia"].includes(action.decision) ? <XCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}Registrar</Button></div>
    </div>}</DialogContent></Dialog>
  </>;
}
