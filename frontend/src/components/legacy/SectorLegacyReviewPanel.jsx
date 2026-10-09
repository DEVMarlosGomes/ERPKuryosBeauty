import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Archive, CheckCircle2, ChevronLeft, ChevronRight, Eye, Forward, PlayCircle, RefreshCw, Search } from "lucide-react";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import LegacyStructuredFields from "@/components/legacy/LegacyStructuredFields";

const PAGE_SIZE = 100;
const SECTOR_LABELS = {
  pcp: "PCP", logistica: "Logística", comercial: "Comercial", cadastros: "Cadastros",
  expedicao: "Expedição", qualidade: "Qualidade", pd: "P&D", compras: "Compras",
  administracao_ti: "Administração / TI", rh: "RH",
};

function text(value, fallback = "—") {
  if (value == null || value === "") return fallback;
  return String(value).replace(/^source_archive:/, "").replaceAll("_", " ");
}

function statusClass(status) {
  if (status === "concluido") return "bg-emerald-100 text-emerald-700";
  if (status === "divergencia") return "bg-red-100 text-red-700";
  if (status === "em_revisao") return "bg-blue-100 text-blue-700";
  return "bg-amber-100 text-amber-700";
}

export default function SectorLegacyReviewPanel({ sector, title }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({ total: 0, por_status: {}, por_colecao: {} });
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [status, setStatus] = useState("todos");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get("/cadastros/revisoes-setoriais", {
        params: {
          sector, q: appliedQuery || undefined, sector_status: status,
          skip: page * PAGE_SIZE, limit: PAGE_SIZE,
        },
      });
      setRows(data?.registros || []);
      setSummary(data?.resumo || { total: 0, por_status: {}, por_colecao: {} });
      setHasMore(Boolean(data?.has_more));
    } catch (err) {
      setError(err?.response?.data?.detail || "Não foi possível carregar as revisões do setor.");
    } finally {
      setLoading(false);
    }
  }, [sector, appliedQuery, status, page]);

  useEffect(() => { setPage(0); }, [sector, appliedQuery, status]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (row) => {
    setDetailLoading(true);
    setNote("");
    try {
      const { data } = await api.get(`/cadastros/revisoes-setoriais/${encodeURIComponent(row.review_collection)}/${encodeURIComponent(row.id)}`);
      setDetail({ ...data, review_collection: row.review_collection });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Não foi possível abrir o registro completo.");
    } finally {
      setDetailLoading(false);
    }
  };

  const runAction = async (action) => {
    const record = detail?.registro;
    if (!record) return;
    if (["divergencia", "encaminhar", "concluir"].includes(action) && note.trim().length < 10) {
      toast.error("Informe uma observação com pelo menos 10 caracteres.");
      return;
    }
    setWorking(true);
    try {
      const { data } = await api.post(
        `/cadastros/revisoes-setoriais/${encodeURIComponent(detail.review_collection)}/${encodeURIComponent(record.id)}/acao`,
        { action, observacao: note.trim(), expected_updated_at: record.updated_at || null },
      );
      toast.success(data?.message || "Revisão atualizada.");
      setDetail(null);
      setNote("");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Não foi possível atualizar a revisão.");
    } finally {
      setWorking(false);
    }
  };

  const record = detail?.registro;
  const coverage = detail?.cobertura_origem || {};

  return (
    <div className="space-y-4">
      <Card className="border-l-4 border-l-amber-500">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2"><Archive className="h-5 w-5 text-amber-500" />{title || `Revisões legadas — ${SECTOR_LABELS[sector] || sector}`}</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Cada registro aparece em um único setor. Abra para conferir todos os campos, registrar divergências e encaminhar sem duplicação.</p>
            </div>
            <Badge variant="secondary" className="w-fit">{summary.total || 0} no setor</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-lg border p-3"><p className="text-xs uppercase text-muted-foreground">Pendentes</p><p className="text-2xl font-black text-amber-600">{summary.por_status?.pendente || 0}</p></div>
            <div className="rounded-lg border p-3"><p className="text-xs uppercase text-muted-foreground">Em revisão</p><p className="text-2xl font-black text-blue-600">{summary.por_status?.em_revisao || 0}</p></div>
            <div className="rounded-lg border p-3"><p className="text-xs uppercase text-muted-foreground">Divergências</p><p className="text-2xl font-black text-red-600">{summary.por_status?.divergencia || 0}</p></div>
            <div className="rounded-lg border p-3"><p className="text-xs uppercase text-muted-foreground">Concluídos</p><p className="text-2xl font-black text-emerald-600">{summary.por_status?.concluido || 0}</p></div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-2 p-4 lg:flex-row">
          <div className="relative flex-1"><Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><Input className="pl-9" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && setAppliedQuery(query.trim())} placeholder="Buscar código, origem, tipo ou etapa..." /></div>
          <Select value={status} onValueChange={setStatus}><SelectTrigger className="w-full lg:w-48"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="todos">Todos os status</SelectItem><SelectItem value="pendente">Pendente</SelectItem><SelectItem value="em_revisao">Em revisão</SelectItem><SelectItem value="divergencia">Divergência</SelectItem><SelectItem value="concluido">Concluído</SelectItem></SelectContent></Select>
          <Button variant="outline" onClick={() => setAppliedQuery(query.trim())}>Buscar</Button>
          <Button variant="outline" onClick={load}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
        </CardContent>
      </Card>

      {error && <div className="rounded-lg border border-red-300 bg-red-500/10 p-4 text-sm text-red-600">{String(error)}</div>}
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["Origem", "Chave", "Tipo", "Etapa", "Status", "Próximo setor", "Dados"].map((label) => <th key={label} className="p-3 text-left">{label}</th>)}</tr></thead>
            <tbody>
              {!loading && rows.map((row) => <tr key={`${row.review_collection}-${row.id}`} className="border-b">
                <td className="p-3"><b>{text(row.source_node)}</b><p className="text-xs text-muted-foreground">{text(row.review_collection)}</p></td>
                <td className="p-3 font-mono text-xs">{text(row.source_key || row.legacy_code || row.id)}</td>
                <td className="p-3">{text(row.record_type)}</td>
                <td className="p-3">{text(row.review_stage)}</td>
                <td className="p-3"><Badge className={statusClass(row.sector_status)}>{text(row.sector_status)}</Badge></td>
                <td className="p-3">{text(SECTOR_LABELS[row.next_sector] || row.next_sector)}</td>
                <td className="p-3"><Button size="sm" variant="outline" disabled={detailLoading} onClick={() => openDetail(row)}><Eye className="mr-2 h-4 w-4" />Abrir</Button></td>
              </tr>)}
              {loading && <tr><td colSpan={7} className="p-10 text-center text-muted-foreground">Carregando revisões...</td></tr>}
              {!loading && !rows.length && !error && <tr><td colSpan={7} className="p-10 text-center text-muted-foreground">Nenhuma revisão encontrada para o filtro.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
          <span>Página {page + 1} · exibindo {rows.length} de {summary.total}</span>
          <div className="flex gap-2"><Button size="sm" variant="outline" disabled={page === 0 || loading} onClick={() => setPage((value) => value - 1)}><ChevronLeft className="h-4 w-4" /></Button><Button size="sm" variant="outline" disabled={!hasMore || loading} onClick={() => setPage((value) => value + 1)}><ChevronRight className="h-4 w-4" /></Button></div>
        </div>
      </Card>

      <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Conferência completa do dado legado</DialogTitle>
            <DialogDescription>{text(record?.source_node)} · {text(record?.source_key || record?.legacy_code || record?.id)}</DialogDescription>
          </DialogHeader>
          {record && <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Setor atual</p><b>{text(SECTOR_LABELS[record.assigned_sector] || record.assigned_sector)}</b></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Próximo setor</p><b>{text(SECTOR_LABELS[record.next_sector] || record.next_sector)}</b></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Campos preenchidos</p><b className="text-emerald-600">{coverage.preenchidos || 0}</b></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Campos vazios na origem</p><b className={coverage.vazios ? "text-amber-600" : "text-emerald-600"}>{coverage.vazios || 0}</b></div>
            </div>
            <div className="rounded-lg border border-amber-300 bg-amber-500/10 p-3 text-sm"><b>Regra de segurança:</b> a conferência organiza o dado no setor, mas não recria automaticamente saldo, nota, pedido ou movimento histórico.</div>
            <div className="space-y-2">
              <Label className="text-base">Dados disponíveis na origem</Label>
              <LegacyStructuredFields data={record.source_payload || record} />
            </div>
            {record.sector_status !== "concluido" && <div className="space-y-2"><Label>Observação da conferência</Label><Textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Registre a validação, correção necessária ou motivo do encaminhamento..." rows={3} /></div>}
          </div>}
          <DialogFooter className="flex-wrap gap-2 sm:justify-between">
            <Button variant="outline" onClick={() => setDetail(null)}>Fechar</Button>
            {record?.sector_status !== "concluido" && <div className="flex flex-wrap gap-2">
              {record?.sector_status !== "em_revisao" && <Button variant="outline" disabled={working} onClick={() => runAction("iniciar")}><PlayCircle className="mr-2 h-4 w-4" />Iniciar revisão</Button>}
              <Button variant="destructive" disabled={working} onClick={() => runAction("divergencia")}><AlertTriangle className="mr-2 h-4 w-4" />Divergência</Button>
              {record?.next_sector ? <Button disabled={working} onClick={() => runAction("encaminhar")}><Forward className="mr-2 h-4 w-4" />Encaminhar para {SECTOR_LABELS[record.next_sector] || record.next_sector}</Button> : <Button disabled={working} onClick={() => runAction("concluir")}><CheckCircle2 className="mr-2 h-4 w-4" />Concluir revisão</Button>}
            </div>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
