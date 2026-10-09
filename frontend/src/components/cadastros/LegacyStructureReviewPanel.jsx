import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { CheckCircle2, Eye, RefreshCw, Rocket, XCircle } from "lucide-react";
import { toast } from "sonner";

const badgeTone = {
  pendente_revisao: "bg-amber-100 text-amber-800",
  aprovado: "bg-emerald-100 text-emerald-800",
  reprovado: "bg-red-100 text-red-800",
  promovido: "bg-blue-100 text-blue-800",
  safe_full: "bg-emerald-100 text-emerald-800",
  partial_pending: "bg-amber-100 text-amber-800",
  unresolved_sku: "bg-red-100 text-red-800",
};

function ReviewBadge({ value }) {
  return <Badge className={badgeTone[value] || "bg-muted text-foreground"}>{String(value || "-").replaceAll("_", " ")}</Badge>;
}

function itemStateLabel(states = {}) {
  const parts = Object.entries(states).map(([state, count]) => `${state}: ${count}`);
  return parts.length ? parts.join(" · ") : "Sem itens";
}

export default function LegacyStructureReviewPanel({ globalSearch = "", onChanged }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({ total: 0, por_tipo: {}, por_status: {} });
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [typeFilter, setTypeFilter] = useState("todos");
  const [statusFilter, setStatusFilter] = useState("todos");
  const [decision, setDecision] = useState(null);
  const [justification, setJustification] = useState("");
  const [detail, setDetail] = useState(null);
  const [promotion, setPromotion] = useState(null);
  const [selectedBomId, setSelectedBomId] = useState("");
  const [parentName, setParentName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/cadastros/estruturas-legadas");
      setRows(response.data.registros || []);
      setSummary(response.data.resumo || {});
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar estruturas legadas.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const query = globalSearch.trim().toLowerCase();
    return rows.filter((row) => {
      if (typeFilter !== "todos" && row.record_type !== typeFilter) return false;
      if (statusFilter !== "todos" && row.review_status !== statusFilter) return false;
      if (!query) return true;
      return [row.target_sku_code, row.legacy_sku, row.source_key, row.legacy_version]
        .some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [rows, globalSearch, typeFilter, statusFilter]);

  const approvedBomsFor = (formula) => rows.filter((row) => (
    row.record_type === "bom"
    && row.target_sku_id === formula.target_sku_id
    && row.review_status === "aprovado"
    && row.activation_status === "bloqueado"
  ));

  const openDecision = (row, action) => {
    setDecision({ row, action });
    setJustification("");
  };

  const submitDecision = async () => {
    if (!decision || justification.trim().length < 3) {
      toast.error("Informe uma justificativa com pelo menos 3 caracteres.");
      return;
    }
    setProcessing(true);
    try {
      await api.post(`/cadastros/estruturas-legadas/${decision.row.id}/decisao`, {
        decision: decision.action,
        justificativa: justification.trim(),
      });
      toast.success(decision.action === "aprovar" ? "Estrutura aprovada para pareamento." : "Estrutura reprovada.");
      setDecision(null);
      await load();
      onChanged?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível registrar a decisão.");
    } finally {
      setProcessing(false);
    }
  };

  const openDetail = async (row) => {
    setProcessing(true);
    try {
      const response = await api.get(`/cadastros/estruturas-legadas/${row.id}`);
      setDetail(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível abrir os detalhes.");
    } finally {
      setProcessing(false);
    }
  };

  const openPromotion = (formula) => {
    const candidates = approvedBomsFor(formula);
    if (!candidates.length) {
      toast.error("Aprove primeiro um BOM completo do mesmo SKU.");
      return;
    }
    setPromotion({ formula, candidates });
    setSelectedBomId(candidates[0].id);
    setParentName(formula.target_sku_code || formula.legacy_sku || "Produto legado");
  };

  const submitPromotion = async () => {
    if (!promotion || !selectedBomId || parentName.trim().length < 2) return;
    setProcessing(true);
    try {
      await api.post("/cadastros/estruturas-legadas/promover", {
        formula_review_id: promotion.formula.id,
        bom_review_id: selectedBomId,
        produto_pai_nome: parentName.trim(),
      });
      toast.success("Fórmula e BOM promovidos atomicamente para a estrutura operacional.");
      setPromotion(null);
      await load();
      onChanged?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível promover a estrutura.");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="rounded-lg border-l-4 border-l-blue-500">
        <CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div><p className="text-xs uppercase text-muted-foreground">Total legado</p><p className="text-2xl font-semibold">{summary.total || 0}</p></div>
          <div><p className="text-xs uppercase text-muted-foreground">Fórmulas</p><p className="text-2xl font-semibold">{summary.por_tipo?.formula || 0}</p></div>
          <div><p className="text-xs uppercase text-muted-foreground">BOMs</p><p className="text-2xl font-semibold">{summary.por_tipo?.bom || 0}</p></div>
          <div><p className="text-xs uppercase text-muted-foreground">Pendentes</p><p className="text-2xl font-semibold text-amber-600">{summary.por_status?.pendente_revisao || 0}</p></div>
          <div><p className="text-xs uppercase text-muted-foreground">Promovidos</p><p className="text-2xl font-semibold text-blue-600">{summary.por_status?.promovido || 0}</p></div>
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div><CardTitle className="text-base">Revisão e promoção controlada</CardTitle><p className="mt-1 text-sm text-muted-foreground">Aprovar não ativa a estrutura. A ativação ocorre somente ao promover um par completo do mesmo SKU.</p></div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw className="mr-1 h-4 w-4" />Atualizar</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <Select value={typeFilter} onValueChange={setTypeFilter}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="todos">Todos os tipos</SelectItem><SelectItem value="formula">Fórmulas</SelectItem><SelectItem value="bom">BOMs</SelectItem></SelectContent></Select>
            <Select value={statusFilter} onValueChange={setStatusFilter}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="todos">Todos os status</SelectItem><SelectItem value="pendente_revisao">Pendentes</SelectItem><SelectItem value="aprovado">Aprovados</SelectItem><SelectItem value="reprovado">Reprovados</SelectItem><SelectItem value="promovido">Promovidos</SelectItem></SelectContent></Select>
          </div>
          <div className="max-h-[620px] overflow-auto rounded-md border">
            <Table>
              <TableHeader><TableRow><TableHead>SKU / versão</TableHead><TableHead>Tipo</TableHead><TableHead>Origem</TableHead><TableHead>Reconciliação</TableHead><TableHead>Revisão</TableHead><TableHead>Itens</TableHead><TableHead className="text-right">Ações</TableHead></TableRow></TableHeader>
              <TableBody>
                {filtered.map((row) => {
                  const promotable = row.record_type === "formula" && row.review_status === "aprovado" && row.activation_status === "bloqueado";
                  return <TableRow key={row.id}>
                    <TableCell><b className="font-mono">{row.target_sku_code || row.legacy_sku || "Não resolvido"}</b><p className="text-xs text-muted-foreground">{row.legacy_version || "sem versão"}</p></TableCell>
                    <TableCell><Badge variant="outline">{row.record_type === "formula" ? "Fórmula" : "BOM"}</Badge></TableCell>
                    <TableCell><span className="text-sm">{row.legacy_status || "Sem status"}</span><p className="max-w-44 truncate text-xs text-muted-foreground">{row.source_key}</p></TableCell>
                    <TableCell><ReviewBadge value={row.reconciliation_classification} /></TableCell>
                    <TableCell><ReviewBadge value={row.activation_status === "promovido" ? "promovido" : row.review_status} /></TableCell>
                    <TableCell><p className="max-w-52 text-xs text-muted-foreground">{itemStateLabel(row.item_states)}</p></TableCell>
                    <TableCell><div className="flex flex-wrap justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => openDetail(row)} disabled={processing}><Eye className="h-4 w-4" /></Button>
                      {row.activation_status !== "promovido" && <>
                        <Button size="sm" variant="outline" disabled={row.reconciliation_classification !== "safe_full" || processing} onClick={() => openDecision(row, "aprovar")}><CheckCircle2 className="mr-1 h-4 w-4" />Aprovar</Button>
                        <Button size="sm" variant="outline" disabled={processing} className="text-red-600" onClick={() => openDecision(row, "reprovar")}><XCircle className="mr-1 h-4 w-4" />Reprovar</Button>
                      </>}
                      {promotable && <Button size="sm" onClick={() => openPromotion(row)} disabled={processing || !approvedBomsFor(row).length}><Rocket className="mr-1 h-4 w-4" />Promover</Button>}
                    </div></TableCell>
                  </TableRow>;
                })}
                {!filtered.length && <TableRow><TableCell colSpan={7} className="py-10 text-center text-muted-foreground">{loading ? "Carregando..." : "Nenhuma estrutura encontrada."}</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={Boolean(decision)} onOpenChange={(open) => !open && setDecision(null)}>
        <DialogContent><DialogHeader><DialogTitle>{decision?.action === "aprovar" ? "Aprovar estrutura legada" : "Reprovar estrutura legada"}</DialogTitle></DialogHeader>
          <div className="space-y-3"><p className="text-sm text-muted-foreground">{decision?.row?.target_sku_code || decision?.row?.legacy_sku} · {decision?.row?.source_key}</p><div><Label>Justificativa obrigatória</Label><Textarea value={justification} onChange={(event) => setJustification(event.target.value)} placeholder="Registre a conferência técnica e a decisão..." /></div></div>
          <DialogFooter><Button variant="outline" onClick={() => setDecision(null)}>Cancelar</Button><Button onClick={submitDecision} disabled={processing}>{decision?.action === "aprovar" ? "Confirmar aprovação" : "Confirmar reprovação"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(promotion)} onOpenChange={(open) => !open && setPromotion(null)}>
        <DialogContent><DialogHeader><DialogTitle>Promover estrutura para produção</DialogTitle></DialogHeader>
          <div className="space-y-3"><div className="rounded-md border border-amber-300 bg-amber-500/10 p-3 text-sm">Esta ação cria produto-pai, BOM bulk e BOM de embalagem em uma única transação e vincula o SKU.</div><div><Label>Fórmula aprovada</Label><Input value={promotion?.formula?.source_key || ""} disabled /></div><div><Label>BOM aprovado do mesmo SKU</Label><Select value={selectedBomId} onValueChange={setSelectedBomId}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(promotion?.candidates || []).map((row) => <SelectItem key={row.id} value={row.id}>{row.source_key} · {row.legacy_version || "sem versão"}</SelectItem>)}</SelectContent></Select></div><div><Label>Nome do produto-pai</Label><Input value={parentName} onChange={(event) => setParentName(event.target.value)} /></div></div>
          <DialogFooter><Button variant="outline" onClick={() => setPromotion(null)}>Cancelar</Button><Button onClick={submitPromotion} disabled={processing || !selectedBomId || parentName.trim().length < 2}><Rocket className="mr-1 h-4 w-4" />Promover atomicamente</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{detail?.source_key}</DialogTitle></DialogHeader>
          {detail && <div className="space-y-4"><div className="grid gap-2 sm:grid-cols-3"><div><Label>SKU destino</Label><p className="font-mono text-sm">{detail.target_sku_code || "Não resolvido"}</p></div><div><Label>Status origem</Label><p className="text-sm">{detail.legacy_status || "Sem status"}</p></div><div><Label>Revisão</Label><div><ReviewBadge value={detail.review_status} /></div></div></div><div><Label>Bloqueios</Label><div className="mt-1 flex flex-wrap gap-1">{(detail.blocking_reasons || []).map((reason) => <Badge key={reason} variant="outline">{reason}</Badge>)}</div></div><div><Label>Itens resolvidos</Label><div className="mt-1 rounded-md border">{(detail.resolved_items || []).map((item) => <div key={item.source_item_key} className="grid grid-cols-[1fr_auto] gap-3 border-b p-2 text-sm last:border-0"><span>{item.target_material_code} · {item.target_type}</span><b>{item.quantity}</b></div>)}</div></div></div>}
          <DialogFooter><Button variant="outline" onClick={() => setDetail(null)}>Fechar</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
